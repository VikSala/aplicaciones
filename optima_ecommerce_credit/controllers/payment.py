from odoo.addons.website_sale.controllers.payment import PaymentPortal as WebsiteSalePaymentPortal


class PaymentPortal(WebsiteSalePaymentPortal):
    def _validate_transaction_for_order(self, transaction, sale_order):
        """Validación backend adicional antes de iniciar el flujo de crédito."""
        super()._validate_transaction_for_order(transaction, sale_order)
        if transaction.provider_code == "optima_credit":
            sale_order._optima_validate_credit_payment(lock_partner=True)
