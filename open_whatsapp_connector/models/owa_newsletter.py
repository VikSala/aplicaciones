"""Phase G: WhatsApp Newsletters / Channels.

A Newsletter is a one-to-many broadcast (writer → followers). The
connected account can either own one (and post to it) or follow others'
newsletters to ingest broadcasts as a special discuss.channel.

JIDs end with ``@newsletter`` and behave differently from group / DM
JIDs in the gateway — handled separately to avoid muddying the group code.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OwaNewsletter(models.Model):
    _name = 'owa.newsletter'
    _description = 'WhatsApp Newsletter / Channel'
    _order = 'name, id'

    wa_account_id = fields.Many2one(
        'owa.account', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, index=True)
    newsletter_jid = fields.Char(string='Newsletter JID', index=True)
    name = fields.Char(required=True)
    description = fields.Text()
    role = fields.Selection([
        ('owner',     'Owner'),
        ('admin',     'Admin'),
        ('subscriber','Subscriber'),
        ('unknown',   'Unknown'),
    ], default='unknown')
    subscriber_count = fields.Integer(default=0)
    muted = fields.Boolean(default=False)
    image_1920 = fields.Image(string='Picture')

    _sql_constraints = [
        ('uniq_account_newsletter_jid',
         'unique(wa_account_id, newsletter_jid)',
         'Only one newsletter record per (account, JID).'),
    ]

    def _api(self):
        self.ensure_one()
        if not self.wa_account_id:
            raise UserError(_("Newsletter has no linked WhatsApp account."))
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
        # The gateway returns the newsletter shape inconsistently — sometimes
        # everything is on the outer dict, sometimes a nested ``metadata`` key
        # holds richer fields. Merge so siblings of the nested dict don't get
        # silently dropped, then resolve thread_metadata identically.
        flat = dict(metadata)
        nested = metadata.get('metadata') or {}
        if isinstance(nested, dict):
            flat.update(nested)
        thread = flat.get('thread_metadata') if isinstance(flat.get('thread_metadata'), dict) else flat
        vals = {
            'newsletter_jid': jid,
            'name': thread.get('name') or flat.get('name') or jid,
            'description': thread.get('description') or flat.get('description') or '',
            'subscriber_count': thread.get('subscribers_count')
                or flat.get('subscriber_count') or 0,
            'role': (flat.get('role') or 'unknown').lower(),
        }
        existing = self.search([
            ('wa_account_id', '=', account.id),
            ('newsletter_jid', '=', jid),
        ], limit=1)
        if existing:
            existing.write(vals)
            return existing
        vals['wa_account_id'] = account.id
        return self.create(vals)

    def action_follow(self):
        for rec in self:
            api = rec._api()
            api.follow_newsletter(rec.newsletter_jid)
            rec.role = 'subscriber'
        return True

    def action_unfollow(self):
        for rec in self:
            api = rec._api()
            api.unfollow_newsletter(rec.newsletter_jid)
        return True

    def action_mute(self):
        for rec in self:
            api = rec._api()
            api.mute_newsletter(rec.newsletter_jid, True)
            rec.muted = True
        return True

    def action_unmute(self):
        for rec in self:
            api = rec._api()
            api.mute_newsletter(rec.newsletter_jid, False)
            rec.muted = False
        return True

    def action_push_picture(self):
        for rec in self:
            api = rec._api()
            api.update_newsletter(rec.newsletter_jid, picture_data=rec.image_1920 or '')
        return True

    def action_push_metadata(self):
        for rec in self:
            api = rec._api()
            api.update_newsletter(
                rec.newsletter_jid,
                name=rec.name,
                description=rec.description or '',
            )
        return True

    @api.model
    def action_open_create_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _("Create WhatsApp Newsletter"),
            'res_model': 'owa.newsletter.create.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    @api.model
    def action_open_subscribe_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _("Subscribe to WhatsApp Newsletter"),
            'res_model': 'owa.newsletter.subscribe.wizard',
            'view_mode': 'form',
            'target': 'new',
        }
