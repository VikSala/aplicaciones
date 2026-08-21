from werkzeug.exceptions import Forbidden

from odoo.http import request, route

from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSaleB2B(WebsiteSale):
    """Block the eCommerce purchase flow for non-approved B2B users.

    Product/catalog browsing remains public. Only cart and checkout operations
    are denied when the central ``website.b2b_can_purchase()`` rule returns
    False.
    """

    @staticmethod
    def _b2b_purchase_blocked():
        return bool(request.website and request.website.b2b_is_blocked(user=request.env.user))

    @staticmethod
    def _b2b_shop_redirect():
        # Phase 5 renders a friendly state-aware notice on /shop.
        return request.redirect('/shop?b2b_purchase_blocked=1')

    def _check_cart(self, order_sudo):
        # Central checkout backstop: /shop/checkout, /shop/address,
        # /shop/confirm_order, /shop/payment and most checkout helpers call it.
        if self._b2b_purchase_blocked():
            return self._b2b_shop_redirect()
        return super()._check_cart(order_sudo)

    @route()
    def cart(self, *args, **kwargs):
        if self._b2b_purchase_blocked():
            return self._b2b_shop_redirect()
        return super().cart(*args, **kwargs)

    @route()
    def cart_update(self, *args, **kwargs):
        if self._b2b_purchase_blocked():
            return self._b2b_shop_redirect()
        return super().cart_update(*args, **kwargs)

    @route()
    def cart_update_json(self, *args, **kwargs):
        if self._b2b_purchase_blocked():
            raise Forbidden("La cuenta B2B todavía no está autorizada para utilizar el carrito.")
        return super().cart_update_json(*args, **kwargs)

    @route()
    def cart_quantity(self, *args, **kwargs):
        # Do not leak an old/saved cart quantity to a blocked session.
        if self._b2b_purchase_blocked():
            return 0
        return super().cart_quantity(*args, **kwargs)

    @route()
    def clear_cart(self, *args, **kwargs):
        if self._b2b_purchase_blocked():
            raise Forbidden("La cuenta B2B todavía no está autorizada para utilizar el carrito.")
        return super().clear_cart(*args, **kwargs)

    @route()
    def is_add_to_cart_allowed(self, *args, **kwargs):
        if self._b2b_purchase_blocked():
            return False
        return super().is_add_to_cart_allowed(*args, **kwargs)

    # Explicit guards for the complete HTTP checkout flow. These duplicate the
    # _check_cart backstop intentionally so future/custom calls cannot bypass it.
    @route()
    def shop_checkout(self, *args, **kwargs):
        if self._b2b_purchase_blocked():
            return self._b2b_shop_redirect()
        return super().shop_checkout(*args, **kwargs)

    @route()
    def shop_address(self, *args, **kwargs):
        if self._b2b_purchase_blocked():
            return self._b2b_shop_redirect()
        return super().shop_address(*args, **kwargs)

    @route()
    def shop_address_submit(self, *args, **kwargs):
        if self._b2b_purchase_blocked():
            raise Forbidden("La cuenta B2B todavía no está autorizada para finalizar pedidos.")
        return super().shop_address_submit(*args, **kwargs)

    @route()
    def shop_update_address(self, *args, **kwargs):
        if self._b2b_purchase_blocked():
            raise Forbidden("La cuenta B2B todavía no está autorizada para finalizar pedidos.")
        return super().shop_update_address(*args, **kwargs)

    @route()
    def shop_confirm_order(self, *args, **kwargs):
        if self._b2b_purchase_blocked():
            return self._b2b_shop_redirect()
        return super().shop_confirm_order(*args, **kwargs)

    @route()
    def extra_info(self, *args, **kwargs):
        if self._b2b_purchase_blocked():
            return self._b2b_shop_redirect()
        return super().extra_info(*args, **kwargs)

    @route()
    def shop_payment(self, *args, **kwargs):
        if self._b2b_purchase_blocked():
            return self._b2b_shop_redirect()
        return super().shop_payment(*args, **kwargs)

    @route()
    def shop_payment_validate(self, *args, **kwargs):
        # Important for zero-total carts: Odoo can validate the order here
        # without creating a normal payment transaction.
        if self._b2b_purchase_blocked():
            return self._b2b_shop_redirect()
        return super().shop_payment_validate(*args, **kwargs)

    @route()
    def express_checkout_shipping_address_compute_taxes(self, *args, **kwargs):
        if self._b2b_purchase_blocked():
            raise Forbidden("La cuenta B2B todavía no está autorizada para finalizar pedidos.")
        return super().express_checkout_shipping_address_compute_taxes(*args, **kwargs)


    # Phase 6: a hidden pricelist selector is not enough. Block manual URL
    # switching so a blocked user cannot force another website pricelist in
    # the session. Verification remains exclusively tied to the partner's
    # assigned commercial pricelist.
    @route()
    def pricelist_change(self, *args, **kwargs):
        if self._b2b_purchase_blocked():
            return request.redirect('/shop')
        return super().pricelist_change(*args, **kwargs)

    @route()
    def pricelist(self, *args, **kwargs):
        if self._b2b_purchase_blocked():
            return request.redirect('/shop')
        return super().pricelist(*args, **kwargs)

    def _get_search_order(self, post):
        """Prevent price-ordering as a relative-price side channel."""
        if self._b2b_purchase_blocked():
            requested_order = post.get('order') or request.website.shop_default_sort or ''
            if 'list_price' in requested_order:
                post = dict(post)
                post['order'] = 'website_sequence asc'
        return super()._get_search_order(post)

    def _get_search_options(
        self, category=None, attrib_values=None, tags=None, min_price=0.0,
        max_price=0.0, conversion_rate=1, **post
    ):
        """Ignore hand-crafted min/max price filters for blocked users.

        The visible range control was already hidden in Phase 2, but without
        this server-side guard a visitor could still infer price bands by
        manually varying ?min_price= / ?max_price= and comparing results.
        """
        if self._b2b_purchase_blocked():
            min_price = 0.0
            max_price = 0.0
            post = dict(post)
            post.pop('min_price', None)
            post.pop('max_price', None)
        return super()._get_search_options(
            category=category,
            attrib_values=attrib_values,
            tags=tags,
            min_price=min_price,
            max_price=max_price,
            conversion_rate=conversion_rate,
            **post,
        )
