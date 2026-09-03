from odoo import _, models
from odoo.exceptions import ValidationError

from ..controllers.main import OptimaCreditController


class PaymentTransaction(models.Model):
    _inherit = "payment.transaction"

    def _get_specific_rendering_values(self, processing_values):
        res = super()._get_specific_rendering_values(processing_values)
        if self.provider_code != "optima_credit":
            return res
        return {
            "api_url": OptimaCreditController._process_url,
            "reference": self.reference,
        }

    def _get_tx_from_notification_data(self, provider_code, notification_data):
        tx = super()._get_tx_from_notification_data(provider_code, notification_data)
        if provider_code != "optima_credit" or len(tx) == 1:
            return tx

        reference = notification_data.get("reference")
        tx = self.search(
            [
                ("reference", "=", reference),
                ("provider_code", "=", "optima_credit"),
            ]
        )
        if not tx:
            raise ValidationError(
                _(
                    "Pago a Crédito: no se ha encontrado una transacción con la "
                    "referencia %s.",
                    reference,
                )
            )
        return tx

    def _process_notification_data(self, notification_data):
        super()._process_notification_data(notification_data)
        if self.provider_code != "optima_credit":
            return

        self.ensure_one()
        orders = self.sale_order_ids
        if not orders:
            self._set_error(_("Pago a Crédito: la transacción no tiene pedido asociado."))
            return

        # El flujo website_sale normal crea una transacción para un único pedido.
        # Si por una personalización hubiera varios, se validan todos antes de
        # confirmar ninguno.
        try:
            for order in orders.filtered(lambda so: so.state in ("draft", "sent")):
                order._optima_validate_credit_payment(lock_partner=True)
        except ValidationError as error:
            self._set_error(str(error))
            return

        cancelled_orders = orders.filtered(lambda so: so.state == "cancel")
        if cancelled_orders:
            self._set_error(_("Pago a Crédito: el pedido ha sido cancelado."))
            return

        orders.filtered(lambda so: so.state in ("draft", "sent")).action_confirm()
        self._set_pending(
            _(
                "Pedido confirmado con Pago a Crédito. El importe queda pendiente "
                "de facturación/cobro según las condiciones acordadas."
            )
        )
