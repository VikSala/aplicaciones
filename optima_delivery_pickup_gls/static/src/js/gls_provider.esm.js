/** @odoo-module **/

import {rpc} from "@web/core/network/rpc";
import publicWidget from "@web/legacy/js/public/public_widget";
import {registerPickupProvider} from "@optima_delivery_pickup/js/provider_registry.esm";

const pickupCheckout = publicWidget.registry.OptimaPickupCheckout;
if (pickupCheckout) {
    pickupCheckout.include({
        _brandMarkerAsset(point) {
            const inherited = this._super(...arguments);
            if (inherited) {
                return inherited;
            }
            const raw = [
                point?.carrier_code,
                point?.carrier_name,
                point?.provider_code,
                point?.provider_name,
            ].filter(Boolean).join(" ").toLowerCase().replace(/[^a-z0-9]+/g, "_");
            if (raw.includes("gls")) {
                return "/optima_delivery_pickup_gls/static/src/img/markers/gls.png";
            }
            return "";
        },
    });
}

registerPickupProvider("gls", {
    async searchPoints({query, radiusM}) {
        // GLS' locator has no browser-safe public API. Going through the generic
        // Odoo provider endpoint keeps the SOAP call server-side. Registering a
        // browser provider here still matters: it makes this RPC start in
        // parallel with Sendcloud's direct Service Points request.
        return await rpc("/shop/optima_pickup/search_points", {
            provider_codes: ["gls"],
            query,
            radius_m: radiusM,
        });
    },

    async open({onError}) {
        // The normal UX is the Optima unified Leaflet map. This callback only
        // exists because the provider registry requires an emergency opener.
        onError?.("GLS ParcelShop se selecciona desde el mapa unificado de puntos de recogida.");
    },
});
