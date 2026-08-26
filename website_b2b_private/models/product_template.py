from odoo import models


class ProductTemplate(models.Model):
    _inherit = "product.template"

    @staticmethod
    def _b2b_sanitize_price_combination_info(values):
        """Neutralize commercial prices in variant/combo JSON payloads."""
        values.update({
            "price": 0.0,
            "list_price": 0.0,
            "price_extra": 0.0,
            "compare_list_price": 0.0,
            "base_unit_price": 0.0,
            "has_discounted_price": False,
            "prevent_zero_price_sale": True,
            "b2b_price_hidden": True,
        })
        return values

    @staticmethod
    def _b2b_sanitize_stock_combination_info(values):
        """Remove real stock data from a blocked B2B combination response."""
        values.update({
            "b2b_stock_hidden": True,
            "free_qty": 0,
            "cart_qty": 0,
            "available_threshold": 0,
            "show_availability": False,
            "out_of_stock_message": "",
            "has_stock_notification": False,
            "stock_notification_email": "",
            "show_click_and_collect_availability": False,
            "b2b_click_collect_hidden": True,
            "is_storable": False,
            "allow_out_of_stock_order": True,
        })
        values.pop("max_combo_quantity", None)
        values.pop("in_store_stock", None)
        return values

    @staticmethod
    def _b2b_sanitize_unavailable_price_info(values):
        """Do not send a usable price for a VZ variant whose cost is zero."""
        values.update({
            "price": 0.0,
            "list_price": 0.0,
            "price_extra": 0.0,
            "compare_list_price": 0.0,
            "base_unit_price": 0.0,
            "has_discounted_price": False,
            "prevent_zero_price_sale": True,
            "b2b_price_unavailable": True,
            # A product without a usable commercial price cannot be reserved
            # through Click & Collect either.
            "show_click_and_collect_availability": False,
        })
        values.pop("in_store_stock", None)
        return values

    @staticmethod
    def _b2b_split_product(product_or_template):
        """Return (template, variant) for a website combination record."""
        if not product_or_template:
            return product_or_template, product_or_template
        if product_or_template._name == "product.product":
            return product_or_template.product_tmpl_id, product_or_template
        if product_or_template._name == "product.template":
            return product_or_template, product_or_template.product_variant_id
        return product_or_template, product_or_template

    def _get_additionnal_combination_info(
        self, product_or_template, quantity, date, website
    ):
        values = super()._get_additionnal_combination_info(
            product_or_template=product_or_template,
            quantity=quantity,
            date=date,
            website=website,
        )

        values["b2b_stock_hidden"] = False
        values["b2b_price_hidden"] = False
        values["b2b_click_collect_hidden"] = False
        values["b2b_price_unavailable"] = False

        template, variant = self._b2b_split_product(product_or_template)
        price_unavailable = bool(
            website
            and website.b2b_is_price_unavailable(
                product=template,
                product_variant=variant,
            )
        )

        if price_unavailable:
            self._b2b_sanitize_unavailable_price_info(values)

        if website and website.b2b_is_blocked(user=self.env.user):
            self._b2b_sanitize_price_combination_info(values)
            self._b2b_sanitize_stock_combination_info(values)
            # Preserve the product-specific flag after the generic B2B
            # sanitizers run so QWeb/JS can distinguish the two situations.
            values["b2b_price_unavailable"] = price_unavailable

        return values

    def _get_additional_configurator_data(
        self, product_or_template, date, currency, pricelist, **kwargs
    ):
        values = super()._get_additional_configurator_data(
            product_or_template,
            date,
            currency,
            pricelist,
            **kwargs,
        )

        website = self.env["website"].get_current_website()
        template, variant = self._b2b_split_product(product_or_template)
        price_unavailable = bool(
            website
            and website.b2b_is_price_unavailable(
                product=template,
                product_variant=variant,
            )
        )

        if price_unavailable:
            for key in (
                "price", "list_price", "price_extra", "compare_list_price",
                "base_unit_price", "strikethrough_price",
            ):
                if key in values:
                    values[key] = 0.0
            values["b2b_price_unavailable"] = True
            values["show_click_and_collect_availability"] = False
            values.pop("in_store_stock", None)
        else:
            values["b2b_price_unavailable"] = False

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
        if website and (
            website.b2b_is_blocked(user=website.env.user)
            or website.b2b_is_price_unavailable(product=self)
        ):
            return "", None
        return super()._search_render_results_prices(mapping, combination_info)
