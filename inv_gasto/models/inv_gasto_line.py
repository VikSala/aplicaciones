from odoo import models, fields, api

class InvGastoLine(models.Model):
    _name = 'inv.gasto.line'
    _description = 'Línea de Gasto'

    gasto_id = fields.Many2one('inv.gasto',string='Gasto Referencia', ondelete='cascade')
    product_id = fields.Many2one('product.product', string='Producto', required=True)
    quantity = fields.Float(string='Cantidad', default=1.0)
    price_unit = fields.Float(string='Precio Unitario', related='product_id.standard_price', readonly=False)
    subtotal = fields.Float(string='Subtotal', compute='_compute_subtotal', store=True)
    stock_move_id = fields.Many2one('stock.move', string='Mov. Stock', readonly=True)

    @api.depends('quantity', 'price_unit')
    def _compute_subtotal(self):
        for line in self:
            line.subtotal = line.quantity * line.price_unit