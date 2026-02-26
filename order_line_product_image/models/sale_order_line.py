from odoo import _, api, fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'
    
    x_product_image_line= fields.Image(related='product_id.image_1920')
