from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = "product.template"

    ontime_length_cm = fields.Float(
        string="OnTime Length (cm)",
        digits=(16, 2),
        help="Product length used to estimate OnTime dimensional restrictions and volumetric weight.",
    )
    ontime_width_cm = fields.Float(
        string="OnTime Width (cm)",
        digits=(16, 2),
        help="Product width used to estimate OnTime dimensional restrictions and volumetric weight.",
    )
    ontime_height_cm = fields.Float(
        string="OnTime Height (cm)",
        digits=(16, 2),
        help="Product height used to estimate OnTime dimensional restrictions and volumetric weight.",
    )

    @api.constrains("ontime_length_cm", "ontime_width_cm", "ontime_height_cm")
    def _check_ontime_dimensions(self):
        for product in self:
            if any(value < 0 for value in (
                product.ontime_length_cm,
                product.ontime_width_cm,
                product.ontime_height_cm,
            )):
                raise ValidationError(_("OnTime product dimensions cannot be negative."))
