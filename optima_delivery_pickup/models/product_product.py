from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductProduct(models.Model):
    _inherit = "product.product"

    shipping_length_mm = fields.Float(
        string="Largo",
        digits=(16, 2),
        help="Largo físico de una unidad del producto, expresado en milímetros.",
    )
    shipping_width_mm = fields.Float(
        string="Ancho",
        digits=(16, 2),
        help="Ancho físico de una unidad del producto, expresado en milímetros.",
    )
    shipping_height_mm = fields.Float(
        string="Alto",
        digits=(16, 2),
        help="Alto físico de una unidad del producto, expresado en milímetros.",
    )

    @api.constrains("shipping_length_mm", "shipping_width_mm", "shipping_height_mm")
    def _check_shipping_dimensions_non_negative(self):
        for product in self:
            if any(
                value < 0
                for value in (
                    product.shipping_length_mm,
                    product.shipping_width_mm,
                    product.shipping_height_mm,
                )
            ):
                raise ValidationError(_("Las dimensiones logísticas no pueden ser negativas."))
