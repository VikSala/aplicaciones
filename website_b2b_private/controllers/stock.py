from werkzeug.exceptions import Forbidden

from odoo.http import request, route

from odoo.addons.website_sale_stock.controllers.main import WebsiteSaleStock


class WebsiteSaleStockB2B(WebsiteSaleStock):
    """Block stock-notification actions for non-approved B2B visitors/users."""

    @route()
    def add_stock_email_notification(self, *args, **kwargs):
        if request.website and request.website.b2b_is_blocked(user=request.env.user):
            raise Forbidden("Stock availability is private for non-approved B2B users.")
        return super().add_stock_email_notification(*args, **kwargs)
