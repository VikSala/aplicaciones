from odoo import api, fields, models


class PaymentProvider(models.Model):
    _inherit = "payment.provider"

    code = fields.Selection(
        selection_add=[("optima_credit", "Pago a Crédito")],
        ondelete={"optima_credit": "set default"},
    )

    @api.model
    def _get_compatible_providers(
        self,
        company_id,
        partner_id,
        amount,
        currency_id=None,
        force_tokenization=False,
        is_express_checkout=False,
        is_validation=False,
        report=None,
        sale_order_id=None,
        **kwargs,
    ):
        """Mostrar Pago a Crédito solo para un PV Ecommerce realmente elegible.

        El filtro visual es deliberadamente conservador. La misma condición se
        vuelve a validar en backend cuando se crea/procesa la transacción.
        """
        all_providers = super()._get_compatible_providers(
            company_id,
            partner_id,
            amount,
            currency_id=currency_id,
            force_tokenization=force_tokenization,
            is_express_checkout=is_express_checkout,
            is_validation=is_validation,
            report=report,
            sale_order_id=sale_order_id,
            **kwargs,
        )

        credit_providers = all_providers.filtered(
            lambda provider: provider.code == "optima_credit"
        )
        providers = all_providers - credit_providers

        # Este medio de pago es exclusivo de pedidos de venta Ecommerce y no
        # soporta validaciones, tokenización ni checkout exprés.
        if (
            not sale_order_id
            or force_tokenization
            or is_express_checkout
            or is_validation
            or not credit_providers
        ):
            return providers

        order = self.env["sale.order"].sudo().browse(sale_order_id).exists()
        if (
            order
            and order.company_id.id == company_id
            and order._optima_can_pay_on_credit()
        ):
            providers += credit_providers

        return providers

    def _get_default_payment_method_codes(self):
        default_codes = super()._get_default_payment_method_codes()
        if self.code == "optima_credit":
            return default_codes | {"optima_credit"}
        return default_codes
