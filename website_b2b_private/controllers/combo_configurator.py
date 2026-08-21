from werkzeug.exceptions import Forbidden

from odoo.http import request, route

from odoo.addons.website_sale.controllers.combo_configurator import (
    WebsiteSaleComboConfiguratorController,
)


class WebsiteSaleComboConfiguratorB2B(WebsiteSaleComboConfiguratorController):
    """Prevent combo-configurator price responses for blocked B2B users."""

    @staticmethod
    def _b2b_blocked():
        return bool(request.website and request.website.b2b_is_blocked(user=request.env.user))

    @staticmethod
    def _raise_b2b_forbidden():
        raise Forbidden("La configuración de compra está disponible solo para clientes verificados.")

    @route()
    def website_sale_combo_configurator_get_data(self, *args, **kwargs):
        if self._b2b_blocked():
            self._raise_b2b_forbidden()
        return super().website_sale_combo_configurator_get_data(*args, **kwargs)

    @route()
    def website_sale_combo_configurator_get_price(self, *args, **kwargs):
        if self._b2b_blocked():
            self._raise_b2b_forbidden()
        return super().website_sale_combo_configurator_get_price(*args, **kwargs)

    @route()
    def website_sale_combo_configurator_update_cart(self, *args, **kwargs):
        if self._b2b_blocked():
            self._raise_b2b_forbidden()
        return super().website_sale_combo_configurator_update_cart(*args, **kwargs)
