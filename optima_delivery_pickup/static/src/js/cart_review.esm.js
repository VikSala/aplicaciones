/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

// The Review order cart is not part of #shop_checkout on all Odoo 18 themes.
// Detect the real product elements rather than guessing td/column class names.
const QUANTITY_SELECTOR = "input.js_quantity, input[data-line-id].js_quantity";
const PRODUCT_ROW_HINT = "tr, .o_cart_product, .o_cart_line, .o_wsale_cart_line, .o_wsale_cart_product, [data-cart-line-id]";
const PRODUCT_TITLE_HINT = ".td-product_name, .o_wsale_product_name, .o_cart_product_name, [itemprop='name']";
const CURRENCY_HINT = ".oe_currency_value, .oe_price, [data-oe-type='monetary'], .o_wsale_cart_line_price";

function getProductTitle(line) {
    const links = Array.from(line.querySelectorAll("a[href]"));
    const productLinks = links.filter((link) => {
        const href = link.getAttribute("href") || "";
        const text = (link.textContent || "").trim();
        return (href.includes("/shop/product/") || /^\/shop\/(?!cart|checkout|payment)/.test(href))
            && text.length > 14 && !link.querySelector(".js_quantity");
    });
    if (productLinks.length) {
        return productLinks.sort((a, b) => (b.textContent || "").length - (a.textContent || "").length)[0];
    }
    const named = line.querySelector(PRODUCT_TITLE_HINT);
    if (named && (named.textContent || "").trim().length > 14) {
        return named;
    }
    return Array.from(line.querySelectorAll("strong, h5, h6"))
        .find((item) => (item.textContent || "").trim().length > 16 && !item.closest(".css_quantity"));
}

function getProductRow(input) {
    // Prefer a known cart-line wrapper, but only if it is one product, with an image.
    const hinted = input.closest(PRODUCT_ROW_HINT);
    if (hinted && hinted.querySelector("img") && getProductTitle(hinted)
            && hinted.querySelectorAll(QUANTITY_SELECTOR).length === 1) {
        return hinted;
    }
    let node = input.parentElement;
    for (let depth = 0; node && depth < 9; depth++, node = node.parentElement) {
        if (node.querySelectorAll(QUANTITY_SELECTOR).length !== 1) {
            break;
        }
        if (node.querySelector("img") && getProductTitle(node)
                && node.getBoundingClientRect().width >= 200) {
            return node;
        }
    }
    return null;
}

function getQuantityGroup(input, row) {
    return input.closest(".css_quantity, .oe_website_spinner, .input-group")
        || (input.parentElement !== row ? input.parentElement : input);
}

function findControlsGroup(group, title, row) {
    let candidate = group;
    for (let parent = group.parentElement; parent && parent !== row; parent = parent.parentElement) {
        if (parent.contains(title) || parent.querySelectorAll(QUANTITY_SELECTOR).length !== 1
                || parent.querySelector("img")) {
            break;
        }
        if (parent.querySelector(CURRENCY_HINT) || /(?:€|\bEUR\b)/.test(parent.textContent || "")) {
            candidate = parent;
        }
    }
    return candidate;
}

function findSeparatePrice(row, controls, title) {
    const values = Array.from(row.querySelectorAll(CURRENCY_HINT)).filter((element) =>
        !controls.contains(element) && !title.contains(element)
    );
    if (!values.length) {
        return null;
    }
    const value = values[values.length - 1];
    // Only position the amount, not a wrapping element with the quantity or product.
    let candidate = value;
    while (candidate.parentElement && candidate.parentElement !== row
            && !candidate.parentElement.contains(controls)
            && !candidate.parentElement.contains(title)
            && candidate.parentElement.querySelectorAll(CURRENCY_HINT).length === 1) {
        candidate = candidate.parentElement;
    }
    return candidate;
}

function updateCartLines() {
    if (!window.matchMedia("(max-width: 575.98px)").matches
            || !window.location.pathname.startsWith("/shop")) {
        return;
    }
    for (const input of document.querySelectorAll(QUANTITY_SELECTOR)) {
        // Product-detail quantity widgets have no product line with a picture/name.
        const row = getProductRow(input);
        if (!row) {
            continue;
        }
        const title = getProductTitle(row);
        if (!title) {
            continue;
        }
        const quantity = getQuantityGroup(input, row);
        const controls = findControlsGroup(quantity, title, row);
        const rect = row.getBoundingClientRect();
        const titleX = title.getBoundingClientRect().left;
        const available = Math.max(65, Math.floor(rect.right - titleX - 156));
        row.classList.add("optima_review_line");
        row.style.setProperty("--optima-review-name-width", `${available}px`);
        title.classList.add("optima_review_name");
        const titleParent = title.parentElement;
        if (titleParent && titleParent !== row && !titleParent.contains(controls)) {
            titleParent.classList.add("optima_review_name_container");
        }
        quantity.classList.add("optima_review_quantity");
        controls.classList.add("optima_review_controls");
        if (controls !== quantity) {
            const inlinePrice = controls.querySelector(CURRENCY_HINT);
            if (inlinePrice) {
                inlinePrice.parentElement?.classList.add("optima_review_price_inline");
            }
        }
        const separatePrice = findSeparatePrice(row, controls, title);
        separatePrice?.classList.add("optima_review_price");
    }
}

publicWidget.registry.OptimaPickupCartReview = publicWidget.Widget.extend({
    selector: "body",
    start() {
        const result = this._super.apply(this, arguments);
        this._scheduledCartRefresh = false;
        this._refreshCartReview = () => {
            if (this._scheduledCartRefresh) {
                return;
            }
            this._scheduledCartRefresh = true;
            window.requestAnimationFrame(() => {
                this._scheduledCartRefresh = false;
                updateCartLines();
            });
        };
        if (window.location.pathname.startsWith("/shop")) {
            this._refreshCartReview();
            // website_sale replaces cart fragments when quantity changes. Only observe
            // child additions/removals: CSS class/style updates cannot re-trigger us.
            this._cartReviewObserver = new MutationObserver(this._refreshCartReview);
            this._cartReviewObserver.observe(document.body, {subtree: true, childList: true});
            window.addEventListener("resize", this._refreshCartReview);
        }
        return result;
    },
    destroy() {
        this._cartReviewObserver?.disconnect();
        if (this._refreshCartReview) {
            window.removeEventListener("resize", this._refreshCartReview);
        }
        return this._super.apply(this, arguments);
    },
});
