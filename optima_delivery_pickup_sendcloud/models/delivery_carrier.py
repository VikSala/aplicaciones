from odoo import models


class DeliveryCarrier(models.Model):
    _inherit = "delivery.carrier"

    def _optima_pickup_get_provider_code(self):
        self.ensure_one()
        code = super()._optima_pickup_get_provider_code()
        if code:
            return code
        if (
            self.delivery_type == "sendcloud"
            and self.sendcloud_service_point_required
            and self.sendcloud_integration_id
            and self.sendcloud_integration_id.active
            and self.sendcloud_integration_id.service_point_enabled
        ):
            return "sendcloud"
        return False
