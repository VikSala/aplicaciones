from odoo import models


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _b2b_has_unavailable_price(self, website=None):
        self.ensure_one()
        website = website or self.env["website"].get_current_website()
        return bool(
            website
            and website.b2b_is_price_unavailable(product_variant=self)
        )

    def _website_show_quick_add(self):
        """Hide quick-add for blocked B2B users and VZ products without cost."""
        self.ensure_one()
        website = self.env["website"].get_current_website()
        if website and (
            website.b2b_is_blocked(user=self.env.user)
            or self._b2b_has_unavailable_price(website=website)
        ):
            return False
        return super()._website_show_quick_add()

    def _is_add_to_cart_allowed(self):
        """Hard product-level guard for blocked or price-unavailable products."""
        self.ensure_one()
        website = self.env["website"].get_current_website()
        if website and (
            website.b2b_is_blocked(user=self.env.user)
            or self._b2b_has_unavailable_price(website=website)
        ):
            return False
        return super()._is_add_to_cart_allowed()
