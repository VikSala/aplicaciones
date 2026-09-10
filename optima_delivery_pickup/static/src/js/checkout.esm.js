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
        this._pickupPrewarmJobs = new Map();
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

        const contextKey = this._pickupMapContextKey(providers);
        const cached = this._loadPickupMapCache(contextKey);
        const modal = this._buildUnifiedMapModal(providers);
        document.body.appendChild(modal);
        document.body.classList.add("optima_pickup_map_open");
        this._pickupMapModal = modal;
        this._pickupMapState = {
            providers,
            currentPoint: currentPoint || {},
            points: Array.isArray(cached?.points) ? cached.points : [],
            selectedKey: cached?.selectedKey || "",
            leaflet: null,
            markers: new Map(),
            contextKey,
            query: cached?.query || this._pickupMapDefaultQuery(providers),
            radiusM: Number(cached?.radiusM || 5000),
            carrierFilter: cached?.carrierFilter || "all",
            mapCenter: Array.isArray(cached?.mapCenter) ? cached.mapCenter : null,
            mapZoom: Number(cached?.mapZoom || 0),
            searchSequence: 0,
            searchRunning: false,
            needsFit: !cached?.points?.length,
        };

        const state = this._pickupMapState;
        // Keep the fingerprint available after the modal closes: _savePoint runs
        // after _closeUnifiedMap(), but still needs to find the warm-up job that
        // belongs to this exact address/logistics context.
        this._pickupPrewarmContextKey = contextKey;
        const input = modal.querySelector("[data-optima-query]");
        const radius = modal.querySelector("[data-optima-radius]");
        if (input) {
            input.value = state.query || "";
        }
        if (radius) {
            radius.value = String(state.radiusM || 5000);
        }

        const close = () => this._closeUnifiedMap();
        modal.querySelectorAll("[data-optima-map-close]").forEach((button) => {
            button.addEventListener("click", close);
        });
        modal.querySelector(".optima_pickup_map_backdrop")?.addEventListener("click", close);
        modal.querySelector("[data-optima-search]")?.addEventListener("click", () => {
            this._searchUnifiedMapPoints();
        });
        input?.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                this._searchUnifiedMapPoints();
            }
        });
        radius?.addEventListener("change", () => this._searchUnifiedMapPoints());

        this._renderUnifiedCarrierFilters();
        this._renderUnifiedMapPointList();
        if (state.points.length) {
            // Warm the nearest likely choice while the customer is looking at
            // cached map results. This is best-effort and never blocks the map.
            this._prewarmNearestUnifiedPoint();
            const status = modal.querySelector("[data-optima-result-status]");
            if (status) {
                status.textContent = `${state.points.length} puntos guardados para esta búsqueda`;
            }
            this._setUnifiedMapLoading(false);
        } else {
            this._setUnifiedMapLoading(true, `Buscando puntos cerca de ${state.query || "tu dirección"}…`);
        }

        // Start map assets and point discovery at the same time.  The map is
        // initialized as soon as Leaflet is available, while the loading overlay
        // hides the generic fallback center until nearby points arrive.
        const leafletPromise = this._loadLeaflet().catch(() => false);
        const searchPromise = !state.points.length
            ? this._searchUnifiedMapPoints({initial: true})
            : Promise.resolve();
        const leafletReady = await leafletPromise;
        if (leafletReady === false || !window.L?.map) {
            modal.querySelector("[data-optima-map-canvas]")?.classList.add("d-none");
            modal.querySelector("[data-optima-map-fallback]")?.classList.remove("d-none");
            await searchPromise;
            return;
        }
        this._initUnifiedLeafletMap();
        await searchPromise;
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
                    <div class="input-group optima_pickup_search_group">
                        <span class="input-group-text bg-white"><i class="fa fa-search" aria-hidden="true"></i></span>
                        <input type="text" class="form-control" data-optima-query placeholder="Dirección, ciudad o código postal"/>
                        <select class="form-select optima_pickup_radius" data-optima-radius aria-label="Radio de búsqueda">
                            <option value="5000" selected>5 km</option>
                            <option value="10000">10 km</option>
                            <option value="20000">20 km</option>
                            <option value="50000">50 km</option>
                        </select>
                        <button type="button" class="btn btn-primary" data-optima-search>Buscar</button>
                    </div>
                    <div class="optima_pickup_filter_row mt-2" data-optima-carrier-filters></div>
                    <div class="d-flex align-items-center mt-2">
                        <span class="small text-muted flex-grow-1" data-optima-result-status>Preparando búsqueda…</span>
                    </div>
                </div>
                <div class="optima_pickup_map_body">
                    <aside class="optima_pickup_point_panel">
                        <div class="optima_pickup_search_error alert alert-warning d-none" data-optima-search-error></div>
                        <div class="optima_pickup_point_list" data-optima-point-list></div>
                    </aside>
                    <div class="optima_pickup_map_visual">
                        <div class="optima_pickup_map_canvas" data-optima-map-canvas></div>
                        <div class="optima_pickup_map_loading" data-optima-map-loading>
                            <div class="spinner-border text-primary mb-2" role="status" aria-hidden="true"></div>
                            <div class="fw-semibold" data-optima-map-loading-label>Buscando puntos cercanos…</div>
                            <div class="small text-muted mt-1">Mostraremos primero los puntos más próximos.</div>
                        </div>
                        <div class="optima_pickup_map_fallback d-none" data-optima-map-fallback>
                            <i class="fa fa-map-o fa-2x mb-2" aria-hidden="true"></i>
                            <div>El mapa no ha podido cargarse.</div>
                            <div class="small text-muted">Puedes elegir el punto desde la lista.</div>
                        </div>
                    </div>
                </div>
            </section>`;
        return root;
    },

    _pickupMapDefaultQuery(providers) {
        for (const provider of providers || []) {
            const config = provider.config || {};
            if (config.default_query) {
                return String(config.default_query);
            }
            if (config.postal_code) {
                return String(config.postal_code);
            }
            const cityQuery = [config.postal_code, config.city].filter(Boolean).join(" ").trim();
            if (cityQuery) {
                return cityQuery;
            }
        }
        return "";
    },

    _pickupMapContextKey(providers) {
        return (providers || []).map((provider) => {
            const config = provider.config || {};
            const token = config.cache_token || [config.country, config.postal_code, config.city].filter(Boolean).join(":");
            return `${provider.code || ""}:${token}`;
        }).sort().join("|");
    },

    _loadPickupMapCache(contextKey) {
        try {
            const raw = window.sessionStorage.getItem("optima_pickup_map_cache_v2");
            if (!raw) {
                return null;
            }
            const cached = JSON.parse(raw);
            const age = Date.now() - Number(cached.savedAt || 0);
            if (cached.contextKey !== contextKey || age < 0 || age > 15 * 60 * 1000) {
                return null;
            }
            return cached;
        } catch {
            return null;
        }
    },

    _persistPickupMapCache() {
        const state = this._pickupMapState;
        if (!state?.contextKey) {
            return;
        }
        try {
            const mapCenter = state.leaflet?.getCenter();
            const payload = {
                savedAt: Date.now(),
                contextKey: state.contextKey,
                query: state.query || "",
                radiusM: Number(state.radiusM || 5000),
                carrierFilter: state.carrierFilter || "all",
                selectedKey: state.selectedKey || "",
                points: (state.points || []).slice(0, 100),
                mapCenter: mapCenter ? [mapCenter.lat, mapCenter.lng] : state.mapCenter,
                mapZoom: state.leaflet?.getZoom() || state.mapZoom || 0,
            };
            window.sessionStorage.setItem("optima_pickup_map_cache_v2", JSON.stringify(payload));
        } catch {
            // sessionStorage may be unavailable in hardened browsers. The map
            // still works; it simply loses reopen persistence.
        }
    },

    async _loadLeaflet() {
        if (window.L?.map) {
            return true;
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
        return true;
    },

    _initUnifiedLeafletMap() {
        const state = this._pickupMapState;
        const canvas = this._pickupMapModal?.querySelector("[data-optima-map-canvas]");
        if (!state || !canvas || state.leaflet || !window.L?.map) {
            return;
        }

        const initialCenter = this._preferredUnifiedMapCenter();
        const initialZoom = state.mapZoom || (initialCenter ? 14 : 6);
        const map = window.L.map(canvas, {
            zoomControl: true,
            attributionControl: true,
        }).setView(initialCenter || [40.4168, -3.7038], initialZoom);

        // Use the official OpenStreetMap raster tiles. They do not require an
        // API key, so the checkout cannot be polluted by provider watermarks
        // such as "API KEY REQUIRED". The map is intentionally street-focused
        // because pickup selection is a short-distance, neighbourhood task.
        window.L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a>',
        }).addTo(map);
        state.leaflet = map;
        map.on("moveend", () => this._persistPickupMapCache());
        window.setTimeout(() => {
            map.invalidateSize();
            this._renderUnifiedMapMarkers({fit: state.needsFit});
            state.needsFit = false;
        }, 50);
    },

    _preferredUnifiedMapCenter() {
        const state = this._pickupMapState;
        if (Array.isArray(state?.mapCenter) && state.mapCenter.length === 2) {
            return state.mapCenter;
        }
        const selected = (state?.points || []).find((point) => point.key === state.selectedKey);
        const current = selected || state?.currentPoint || {};
        const currentLat = Number(current.latitude || current.lat || 0);
        const currentLng = Number(current.longitude || current.lng || current.lon || 0);
        if (currentLat && currentLng) {
            return [currentLat, currentLng];
        }
        const nearest = [...(state?.points || [])]
            .filter((point) => Number(point.latitude) && Number(point.longitude))
            .sort((a, b) => Number(a.distance_m || Number.MAX_SAFE_INTEGER) - Number(b.distance_m || Number.MAX_SAFE_INTEGER))[0];
        return nearest ? [Number(nearest.latitude), Number(nearest.longitude)] : null;
    },

    _setUnifiedMapLoading(loading, label = "Buscando puntos cercanos…") {
        const overlay = this._pickupMapModal?.querySelector("[data-optima-map-loading]");
        const labelNode = this._pickupMapModal?.querySelector("[data-optima-map-loading-label]");
        if (labelNode) {
            labelNode.textContent = label;
        }
        overlay?.classList.toggle("d-none", !loading);
    },

    async _searchUnifiedMapPoints({initial = false} = {}) {
        const modal = this._pickupMapModal;
        const state = this._pickupMapState;
        if (!modal || !state || state.searchRunning) {
            return;
        }
        const input = modal.querySelector("[data-optima-query]");
        const radius = modal.querySelector("[data-optima-radius]");
        const status = modal.querySelector("[data-optima-result-status]");
        const errorBox = modal.querySelector("[data-optima-search-error]");
        const searchButton = modal.querySelector("[data-optima-search]");
        const query = (input?.value || state.query || this._pickupMapDefaultQuery(state.providers) || "").trim();
        const radiusM = Number.parseInt(radius?.value || String(state.radiusM || 5000), 10) || 5000;
        const sequence = ++state.searchSequence;

        state.searchRunning = true;
        state.query = query;
        state.radiusM = radiusM;
        status.textContent = state.points.length ? "Actualizando puntos cercanos…" : "Buscando puntos compatibles…";
        errorBox.classList.add("d-none");
        errorBox.replaceChildren();
        searchButton.disabled = true;
        if (!state.points.length || initial) {
            this._setUnifiedMapLoading(true, `Buscando puntos cerca de ${query || "tu dirección"}…`);
        }

        try {
            const result = await this._searchUnifiedProviderPoints({query, radiusM});
            if (sequence !== state.searchSequence || !this._pickupMapState) {
                return;
            }
            if (result.query) {
                state.query = result.query;
                if (input) {
                    input.value = result.query;
                }
            }
            state.points = Array.isArray(result.points) ? result.points : [];
            state.needsFit = true;
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
                ? `${state.points.length} puntos encontrados en ${Math.round(radiusM / 1000)} km`
                : "No se han encontrado puntos compatibles en este radio.";
            this._renderUnifiedCarrierFilters();
            this._renderUnifiedMapPointList();
            this._renderUnifiedMapMarkers({fit: true});
            state.needsFit = !state.leaflet;
            this._persistPickupMapCache();
            this._prewarmNearestUnifiedPoint();
        } catch (error) {
            if (sequence !== state.searchSequence || !this._pickupMapState) {
                return;
            }
            // Never destroy already useful results because a refresh timed out.
            // Closing/reopening therefore remains instant and resilient.
            if (state.points.length) {
                status.textContent = `${state.points.length} puntos guardados · no se ha podido actualizar ahora`;
                errorBox.textContent = "No se ha podido actualizar la búsqueda. Se mantienen los últimos puntos encontrados.";
            } else {
                status.textContent = "No se ha podido completar la búsqueda.";
                errorBox.textContent = this._isConnectionError(error)
                    ? "La búsqueda ha tardado demasiado. Reintenta o usa el selector oficial de Sendcloud."
                    : this._errorMessage(error);
            }
            errorBox.classList.remove("d-none");
            this._appendOfficialSelectorFallback(errorBox);
        } finally {
            if (this._pickupMapState && sequence === state.searchSequence) {
                state.searchRunning = false;
                searchButton.disabled = false;
                this._setUnifiedMapLoading(false);
            }
        }
    },

    async _searchUnifiedProviderPoints({query, radiusM}) {
        const state = this._pickupMapState;
        if (!state) {
            return {query, points: [], errors: []};
        }

        // Providers may expose a browser-side discovery method.  This is ideal
        // for APIs such as Sendcloud Service Points that explicitly support a
        // public API key: it avoids routing the discovery request through the
        // Odoo worker/reverse proxy.  Providers without such an API continue to
        // use the generic server-side hook.  All providers run in parallel.
        const jobs = (state.providers || []).map(async (descriptor) => {
            const provider = pickupProviderRegistry.get(descriptor.code);
            if (!provider?.searchPoints) {
                return {code: descriptor.code, fallback: true};
            }
            try {
                const result = await provider.searchPoints({
                    config: descriptor.config || {},
                    query,
                    radiusM,
                });
                return {
                    code: descriptor.code,
                    direct: true,
                    result: result || {},
                };
            } catch (error) {
                return {code: descriptor.code, fallback: true, error};
            }
        });

        const settled = await Promise.all(jobs);
        const points = [];
        const errors = [];
        const fallbackCodes = [];
        for (const item of settled) {
            if (item.direct) {
                if (Array.isArray(item.result.points)) {
                    points.push(...item.result.points);
                }
                if (Array.isArray(item.result.errors)) {
                    errors.push(...item.result.errors);
                }
            } else if (item.code) {
                fallbackCodes.push(item.code);
            }
        }

        if (fallbackCodes.length) {
            try {
                const fallback = await rpc("/shop/optima_pickup/search_points", {
                    provider_codes: fallbackCodes,
                    query,
                    radius_m: radiusM,
                });
                if (Array.isArray(fallback?.points)) {
                    points.push(...fallback.points);
                }
                if (Array.isArray(fallback?.errors)) {
                    errors.push(...fallback.errors);
                }
            } catch (error) {
                // If no provider returned anything directly, preserve the old
                // connection error semantics so the official selector fallback
                // remains available.
                if (!points.length) {
                    throw error;
                }
                errors.push({message: "No se han podido actualizar algunos proveedores."});
            }
        }

        points.sort((a, b) => {
            const da = Number(a.distance_m || Number.MAX_SAFE_INTEGER);
            const db = Number(b.distance_m || Number.MAX_SAFE_INTEGER);
            return da - db || String(a.name || "").localeCompare(String(b.name || ""));
        });
        return {query, points: points.slice(0, 100), errors};
    },

    _appendOfficialSelectorFallback(container) {
        const state = this._pickupMapState;
        if (!container || !state || container.querySelector("[data-optima-official-fallback]")) {
            return;
        }
        const descriptor = state.providers.length === 1 ? state.providers[0] : null;
        const provider = descriptor ? pickupProviderRegistry.get(descriptor.code) : null;
        if (!descriptor || !provider?.open) {
            return;
        }
        const wrapper = document.createElement("div");
        wrapper.className = "mt-2";
        wrapper.innerHTML = `<button type="button" class="btn btn-sm btn-outline-primary" data-optima-official-fallback>Usar selector oficial de ${this._escapeHtml(descriptor.name || descriptor.code)}</button>`;
        wrapper.querySelector("button").addEventListener("click", async () => {
            const currentPoint = state.currentPoint || {};
            this._closeUnifiedMap();
            await provider.open({
                config: descriptor.config || {},
                currentPoint,
                onSelect: async (rawPoint, extra = {}) => {
                    await this._savePoint(descriptor.code, rawPoint, extra);
                },
                onError: (message) => this._showError(this._getLivePickupContainer(), message),
            });
        });
        container.appendChild(wrapper);
    },

    _renderUnifiedCarrierFilters() {
        const container = this._pickupMapModal?.querySelector("[data-optima-carrier-filters]");
        const state = this._pickupMapState;
        if (!container || !state) {
            return;
        }
        const carriers = new Map();
        for (const point of state.points || []) {
            const key = point.carrier_code || point.carrier_name || point.provider_code || "other";
            if (!carriers.has(key)) {
                carriers.set(key, {
                    key,
                    name: point.carrier_name || point.carrier_code || point.provider_name || "Otros",
                    count: 0,
                });
            }
            carriers.get(key).count += 1;
        }
        container.replaceChildren();
        if (carriers.size <= 1) {
            return;
        }
        const options = [
            {key: "all", name: "Todos", count: state.points.length},
            ...Array.from(carriers.values()).sort((a, b) => a.name.localeCompare(b.name)),
        ];
        if (!options.some((item) => item.key === state.carrierFilter)) {
            state.carrierFilter = "all";
        }
        for (const item of options) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "optima_pickup_filter_chip";
            button.classList.toggle("active", state.carrierFilter === item.key);
            button.innerHTML = `<span>${this._escapeHtml(item.name)}</span><span class="optima_pickup_filter_count">${item.count}</span>`;
            button.addEventListener("click", () => {
                state.carrierFilter = item.key;
                this._renderUnifiedCarrierFilters();
                this._renderUnifiedMapPointList();
                this._renderUnifiedMapMarkers({fit: true});
                this._persistPickupMapCache();
                this._prewarmNearestUnifiedPoint();
            });
            container.appendChild(button);
        }
    },

    _visibleUnifiedPoints() {
        const state = this._pickupMapState;
        const filter = state?.carrierFilter || "all";
        const points = filter === "all"
            ? [...(state?.points || [])]
            : (state?.points || []).filter(
                (point) => (point.carrier_code || point.carrier_name || point.provider_code || "other") === filter
            );
        const missing = Number.MAX_SAFE_INTEGER;
        const distance = (point) => {
            const value = Number(point.distance_m || 0);
            return value > 0 ? value : missing;
        };
        points.sort((a, b) => distance(a) - distance(b) || String(a.name || "").localeCompare(String(b.name || "")));
        return points;
    },

    _renderUnifiedMapPointList() {
        const list = this._pickupMapModal?.querySelector("[data-optima-point-list]");
        if (!list) {
            return;
        }
        list.replaceChildren();
        const points = this._visibleUnifiedPoints();
        for (const point of points) {
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
            const brandMarker = this._brandMarkerAsset(point);
            const logo = brandMarker
                ? `<img class="optima_pickup_card_marker" src="${this._escapeAttr(brandMarker)}" alt="${this._escapeAttr(point.carrier_name || point.carrier_code || "Transportista")}"/>`
                : point.marker_icon
                    ? `<img class="optima_pickup_card_logo" src="${this._escapeAttr(point.marker_icon)}" alt="${this._escapeAttr(point.carrier_name || point.carrier_code || "Transportista")}"/>`
                    : `<span class="optima_pickup_card_logo optima_pickup_card_logo_fallback">${this._escapeHtml(this._carrierInitials(point))}</span>`;
            card.innerHTML = `
                <div class="d-flex align-items-start gap-2">
                    ${logo}
                    <div class="flex-grow-1 min-w-0">
                        <div class="d-flex justify-content-between gap-2">
                            <strong class="text-truncate">${this._escapeHtml(point.name || "Punto de recogida")}</strong>
                            <span class="text-nowrap fw-semibold">${this._escapeHtml(priceText)}</span>
                        </div>
                        <div class="small text-muted">${this._escapeHtml(point.carrier_name || point.carrier_code || point.provider_name || "")}</div>
                        <div class="small mt-1">${this._escapeHtml(point.street || "")}<br/>${this._escapeHtml([point.zip_code, point.city].filter(Boolean).join(" "))}</div>
                        <div class="optima_pickup_point_meta small mt-2">
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
        if (!points.length && !this._pickupMapState?.searchRunning) {
            const empty = document.createElement("div");
            empty.className = "text-muted small p-3";
            empty.textContent = "No hay puntos para el filtro seleccionado.";
            list.appendChild(empty);
        }
        if (this._pickupMapState?.selectedKey) {
            const selected = (this._pickupMapState.points || []).find(
                (point) => point.key === this._pickupMapState.selectedKey
            );
            if (selected && this._findUnifiedPointCard(selected.key)) {
                this._showUnifiedPointConfirm(selected);
            }
        }
    },

    _carrierInitials(point) {
        const name = String(point.carrier_name || point.carrier_code || "P").trim();
        return name.split(/\s+/).map((part) => part[0] || "").join("").slice(0, 3).toUpperCase() || "P";
    },

    _brandMarkerAsset(point) {
        const raw = [
            point?.carrier_code,
            point?.carrier_name,
            point?.provider_code,
            point?.provider_name,
        ].filter(Boolean).join(" ").toLowerCase().replace(/[^a-z0-9]+/g, "_");
        if (raw.includes("correos_express")) {
            return "/optima_delivery_pickup/static/src/img/markers/correos_express.svg";
        }
        if (raw.includes("correos")) {
            return "/optima_delivery_pickup/static/src/img/markers/correos.svg";
        }
        if (raw.includes("inpost") || raw.includes("mondial_relay")) {
            return "/optima_delivery_pickup/static/src/img/markers/inpost.svg";
        }
        return "";
    },

    _renderUnifiedMapMarkers({fit = false} = {}) {
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
        for (const point of this._visibleUnifiedPoints()) {
            const lat = Number(point.latitude || 0);
            const lng = Number(point.longitude || 0);
            if (!lat || !lng) {
                continue;
            }
            const isSelected = state.selectedKey === point.key;
            const brandMarker = this._brandMarkerAsset(point);
            let icon;
            if (brandMarker) {
                icon = window.L.divIcon({
                    className: "optima_pickup_marker_wrapper",
                    html: `<img class="optima_pickup_brand_marker${isSelected ? " active" : ""}" src="${this._escapeAttr(brandMarker)}" alt="${this._escapeAttr(point.carrier_name || point.carrier_code || "Transportista")}"/>`,
                    iconSize: [39, 51],
                    iconAnchor: [20, 49],
                    tooltipAnchor: [0, -42],
                });
            } else {
                const logo = point.marker_icon
                    ? `<img src="${this._escapeAttr(point.marker_icon)}" alt=""/>`
                    : `<span>${this._escapeHtml(this._carrierInitials(point))}</span>`;
                icon = window.L.divIcon({
                    className: "optima_pickup_marker_wrapper",
                    html: `<span class="optima_pickup_marker${isSelected ? " active" : ""}">${logo}</span>`,
                    iconSize: [46, 46],
                    iconAnchor: [23, 44],
                });
            }
            const marker = window.L.marker([lat, lng], {icon, keyboard: true}).addTo(map);
            marker.on("click", () => this._selectUnifiedPointPreview(point));
            marker.bindTooltip(
                `<strong>${this._escapeHtml(point.name || "Punto")}</strong><br/>${this._escapeHtml(point.carrier_name || point.carrier_code || "")} · ${this._escapeHtml(this._formatDistance(point.distance_m))}`,
                {direction: "top", offset: [0, -36]}
            );
            state.markers.set(point.key, marker);
            bounds.push([lat, lng]);
        }
        if (!fit || !bounds.length) {
            return;
        }
        if (bounds.length === 1) {
            map.setView(bounds[0], 16);
        } else {
            map.fitBounds(bounds, {padding: [38, 38], maxZoom: 15});
        }
    },

    _selectUnifiedPointPreview(point) {
        const state = this._pickupMapState;
        if (!state) {
            return;
        }
        state.selectedKey = point.key;
        this._startPickupPointPrewarm(point);
        this._renderUnifiedMapPointList();
        this._renderUnifiedMapMarkers({fit: false});
        const marker = state.markers.get(point.key);
        if (marker && state.leaflet) {
            const zoom = Math.max(state.leaflet.getZoom(), 16);
            state.leaflet.setView(marker.getLatLng(), zoom, {animate: true});
            marker.openTooltip();
        }
        const selectedCard = this._findUnifiedPointCard(point.key);
        selectedCard?.scrollIntoView({block: "nearest", behavior: "smooth"});
        this._showUnifiedPointConfirm(point);
        this._persistPickupMapCache();
    },

    _pickupPointPrewarmKey(providerCode, point = {}) {
        const carrier = String(point.carrier || point.carrier_code || "").trim().toLowerCase();
        const postalCode = String(point.postal_code || point.zip_code || "").trim().toUpperCase();
        const contextKey = this._pickupMapState?.contextKey || this._pickupPrewarmContextKey || "";
        return [contextKey, providerCode || "", carrier, postalCode].join("|");
    },

    _startPickupPointPrewarm(point) {
        if (!point?.provider_code) {
            return null;
        }
        const rawPoint = point.raw_point || point;
        const extra = point.extra || {};
        const key = this._pickupPointPrewarmKey(point.provider_code, rawPoint);
        if (!key || this._pickupPrewarmJobs?.has(key)) {
            return this._pickupPrewarmJobs?.get(key) || null;
        }
        if (!this._pickupPrewarmJobs) {
            this._pickupPrewarmJobs = new Map();
        }

        // Do not surface warm-up errors: final set_point is still authoritative
        // and will show the normal checkout error if Sendcloud is unavailable.
        const job = rpc("/shop/optima_pickup/prewarm_point", {
            provider_code: point.provider_code,
            point: rawPoint,
            extra,
        })
            .catch(() => ({success: false, prepared: false}))
            .then((result) => {
                // Failed warm-ups may be retried shortly; successful ones are
                // remembered only while the corresponding server cache is fresh.
                const retention = result?.prepared ? 20 * 60 * 1000 : 1500;
                window.setTimeout(() => {
                    if (this._pickupPrewarmJobs?.get(key) === job) {
                        this._pickupPrewarmJobs.delete(key);
                    }
                }, retention);
                return result;
            });
        this._pickupPrewarmJobs.set(key, job);
        return job;
    },

    _prewarmNearestUnifiedPoint() {
        const point = this._visibleUnifiedPoints()[0];
        if (point) {
            this._startPickupPointPrewarm(point);
        }
    },

    async _awaitPickupPointPrewarm(providerCode, rawPoint) {
        const key = this._pickupPointPrewarmKey(providerCode, rawPoint);
        const job = this._pickupPrewarmJobs?.get(key);
        if (!job) {
            return;
        }
        try {
            await job;
        } catch {
            // Final resolution below remains the source of truth.
        }
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
            this._persistPickupMapCache();
            this._closeUnifiedMap();
            await this._savePoint(point.provider_code, rawPoint, extra);
        });
        card.appendChild(action);
    },

    _closeUnifiedMap() {
        this._persistPickupMapCache();
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
            return "Plazo al seleccionar";
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

    _escapeAttr(value) {
        return String(value ?? "")
            .replaceAll("&", "&amp;")
            .replaceAll('"', "&quot;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;");
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
            // If this exact carrier/postcode was already being prepared while the
            // customer looked at the map, let that request finish first. The real
            // set_point call then reuses its server-side caches instead of issuing
            // the same Sendcloud requests a second time.
            await this._awaitPickupPointPrewarm(providerCode, rawPoint);
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
