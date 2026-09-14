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
        raise ValidationError(
            _(
                "El ParcelShop GLS está seleccionado y validado, pero el envío final a GLS "
                "todavía necesita integrar Destinatario/Codigo en la expedición. "
                "No se ha enviado nada al transportista."
            )
        )
