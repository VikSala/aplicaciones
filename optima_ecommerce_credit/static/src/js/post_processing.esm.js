/** @odoo-module **/

import paymentPostProcessing from "@payment/js/post_processing";

paymentPostProcessing.include({
    /**
     * Pago a Crédito permanece en estado pending porque no existe un cobro
     * online inmediato. Para website_sale ese estado debe considerarse final.
     */
    _getFinalStates(providerCode) {
        const finalStates = this._super(...arguments);
        if (providerCode === "optima_credit") {
            finalStates.add("pending");
        }
        return finalStates;
    },
});
