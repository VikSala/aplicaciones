from werkzeug.exceptions import Forbidden

from odoo.http import request, route

from odoo.addons.website_sale_collect.controllers.delivery import InStoreDelivery


class DeliveryB2B(InStoreDelivery):
    """Prevent delivery/express-checkout calls on a blocked B2B cart."""

    @staticmethod
    def _b2b_ensure_purchase_allowed():
        if request.website and request.website.b2b_is_blocked(user=request.env.user):
            raise Forbidden("B2B account is not authorized to checkout.")

    @route()
    def shop_delivery_methods(self, *args, **kwargs):
        self._b2b_ensure_purchase_allowed()
        return super().shop_delivery_methods(*args, **kwargs)

    @route()
    def shop_set_delivery_method(self, *args, **kwargs):
        self._b2b_ensure_purchase_allowed()
        return super().shop_set_delivery_method(*args, **kwargs)

    @route()
    def shop_get_delivery_rate(self, *args, **kwargs):
        self._b2b_ensure_purchase_allowed()
        return super().shop_get_delivery_rate(*args, **kwargs)

    @route()
    def website_sale_set_pickup_location(self, *args, **kwargs):
        self._b2b_ensure_purchase_allowed()
        return super().website_sale_set_pickup_location(*args, **kwargs)

    @route()
    def website_sale_get_pickup_locations(self, *args, **kwargs):
        self._b2b_ensure_purchase_allowed()
        return super().website_sale_get_pickup_locations(*args, **kwargs)

    @route()
    def shop_set_click_and_collect_location(self, *args, **kwargs):
        self._b2b_ensure_purchase_allowed()
        return super().shop_set_click_and_collect_location(*args, **kwargs)

    @route()
    def express_checkout_process_delivery_address(self, *args, **kwargs):
        self._b2b_ensure_purchase_allowed()
        return super().express_checkout_process_delivery_address(*args, **kwargs)
