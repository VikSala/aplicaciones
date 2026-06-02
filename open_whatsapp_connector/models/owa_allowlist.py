from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format


class OwaAllowlistEntry(models.Model):
    """Phase 5 — per-account inbound DM allowlist.

    When ``owa.account.dm_policy`` is ``allowlist``, only contacts with an
    entry in this table can DM the account; everyone else is dropped at the
    inbound webhook controller. ``pairing`` policy auto-creates entries when
    the admin approves a pending pair (Phase 7).
    """
    _name = 'owa.allowlist.entry'
    _description = 'WhatsApp DM Allowlist Entry'
    _order = 'account_id, id desc'
    _rec_name = 'phone_formatted'

    account_id = fields.Many2one(
        'owa.account', required=True, ondelete='cascade', index=True)
    phone = fields.Char(string="Phone", required=True)
    phone_formatted = fields.Char(
        string="Formatted phone", compute='_compute_phone_formatted', store=True, index=True)
    partner_id = fields.Many2one('res.partner', string="Linked partner")
    note = fields.Char(string="Note")

    _sql_constraints = [
        ('phone_uniq_per_account',
         'UNIQUE(account_id, phone_formatted)',
         'This number is already in the allowlist for that account.'),
    ]

    @api.depends('phone')
    def _compute_phone_formatted(self):
        for rec in self:
            if rec.phone:
                rec.phone_formatted = wa_phone_format(self.env, rec.phone) or rec.phone.strip()
            else:
                rec.phone_formatted = False

    @api.constrains('phone')
    def _check_phone(self):
        for rec in self:
            if not rec.phone or not rec.phone.strip():
                raise ValidationError(_("Phone number is required."))

    @api.model
    def is_allowed(self, account_id, phone):
        """Returns True if the (account, phone) pair is in the allowlist."""
        if not account_id or not phone:
            return False
        formatted = wa_phone_format(self.env, phone) or phone
        return bool(self.sudo().search([
            ('account_id', '=', account_id),
            ('phone_formatted', '=', formatted),
        ], limit=1))
