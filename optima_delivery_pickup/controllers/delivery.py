from odoo import _
from odoo.exceptions import UserError, ValidationError
from odoo.http import request, route
from odoo.addons.website_sale.controllers.delivery import Delivery


class OptimaPickupDelivery(Delivery):

    def _prepare_checkout_page_values(self, order_sudo, **kwargs):
        """Add pickup values to the initial /shop/checkout rendering."""
        values = super()._prepare_checkout_page_values(order_sudo, **kwargs)
        values.update(order_sudo._optima_pickup_checkout_values())
        return values

    def _get_additional_delivery_context(self):
        values = super()._get_additional_delivery_context()
        order_sudo = request.website.sale_get_order()
        if order_sudo:
            values.update(order_sudo._optima_pickup_checkout_values())
        else:
            values.update(
                {
                    "optima_pickup_available": False,
                    "optima_pickup_selected": False,
                    "optima_pickup_provider_codes": [],
                    "optima_pickup_point": {},
                    "optima_pickup_resolved": False,
                    "optima_pickup_price": 0.0,
                    "optima_pickup_currency": "EUR",
                    "optima_pickup_delivery_carrier_name": "",
                    "optima_pickup_resolution_message": "",
                }
            )
        return values

    @staticmethod
    def _check_order_can_change_delivery(order_sudo):
        for tx_sudo in order_sudo.transaction_ids:
            if tx_sudo.state not in ("draft", "cancel", "error"):
                raise UserError(
                    _(
                        "Ya existe una transacción para este pedido y no se puede cambiar el método de entrega."
                    )
                )

    @route(
        "/shop/optima_pickup/state",
        type="json",
        auth="public",
        methods=["POST"],
        website=True,
    )
    def optima_pickup_state(self):
        order_sudo = request.website.sale_get_order()
        if not order_sudo:
            raise ValidationError(_("El carrito está vacío."))
        order_sudo._optima_pickup_ensure_current_state()
        return {
            "success": True,
            "providers": order_sudo._optima_pickup_get_providers(),
            "point": order_sudo._optima_pickup_selected_point(),
            "resolution": order_sudo._optima_pickup_resolution_payload(),
            "summary": self._order_summary_values(order_sudo),
        }

    @route(
        "/shop/optima_pickup/select_mode",
        type="json",
        auth="public",
        methods=["POST"],
        website=True,
    )
    def optima_pickup_select_mode(self):
        order_sudo = request.website.sale_get_order()
        if not order_sudo:
            raise ValidationError(_("El carrito está vacío."))
        self._check_order_can_change_delivery(order_sudo)

        providers = order_sudo._optima_pickup_get_providers()

        # Durante el desarrollo el modo pickup puede seleccionarse aunque no
        # haya proveedores. La opción genérica se mantiene siempre visible.
        order_sudo._remove_delivery_line()
        order_sudo.write({"carrier_id": False})
        order_sudo._optima_pickup_clear_selection(keep_mode=True)
        return {
            "success": True,
            "summary": self._order_summary_values(order_sudo),
            "providers": providers,
            "point": {},
            "resolution": order_sudo._optima_pickup_resolution_payload(),
        }

    @route(
        "/shop/optima_pickup/clear_mode",
        type="json",
        auth="public",
        methods=["POST"],
        website=True,
    )
    def optima_pickup_clear_mode(self):
        order_sudo = request.website.sale_get_order()
        if not order_sudo:
            return {"success": True}
        order_sudo._optima_pickup_clear_selection(keep_mode=False)
        return {"success": True}

    @route(
        "/shop/optima_pickup/set_point",
        type="json",
        auth="public",
        methods=["POST"],
        website=True,
    )
    def optima_pickup_set_point(self, provider_code=None, point=None, extra=None):
        order_sudo = request.website.sale_get_order()
        if not order_sudo:
            raise ValidationError(_("El carrito está vacío."))
        self._check_order_can_change_delivery(order_sudo)
        if not order_sudo.optima_pickup_mode:
            raise UserError(_("Selecciona primero la opción Punto de recogida."))
        if not provider_code or not isinstance(point, dict):
            raise ValidationError(_("El punto de recogida recibido no es válido."))

        available_codes = {
            provider["code"] for provider in order_sudo._optima_pickup_get_providers()
        }
        if provider_code not in available_codes:
            raise UserError(_("Ese proveedor de puntos ya no está disponible para el pedido."))

        # Resolve in the same RPC that stores the point. The frontend already
        # renders a local preview and spinner before this request starts, so a
        # second controller route is unnecessary. Keeping store + validation +
        # rating together also preserves provider-specific callback data (for
        # example Sendcloud post_number) exactly as in the proven 0.3.2 flow.
        stored = order_sudo._optima_pickup_store_point(
            provider_code, point, extra or {}, resolve=True
        )
        return {
            "success": True,
            "point": stored["point"],
            "resolution": stored["resolution"],
            "summary": self._order_summary_values(order_sudo),
        }
