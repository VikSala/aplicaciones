from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    shipping_length_mm = fields.Float(
        string="Largo",
        compute="_compute_shipping_length_mm",
        inverse="_set_shipping_length_mm",
        store=True,
        digits=(16, 2),
        help="Largo físico de una unidad del producto, expresado en milímetros.",
    )
    shipping_width_mm = fields.Float(
        string="Ancho",
        compute="_compute_shipping_width_mm",
        inverse="_set_shipping_width_mm",
        store=True,
        digits=(16, 2),
        help="Ancho físico de una unidad del producto, expresado en milímetros.",
    )
    shipping_height_mm = fields.Float(
        string="Alto",
        compute="_compute_shipping_height_mm",
        inverse="_set_shipping_height_mm",
        store=True,
        digits=(16, 2),
        help="Alto físico de una unidad del producto, expresado en milímetros.",
    )

    @api.depends("product_variant_ids.shipping_length_mm")
    def _compute_shipping_length_mm(self):
        self._compute_template_field_from_variant_field("shipping_length_mm")

    def _set_shipping_length_mm(self):
        self._set_product_variant_field("shipping_length_mm")

    @api.depends("product_variant_ids.shipping_width_mm")
    def _compute_shipping_width_mm(self):
        self._compute_template_field_from_variant_field("shipping_width_mm")

    def _set_shipping_width_mm(self):
        self._set_product_variant_field("shipping_width_mm")

    @api.depends("product_variant_ids.shipping_height_mm")
    def _compute_shipping_height_mm(self):
        self._compute_template_field_from_variant_field("shipping_height_mm")

    def _set_shipping_height_mm(self):
        self._set_product_variant_field("shipping_height_mm")

    def _get_related_fields_variant_template(self):
        return super()._get_related_fields_variant_template() + [
            "shipping_length_mm",
            "shipping_width_mm",
            "shipping_height_mm",
        ]

    @api.constrains("shipping_length_mm", "shipping_width_mm", "shipping_height_mm")
    def _check_shipping_dimensions_non_negative(self):
        for template in self:
            if any(
                value < 0
                for value in (
                    template.shipping_length_mm,
                    template.shipping_width_mm,
                    template.shipping_height_mm,
                )
            ):
                raise ValidationError(_("Las dimensiones logísticas no pueden ser negativas."))
