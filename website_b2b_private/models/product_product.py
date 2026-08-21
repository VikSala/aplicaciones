from odoo import models


class ProductProduct(models.Model):
    _inherit = "product.product"

    def _website_show_quick_add(self):
        """Hide all standard Odoo quick-add buttons for blocked users.

        This method is reused by /shop optional quick-add and by the standard
        dynamic product snippets, so keeping the rule here avoids duplicating
        QWeb conditions across many card templates.
        """
        self.ensure_one()
        website = self.env["website"].get_current_website()
        if website and website.b2b_is_blocked(user=self.env.user):
            return False
        return super()._website_show_quick_add()

    def _is_add_to_cart_allowed(self):
        """Backend permission check used by website_sale before adding items."""
        self.ensure_one()
        website = self.env["website"].get_current_website()
        if website and website.b2b_is_blocked(user=self.env.user):
            return False
        return super()._is_add_to_cart_allowed()
