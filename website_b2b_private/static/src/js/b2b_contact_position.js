/** @odoo-module **/

/**
 * Place Odoo's native zero-price contact CTA immediately below the custom
 * "Disponibilidad en nuestros almacenes" heading for blocked B2B users.
 *
 * We move the existing #contact_us_wrapper instead of cloning/recreating it.
 * That keeps the standard Odoo CTA behaviour and gives both public visitors
 * and registered-but-unverified users the exact same DOM/layout.
 */

const STOCK_HEADING_TEXT = "disponibilidad en nuestros almacenes";

function normalizeText(value) {
    return (value || "")
        .replace(/\s+/g, " ")
        .trim()
        .toLocaleLowerCase();
}

function findStockHeading() {
    const preferred = document.querySelectorAll(".tp-hook-terms h6");
    for (const heading of preferred) {
        if (normalizeText(heading.textContent).includes(STOCK_HEADING_TEXT)) {
            return heading;
        }
    }

    // Fallback in case the custom classes are edited later.
    for (const heading of document.querySelectorAll("h1, h2, h3, h4, h5, h6")) {
        if (normalizeText(heading.textContent).includes(STOCK_HEADING_TEXT)) {
            return heading;
        }
    }
    return null;
}

function positionContactCTA() {
    const body = document.body;
    if (!body || body.dataset.b2bCartDisabled !== "1") {
        return;
    }

    const wrapper = document.getElementById("contact_us_wrapper");
    const heading = findStockHeading();
    if (!wrapper || !heading) {
        return;
    }

    if (heading.nextElementSibling !== wrapper) {
        heading.insertAdjacentElement("afterend", wrapper);
    }
    wrapper.classList.add("b2b-stock-contact-positioned");
}

function startContactPositioning() {
    positionContactCTA();

    // website_sale can re-render CTA/variant fragments. Re-apply the position
    // if that happens, without polling.
    let scheduled = false;
    const observer = new MutationObserver(() => {
        if (scheduled) {
            return;
        }
        scheduled = true;
        window.requestAnimationFrame(() => {
            scheduled = false;
            positionContactCTA();
        });
    });
    observer.observe(document.body, { childList: true, subtree: true });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", startContactPositioning, { once: true });
} else {
    startContactPositioning();
}
