from werkzeug.exceptions import Forbidden

from odoo.http import request, route

from odoo.addons.website_sale.controllers.payment import PaymentPortal


class PaymentPortalB2B(PaymentPortal):
    """Stop transaction creation for blocked B2B website users."""

    @route()
    def shop_payment_transaction(self, *args, **kwargs):
        if request.website and request.website.b2b_is_blocked(user=request.env.user):
            raise Forbidden("B2B account is not authorized to create a payment transaction.")
        return super().shop_payment_transaction(*args, **kwargs)
