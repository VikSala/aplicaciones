/** @odoo-module **/

import {rpc} from "@web/core/network/rpc";
import publicWidget from "@web/legacy/js/public/public_widget";
import {pickupProviderRegistry} from "./provider_registry.esm";

publicWidget.registry.OptimaPickupCheckout = publicWidget.Widget.extend({
    selector: "#shop_checkout",
    events: {
        "click input[name='o_optima_pickup_radio']": "_onPickupRadioClick",
        "click [name='o_optima_pickup_selector']": "_onPickupSelectorClick",
        "click input[name='o_delivery_radio']": "_onStandardDeliveryClick",
        "click a[name='website_sale_main_button']": "_onMainButtonClick",
    },

    start() {
        const result = this._super.apply(this, arguments);
        const pickupRadio = this._getPickupRadio();
        if (pickupRadio?.checked) {
            this._markPickupSelected();
            if (pickupRadio.dataset.resolved === "1") {
                this._setPickupLoading(false);
                this._enableMainButton();
            } else {
                this._disableMainButton();
                // If the customer refreshed the page after the point had already
                // been saved but before rating finished, resume the resolution.
                if (pickupRadio.dataset.pointId) {
                    this._resolveStoredPoint().catch(() => {});
                }
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
            await this._openProviderSelector(result.providers, result.point);
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
            await this._openProviderSelector(result.providers, result.point);
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

    async _openProviderSelector(providers, currentPoint) {
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

        await provider.open({
            config: descriptor.config || {},
            currentPoint: currentPoint || {},
            onSelect: async (rawPoint, extra = {}) => {
                await this._savePoint(descriptor.code, rawPoint, extra);
            },
            onError: (message) => this._showError(this._getLivePickupContainer(), message),
        });
    },

    async _savePoint(providerCode, rawPoint, extra) {
        // The Sendcloud modal has already closed at this point. Reflect the
        // customer's choice immediately, show the spinner and block checkout.
        this._markPickupSelected();
        this._previewRawPoint(rawPoint);
        this._setPickupLoading(true, "Calculando precio…");
        this._disableMainButton();
        this._clearError(this._getLivePickupContainer());

        try {
            const stored = await rpc("/shop/optima_pickup/set_point", {
                provider_code: providerCode,
                point: rawPoint,
                extra,
            });
            if (!stored?.success) {
                throw new Error("No se ha podido guardar el punto de recogida.");
            }

            this._markPickupSelected();
            this._updatePickupPointPending(stored.point);
            this._updateCartSummary(stored.summary);

            await this._resolveStoredPoint();
        } catch (error) {
            this._setPickupLoading(false);
            this._disableMainButton();
            this._markPickupSelected();
            this._showError(this._getLivePickupContainer(), this._errorMessage(error));
        }
    },

    async _resolveStoredPoint() {
        const container = this._getLivePickupContainer();
        const radio = this._getPickupRadio();
        if (!radio?.checked || !radio.dataset.pointId) {
            return;
        }

        this._markPickupSelected();
        this._setPickupLoading(true, "Calculando precio…");
        this._disableMainButton();
        this._clearError(container);

        try {
            const result = await rpc("/shop/optima_pickup/resolve", {});
            if (!result?.success) {
                throw new Error("No se ha podido calcular el método de entrega.");
            }
            this._markPickupSelected();
            this._updatePickupPoint(this._getLivePickupContainer(), result.point, result.resolution || {});
            this._updateCartSummary(result.summary);
        } catch (error) {
            this._setPickupLoading(false);
            this._disableMainButton();
            this._markPickupSelected();
            this._setPriceText("Precio no disponible");
            this._showError(this._getLivePickupContainer(), this._errorMessage(error));
            throw error;
        }
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
