/** @odoo-module **/

import {ensureJQuery} from "@web/core/ensure_jquery";
import {loadJS} from "@web/core/assets";
import {registerPickupProvider} from "@optima_delivery_pickup/js/provider_registry.esm";

const PICKER_URL = "/delivery_sendcloud_oca/static/src/lib/sendcloud/api.min.js";

const SERVICE_POINTS_URL = "https://servicepoints.sendcloud.sc/api/v2/service-points";

function sendcloudCarrierName(code) {
    const token = String(code || "").trim().toLowerCase().replaceAll("-", "_").replaceAll(" ", "_");
    const aliases = {
        inpost: "InPost",
        inpost_es: "InPost",
        inpost_iberia: "InPost",
        mondial_relay: "InPost",
        mondialrelay: "InPost",
        correos: "Correos",
        correos_express: "Correos Express",
        correosexpress: "Correos Express",
        ups: "UPS",
        gls: "GLS",
        fedex: "FedEx",
        dhl: "DHL",
        dpd: "DPD",
    };
    return aliases[token] || String(code || "Sendcloud").replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function sendcloudPoint(raw) {
    const carrierCode = String(raw?.carrier || "");
    const id = String(raw?.id || "");
    const latitude = Number(raw?.latitude || 0);
    const longitude = Number(raw?.longitude || 0);
    const distance = Math.max(Number(raw?.distance || 0), 0);
    const rawPoint = {
        id: raw?.id,
        name: raw?.name || "",
        street: raw?.street || "",
        house_number: raw?.house_number || "",
        postal_code: raw?.postal_code || "",
        city: raw?.city || "",
        country: raw?.country || "",
        carrier: carrierCode,
        latitude,
        longitude,
        general_shop_type: raw?.general_shop_type || raw?.shop_type || "",
        formatted_opening_times: raw?.formatted_opening_times || {},
        open_tomorrow: Boolean(raw?.open_tomorrow),
        open_upcoming_week: raw?.open_upcoming_week !== false,
    };
    return {
        key: `sendcloud:${id}`,
        provider_code: "sendcloud",
        provider_name: "Sendcloud",
        id,
        name: raw?.name || "",
        street: [raw?.street, raw?.house_number].filter(Boolean).join(" ").trim(),
        zip_code: String(raw?.postal_code || ""),
        city: raw?.city || "",
        country_code: raw?.country || "",
        carrier_code: carrierCode,
        carrier_name: sendcloudCarrierName(carrierCode),
        latitude,
        longitude,
        distance_m: distance,
        shop_type: raw?.general_shop_type || raw?.shop_type || "",
        opening_times: raw?.formatted_opening_times || {},
        open_tomorrow: Boolean(raw?.open_tomorrow),
        quote: {price: null, currency: "EUR", method_name: "", lead_time_hours: 0, estimated: true},
        raw_point: rawPoint,
        extra: {},
    };
}

registerPickupProvider("sendcloud", {
    async searchPoints({config, query, radiusM}) {
        if (!config?.api_key || !config?.country) {
            throw new Error("Falta la configuración pública de Sendcloud para buscar puntos.");
        }
        const params = new URLSearchParams({
            access_token: String(config.api_key),
            country: String(config.country).toUpperCase(),
            address: String(query || config.postal_code || config.city || "").trim(),
            radius: String(Math.min(Math.max(Number(radiusM || 5000), 100), 50000)),
        });
        if (Number(config.weight_kg || 0) > 0) {
            params.set("weight", String(Number(config.weight_kg)));
        }

        const controller = new AbortController();
        const timer = window.setTimeout(() => controller.abort(), 8000);
        let response;
        try {
            // Sendcloud's Service Points API accepts the integration public key
            // as access_token, so discovery can run directly in the browser.
            // The secret key never leaves Odoo.
            response = await fetch(`${SERVICE_POINTS_URL}?${params.toString()}`, {
                method: "GET",
                mode: "cors",
                credentials: "omit",
                signal: controller.signal,
            });
        } finally {
            window.clearTimeout(timer);
        }
        if (!response?.ok) {
            throw new Error(`Sendcloud no ha podido devolver puntos (${response?.status || "red"}).`);
        }
        const payload = await response.json();
        const points = (Array.isArray(payload) ? payload : [])
            .filter((raw) => raw && raw.id && raw.open_upcoming_week !== false)
            .map(sendcloudPoint)
            .filter((point) => point.latitude && point.longitude)
            .sort((a, b) => Number(a.distance_m || Number.MAX_SAFE_INTEGER) - Number(b.distance_m || Number.MAX_SAFE_INTEGER))
            .slice(0, 100);
        return {query, points, errors: []};
    },

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
        if (currentPoint?.provider_code === "sendcloud" && currentPoint.id) {
            const parsedId = Number.parseInt(currentPoint.id, 10);
            if (!Number.isNaN(parsedId)) {
                options.servicePointId = parsedId;
            }
        }
        if (config.post_number) {
            options.postNumber = config.post_number;
        }

        // Sin filtro `carriers`: Sendcloud muestra todos los carriers habilitados
        // para Service Points en la integración.
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
