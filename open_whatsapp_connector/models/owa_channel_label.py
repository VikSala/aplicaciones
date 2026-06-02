"""Phase 26B: color-coded labels on WhatsApp Discuss channels."""
from odoo import fields, models


class OwaChannelLabel(models.Model):
    _name = 'owa.channel.label'
    _description = 'WhatsApp Conversation Label'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    color = fields.Integer(default=0,
        help="Color index 0..11 matching Odoo's standard tag widget palette.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    description = fields.Char()
    company_id = fields.Many2one('res.company', default=lambda s: s.env.company)

    _sql_constraints = [
        ('uniq_name_company',
         'unique(name, company_id)',
         'Label names must be unique per company.'),
    ]
