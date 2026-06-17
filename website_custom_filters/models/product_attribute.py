from odoo import fields, models

class ProductAttribute(models.Model):
    _inherit = 'product.attribute'

    display_type = fields.Selection(selection_add=[
        ('range', 'Rango Numérico')
    ], ondelete={'range': 'set default'})

    range_min = fields.Float(string="Mínimo para el Slider", default=0.0)
    range_max = fields.Float(string="Máximo para el Slider", default=100.0)