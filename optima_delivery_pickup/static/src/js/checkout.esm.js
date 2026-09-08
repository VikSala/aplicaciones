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
    },

    start() {
        const result = this._super.apply(this, arguments);
        const pickupRadio = this.el.querySelector("input[name='o_optima_pickup_radio']");
        if (pickupRadio?.checked) {
            if (pickupRadio.dataset.resolved === "1") {
                this._enableMainButton();
            } else {
                this._disableMainButton();
            }
        }
        return result;
    },

    async _onPickupRadioClick(ev) {
        if (!ev.currentTarget.checked) {
            return;
        }
        this._uncheckStandardDeliveryMethods();
        this._disableMainButton();
        const container = this._getPickupContainer(ev.currentTarget);
        this._showPickupArea(container);
        this._clearError(container);
        try {
            const result = await rpc("/shop/optima_pickup/select_mode", {});
            this._updateCartSummary(result.summary);
            await this._openProviderSelector(container, result.providers, result.point);
        } catch (error) {
            ev.currentTarget.checked = false;
            this._showError(container, this._errorMessage(error));
        }
    },

    async _onPickupSelectorClick(ev) {
        ev.preventDefault();
        ev.stopPropagation();
        const container = this._getPickupContainer(ev.currentTarget);
        const radio = container.querySelector("input[name='o_optima_pickup_radio']");
        this._clearError(container);
        try {
            let result;
            if (!radio.checked) {
                radio.checked = true;
                this._uncheckStandardDeliveryMethods();
                this._disableMainButton();
                result = await rpc("/shop/optima_pickup/select_mode", {});
                this._updateCartSummary(result.summary);
            } else {
                result = await rpc("/shop/optima_pickup/state", {});
            }
            await this._openProviderSelector(container, result.providers, result.point);
        } catch (error) {
            this._showError(container, this._errorMessage(error));
        }
    },

    _onStandardDeliveryClick() {
        const pickupRadio = this.el.querySelector("input[name='o_optima_pickup_radio']");
        if (pickupRadio) {
            pickupRadio.checked = false;
            pickupRadio.dataset.resolved = "0";
        }
        this.el
            .querySelector("[name='o_optima_pickup_location']")
            ?.classList.add("d-none");
        this._enableMainButton();
        rpc("/shop/optima_pickup/clear_mode", {}).catch(() => {});
    },

    async _openProviderSelector(container, providers, currentPoint) {
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
                await this._savePoint(container, descriptor.code, rawPoint, extra);
            },
            onError: (message) => this._showError(container, message),
        });
    },

    async _savePoint(container, providerCode, rawPoint, extra) {
        this._disableMainButton();
        this._clearError(container);
        try {
            const result = await rpc("/shop/optima_pickup/set_point", {
                provider_code: providerCode,
                point: rawPoint,
                extra,
            });
            if (!result?.success) {
                throw new Error("No se ha podido guardar el punto de recogida.");
            }
            this._updatePickupPoint(container, result.point, result.resolution || {});
            this._updateCartSummary(result.summary);
        } catch (error) {
            this._disableMainButton();
            this._showError(container, this._errorMessage(error));
        }
    },

    _updatePickupPoint(container, point, resolution = {}) {
        const details = container.querySelector("[name='o_optima_pickup_details']");
        const name = container.querySelector("[name='o_optima_pickup_name']");
        const address = container.querySelector("[name='o_optima_pickup_address']");
        const carrier = container.querySelector("[name='o_optima_pickup_carrier']");
        const initialButtons = container.querySelectorAll(
            ":scope > [name='o_optima_pickup_location'] > button[name='o_optima_pickup_selector']"
        );
        const price = container.querySelector(".optima_pickup_price");
        const radio = container.querySelector("input[name='o_optima_pickup_radio']");

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
        initialButtons.forEach((button) => button.classList.add("d-none"));

        if (resolution.success) {
            if (price) {
                price.textContent = this._formatCurrency(
                    resolution.price || 0,
                    resolution.currency || "EUR"
                );
            }
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
            if (price) {
                price.textContent = "Precio pendiente de cálculo";
            }
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

    _getPickupContainer(element) {
        return element.closest("[name='o_optima_pickup_method']");
    },

    _uncheckStandardDeliveryMethods() {
        this.el.querySelectorAll("input[name='o_delivery_radio']").forEach((radio) => {
            radio.checked = false;
        });
    },

    _disableMainButton() {
        document.querySelector("a[name='website_sale_main_button']")?.classList.add("disabled");
    },

    _enableMainButton() {
        document.querySelector("a[name='website_sale_main_button']")?.classList.remove("disabled");
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
        const alert = container?.querySelector("[name='o_optima_pickup_error']");
        if (alert) {
            alert.textContent = message || "Se ha producido un error al procesar el punto de recogida.";
            alert.classList.remove("d-none");
        }
    },

    _clearError(container) {
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
