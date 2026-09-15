from odoo import _, models
from odoo.exceptions import ValidationError


class StockPicking(models.Model):
    _inherit = "stock.picking"

    def _optima_delivery_provider_preflight(self):
        result = super()._optima_delivery_provider_preflight()
        self.ensure_one()
        if self.optima_delivery_pickup_provider_code != "gls":
            return result
        if self.carrier_id.delivery_type != "gls_asm" or self.carrier_id.gls_asm_shiptime != "19":
            raise ValidationError(
                _(
                    "La expedición GLS ParcelShop no está asociada a un método GLS con Horario 19."
                )
            )
        point_code = str(self.optima_delivery_pickup_external_id or "").strip()
        if not point_code:
            raise ValidationError(
                _("Falta el código GLS del ParcelShop seleccionado en la expedición.")
            )
        if self.carrier_id.gls_is_pickup_service:
            raise ValidationError(
                _(
                    "El servicio GLS configurado es un servicio de recogida, no una entrega "
                    "a ParcelShop. Revisa el Servicio GLS del método de envío."
                )
            )
        return result
