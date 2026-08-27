/** @odoo-module **/

import { whenReady } from "@odoo/owl";

whenReady(() => {
    const sameBilling = document.querySelector("#cabrera_same_billing");
    const billingPanel = document.querySelector("#cabrera_billing_panel");

    if (!sameBilling || !billingPanel) {
        return;
    }

    const refreshBillingVisibility = () => {
        billingPanel.classList.toggle("d-none", sameBilling.checked);
        billingPanel.setAttribute("aria-hidden", sameBilling.checked ? "true" : "false");
    };

    sameBilling.addEventListener("change", refreshBillingVisibility);
    refreshBillingVisibility();
});
