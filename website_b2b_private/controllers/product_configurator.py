from werkzeug.exceptions import Forbidden

from odoo.http import request, route

from odoo.addons.website_sale.controllers.product_configurator import (
    WebsiteSaleProductConfiguratorController,
)


class WebsiteSaleProductConfiguratorB2B(WebsiteSaleProductConfiguratorController):
    """Do not expose configurator pricing to blocked B2B sessions.

    The standard configurator JSON contains commercial prices. Blocked users
    cannot purchase anyway, so there is no legitimate need to call these
    endpoints before the account is approved.
    """

    @staticmethod
    def _b2b_blocked():
        return bool(request.website and request.website.b2b_is_blocked(user=request.env.user))

    @staticmethod
    def _raise_b2b_forbidden():
        raise Forbidden("La configuración de compra está disponible solo para clientes verificados.")

    @route()
    def website_sale_should_show_product_configurator(self, *args, **kwargs):
        if self._b2b_blocked():
            return False
        return super().website_sale_should_show_product_configurator(*args, **kwargs)

    @route()
    def website_sale_product_configurator_get_values(self, *args, **kwargs):
        if self._b2b_blocked():
            self._raise_b2b_forbidden()
        return super().website_sale_product_configurator_get_values(*args, **kwargs)

    @route()
    def website_sale_product_configurator_create_product(self, *args, **kwargs):
        if self._b2b_blocked():
            self._raise_b2b_forbidden()
        return super().website_sale_product_configurator_create_product(*args, **kwargs)

    @route()
    def website_sale_product_configurator_update_combination(self, *args, **kwargs):
        if self._b2b_blocked():
            self._raise_b2b_forbidden()
        return super().website_sale_product_configurator_update_combination(*args, **kwargs)

    @route()
    def website_sale_product_configurator_get_optional_products(self, *args, **kwargs):
        if self._b2b_blocked():
            self._raise_b2b_forbidden()
        return super().website_sale_product_configurator_get_optional_products(*args, **kwargs)

    @route()
    def website_sale_product_configurator_update_cart(self, *args, **kwargs):
        if self._b2b_blocked():
            self._raise_b2b_forbidden()
        return super().website_sale_product_configurator_update_cart(*args, **kwargs)
