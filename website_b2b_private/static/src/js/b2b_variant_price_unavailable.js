/** @odoo-module **/

import { WebsiteSale } from "@website_sale/js/website_sale";

/**
 * IMPORTANT:
 * website_sale builds WebsiteSale with Widget.extend(VariantMixin, ...). That
 * copies VariantMixin methods into WebsiteSale when website_sale.js is loaded.
 * Patching VariantMixin afterwards therefore does not replace the method used
 * by the already-created WebsiteSale widget.
 *
 * Extend WebsiteSale itself so this code runs AFTER Odoo's own combination
 * handler (and after website_sale_stock's extension, because this module
 * depends on website_sale_stock).
 *
 * For a verified customer viewing a VZ product whose current variant has zero
 * cost, the dedicated #b2b_product_price_unavailable CTA is the only Contact
 * button we want. Odoo still receives prevent_zero_price_sale=true so its core
 * handler tries to re-show the native #contact_us_wrapper asynchronously.
 * Hide that native wrapper again after the full WebsiteSale chain has run.
 *
 * Public/unverified B2B users intentionally keep the native wrapper because
 * b2b_contact_position.js moves it below "Disponibilidad en nuestros
 * almacenes".
 */
WebsiteSale.include({
    _onChangeCombination: function (ev, $parent, combination) {
        const result = this._super.apply(this, arguments);

        if (combination?.b2b_price_unavailable) {
            // Never expose purchase controls for a product without a usable
            // commercial price, even if website_sale_stock re-opened its CTA
            // wrapper during the same combination update.
            $parent
                .find("#o_wsale_cta_wrapper")
                .removeClass("d-flex")
                .addClass("d-none");
            $parent
                .find("#add_to_cart_wrap")
                .removeClass("d-inline-flex")
                .addClass("d-none");

            const isBlockedB2B = document.body?.dataset?.b2bCartDisabled === "1";
            if (!isBlockedB2B) {
                const $contactUsWrapper = $parent
                    .parents("#product_details")
                    .find("#contact_us_wrapper");
                $contactUsWrapper
                    .removeClass("d-flex")
                    .addClass("d-none");
            }
        }

        return result;
    },
});
