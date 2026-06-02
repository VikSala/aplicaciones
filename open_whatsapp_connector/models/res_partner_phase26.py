"""Phase 26I: opt-in tracking on res.partner — required for compliant
outbound campaigns under WhatsApp's business policy."""
from odoo import api, fields, models, _


class ResPartnerOwaPhase26(models.Model):
    _inherit = 'res.partner'

    wa_is_opted_in = fields.Boolean(
        string="WhatsApp opted-in", default=False, tracking=True,
        help="Customer has explicitly opted in to receiving WhatsApp messages "
             "from this organisation. Outbound campaigns skip non-opted-in "
             "partners by default.")
    wa_opt_in_at = fields.Datetime(string="Opted-in at", readonly=True)
    wa_opt_in_source = fields.Char(
        string="Opt-in source", readonly=True,
        help="Where this opt-in was captured: manual / form / SO / chatbot etc.")

    @api.model
    def opt_in(self, partner, source='manual'):
        partner.write({
            'wa_is_opted_in': True,
            'wa_opt_in_at': fields.Datetime.now(),
            'wa_opt_in_source': source,
        })

    def write(self, vals):
        # Track manual opt-in toggles
        if 'wa_is_opted_in' in vals and vals['wa_is_opted_in']:
            for rec in self.filtered(lambda p: not p.wa_is_opted_in):
                vals.setdefault('wa_opt_in_at', fields.Datetime.now())
                vals.setdefault('wa_opt_in_source', 'manual')
        return super().write(vals)
