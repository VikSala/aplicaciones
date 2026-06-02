import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format

_logger = logging.getLogger(__name__)


class OwaBlacklist(models.Model):
    _name = 'owa.blacklist'
    _description = 'WhatsApp Phone Blacklist'
    _order = 'id desc'
    _rec_name = 'phone'

    phone = fields.Char(string="Phone Number", required=True, index=True)
    phone_formatted = fields.Char(
        string="Formatted Phone", compute='_compute_phone_formatted', store=True)
    reason = fields.Char(string="Reason")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('phone_unique', 'UNIQUE(phone_formatted)',
         'This phone number is already blacklisted.'),
    ]

    @api.depends('phone')
    def _compute_phone_formatted(self):
        for rec in self:
            if rec.phone:
                # Fall back to the trimmed raw phone so phone_formatted is
                # never NULL — Postgres treats each NULL as distinct, which
                # would otherwise let the UNIQUE constraint be bypassed.
                rec.phone_formatted = (
                    wa_phone_format(self.env, rec.phone)
                    or (rec.phone or '').strip()
                    or False
                )
            else:
                rec.phone_formatted = False

    @api.constrains('phone')
    def _check_phone_yields_formatted(self):
        for rec in self:
            if not rec.phone or not (rec.phone or '').strip():
                raise ValidationError(_(
                    "Phone number is required for a blacklist entry."
                ))
            # Force-recompute (compute may not have flushed yet inside the
            # constraint) and then check the stored result.
            if not rec.phone_formatted:
                raise ValidationError(_(
                    "Cannot blacklist a phone number that fails normalization. "
                    "Please enter a valid number."
                ))

    @api.model
    def is_blacklisted(self, phone):
        """Check if a phone number is blacklisted.

        :param phone: Phone number string (any format)
        :return: True if blacklisted
        """
        formatted = wa_phone_format(self.env, phone) or phone
        return bool(self.search([
            ('phone_formatted', '=', formatted),
            ('active', '=', True),
        ], limit=1))

    @api.model
    def add_to_blacklist(self, phone, reason=None):
        """Add a phone number to the blacklist.

        :param phone: Phone number string
        :param reason: Optional reason for blacklisting
        :return: blacklist record
        """
        formatted = wa_phone_format(self.env, phone) or phone
        existing = self.search([('phone_formatted', '=', formatted)], limit=1)
        if existing:
            update = {}
            if not existing.active:
                update['active'] = True
            if reason:
                update['reason'] = reason
            if update:
                existing.write(update)
            return existing
        return self.create({
            'phone': phone,
            'reason': reason or _('Manually blacklisted'),
        })

    @api.model
    def remove_from_blacklist(self, phone):
        """Remove a phone number from the blacklist.

        :param phone: Phone number string
        """
        formatted = wa_phone_format(self.env, phone) or phone
        records = self.search([('phone_formatted', '=', formatted)])
        records.write({'active': False})

    def button_unblacklist(self):
        """Button action to remove from blacklist."""
        self.write({'active': False})
