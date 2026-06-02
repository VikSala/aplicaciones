"""Phase F: WhatsApp group creation wizard.

Create a brand-new WhatsApp group from Odoo. Initial participants come
from a partner picker (their phone is read off ``res.partner.phone``)
and / or a free-form list of phone numbers — both supported per user
preference.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format

_logger = logging.getLogger(__name__)


class OwaGroupCreateWizard(models.TransientModel):
    _name = 'owa.group.create.wizard'
    _description = 'WhatsApp Group Creation Wizard'

    wa_account_id = fields.Many2one(
        'owa.account', required=True, string='WhatsApp Account',
        help='The connected account that will own / be admin of the new group.')
    subject = fields.Char(
        string='Group Name', required=True, size=100,
        help='WhatsApp group title — max 100 characters.')
    partner_ids = fields.Many2many(
        'res.partner', string='Initial Participants',
        domain=[('phone', '!=', False)],
        help='Each picked partner must have a phone number.')
    raw_phones = fields.Text(
        string='Or — Raw Phone Numbers',
        help='Optional, in addition to picked contacts. One number per line, '
             'or comma-separated. Country code first, no spaces.')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if 'wa_account_id' in fields_list and not vals.get('wa_account_id'):
            Account = self.env['owa.account'].sudo()
            account = (Account.search([('session_state', '=', 'connected')], limit=1)
                       or Account.search([], limit=1))
            if account:
                vals['wa_account_id'] = account.id
        return vals

    def _resolve_jids(self):
        jids = []
        seen = set()

        def add(phone):
            phone = (phone or '').strip()
            if not phone:
                return
            normalized = wa_phone_format(self.env, phone) or phone
            digits = normalized.lstrip('+').split('@')[0]
            if not digits or digits in seen:
                return
            seen.add(digits)
            jids.append(f'{digits}@s.whatsapp.net')

        for p in self.partner_ids:
            add(p.phone)
        for raw in (self.raw_phones or '').replace(',', '\n').split('\n'):
            add(raw)
        return jids

    def action_create(self):
        self.ensure_one()
        if self.wa_account_id.session_state != 'connected':
            raise UserError(_(
                "WhatsApp account '%s' is not connected. "
                "Open WhatsApp → Configuration → Accounts and click "
                "Connect or Refresh Status, then retry."
            ) % self.wa_account_id.name)
        if not self.subject.strip():
            raise UserError(_("Please enter a group name."))
        jids = self._resolve_jids()
        if not jids:
            raise UserError(_("Pick at least one partner with a phone number, "
                              "or enter at least one raw number."))
        api = self.wa_account_id._get_baileys_api()
        try:
            metadata = api.create_group(self.subject.strip(), jids)
        except Exception as exc:
            _logger.exception("Group creation failed")
            raise UserError(_("WhatsApp rejected the group creation: %s") % exc)
        Session = self.env['owa.group.session'].sudo()
        row = Session._upsert_from_metadata(self.wa_account_id, metadata)
        if not row:
            raise UserError(_("Group was created on WhatsApp but no metadata "
                              "returned — refresh the Groups list to pick it up."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("WhatsApp Group"),
            'res_model': 'owa.group.session',
            'res_id': row.id,
            'view_mode': 'form',
            'target': 'current',
        }
