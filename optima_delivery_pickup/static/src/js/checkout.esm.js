/** @odoo-module **/

import {rpc} from "@web/core/network/rpc";
import publicWidget from "@web/legacy/js/public/public_widget";
import {pickupProviderRegistry} from "./provider_registry.esm";

publicWidget.registry.OptimaPickupCheckout = publicWidget.Widget.extend({
    selector: "#shop_checkout",
    events: {
        "click input[name='o_optima_pickup_radio']": "_onPickupRadioClick",
        "click [name='o_optima_pickup_selector']": "_onPickupSelectorClick",
        "click [name='o_optima_pickup_offer']": "_onPickupOfferClick",
        "click [name='o_optima_pickup_open_all']": "_onPickupOpenAllClick",
        "click input[name='o_delivery_radio']": "_onStandardDeliveryClick",
        "click a[name='website_sale_main_button']": "_onMainButtonClick",
    },

    start() {
        this._pickupProviders = [];
        this._pickupOptionGroups = [];
        const result = this._super.apply(this, arguments);
        const pickupRadio = this._getPickupRadio();
        if (pickupRadio?.checked) {
            this._markPickupSelected();
            if (pickupRadio.dataset.resolved === "1") {
                this._setPickupLoading(false);
                this._enableMainButton();
            } else {
                // An unresolved point can only be a stale selection from an
                // interrupted/older checkout flow. Keep confirmation blocked
                // and let the customer choose the point again; normal 0.4.5
                // selection resolves atomically in the set_point request.
                this._setPickupLoading(false);
                this._disableMainButton();
            }
        }
        return result;
    },

    async _onPickupRadioClick(ev) {
        if (!ev.currentTarget.checked) {
            return;
        }
        const container = this._getLivePickupContainer();
        this._markPickupSelected();
        this._disableMainButton();
        this._showPickupArea(container);
        this._clearError(container);
        try {
            const result = await rpc("/shop/optima_pickup/select_mode", {});
            this._updateCartSummary(result.summary);
            this._markPickupSelected();
            await this._loadPickupOptions(result.providers, result.point, result.resolution || {});
        } catch (error) {
            const radio = this._getPickupRadio();
            if (radio) {
                radio.checked = false;
            }
            this._setPickupLoading(false);
            this._showError(this._getLivePickupContainer(), this._errorMessage(error));
        }
    },

    async _onPickupSelectorClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (this._isPickupLoading()) {
            return;
        }
        const container = this._getLivePickupContainer();
        const radio = this._getPickupRadio();
        this._clearError(container);
        try {
            let result;
            if (!radio?.checked) {
                if (radio) {
                    radio.checked = true;
                }
                this._markPickupSelected();
                this._disableMainButton();
                result = await rpc("/shop/optima_pickup/select_mode", {});
                this._updateCartSummary(result.summary);
            } else {
                result = await rpc("/shop/optima_pickup/state", {});
            }
            this._markPickupSelected();
            await this._loadPickupOptions(result.providers, result.point, result.resolution || {});
        } catch (error) {
            this._showError(this._getLivePickupContainer(), this._errorMessage(error));
        }
    },

    _onStandardDeliveryClick(ev) {
        if (this._isPickupLoading()) {
            ev.preventDefault();
            ev.stopImmediatePropagation();
            this._markPickupSelected();
            return;
        }
        const pickupRadio = this._getPickupRadio();
        if (pickupRadio) {
            pickupRadio.checked = false;
            pickupRadio.dataset.resolved = "0";
            pickupRadio.dataset.pointId = "";
        }
        this._getLivePickupContainer()
            ?.querySelector("[name='o_optima_pickup_location']")
            ?.classList.add("d-none");
        this._hidePickupOptions();
        this._setPickupLoading(false);
        this._enableMainButton();
        rpc("/shop/optima_pickup/clear_mode", {}).catch(() => {});
    },

    _onMainButtonClick(ev) {
        const pickupRadio = this._getPickupRadio();
        if (pickupRadio?.checked && pickupRadio.dataset.resolved !== "1") {
            ev.preventDefault();
            ev.stopImmediatePropagation();
        }
    },

    async _loadPickupOptions(providers, currentPoint = {}, currentResolution = {}) {
        const container = this._getLivePickupContainer();
        const keepResolvedSelection = Boolean(currentPoint?.id && currentResolution?.success);
        this._pickupProviders = providers || [];
        this._pickupOptionGroups = [];
        this._showPickupArea(container);
        this._showPickupOptions();
        this._setPickupOptionsLoading(true, keepResolvedSelection);
        this._clearError(container);
        if (!keepResolvedSelection) {
            this._disableMainButton();
        }

        if (!this._pickupProviders.length) {
            this._setPickupOptionsLoading(false);
            if (keepResolvedSelection) {
                this._enableMainButton();
            }
            this._showError(container, "No hay proveedores de puntos de recogida disponibles.");
            return;
        }
        if (this._pickupProviders.length > 1) {
            this._setPickupOptionsLoading(false);
            if (keepResolvedSelection) {
                this._enableMainButton();
            }
            this._showError(
                container,
                "Hay varios proveedores de puntos disponibles. La vista unificada multi-proveedor se añadirá en la Fase 5."
            );
            return;
        }

        const descriptor = this._pickupProviders[0];
        try {
            const result = await rpc("/shop/optima_pickup/options", {
                provider_code: descriptor.code,
            });
            this._setPickupOptionsLoading(false);
            if (!result?.success) {
                this._renderPickupOptions([]);
                if (!keepResolvedSelection) {
                    this._setPriceText("Precio no disponible");
                } else {
                    this._enableMainButton();
                }
                this._showError(
                    container,
                    result?.message || "No se han podido calcular las opciones de recogida."
                );
                return;
            }

            this._pickupProviders = result.providers || this._pickupProviders;
            this._pickupOptionGroups = Array.isArray(result.groups) ? result.groups : [];
            this._renderPickupOptions(this._pickupOptionGroups, result);
            this._setPickupLoading(false);
            if (!keepResolvedSelection) {
                this._setPriceText(
                    this._pickupOptionGroups.length ? "Elige un punto" : "Sin opciones compatibles"
                );
            }
            if (result.message) {
                this._showError(container, result.message);
            } else {
                this._clearError(container);
            }
            if (!this._pickupOptionGroups.length && !keepResolvedSelection) {
                this._disableMainButton();
            } else if (keepResolvedSelection) {
                this._enableMainButton();
            }
        } catch (error) {
            this._setPickupOptionsLoading(false);
            this._renderPickupOptions([]);
            if (!keepResolvedSelection) {
                this._setPriceText("Precio no disponible");
            } else {
                this._enableMainButton();
            }
            this._showError(container, this._errorMessage(error));
        }
    },

    _renderPickupOptions(groups = [], result = {}) {
        const container = this._getLivePickupContainer();
        const list = container?.querySelector("[name='o_optima_pickup_options_list']");
        const mapButton = container?.querySelector("[name='o_optima_pickup_open_all']");
        if (!list) {
            return;
        }
        list.replaceChildren();

        const mapCarriers = new Set();
        for (const group of groups) {
            for (const offer of group.offers || []) {
                for (const code of String(offer.map_carriers || "").split(",")) {
                    if (code.trim()) {
                        mapCarriers.add(code.trim());
                    }
                }
            }
        }
        if (mapButton) {
            mapButton.classList.toggle("d-none", !groups.length || !mapCarriers.size);
            mapButton.dataset.carriers = Array.from(mapCarriers).join(",");
        }

        if (!groups.length) {
            const empty = document.createElement("div");
            empty.className = "small text-muted py-2";
            empty.textContent = result?.empty_label || "No hay puntos compatibles para este pedido.";
            list.appendChild(empty);
            return;
        }

        groups.forEach((group, groupIndex) => {
            const point = group.point || {};
            const card = document.createElement("div");
            card.className = "optima_pickup_option_card border rounded p-3 mb-2";

            const header = document.createElement("div");
            header.className = "d-flex align-items-start justify-content-between gap-3";
            const identity = document.createElement("div");
            identity.className = "flex-grow-1";
            const title = document.createElement("div");
            title.className = "fw-semibold";
            title.textContent = point.name || "Punto de recogida";
            identity.appendChild(title);

            const address = document.createElement("div");
            address.className = "small text-muted";
            address.textContent = [
                point.street_display || point.street,
                [point.zip_code, point.city].filter(Boolean).join(" "),
            ]
                .filter(Boolean)
                .join(" · ");
            identity.appendChild(address);
            header.appendChild(identity);

            const distance = document.createElement("span");
            distance.className = "badge text-bg-light optima_pickup_distance";
            distance.textContent = this._formatDistance(group.distance_m);
            header.appendChild(distance);
            card.appendChild(header);

            const offers = document.createElement("div");
            offers.className = "mt-2 d-grid gap-2";
            (group.offers || []).forEach((offer, offerIndex) => {
                const row = document.createElement("div");
                row.className = "optima_pickup_offer_row d-flex flex-column flex-lg-row align-items-lg-center gap-2 border-top pt-2";

                const details = document.createElement("div");
                details.className = "flex-grow-1";
                const method = document.createElement("div");
                method.className = "small fw-semibold";
                method.textContent = offer.carrier_name || offer.method_name || "Método compatible";
                details.appendChild(method);

                if (offer.method_name && offer.method_name !== offer.carrier_name) {
                    const methodName = document.createElement("div");
                    methodName.className = "small text-muted";
                    methodName.textContent = offer.method_name;
                    details.appendChild(methodName);
                }
                if (offer.eta_label) {
                    const eta = document.createElement("div");
                    eta.className = "small text-muted";
                    eta.textContent = offer.eta_label;
                    details.appendChild(eta);
                }
                row.appendChild(details);

                const actions = document.createElement("div");
                actions.className = "d-flex align-items-center justify-content-between justify-content-lg-end gap-3";
                const price = document.createElement("span");
                price.className = "fw-bold text-nowrap";
                price.textContent = this._formatCurrency(offer.price || 0, offer.currency || "EUR");
                actions.appendChild(price);

                const button = document.createElement("button");
                button.type = "button";
                button.className = "btn btn-primary btn-sm text-nowrap";
                button.name = "o_optima_pickup_offer";
                button.dataset.groupIndex = String(groupIndex);
                button.dataset.offerIndex = String(offerIndex);
                button.textContent = "Elegir";
                actions.appendChild(button);
                row.appendChild(actions);
                offers.appendChild(row);
            });
            card.appendChild(offers);
            list.appendChild(card);
        });
    },

    async _onPickupOfferClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (this._isPickupLoading()) {
            return;
        }
        const groupIndex = Number.parseInt(ev.currentTarget.dataset.groupIndex || "-1", 10);
        const offerIndex = Number.parseInt(ev.currentTarget.dataset.offerIndex || "-1", 10);
        const group = this._pickupOptionGroups[groupIndex];
        const offer = group?.offers?.[offerIndex];
        if (!group || !offer) {
            this._showError(this._getLivePickupContainer(), "La opción elegida ya no está disponible.");
            return;
        }
        const point = group.point || {};
        await this._openProviderSelector(this._pickupProviders, point, {
            currentPoint: {
                ...point,
                provider_code: offer.provider_code || "sendcloud",
            },
            config: {
                carriers: offer.map_carriers || "",
                service_point_id: point.id || "",
            },
            extra: {
                selected_offer_key: offer.key || "",
            },
        });
    },

    async _onPickupOpenAllClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        if (this._isPickupLoading()) {
            return;
        }
        const carriers = ev.currentTarget.dataset.carriers || "";
        const statePoint = this._getPickupRadio()?.dataset.pointId
            ? {provider_code: "sendcloud", id: this._getPickupRadio().dataset.pointId}
            : {};
        await this._openProviderSelector(this._pickupProviders, statePoint, {
            config: {carriers},
            extra: {selected_offer_key: ""},
        });
    },

    _showPickupOptions() {
        this._getLivePickupContainer()
            ?.querySelector("[name='o_optima_pickup_options']")
            ?.classList.remove("d-none");
    },

    _hidePickupOptions() {
        const area = this._getLivePickupContainer()?.querySelector("[name='o_optima_pickup_options']");
        area?.classList.add("d-none");
        this._pickupOptionGroups = [];
    },

    _setPickupOptionsLoading(loading, keepResolvedSelection = false) {
        const container = this._getLivePickupContainer();
        this._showPickupOptions();
        container
            ?.querySelector(".optima_pickup_options_loading")
            ?.classList.toggle("d-none", !loading);
        const list = container?.querySelector("[name='o_optima_pickup_options_list']");
        if (loading && list) {
            list.replaceChildren();
        }
        const mapButton = container?.querySelector("[name='o_optima_pickup_open_all']");
        if (loading) {
            mapButton?.classList.add("d-none");
            if (!keepResolvedSelection) {
                this._setPickupLoading(true, "Buscando opciones…");
            }
        } else if (!keepResolvedSelection) {
            this._setPickupLoading(false);
        }
    },

    _formatDistance(distanceMeters) {
        const value = Number(distanceMeters);
        if (!Number.isFinite(value) || value < 0) {
            return "Distancia no disponible";
        }
        if (value < 1000) {
            return `${Math.round(value)} m`;
        }
        return `${(value / 1000).toFixed(value < 10000 ? 1 : 0)} km`;
    },

    async _openProviderSelector(providers, currentPoint, selectorContext = {}) {
        const container = this._getLivePickupContainer();
        if (!providers?.length) {
            this._showError(container, "No hay proveedores de puntos de recogida disponibles.");
            return;
        }
        if (providers.length > 1) {
            this._showError(
                container,
                "Hay varios proveedores de puntos disponibles. El mapa unificado se añadirá en una fase posterior."
            );
            return;
        }

        const descriptor = providers[0];
        const provider = pickupProviderRegistry.get(descriptor.code);
        if (!provider) {
            this._showError(
                container,
                `El proveedor ${descriptor.name || descriptor.code} no tiene interfaz frontend instalada.`
            );
            return;
        }

        const config = {
            ...(descriptor.config || {}),
            ...(selectorContext.config || {}),
        };
        const pointForMap = selectorContext.currentPoint || currentPoint || {};
        const selectionExtra = selectorContext.extra || {};

        await provider.open({
            config,
            currentPoint: pointForMap,
            onSelect: async (rawPoint, extra = {}) => {
                await this._savePoint(descriptor.code, rawPoint, {
                    ...extra,
                    ...selectionExtra,
                });
            },
            onError: (message) => this._showError(this._getLivePickupContainer(), message),
        });
    },

    async _savePoint(providerCode, rawPoint, extra) {
        // The provider modal has already closed at this point. Reflect the
        // customer's choice immediately, show the spinner and block checkout.
        this._markPickupSelected();
        this._previewRawPoint(rawPoint);
        this._setPickupLoading(true, "Calculando precio…");
        this._disableMainButton();
        this._clearError(this._getLivePickupContainer());

        const payload = {
            provider_code: providerCode,
            point: rawPoint,
            extra,
        };

        try {
            const result = await this._setPointWithRecovery(payload, rawPoint);
            if (!result?.success) {
                throw new Error("No se ha podido guardar y calcular el punto de recogida.");
            }

            this._markPickupSelected();
            this._updatePickupPoint(
                this._getLivePickupContainer(),
                result.point || {},
                result.resolution || {}
            );
            this._updateCartSummary(result.summary);
            this._hidePickupOptions();
        } catch (error) {
            // A transport interruption must not leave the browser showing a
            // point different from the server. Restore the authoritative state
            // when possible; otherwise keep confirmation safely blocked.
            const restored = await this._restorePickupStateAfterFailure(error);
            if (!restored) {
                this._setPickupLoading(false);
                this._disableMainButton();
                this._markPickupSelected();
                this._setPriceText("Precio no disponible");
                this._showError(this._getLivePickupContainer(), this._errorMessage(error));
            }
        }
    },

    async _setPointWithRecovery(payload, rawPoint) {
        try {
            return await rpc("/shop/optima_pickup/set_point", payload);
        } catch (error) {
            if (!this._isConnectionError(error)) {
                throw error;
            }

            // The HTTP response can be lost after Odoo has already committed
            // the selection. Query the cheap state endpoint before retrying the
            // expensive Sendcloud validation.
            try {
                const state = await rpc("/shop/optima_pickup/state", {});
                const selectedId = rawPoint?.id ? String(rawPoint.id) : "";
                const storedId = state?.point?.id ? String(state.point.id) : "";
                if (
                    state?.success &&
                    selectedId &&
                    selectedId === storedId &&
                    (state.resolution?.success || state.resolution?.message)
                ) {
                    return {
                        success: true,
                        point: state.point || {},
                        resolution: state.resolution || {},
                        summary: state.summary,
                    };
                }
            } catch {
                // Ignore state lookup failure and perform one idempotent retry.
            }

            await new Promise((resolve) => window.setTimeout(resolve, 250));
            return await rpc("/shop/optima_pickup/set_point", payload);
        }
    },

    async _restorePickupStateAfterFailure(error) {
        try {
            const state = await rpc("/shop/optima_pickup/state", {});
            if (!state?.success) {
                return false;
            }
            const point = state.point || {};
            const resolution = state.resolution || {};
            this._markPickupSelected();
            if (point.id) {
                this._updatePickupPoint(this._getLivePickupContainer(), point, resolution);
            } else {
                this._setPickupLoading(false);
                this._setPriceText("Precio no disponible");
                this._disableMainButton();
            }
            this._updateCartSummary(state.summary);
            const message = resolution.success
                ? "No se ha podido completar el cambio de punto. Se mantiene la última selección válida."
                : this._errorMessage(error);
            this._showError(this._getLivePickupContainer(), message);
            return true;
        } catch {
            return false;
        }
    },

    _isConnectionError(error) {
        const message = this._errorMessage(error).toLowerCase();
        return (
            message.includes("couldn't be established") ||
            message.includes("could not be established") ||
            message.includes("interrupted") ||
            message.includes("connection") ||
            message.includes("network")
        );
    },

    _previewRawPoint(point = {}) {
        const normalizedPreview = {
            id: point.id ? String(point.id) : "",
            name: point.name || "",
            street: [point.street, point.house_number].filter(Boolean).join(" "),
            zip_code: point.postal_code || point.zip_code || "",
            city: point.city || "",
        };
        this._updatePickupPointPending(normalizedPreview);
    },

    _updatePickupPointPending(point = {}) {
        const container = this._getLivePickupContainer();
        const details = container?.querySelector("[name='o_optima_pickup_details']");
        const name = container?.querySelector("[name='o_optima_pickup_name']");
        const address = container?.querySelector("[name='o_optima_pickup_address']");
        const carrier = container?.querySelector("[name='o_optima_pickup_carrier']");
        const radio = this._getPickupRadio();

        if (name) {
            name.textContent = point.name || "";
        }
        if (address) {
            address.replaceChildren(
                document.createTextNode(point.street || ""),
                document.createElement("br"),
                document.createTextNode([point.zip_code, point.city].filter(Boolean).join(" "))
            );
        }
        details?.classList.remove("d-none");
        this._hideInitialSelectorButton(container);
        if (carrier) {
            carrier.textContent = "";
            carrier.classList.add("d-none");
        }
        if (radio) {
            radio.checked = true;
            radio.dataset.resolved = "0";
            if (point.id) {
                radio.dataset.pointId = String(point.id);
            }
        }
        this._showPickupArea(container);
        this._setPriceText("Calculando precio…");
    },

    _updatePickupPoint(container, point, resolution = {}) {
        container = this._getLivePickupContainer() || container;
        const details = container?.querySelector("[name='o_optima_pickup_details']");
        const name = container?.querySelector("[name='o_optima_pickup_name']");
        const address = container?.querySelector("[name='o_optima_pickup_address']");
        const carrier = container?.querySelector("[name='o_optima_pickup_carrier']");
        const radio = this._getPickupRadio();

        if (name) {
            name.textContent = point.name || "";
        }
        if (address) {
            address.replaceChildren(
                document.createTextNode(point.street || ""),
                document.createElement("br"),
                document.createTextNode([point.zip_code, point.city].filter(Boolean).join(" "))
            );
        }
        details?.classList.remove("d-none");
        this._hideInitialSelectorButton(container);

        if (radio) {
            radio.checked = true;
            radio.dataset.pointId = point.id ? String(point.id) : radio.dataset.pointId || "";
        }

        this._setPickupLoading(false);
        if (resolution.success) {
            this._setPriceText(
                this._formatCurrency(resolution.price || 0, resolution.currency || "EUR")
            );
            if (carrier) {
                carrier.textContent = resolution.carrier_name
                    ? `Método: ${resolution.carrier_name}`
                    : "";
                carrier.classList.toggle("d-none", !resolution.carrier_name);
            }
            if (radio) {
                radio.dataset.resolved = "1";
            }
            if (resolution.message) {
                this._showError(container, resolution.message);
            } else {
                this._clearError(container);
            }
            this._enableMainButton();
        } else {
            this._setPriceText("Precio no disponible");
            if (carrier) {
                carrier.textContent = "";
                carrier.classList.add("d-none");
            }
            if (radio) {
                radio.dataset.resolved = "0";
            }
            this._disableMainButton();
            if (resolution.message) {
                this._showError(container, resolution.message);
            }
        }
        this._markPickupSelected();
    },

    _setPickupLoading(loading, label = "Calculando precio…") {
        const container = this._getLivePickupContainer();
        container?.classList.toggle("optima_pickup_loading", Boolean(loading));
        const spinner = container?.querySelector(".optima_pickup_spinner");
        spinner?.classList.toggle("d-none", !loading);
        if (loading) {
            this._setPriceText(label);
        }
    },

    _isPickupLoading() {
        return Boolean(this._getLivePickupContainer()?.classList.contains("optima_pickup_loading"));
    },

    _setPriceText(text) {
        const element = this._getLivePickupContainer()?.querySelector(".optima_pickup_price_text");
        if (element) {
            element.textContent = text || "";
        }
    },

    _hideInitialSelectorButton(container) {
        container
            ?.querySelectorAll("[name='o_optima_pickup_location'] > button[name='o_optima_pickup_selector']")
            .forEach((button) => button.classList.add("d-none"));
    },

    _formatCurrency(amount, currency) {
        try {
            const language = document.documentElement.lang || "es-ES";
            return new Intl.NumberFormat(language, {
                style: "currency",
                currency,
            }).format(Number(amount || 0));
        } catch {
            return `${Number(amount || 0).toFixed(2)} ${currency || ""}`.trim();
        }
    },

    _showPickupArea(container) {
        container?.querySelector("[name='o_optima_pickup_location']")?.classList.remove("d-none");
    },

    _getLivePickupContainer() {
        return this.el.querySelector("[name='o_optima_pickup_method']");
    },

    _getPickupRadio() {
        return this.el.querySelector("input[name='o_optima_pickup_radio']");
    },

    _markPickupSelected() {
        const pickupRadio = this._getPickupRadio();
        if (pickupRadio) {
            pickupRadio.checked = true;
        }
        this._uncheckStandardDeliveryMethods();
        this._showPickupArea(this._getLivePickupContainer());
    },

    _uncheckStandardDeliveryMethods() {
        this.el.querySelectorAll("input[name='o_delivery_radio']").forEach((radio) => {
            radio.checked = false;
        });
    },

    _disableMainButton() {
        const button = document.querySelector("a[name='website_sale_main_button']");
        if (!button) {
            return;
        }
        button.classList.add("disabled");
        button.setAttribute("aria-disabled", "true");
        button.setAttribute("tabindex", "-1");
    },

    _enableMainButton() {
        const button = document.querySelector("a[name='website_sale_main_button']");
        if (!button) {
            return;
        }
        button.classList.remove("disabled");
        button.removeAttribute("aria-disabled");
        button.removeAttribute("tabindex");
    },

    _updateCartSummary(result) {
        if (!result?.success) {
            return;
        }
        const values = [
            ["#order_delivery .monetary_field", "amount_delivery"],
            ["#order_total_untaxed .monetary_field", "amount_untaxed"],
            ["#order_total_taxes .monetary_field", "amount_tax"],
        ];
        for (const [selector, key] of values) {
            const element = document.querySelector(selector);
            if (element && result[key] !== undefined) {
                element.innerHTML = result[key];
            }
        }
        if (result.amount_total !== undefined) {
            document
                .querySelectorAll("#order_total .monetary_field, #amount_total_summary.monetary_field")
                .forEach((element) => (element.innerHTML = result.amount_total));
        }
    },

    _showError(container, message) {
        container = this._getLivePickupContainer() || container;
        const alert = container?.querySelector("[name='o_optima_pickup_error']");
        if (alert) {
            alert.textContent = message || "Se ha producido un error al procesar el punto de recogida.";
            alert.classList.remove("d-none");
        }
    },

    _clearError(container) {
        container = this._getLivePickupContainer() || container;
        const alert = container?.querySelector("[name='o_optima_pickup_error']");
        if (alert) {
            alert.textContent = "";
            alert.classList.add("d-none");
        }
    },

    _errorMessage(error) {
        return error?.data?.message || error?.message || "Se ha producido un error al procesar el punto de recogida.";
    },
});
