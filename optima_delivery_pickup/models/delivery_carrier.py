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


    def rate_shipment(self, order):
        """Reuse the resolved pickup rate during standard Odoo refreshes.

        This prevents website_sale from re-querying a technical pickup carrier
        when the customer comes back to checkout. Provider-specific rating is
        performed only by the pickup adapter when the point is selected.
        """
        self.ensure_one()
        if (
            getattr(order, "optima_pickup_mode", False)
            and getattr(order, "optima_pickup_resolved", False)
            and getattr(order, "optima_pickup_delivery_carrier_id", False) == self
        ):
            return {
                "success": True,
                "price": order.optima_pickup_delivery_price or 0.0,
                "error_message": False,
                "warning_message": False,
            }
        return super().rate_shipment(order)
