from odoo import models


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    def _optima_pickup_get_provider_code(self):
        """Expose only real GLS ParcelShop delivery methods to pickup checkout.

        GLS uses shipping time 19 for ParcelShop deliveries. Keeping ordinary
        GLS methods out of the pickup provider prevents a normal home-delivery
        carrier from being selected accidentally for a ParcelShop.
        """
        self.ensure_one()
        code = super()._optima_pickup_get_provider_code()
        if code:
            return code
        if self.delivery_type == "gls_asm" and self.gls_asm_shiptime == "19":
            return "gls"
        return False
