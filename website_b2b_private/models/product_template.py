from odoo import models


class ProductTemplate(models.Model):
    _inherit = "product.template"


    @staticmethod
    def _b2b_sanitize_price_combination_info(values):
        """Neutralize commercial prices in variant/combo JSON payloads.

        QWeb hiding prevents visual disclosure, but Odoo's combination endpoint
        also sends price fields to the browser and uses list_price in product
        tracking data.  Blocked B2B sessions receive only neutral values.
        """
        values.update({
            "price": 0.0,
            "list_price": 0.0,
            "price_extra": 0.0,
            "compare_list_price": 0.0,
            "base_unit_price": 0.0,
            "has_discounted_price": False,
            # Keep Odoo's native contact mode active independently from the
            # numeric value (1000 EUR) of our blocking pricelist.
            "prevent_zero_price_sale": True,
            "b2b_price_hidden": True,
        })
        return values

    @staticmethod
    def _b2b_sanitize_stock_combination_info(values):
        """Remove real stock data from a website combination response.

        Hiding the availability widget in QWeb/CSS is not sufficient because
        ``website_sale_stock`` sends stock quantities to the browser as part of
        the variant combination JSON.  For blocked B2B users we therefore send
        neutral values and mark the payload as private.

        The neutral keys are deliberately kept instead of blindly deleting all
        of them: Odoo's frontend stock mixin expects several of these names to
        exist while a variant changes.  No real quantity leaves the server.
        """
        values.update({
            "b2b_stock_hidden": True,
            "free_qty": 0,
            "cart_qty": 0,
            "available_threshold": 0,
            "show_availability": False,
            "out_of_stock_message": "",
            "has_stock_notification": False,
            "stock_notification_email": "",
            # Click & Collect is also stock/availability information. Keep its
            # OWL component disabled and never send in-store quantities to a
            # blocked visitor or pending B2B account.
            "show_click_and_collect_availability": False,
            "b2b_click_collect_hidden": True,
            # Make the stock frontend skip quantity/availability logic. The
            # Phase 3 backend cart guards still prevent purchasing.
            "is_storable": False,
            "allow_out_of_stock_order": True,
        })
        # Stock-derived values must not remain in the response.
        values.pop("max_combo_quantity", None)
        values.pop("in_store_stock", None)
        return values

    def _get_additionnal_combination_info(
        self, product_or_template, quantity, date, website
    ):
        values = super()._get_additionnal_combination_info(
            product_or_template=product_or_template,
            quantity=quantity,
            date=date,
            website=website,
        )

        # Always provide flags so frontend/custom code can reference them safely.
        values["b2b_stock_hidden"] = False
        values["b2b_price_hidden"] = False
        values["b2b_click_collect_hidden"] = False

        if website and website.b2b_is_blocked(user=self.env.user):
            # Force Odoo's native contact CTA mode for every blocked B2B
            # visitor, including the public (not logged-in) website user.
            # This flag is controlled by our B2B authorization state, not by
            # the numerical value configured on the blocking pricelist.
            self._b2b_sanitize_price_combination_info(values)
            self._b2b_sanitize_stock_combination_info(values)

        return values

    def _get_additional_configurator_data(
        self, product_or_template, date, currency, pricelist, **kwargs
    ):
        """Do not expose stock-derived configurator quantities either."""
        values = super()._get_additional_configurator_data(
            product_or_template,
            date,
            currency,
            pricelist,
            **kwargs,
        )

        website = self.env["website"].get_current_website()
        if website and website.b2b_is_blocked(user=self.env.user):
            values.pop("free_qty", None)
            values.pop("max_quantity", None)
            for key in (
                "price", "list_price", "price_extra", "compare_list_price",
                "base_unit_price", "strikethrough_price",
            ):
                if key in values:
                    values[key] = 0.0
            values["b2b_stock_hidden"] = True
            values["b2b_price_hidden"] = True
        else:
            values["b2b_stock_hidden"] = False
            values["b2b_price_hidden"] = False

        return values

    def _search_render_results_prices(self, mapping, combination_info):
        """Do not expose product prices through website autocomplete."""
        website = self.env["website"].get_current_website()
        if website and website.b2b_is_blocked(user=website.env.user):
            return "", None
        return super()._search_render_results_prices(mapping, combination_info)
