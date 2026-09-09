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
        try {
            await this._openUnifiedMap(providers, currentPoint || {});
        } catch (error) {
            // Keep the proven hosted provider selector as an emergency fallback
            // when the unified map cannot be loaded at all.
            if (providers.length === 1) {
                const descriptor = providers[0];
                const provider = pickupProviderRegistry.get(descriptor.code);
                if (provider?.open) {
                    this._showError(
                        container,
                        `El mapa unificado no está disponible. Abriendo el selector de ${descriptor.name || descriptor.code}.`
                    );
                    await provider.open({
                        config: descriptor.config || {},
                        currentPoint: currentPoint || {},
                        onSelect: async (rawPoint, extra = {}) => {
                            await this._savePoint(descriptor.code, rawPoint, extra);
                        },
                        onError: (message) => this._showError(this._getLivePickupContainer(), message),
                    });
                    return;
                }
            }
            this._showError(container, this._errorMessage(error));
        }
    },

    async _openUnifiedMap(providers, currentPoint) {
        this._closeUnifiedMap();
        const modal = this._buildUnifiedMapModal(providers);
        document.body.appendChild(modal);
        document.body.classList.add("optima_pickup_map_open");
        this._pickupMapModal = modal;
        this._pickupMapState = {
            providers,
            currentPoint,
            points: [],
            selectedKey: "",
            leaflet: null,
            markers: new Map(),
        };

        const close = () => this._closeUnifiedMap();
        modal.querySelectorAll("[data-optima-map-close]").forEach((button) => {
            button.addEventListener("click", close);
        });
        modal.querySelector(".optima_pickup_map_backdrop")?.addEventListener("click", close);
        modal.querySelector("[data-optima-search]")?.addEventListener("click", () => {
            this._searchUnifiedMapPoints();
        });
        modal.querySelector("[data-optima-query]")?.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                this._searchUnifiedMapPoints();
            }
        });
        modal.querySelector("[data-optima-sort]")?.addEventListener("change", () => {
            this._renderUnifiedMapPointList();
        });

        // The list remains fully usable if the map library/CDN is unavailable.
        this._loadLeaflet().then(() => this._initUnifiedLeafletMap()).catch(() => {
            modal.querySelector("[data-optima-map-canvas]")?.classList.add("d-none");
            modal.querySelector("[data-optima-map-fallback]")?.classList.remove("d-none");
        });
        await this._searchUnifiedMapPoints();
    },

    _buildUnifiedMapModal(providers) {
        const root = document.createElement("div");
        root.className = "optima_pickup_map_shell";
        const providerNames = providers.map((provider) => provider.name || provider.code).join(" · ");
        root.innerHTML = `
            <div class="optima_pickup_map_backdrop" data-optima-map-close></div>
            <section class="optima_pickup_map_modal" role="dialog" aria-modal="true" aria-label="Puntos de recogida">
                <header class="optima_pickup_map_header">
                    <div>
                        <div class="h5 mb-0">Elige tu punto de recogida</div>
                        <div class="small text-muted">${this._escapeHtml(providerNames)}</div>
                    </div>
                    <button type="button" class="btn-close" aria-label="Cerrar" data-optima-map-close></button>
                </header>
                <div class="optima_pickup_map_toolbar">
                    <div class="input-group">
                        <input type="text" class="form-control" data-optima-query placeholder="Dirección, ciudad o código postal"/>
                        <select class="form-select optima_pickup_radius" data-optima-radius aria-label="Radio de búsqueda">
                            <option value="5000">5 km</option>
                            <option value="10000" selected>10 km</option>
                            <option value="20000">20 km</option>
                            <option value="50000">50 km</option>
                        </select>
                        <button type="button" class="btn btn-primary" data-optima-search>
                            <i class="fa fa-search me-1" aria-hidden="true"></i>Buscar
                        </button>
                    </div>
                    <div class="d-flex align-items-center gap-2 mt-2">
                        <span class="small text-muted flex-grow-1" data-optima-result-status>Buscando puntos…</span>
                        <label class="small text-muted mb-0" for="optima_pickup_sort">Ordenar:</label>
                        <select id="optima_pickup_sort" class="form-select form-select-sm optima_pickup_sort" data-optima-sort>
                            <option value="distance">Distancia</option>
                            <option value="price">Precio</option>
                            <option value="eta">Entrega</option>
                        </select>
                    </div>
                </div>
                <div class="optima_pickup_map_body">
                    <div class="optima_pickup_map_visual">
                        <div class="optima_pickup_map_canvas" data-optima-map-canvas></div>
                        <div class="optima_pickup_map_fallback d-none" data-optima-map-fallback>
                            <i class="fa fa-map-o fa-2x mb-2" aria-hidden="true"></i>
                            <div>El mapa no ha podido cargarse.</div>
                            <div class="small text-muted">Puedes elegir el punto desde la lista.</div>
                        </div>
                    </div>
                    <aside class="optima_pickup_point_panel">
                        <div class="optima_pickup_search_error alert alert-warning d-none" data-optima-search-error></div>
                        <div class="optima_pickup_point_list" data-optima-point-list></div>
                    </aside>
                </div>
                <footer class="optima_pickup_map_footer">
                    <span class="small text-muted">El precio mostrado en el mapa es orientativo; al elegir el punto se valida el método y precio exactos.</span>
                    <button type="button" class="btn btn-outline-secondary" data-optima-map-close>Cancelar</button>
                </footer>
            </section>`;
        return root;
    },

    async _loadLeaflet() {
        if (window.L?.map) {
            return;
        }
        if (!document.querySelector('link[data-optima-leaflet="1"]')) {
            const link = document.createElement("link");
            link.rel = "stylesheet";
            link.href = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.css";
            link.dataset.optimaLeaflet = "1";
            document.head.appendChild(link);
        }
        if (!document.querySelector('script[data-optima-leaflet="1"]')) {
            await new Promise((resolve, reject) => {
                const script = document.createElement("script");
                script.src = "https://unpkg.com/leaflet@1.9.4/dist/leaflet.js";
                script.async = true;
                script.dataset.optimaLeaflet = "1";
                script.onload = resolve;
                script.onerror = reject;
                document.head.appendChild(script);
            });
        } else if (!window.L?.map) {
            await new Promise((resolve, reject) => {
                let attempts = 0;
                const timer = window.setInterval(() => {
                    attempts += 1;
                    if (window.L?.map) {
                        window.clearInterval(timer);
                        resolve();
                    } else if (attempts > 50) {
                        window.clearInterval(timer);
                        reject(new Error("Leaflet no disponible"));
                    }
                }, 100);
            });
        }
        if (!window.L?.map) {
            throw new Error("Leaflet no disponible");
        }
    },

    _initUnifiedLeafletMap() {
        const state = this._pickupMapState;
        const canvas = this._pickupMapModal?.querySelector("[data-optima-map-canvas]");
        if (!state || !canvas || state.leaflet || !window.L?.map) {
            return;
        }
        const map = window.L.map(canvas, {zoomControl: true}).setView([40.4168, -3.7038], 6);
        window.L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
        }).addTo(map);
        state.leaflet = map;
        window.setTimeout(() => map.invalidateSize(), 50);
        this._renderUnifiedMapMarkers();
    },

    async _searchUnifiedMapPoints() {
        const modal = this._pickupMapModal;
        const state = this._pickupMapState;
        if (!modal || !state) {
            return;
        }
        const input = modal.querySelector("[data-optima-query]");
        const radius = modal.querySelector("[data-optima-radius]");
        const status = modal.querySelector("[data-optima-result-status]");
        const errorBox = modal.querySelector("[data-optima-search-error]");
        const searchButton = modal.querySelector("[data-optima-search]");
        status.textContent = "Buscando puntos compatibles…";
        errorBox.classList.add("d-none");
        errorBox.textContent = "";
        searchButton.disabled = true;
        try {
            const result = await rpc("/shop/optima_pickup/search_points", {
                provider_codes: state.providers.map((provider) => provider.code),
                query: input.value || "",
                radius_m: Number.parseInt(radius.value || "10000", 10),
            });
            if (!input.value && result.query) {
                input.value = result.query;
            }
            state.points = Array.isArray(result.points) ? result.points : [];
            if (state.currentPoint?.id) {
                const currentProvider = state.currentPoint.provider_code || "";
                const match = state.points.find(
                    (point) => String(point.id || "") === String(state.currentPoint.id)
                        && (!currentProvider || point.provider_code === currentProvider)
                );
                state.selectedKey = match?.key || "";
            }
            const errors = Array.isArray(result.errors) ? result.errors : [];
            if (errors.length) {
                errorBox.textContent = errors.map((item) => item.message || String(item)).join(" · ");
                errorBox.classList.remove("d-none");
            }
            status.textContent = state.points.length
                ? `${state.points.length} puntos compatibles encontrados`
                : "No se han encontrado puntos compatibles en este radio.";
            this._renderUnifiedMapPointList();
            this._renderUnifiedMapMarkers();
        } catch (error) {
            state.points = [];
            this._renderUnifiedMapPointList();
            this._renderUnifiedMapMarkers();
            status.textContent = "No se ha podido completar la búsqueda.";
            errorBox.textContent = this._errorMessage(error);
            errorBox.classList.remove("d-none");
        } finally {
            searchButton.disabled = false;
        }
    },

    _sortedUnifiedPoints() {
        const state = this._pickupMapState;
        const sort = this._pickupMapModal?.querySelector("[data-optima-sort]")?.value || "distance";
        const points = [...(state?.points || [])];
        const missing = Number.MAX_SAFE_INTEGER;
        const score = (point) => {
            if (sort === "price") {
                const value = point.quote?.price;
                return value === null || value === undefined ? missing : Number(value);
            }
            if (sort === "eta") {
                return Number(point.quote?.lead_time_hours || missing);
            }
            return Number(point.distance_m || missing);
        };
        points.sort((a, b) => score(a) - score(b) || Number(a.distance_m || missing) - Number(b.distance_m || missing));
        return points;
    },

    _renderUnifiedMapPointList() {
        const list = this._pickupMapModal?.querySelector("[data-optima-point-list]");
        if (!list) {
            return;
        }
        list.replaceChildren();
        for (const point of this._sortedUnifiedPoints()) {
            const card = document.createElement("button");
            card.type = "button";
            card.className = "optima_pickup_point_card text-start";
            card.dataset.pointKey = point.key;
            if (this._pickupMapState?.selectedKey === point.key) {
                card.classList.add("active");
            }
            const price = point.quote?.price;
            const priceText = price === null || price === undefined
                ? "Precio al seleccionar"
                : `≈ ${this._formatCurrency(price, point.quote?.currency || "EUR")}`;
            const etaText = this._formatLeadTime(point.quote?.lead_time_hours);
            const distanceText = this._formatDistance(point.distance_m);
            const today = this._openingToday(point.opening_times);
            const type = point.shop_type === "locker" ? "Locker" : "Punto";
            card.innerHTML = `
                <div class="d-flex align-items-start gap-2">
                    <span class="optima_pickup_provider_dot" aria-hidden="true"></span>
                    <div class="flex-grow-1 min-w-0">
                        <div class="d-flex justify-content-between gap-2">
                            <strong class="text-truncate">${this._escapeHtml(point.name || "Punto de recogida")}</strong>
                            <span class="text-nowrap fw-semibold">${this._escapeHtml(priceText)}</span>
                        </div>
                        <div class="small text-muted">${this._escapeHtml(point.carrier_name || point.carrier_code || point.provider_name || "")}</div>
                        <div class="small">${this._escapeHtml(point.street || "")} · ${this._escapeHtml([point.zip_code, point.city].filter(Boolean).join(" "))}</div>
                        <div class="optima_pickup_point_meta small mt-1">
                            <span><i class="fa fa-location-arrow me-1"></i>${this._escapeHtml(distanceText)}</span>
                            <span><i class="fa fa-clock-o me-1"></i>${this._escapeHtml(etaText)}</span>
                            <span>${this._escapeHtml(type)}</span>
                        </div>
                        ${today ? `<div class="small text-muted mt-1">Hoy: ${this._escapeHtml(today)}</div>` : ""}
                    </div>
                </div>`;
            card.addEventListener("click", () => this._selectUnifiedPointPreview(point));
            list.appendChild(card);
        }
        if (this._pickupMapState?.selectedKey) {
            const selected = this._pickupMapState.points.find(
                (point) => point.key === this._pickupMapState.selectedKey
            );
            if (selected) {
                this._showUnifiedPointConfirm(selected);
            }
        }
    },

    _renderUnifiedMapMarkers() {
        const state = this._pickupMapState;
        const map = state?.leaflet;
        if (!map || !window.L) {
            return;
        }
        for (const marker of state.markers.values()) {
            marker.remove();
        }
        state.markers.clear();
        const bounds = [];
        for (const point of state.points || []) {
            const lat = Number(point.latitude || 0);
            const lng = Number(point.longitude || 0);
            if (!lat || !lng) {
                continue;
            }
            const icon = window.L.divIcon({
                className: "optima_pickup_marker_wrapper",
                html: `<span class="optima_pickup_marker"><b></b></span>`,
                iconSize: [34, 34],
                iconAnchor: [17, 34],
            });
            const marker = window.L.marker([lat, lng], {icon}).addTo(map);
            marker.on("click", () => this._selectUnifiedPointPreview(point));
            state.markers.set(point.key, marker);
            bounds.push([lat, lng]);
        }
        if (bounds.length === 1) {
            map.setView(bounds[0], 15);
        } else if (bounds.length > 1) {
            map.fitBounds(bounds, {padding: [25, 25], maxZoom: 15});
        }
    },

    _selectUnifiedPointPreview(point) {
        const state = this._pickupMapState;
        if (!state) {
            return;
        }
        state.selectedKey = point.key;
        this._renderUnifiedMapPointList();
        const marker = state.markers.get(point.key);
        if (marker && state.leaflet) {
            state.leaflet.panTo(marker.getLatLng());
        }
        const selectedCard = this._findUnifiedPointCard(point.key);
        selectedCard?.scrollIntoView({block: "nearest", behavior: "smooth"});
        this._showUnifiedPointConfirm(point);
    },

    _findUnifiedPointCard(key) {
        return Array.from(this._pickupMapModal?.querySelectorAll("[data-point-key]") || []).find(
            (element) => element.dataset.pointKey === key
        );
    },

    _showUnifiedPointConfirm(point) {
        const card = this._findUnifiedPointCard(point.key);
        if (!card || card.querySelector("[data-optima-choose-point]")) {
            return;
        }
        const action = document.createElement("div");
        action.className = "mt-2 d-grid";
        action.innerHTML = `<button type="button" class="btn btn-primary btn-sm" data-optima-choose-point>Elegir este punto</button>`;
        action.querySelector("button").addEventListener("click", async (event) => {
            event.stopPropagation();
            const rawPoint = point.raw_point || point;
            const extra = point.extra || {};
            this._closeUnifiedMap();
            await this._savePoint(point.provider_code, rawPoint, extra);
        });
        card.appendChild(action);
    },

    _closeUnifiedMap() {
        if (this._pickupMapState?.leaflet) {
            this._pickupMapState.leaflet.remove();
        }
        this._pickupMapModal?.remove();
        this._pickupMapModal = null;
        this._pickupMapState = null;
        document.body.classList.remove("optima_pickup_map_open");
    },

    _formatDistance(distanceM) {
        const distance = Number(distanceM || 0);
        if (!distance) {
            return "Distancia no disponible";
        }
        if (distance < 1000) {
            return `${Math.round(distance)} m`;
        }
        return `${(distance / 1000).toFixed(distance < 10000 ? 1 : 0)} km`;
    },

    _formatLeadTime(hours) {
        const value = Number(hours || 0);
        if (!value) {
            return "Plazo no disponible";
        }
        if (value < 24) {
            return `≈ ${Math.round(value)} h`;
        }
        const days = value / 24;
        return `≈ ${Number.isInteger(days) ? days : days.toFixed(1)} día${days === 1 ? "" : "s"}`;
    },

    _openingToday(openingTimes) {
        if (!openingTimes || typeof openingTimes !== "object") {
            return "";
        }
        const sendcloudDay = (new Date().getDay() + 6) % 7;
        const values = openingTimes[String(sendcloudDay)] || openingTimes[sendcloudDay] || [];
        return Array.isArray(values) && values.length ? values.join(" / ") : "Cerrado";
    },

    _escapeHtml(value) {
        const div = document.createElement("div");
        div.textContent = String(value ?? "");
        return div.innerHTML;
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
