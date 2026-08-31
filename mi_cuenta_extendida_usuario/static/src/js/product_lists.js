/** @odoo-module **/

import { whenReady } from "@odoo/owl";

function clampQuantity(value) {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isFinite(parsed)) {
        return 1;
    }
    return Math.max(1, Math.min(parsed, 9999));
}

function formatMoney(amount, currency) {
    const htmlLang = (document.documentElement.lang || "es-ES").replace("_", "-");
    try {
        return new Intl.NumberFormat(htmlLang, {
            style: "currency",
            currency: currency || "EUR",
        }).format(amount);
    } catch {
        return `${amount.toFixed(2)} ${currency || "€"}`;
    }
}

function setupCartForm(form) {
    const input = form.querySelector(".cabrera-qty-input");
    const total = form.querySelector(".cabrera-product-line-total");
    if (!input || !total) {
        return;
    }

    const unitPrice = Number.parseFloat(form.dataset.unitPrice || "0") || 0;
    const currency = form.dataset.currency || "EUR";

    const refresh = () => {
        const quantity = clampQuantity(input.value);
        input.value = String(quantity);
        total.textContent = formatMoney(unitPrice * quantity, currency);
    };

    form.querySelectorAll("[data-cabrera-qty-action]").forEach((button) => {
        button.addEventListener("click", () => {
            const current = clampQuantity(input.value);
            input.value = String(
                button.dataset.cabreraQtyAction === "increase"
                    ? Math.min(current + 1, 9999)
                    : Math.max(current - 1, 1)
            );
            refresh();
        });
    });

    input.addEventListener("input", refresh);
    input.addEventListener("change", refresh);
    refresh();
}

whenReady(() => {
    document.querySelectorAll(".cabrera-product-cart-form").forEach(setupCartForm);
});
