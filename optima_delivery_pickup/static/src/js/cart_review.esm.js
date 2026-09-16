/** @odoo-module **/

import publicWidget from "@web/legacy/js/public/public_widget";

// Only shorten product *labels* in the mobile review cart.  Do not change
// product records, quantity controls, totals or desktop layout.
const QUANTITY_SELECTOR = "input.js_quantity, input[data-line-id].js_quantity";
const PRODUCT_ROW_HINT = "tr, .o_cart_product, .o_cart_line, .o_wsale_cart_line, .o_wsale_cart_product, [data-cart-line-id]";
const PRODUCT_NAME_PATTERN = /^\s*(\[[^\]\r\n]+\])\s+(\S+)(?:\s+([\s\S]+))?\s*$/u;

function shortenProductName(fullName) {
    const name = String(fullName || "").trim();
    const match = name.match(PRODUCT_NAME_PATTERN);
    if (!match || !match[3]?.trim()) {
        return name;
    }
    return `${match[1]} ${match[2]}...`;
}

function getProductTitle(line) {
    const candidates = Array.from(line.querySelectorAll("a[href]"))
        .filter((link) => {
            const href = link.getAttribute("href") || "";
            return (href.includes("/shop/product/") || /^\/shop\/(?!cart|checkout|payment)/.test(href))
                && PRODUCT_NAME_PATTERN.test((link.textContent || "").trim());
        });
    if (candidates.length) {
        return candidates.sort((a, b) => b.textContent.length - a.textContent.length)[0];
    }
    return Array.from(line.querySelectorAll(
        ".o_wsale_product_name, .o_cart_product_name, [itemprop='name'], strong, h5, h6"
    )).find((element) => PRODUCT_NAME_PATTERN.test((element.textContent || "").trim())
        && !element.querySelector("a, button, input, .css_quantity, .oe_currency_value")) || null;
}

function getProductRow(input) {
    const hinted = input.closest(PRODUCT_ROW_HINT);
    if (hinted?.querySelector("img") && getProductTitle(hinted)
            && hinted.querySelectorAll(QUANTITY_SELECTOR).length === 1) {
        return hinted;
    }
    let node = input.parentElement;
    for (let depth = 0; node && depth < 9; depth++, node = node.parentElement) {
        if (node.querySelectorAll(QUANTITY_SELECTOR).length !== 1) {
            break;
        }
        if (node.querySelector("img") && getProductTitle(node)) {
            return node;
        }
    }
    return null;
}

// Preserve the element containing the link and its styling (typically an <a>
// around <strong>). Only replace the innermost single text-bearing node.
function getTextHost(title) {
    let host = title;
    while (host.children.length === 1 && !Array.from(host.childNodes).some(
        (node) => node.nodeType === 3 && node.textContent.trim()
    )) {
        const child = host.firstElementChild;
        if (!child || child.matches("a, button, input, img, svg, .css_quantity")) {
            break;
        }
        host = child;
    }
    // Never remove nested controls or links when abbreviating a title.
    if (host.querySelector("a, button, input, img, svg, .css_quantity")) {
        return null;
    }
    return host;
}

publicWidget.registry.OptimaPickupCartReview = publicWidget.Widget.extend({
    selector: "body",

    start() {
        const result = this._super.apply(this, arguments);
        this._shortenedNames = new Map();
        this._scheduledCartRefresh = false;
        this._refreshCartReview = () => {
            if (this._scheduledCartRefresh) {
                return;
            }
            this._scheduledCartRefresh = true;
            window.requestAnimationFrame(() => {
                this._scheduledCartRefresh = false;
                this._updateCartTitles();
            });
        };
        if (window.location.pathname.startsWith("/shop")) {
            this._refreshCartReview();
            // Odoo replaces cart rows after quantity changes. Reapply only to new
            // rows. Our one-time text replacement cannot produce an observer loop.
            this._cartReviewObserver = new MutationObserver(this._refreshCartReview);
            this._cartReviewObserver.observe(document.body, {subtree: true, childList: true});
            window.addEventListener("resize", this._refreshCartReview);
        }
        return result;
    },

    _updateCartTitles() {
        const isMobile = window.matchMedia("(max-width: 575.98px)").matches;
        // Restore complete titles when switching from mobile to desktop.
        for (const [host, saved] of this._shortenedNames) {
            if (!host.isConnected) {
                this._shortenedNames.delete(host);
            } else if (!isMobile) {
                host.textContent = saved.fullName;
                if (saved.hadTitle) {
                    saved.title.setAttribute("title", saved.previousTitle);
                } else {
                    saved.title.removeAttribute("title");
                }
                this._shortenedNames.delete(host);
            }
        }
        if (!isMobile) {
            return;
        }
        for (const input of document.querySelectorAll(QUANTITY_SELECTOR)) {
            const row = getProductRow(input);
            const title = row && getProductTitle(row);
            if (!title) {
                continue;
            }
            const host = getTextHost(title);
            if (!host) {
                continue;
            }
            const saved = this._shortenedNames.get(host);
            if (saved && host.textContent === saved.shortName) {
                continue;
            }
            const fullName = (host.textContent || "").trim();
            const shortName = shortenProductName(fullName);
            if (fullName === shortName) {
                continue;
            }
            this._shortenedNames.set(host, {
                title,
                fullName,
                shortName,
                hadTitle: title.hasAttribute("title"),
                previousTitle: title.getAttribute("title"),
            });
            title.setAttribute("title", fullName);
            host.textContent = shortName;
        }
    },

    destroy() {
        this._cartReviewObserver?.disconnect();
        if (this._refreshCartReview) {
            window.removeEventListener("resize", this._refreshCartReview);
        }
        for (const [host, saved] of this._shortenedNames || []) {
            if (host.isConnected) {
                host.textContent = saved.fullName;
                if (saved.hadTitle) {
                    saved.title.setAttribute("title", saved.previousTitle);
                } else {
                    saved.title.removeAttribute("title");
                }
            }
        }
        this._shortenedNames?.clear();
        return this._super.apply(this, arguments);
    },
});
