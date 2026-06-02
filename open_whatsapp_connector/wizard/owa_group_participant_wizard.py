"""Phase C1: WhatsApp group participant administration wizard.

Reachable from a WhatsApp group's ``discuss.channel`` form ("Manage
participants" smart button). Lets an admin add / remove / promote /
demote one or more contacts on the WhatsApp side via the sidecar's
``sock.groupParticipantsUpdate``.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError
from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format

_logger = logging.getLogger(__name__)


class OwaGroupParticipantWizard(models.TransientModel):
    _name = 'owa.group.participant.wizard'
    _description = 'WhatsApp Group Participant Update Wizard'

    channel_id = fields.Many2one(
        'discuss.channel', required=True, ondelete='cascade')
    wa_account_id = fields.Many2one(
        'owa.account', related='channel_id.owa_account_id', readonly=True)
    group_jid = fields.Char(
        string='WhatsApp Group JID', related='channel_id.whatsapp_number',
        readonly=True)
    action_kind = fields.Selection([
        ('add',     'Add to WhatsApp group'),
        ('remove',  'Remove from WhatsApp group'),
        ('promote', 'Promote to WhatsApp admin'),
        ('demote',  'Demote from WhatsApp admin'),
    ], string='Action', required=True, default='add')
    partner_ids = fields.Many2many(
        'res.partner', string='WhatsApp Contacts',
        help='Targets for the action. Each partner must have a phone number set.')
    raw_phones = fields.Char(
        string='Or — Raw Phones (comma-separated)',
        help='Alternative to picking partners: comma-separated phone numbers '
             '(country code first, no spaces). Useful for non-partner JIDs.')

    def _resolve_jids(self):
        jids = []
        for p in self.partner_ids:
            phone = wa_phone_format(self.env, p.phone or '')
            if not phone:
                continue
            jids.append(phone.lstrip('+') + '@s.whatsapp.net')
        for raw in (self.raw_phones or '').split(','):
            raw = raw.strip()
            if not raw:
                continue
            phone = wa_phone_format(self.env, raw) or raw
            jids.append(phone.lstrip('+') + '@s.whatsapp.net')
        return [j for j in jids if '@' in j]

    def action_apply(self):
        self.ensure_one()
        if not self.group_jid or not self.group_jid.endswith('@g.us'):
            raise UserError(_("This action only works on WhatsApp group channels."))
        jids = self._resolve_jids()
        if not jids:
            raise UserError(_("Pick at least one contact or enter at least one phone."))
        api = self.wa_account_id._get_baileys_api()
        result = api.group_participants_update(self.group_jid, self.action_kind, jids)
        ok = sum(1 for r in result if str(r.get('status', '')).lower() in ('200', 'ok'))
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _("WhatsApp group updated"),
                'message': _("%(ok)d of %(total)d targets succeeded (action: %(action)s).") % {
                    'ok': ok, 'total': len(result), 'action': self.action_kind,
                },
                'sticky': False,
            },
        }
