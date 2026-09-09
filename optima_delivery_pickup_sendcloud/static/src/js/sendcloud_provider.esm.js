/** @odoo-module **/

import {ensureJQuery} from "@web/core/ensure_jquery";
import {loadJS} from "@web/core/assets";
import {registerPickupProvider} from "@optima_delivery_pickup/js/provider_registry.esm";

const PICKER_URL = "/delivery_sendcloud_oca/static/src/lib/sendcloud/api.min.js";

registerPickupProvider("sendcloud", {
    async open({config, currentPoint, onSelect, onError}) {
        try {
            await ensureJQuery();
            await loadJS(PICKER_URL);
        } catch {
            onError("No se ha podido cargar el mapa oficial de Sendcloud.");
            return;
        }

        const api = window.sendcloud;
        if (!api?.servicePoints?.open) {
            onError("El selector de puntos de Sendcloud no está disponible.");
            return;
        }

        const options = {
            apiKey: config.api_key,
            country: config.country,
            postalCode: config.postal_code,
            city: config.city,
            language: config.language || "es-es",
        };
        // Phase 2 can narrow the hosted picker to the concrete offer/carrier
        // the customer is evaluating. Without this option the stable Phase 1
        // behavior remains unchanged and Sendcloud shows every enabled carrier.
        if (config.carriers) {
            options.carriers = String(config.carriers);
        }

        const requestedServicePoint = Number.parseInt(config.service_point_id || "", 10);
        if (!Number.isNaN(requestedServicePoint)) {
            options.servicePointId = requestedServicePoint;
        } else if (currentPoint?.provider_code === "sendcloud" && currentPoint.id) {
            const parsedId = Number.parseInt(currentPoint.id, 10);
            if (!Number.isNaN(parsedId)) {
                options.servicePointId = parsedId;
            }
        }
        if (config.post_number) {
            options.postNumber = config.post_number;
        }

        api.servicePoints.open(
            options,
            (servicePoint, postNumber) => {
                onSelect(servicePoint, {post_number: postNumber || ""});
            },
            (errors) => {
                const relevant = Array.from(errors || []).filter((error) => error !== "Closed");
                if (relevant.length) {
                    onError(relevant.join("\n"));
                }
            }
        );
    },
});
