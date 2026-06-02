"""Phase G: WhatsApp Communities — umbrella linking related groups.

A Community is a parent JID (also ending in @g.us) that aggregates child
groups. Membership / admin events are still per-group, but communities
let you push announcements that fan out to every linked group.

This model mirrors :class:`OwaGroupSession` but at the community level.
We don't materialise child groups here — instead the existing
:class:`OwaGroupSession` already represents each member group, and the
``parent_community_jid`` linkage is maintained on the community side.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OwaCommunity(models.Model):
    _name = 'owa.community'
    _description = 'WhatsApp Community'
    _order = 'subject, id'
    _rec_name = 'subject'

    wa_account_id = fields.Many2one(
        'owa.account', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, index=True)
    community_jid = fields.Char(string='WhatsApp Community JID', index=True)
    subject = fields.Char(required=True)
    description = fields.Text()
    owner_jid = fields.Char(string='Owner JID')
    creation_ts = fields.Integer(string='Created (epoch)')
    bot_state = fields.Selection([
        ('active',   'Active'),
        ('disabled', 'Disabled'),
    ], default='active', index=True)
    image_1920 = fields.Image(string='Picture')
    linked_group_count = fields.Integer(
        compute='_compute_linked_group_count',
        string='Linked groups')

    _sql_constraints = [
        ('uniq_account_community_jid',
         'unique(wa_account_id, community_jid)',
         'Only one community record per (account, community JID).'),
    ]

    def _compute_linked_group_count(self):
        Session = self.env['owa.group.session'].sudo()
        for rec in self:
            rec.linked_group_count = Session.search_count([
                ('wa_account_id', '=', rec.wa_account_id.id),
                ('parent_community_jid', '=', rec.community_jid or '__none__'),
            ])

    def _api(self):
        self.ensure_one()
        if not self.wa_account_id:
            raise UserError(_("Community has no linked WhatsApp account."))
        if self.wa_account_id.session_state != 'connected':
            raise UserError(_("WhatsApp account is not connected."))
        return self.wa_account_id._get_baileys_api()

    @api.model
    def _upsert_from_metadata(self, account, metadata):
        if not metadata:
            return self.browse()
        jid = metadata.get('id') or metadata.get('jid')
        if not jid:
            return self.browse()
        vals = {
            'community_jid': jid,
            'subject': metadata.get('subject') or jid,
            'description': metadata.get('desc') or metadata.get('description') or '',
            'owner_jid': metadata.get('subjectOwner') or metadata.get('owner') or '',
            'creation_ts': metadata.get('creation') or 0,
        }
        existing = self.search([
            ('wa_account_id', '=', account.id),
            ('community_jid', '=', jid),
        ], limit=1)
        if existing:
            existing.write(vals)
            return existing
        vals['wa_account_id'] = account.id
        return self.create(vals)

    @api.model
    def action_refresh_all(self):
        Account = self.env['owa.account'].sudo()
        accounts = Account.search([('session_state', '=', 'connected')])
        if not accounts:
            raise UserError(_("No connected WhatsApp accounts."))
        total = 0
        errors = []
        for account in accounts:
            try:
                api = account._get_baileys_api()
                communities = api.fetch_all_communities()
                GroupSession = self.env['owa.group.session'].sudo()
                for meta in communities or []:
                    self._upsert_from_metadata(account, meta)
                    # Link sub-groups: write parent_community_jid on each linked
                    # group session so the community's linked-group COUNT and
                    # "Open linked groups" action resolve. The field was
                    # declared but never written by anything. (#community)
                    cjid = meta.get('id') or meta.get('jid')
                    if cjid:
                        try:
                            for g in (api.get_community_linked_groups(cjid) or []):
                                gjid = g.get('id') or g.get('jid')
                                if not gjid:
                                    continue
                                grow = GroupSession._upsert_from_metadata(
                                    account, g, link_create_channel=False)
                                if grow:
                                    grow.parent_community_jid = cjid
                        except Exception:
                            _logger.exception(
                                "linked-group sync failed for community %s", cjid)
                total += len(communities or [])
            except Exception as exc:
                _logger.exception("Community refresh failed for %s", account.name)
                errors.append("%s: %s" % (account.name, exc))
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _("WhatsApp Communities"),
                'message': _("Refreshed %s community(ies).") % total,
                'type': 'warning' if errors else 'success',
                'sticky': bool(errors),
            },
        }

    def action_leave(self):
        for rec in self:
            api = rec._api()
            api.leave_community(rec.community_jid)
            rec.bot_state = 'disabled'
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'title': _("Community"),
                       'message': _("Left %s community(ies).") % len(self),
                       'type': 'success'},
        }

    def action_set_subject(self):
        for rec in self:
            api = rec._api()
            api.update_community_subject(rec.community_jid, rec.subject or '')
        return True

    def action_open_linked_groups(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Linked Groups"),
            'res_model': 'owa.group.session',
            'view_mode': 'list,form',
            'domain': [
                ('wa_account_id', '=', self.wa_account_id.id),
                ('parent_community_jid', '=', self.community_jid),
            ],
            'context': {
                'default_wa_account_id': self.wa_account_id.id,
                'default_parent_community_jid': self.community_jid,
            },
        }

    @api.model
    def action_open_create_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _("Create WhatsApp Community"),
            'res_model': 'owa.community.create.wizard',
            'view_mode': 'form',
            'target': 'new',
        }
