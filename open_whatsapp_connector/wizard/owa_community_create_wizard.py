"""Phase G: WhatsApp Community creation wizard."""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OwaCommunityCreateWizard(models.TransientModel):
    _name = 'owa.community.create.wizard'
    _description = 'WhatsApp Community Creation Wizard'

    wa_account_id = fields.Many2one(
        'owa.account', required=True, string='WhatsApp Account')
    subject = fields.Char(string='Community Name', required=True, size=100)
    description = fields.Text(string='Description', size=512)

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

    def action_create(self):
        self.ensure_one()
        if self.wa_account_id.session_state != 'connected':
            raise UserError(_(
                "WhatsApp account '%s' is not connected. "
                "Open WhatsApp → Configuration → Accounts and click "
                "Connect or Refresh Status, then retry."
            ) % self.wa_account_id.name)
        if not self.subject.strip():
            raise UserError(_("Please enter a community name."))
        api = self.wa_account_id._get_baileys_api()
        try:
            metadata = api.create_community(self.subject.strip(), self.description or '')
        except Exception as exc:
            _logger.exception("Community creation failed")
            raise UserError(_("WhatsApp rejected the creation: %s") % exc)
        Community = self.env['owa.community'].sudo()
        row = Community._upsert_from_metadata(self.wa_account_id, metadata)
        if not row:
            raise UserError(_("Community created but no metadata returned. "
                              "Use Refresh to pick it up."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("WhatsApp Community"),
            'res_model': 'owa.community',
            'res_id': row.id,
            'view_mode': 'form',
            'target': 'current',
        }
