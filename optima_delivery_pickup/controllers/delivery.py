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
        return {
            "success": True,
            "providers": order_sudo._optima_pickup_get_providers(),
            "point": order_sudo._optima_pickup_selected_point(),
            "resolution": order_sudo._optima_pickup_resolution_payload(),
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

        # Store the selected point first and return quickly. Price/method
        # resolution is intentionally a second request so the checkout can
        # immediately show the chosen point and a loading state while provider
        # APIs are queried.
        order_sudo._optima_pickup_clear_resolution(remove_delivery_line=True)
        stored = order_sudo._optima_pickup_store_point(
            provider_code, point, extra or {}, resolve=False
        )
        return {
            "success": True,
            "point": stored["point"],
            "resolution": stored["resolution"],
            "summary": self._order_summary_values(order_sudo),
        }

    @route(
        "/shop/optima_pickup/resolve",
        type="json",
        auth="public",
        methods=["POST"],
        website=True,
    )
    def optima_pickup_resolve(self):
        order_sudo = request.website.sale_get_order()
        if not order_sudo:
            raise ValidationError(_("El carrito está vacío."))
        self._check_order_can_change_delivery(order_sudo)
        if not order_sudo.optima_pickup_mode or not order_sudo.optima_pickup_external_id:
            raise UserError(_("Selecciona primero un punto de recogida."))

        resolution = order_sudo._optima_pickup_resolve_stored_point()
        return {
            "success": True,
            "point": order_sudo._optima_pickup_selected_point(),
            "resolution": resolution,
            "summary": self._order_summary_values(order_sudo),
        }
