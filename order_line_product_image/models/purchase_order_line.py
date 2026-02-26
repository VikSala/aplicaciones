from odoo import _, api, fields, models


class PruchaseOrderLine(models.Model):
    _inherit = 'purchase.order.line'
    
    x_product_image_line= fields.Image(related='product_id.image_1920')
