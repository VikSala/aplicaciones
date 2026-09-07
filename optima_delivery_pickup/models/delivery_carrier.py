from odoo import fields, models


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    optima_pickup_provider_code = fields.Char(
        string="Proveedor de punto de recogida",
        compute="_compute_optima_pickup_provider_code",
        help=(
            "Código técnico del proveedor que aporta puntos de recogida. "
            "Los módulos adaptadores lo establecen dinámicamente."
        ),
    )

    def _compute_optima_pickup_provider_code(self):
        for carrier in self:
            carrier.optima_pickup_provider_code = carrier._optima_pickup_get_provider_code()

    def _optima_pickup_get_provider_code(self):
        self.ensure_one()
        return False
