/** @odoo-module **/

import { Component, useState, useRef, onMounted, onPatched, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";
import { loadChartJS } from "./utils/cdn_loader";

const STATUS_LABELS = {
    outgoing: "Queued",
    sent: "Sent",
    delivered: "Delivered",
    read: "Read",
    received: "Received",
    error: "Error",
    bounced: "Bounced",
    cancel: "Cancelled",
    replied: "Replied",
};
const STATUS_COLORS = {
    outgoing: "#d97706",   // amber
    sent:     "#0891b2",   // cyan
    delivered:"#25d366",   // whatsapp green
    read:     "#027a48",   // deep green
    received: "#7c3aed",   // violet
    error:    "#d92d20",   // red
    bounced:  "#e54690",   // pink
    cancel:   "#9ca3af",   // gray
    replied:  "#4f46e5",   // indigo
};

// Shared chart styling for the light professional theme
const OWA_CHART_THEME = {
    text:      "#374151",
    textDim:   "#6b7280",
    grid:      "rgba(17, 24, 39, 0.06)",
    gridSoft:  "rgba(17, 24, 39, 0.03)",
    tooltipBg: "#111827",
    tooltipBd: "#111827",
    font:      "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif",
};

function _applyChartTheme(Chart) {
    // Re-apply on every render so theme survives bundle re-init.
    // Be defensive: if another Odoo addon pre-loaded an older Chart.js
    // (v2/v3) the defaults sub-objects (font, plugins.legend.labels,
    // plugins.tooltip) may not exist and naive sets crash the dashboard
    // with "Cannot set properties of undefined (setting 'family')".
    const d = Chart.defaults || (Chart.defaults = {});
    d.color = OWA_CHART_THEME.text;
    d.borderColor = OWA_CHART_THEME.grid;
    d.font = d.font || {};
    d.font.family = OWA_CHART_THEME.font;
    d.font.size = 11;
    d.plugins = d.plugins || {};
    d.plugins.legend = d.plugins.legend || {};
    d.plugins.legend.labels = d.plugins.legend.labels || {};
    const lbl = d.plugins.legend.labels;
    lbl.boxWidth = 8;
    lbl.boxHeight = 8;
    lbl.padding = 14;
    lbl.usePointStyle = true;
    d.plugins.tooltip = d.plugins.tooltip || {};
    const tt = d.plugins.tooltip;
    tt.backgroundColor = OWA_CHART_THEME.tooltipBg;
    tt.borderColor = OWA_CHART_THEME.tooltipBd;
    tt.borderWidth = 0;
    tt.titleColor = "#ffffff";
    tt.bodyColor = "#e5e7eb";
    tt.padding = 10;
    tt.cornerRadius = 6;
    tt.displayColors = true;
    tt.boxPadding = 6;
}

function _axisOptions() {
    return {
        ticks: { color: OWA_CHART_THEME.textDim, font: { size: 10 }, precision: 0 },
        grid:  { color: OWA_CHART_THEME.grid, drawBorder: false },
        border:{ display: false },
    };
}

function todayIso() {
    const d = new Date();
    return d.toISOString().slice(0, 10);
}
function isoDaysAgo(n) {
    const d = new Date();
    d.setDate(d.getDate() - n);
    return d.toISOString().slice(0, 10);
}

export class OwaDashboard extends Component {
    static template = "open_whatsapp_connector.OwaDashboard";

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.busService = useService("bus_service");

        this.statusChart = useRef("statusChart");
        this.perDayChart = useRef("perDayChart");
        this.topPartnersChart = useRef("topPartnersChart");
        this.failureChart = useRef("failureChart");

        this._charts = [];
        this._pendingChartInit = false;

        this.state = useState({
            loading: true,
            startingSidecars: false,
            accounts: [],
            filters: {
                dateFrom: isoDaysAgo(30),
                dateTo: todayIso(),
                accountIds: [],
            },
            data: this._emptyData(),
        });

        onMounted(async () => {
            await this._loadAccountList();
            await this.loadDashboardData();
        });

        // Push-based refresh: the sidecar pushes every connection-state
        // transition to controllers/main.py which fans it out on the
        // 'open_whatsapp_connector/account_updated' bus channel. Nothing was
        // listening, so the dashboard never flipped to "Connected" without a
        // manual refresh. Debounced so a burst of reconnects collapses into
        // one reload. (#push_state)
        this._onAccountUpdated = () => {
            clearTimeout(this._acctUpdateTimer);
            this._acctUpdateTimer = setTimeout(() => {
                if (!this.state.loading) {
                    this._loadAccountList();
                    this.loadDashboardData();
                }
            }, 400);
        };
        this.busService.subscribe(
            "open_whatsapp_connector/account_updated", this._onAccountUpdated);

        onPatched(() => {
            if (!this.state.loading && this._pendingChartInit) {
                this._pendingChartInit = false;
                this._renderCharts();
            }
        });

        onWillUnmount(() => {
            this._destroyCharts();
            clearTimeout(this._acctUpdateTimer);
            this.busService.unsubscribe(
                "open_whatsapp_connector/account_updated", this._onAccountUpdated);
        });
    }

    _emptyData() {
        return {
            counters: {
                total_messages: 0, messages_sent: 0, messages_received: 0,
                messages_failed_24h: 0, messages_outgoing_now: 0,
                accounts_total: 0, accounts_connected: 0, accounts_disconnected: 0,
                sidecars_total: 0, sidecars_running: 0,
                disconnected_accounts_detail: [],
                active_channels: 0, campaigns_running: 0,
                notification_rules_active: 0, auto_reply_rules_active: 0,
                chatbot_sessions_active: 0,
                missed_calls_24h: 0, calls_total: 0, video_calls_total: 0,
            },
            status_counts: {},
            messages_per_day: { outbound: {}, inbound: {} },
            messages_per_account: [],
            top_partners: [],
            top_failure_reasons: [],
            recent_failures: [],
            account_health: [],
            filters_echo: {},
        };
    }

    async _loadAccountList() {
        try {
            this.state.accounts = await this.orm.searchRead(
                "owa.account", [], ["id", "name"], { order: "name" },
            );
        } catch (e) {
            this.notification.add(_t("Failed to load account list."), { type: "warning" });
        }
    }

    async loadDashboardData() {
        this.state.loading = true;
        this._destroyCharts();
        try {
            const args = [
                this.state.filters.dateFrom || null,
                this.state.filters.dateTo || null,
                this.state.filters.accountIds.length ? this.state.filters.accountIds : null,
            ];
            const data = await this.orm.call(
                "owa.dashboard", "get_dashboard_data", args,
            );
            this.state.data = data;
        } catch (e) {
            this.notification.add(_t("Failed to load dashboard data."), { type: "danger" });
            this.state.data = this._emptyData();
        }
        this._pendingChartInit = true;
        this.state.loading = false;
    }

    sidecarsAllRunning() {
        const c = this.state.data.counters || {};
        return (c.sidecars_total || 0) > 0 && c.sidecars_running >= c.sidecars_total;
    }

    accountsAllConnected() {
        const c = this.state.data.counters || {};
        return (c.accounts_total || 0) > 0 && c.accounts_connected >= c.accounts_total;
    }

    /** Fully online = every sidecar up AND every WhatsApp session connected. */
    sidecarsFullyOnline() {
        return this.sidecarsAllRunning() && this.accountsAllConnected();
    }

    sidecarBtnClass() {
        const base = "btn";
        if (this.sidecarsFullyOnline()) {
            return `${base} owa_btn_sidecar_running`;
        }
        // Amber 'pairing' state: the Node process(es) are up but at least one
        // account isn't connected yet (qr_pending / connecting) — distinct
        // from fully-stopped (red). (#start_sidecar)
        if (this.sidecarsAllRunning()) {
            return `${base} owa_btn_sidecar_pairing`;
        }
        return `${base} owa_btn_sidecar_stopped`;
    }

    sidecarBtnLabel() {
        const c = this.state.data.counters || {};
        if (this.state.startingSidecars) {
            return _t("Starting…");
        }
        if (this.sidecarsFullyOnline()) {
            return c.accounts_total > 1 ? _t("All Connected") : _t("Connected");
        }
        return _t("Start Sidecar");
    }

    sidecarBtnIcon() {
        if (this.state.startingSidecars) {
            return "fa fa-spinner fa-spin";
        }
        return this.sidecarsFullyOnline() ? "fa fa-check-circle" : "fa fa-play";
    }

    async onStartSidecars() {
        if (this.state.startingSidecars || this.sidecarsFullyOnline()) {
            return;
        }
        this.state.startingSidecars = true;
        try {
            const result = await this.orm.call(
                "owa.dashboard", "action_start_sidecars", [],
            );
            const started = result.started || [];
            const already = result.already_running || [];
            const failed = result.failed || [];
            const connected = result.connected || [];
            const connectSkipped = result.connect_skipped || [];
            const connectFailed = result.connect_failed || [];
            if (failed.length) {
                this.notification.add(
                    _t("Failed to start sidecar for: %s", failed.map((f) => f.name).join(", ")),
                    { type: "danger" },
                );
            }
            if (started.length) {
                this.notification.add(
                    _t("Sidecar started: %s", started.join(", ")),
                    { type: "success" },
                );
            } else if (!failed.length && already.length && !connected.length) {
                this.notification.add(
                    _t("Sidecar already running: %s", already.join(", ")),
                    { type: "info" },
                );
            } else if (!failed.length && !started.length && !already.length) {
                this.notification.add(_t("No accounts configured."), { type: "warning" });
            }
            if (connected.length) {
                this.notification.add(
                    _t("WhatsApp connected: %s", connected.join(", ")),
                    { type: "success" },
                );
            }
            if (connectSkipped.length) {
                const detail = connectSkipped
                    .map((s) => `${s.name} (${s.reason})`)
                    .join(", ");
                this.notification.add(
                    _t("WhatsApp connect skipped: %s", detail),
                    { type: "warning" },
                );
            }
            if (connectFailed.length) {
                const detail = connectFailed
                    .map((f) => `${f.name}: ${f.err}`)
                    .join("; ");
                this.notification.add(
                    _t("WhatsApp connect failed: %s", detail),
                    { type: "danger" },
                );
            }
            await this.loadDashboardData();
        } catch (e) {
            this.notification.add(_t("Failed to start sidecars."), { type: "danger" });
        }
        this.state.startingSidecars = false;
    }

    onAccountFilterChange(ev) {
        const value = ev.target.value;
        this.state.filters.accountIds = value ? [parseInt(value, 10)] : [];
        this.loadDashboardData();
    }

    // ── Charts ────────────────────────────────────────────────────────────
    async _renderCharts() {
        let Chart;
        try {
            Chart = await loadChartJS();
        } catch (e) {
            this.notification.add(_t("Failed to load Chart.js. Charts disabled."), { type: "warning" });
            return;
        }
        _applyChartTheme(Chart);

        // Status doughnut
        if (this.statusChart.el) {
            const counts = this.state.data.status_counts || {};
            const keys = Object.keys(counts);
            if (keys.length) {
                this._charts.push(new Chart(this.statusChart.el, {
                    type: "doughnut",
                    data: {
                        labels: keys.map((k) => STATUS_LABELS[k] || k),
                        datasets: [{
                            data: keys.map((k) => counts[k]),
                            backgroundColor: keys.map((k) => STATUS_COLORS[k] || "#9ca3af"),
                            borderColor: "#ffffff",
                            borderWidth: 2,
                            hoverOffset: 6,
                        }],
                    },
                    options: {
                        responsive: true, maintainAspectRatio: false,
                        cutout: "62%",
                        plugins: { legend: { position: "bottom" } },
                    },
                }));
            }
        }

        // Messages per day line
        if (this.perDayChart.el) {
            const out = this.state.data.messages_per_day.outbound || {};
            const inn = this.state.data.messages_per_day.inbound || {};
            const days = Array.from(new Set([...Object.keys(out), ...Object.keys(inn)])).sort();
            // Build vertical gradients for the area fills
            const ctx = this.perDayChart.el.getContext("2d");
            const gradOut = ctx.createLinearGradient(0, 0, 0, 260);
            gradOut.addColorStop(0, "rgba(37, 211, 102, 0.22)");
            gradOut.addColorStop(1, "rgba(37, 211, 102, 0)");
            const gradIn = ctx.createLinearGradient(0, 0, 0, 260);
            gradIn.addColorStop(0, "rgba(79, 70, 229, 0.18)");
            gradIn.addColorStop(1, "rgba(79, 70, 229, 0)");
            this._charts.push(new Chart(this.perDayChart.el, {
                type: "line",
                data: {
                    labels: days,
                    datasets: [
                        {
                            label: _t("Outbound"),
                            data: days.map((d) => out[d] || 0),
                            borderColor: "#25d366",
                            backgroundColor: gradOut,
                            borderWidth: 2,
                            pointRadius: 0,
                            pointHoverRadius: 5,
                            pointHoverBackgroundColor: "#25d366",
                            pointHoverBorderColor: "#ffffff",
                            pointHoverBorderWidth: 2,
                            tension: 0.35, fill: true,
                        },
                        {
                            label: _t("Inbound"),
                            data: days.map((d) => inn[d] || 0),
                            borderColor: "#4f46e5",
                            backgroundColor: gradIn,
                            borderWidth: 2,
                            pointRadius: 0,
                            pointHoverRadius: 5,
                            pointHoverBackgroundColor: "#4f46e5",
                            pointHoverBorderColor: "#ffffff",
                            pointHoverBorderWidth: 2,
                            tension: 0.35, fill: true,
                        },
                    ],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    interaction: { mode: "index", intersect: false },
                    plugins: { legend: { position: "bottom" } },
                    scales: {
                        x: _axisOptions(),
                        y: { ..._axisOptions(), beginAtZero: true },
                    },
                },
            }));
        }

        // Top partners h-bar
        if (this.topPartnersChart.el && this.state.data.top_partners.length) {
            const partners = this.state.data.top_partners;
            this._charts.push(new Chart(this.topPartnersChart.el, {
                type: "bar",
                data: {
                    labels: partners.map((p) => p.name),
                    datasets: [{
                        label: _t("Channels"),
                        data: partners.map((p) => p.channel_count),
                        backgroundColor: "rgba(79, 70, 229, 0.78)",
                        hoverBackgroundColor: "#4f46e5",
                        borderRadius: 4,
                        borderSkipped: false,
                        barThickness: 14,
                    }],
                },
                options: {
                    indexAxis: "y",
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { ..._axisOptions(), beginAtZero: true },
                        y: _axisOptions(),
                    },
                },
            }));
        }

        // Failure reasons bar
        if (this.failureChart.el && this.state.data.top_failure_reasons.length) {
            const reasons = this.state.data.top_failure_reasons;
            this._charts.push(new Chart(this.failureChart.el, {
                type: "bar",
                data: {
                    labels: reasons.map((r) => r.failure_type),
                    datasets: [{
                        label: _t("Failures"),
                        data: reasons.map((r) => r.count),
                        backgroundColor: "rgba(217, 45, 32, 0.72)",
                        hoverBackgroundColor: "#d92d20",
                        borderRadius: 4,
                        borderSkipped: false,
                        barThickness: 22,
                    }],
                },
                options: {
                    responsive: true, maintainAspectRatio: false,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: _axisOptions(),
                        y: { ..._axisOptions(), beginAtZero: true },
                    },
                },
            }));
        }
    }

    _destroyCharts() {
        for (const c of this._charts) {
            try { c.destroy(); } catch (e) { /* ignore */ }
        }
        this._charts = [];
    }

    // ── Connectivity tile helpers ─────────────────────────────────────────

    /** True when at least one account is not in the 'connected' WhatsApp state. */
    hasConnectivityIssue() {
        const c = this.state.data.counters || {};
        const total = c.accounts_total || 0;
        const connected = c.accounts_connected || 0;
        return total > 0 && connected < total;
    }

    /** Severity class on the Connected KPI tile — 'danger' when any account
     * is offline, 'success' when everything is up, 'info' when no accounts
     * exist at all. */
    connectedTileClass() {
        const c = this.state.data.counters || {};
        if (!c.accounts_total) return "info";
        return this.hasConnectivityIssue() ? "danger attention" : "success";
    }

    /** One-line reason summary shown under the Connected KPI value. */
    connectedTileSubtext() {
        const c = this.state.data.counters || {};
        if (!c.accounts_total) {
            return _t("no accounts");
        }
        if (!this.hasConnectivityIssue()) {
            return _t("live sessions");
        }
        const detail = c.disconnected_accounts_detail || [];
        if (!detail.length) {
            return _t("disconnected");
        }
        // Single account: be specific. Multiple: aggregate.
        if (detail.length === 1) {
            const d = detail[0];
            return `${d.name} · ${this._reasonText(d.reason)}`;
        }
        // Pick the worst-shared reason.
        const reasons = new Set(detail.map((d) => d.reason));
        if (reasons.has("sidecar_stopped")) {
            return _t("sidecar stopped on %s account(s)", detail.length);
        }
        return _t("%s accounts not connected", detail.length);
    }

    _reasonText(reason) {
        const map = {
            sidecar_stopped:        _t("sidecar not running"),
            awaiting_qr:            _t("awaiting QR scan"),
            logged_out:             _t("logged out — re-scan QR"),
            connecting:             _t("connecting…"),
            whatsapp_disconnected:  _t("WhatsApp not connected"),
        };
        return map[reason] || _t("not connected");
    }

    // ── Drill-through ─────────────────────────────────────────────────────
    openAction(key) {
        const accountDomain = this.state.filters.accountIds.length
            ? [["wa_account_id", "in", this.state.filters.accountIds]]
            : [];
        const messageList = (extraDomain, name) => ({
            type: "ir.actions.act_window",
            name: name,
            res_model: "owa.message",
            views: [[false, "list"], [false, "form"]],
            domain: [...extraDomain, ...accountDomain],
            target: "current",
        });

        const actions = {
            all_messages: messageList([], _t("All WhatsApp Messages")),
            sent: messageList([
                ["message_type", "=", "outbound"],
                ["state", "in", ["sent", "delivered", "read"]],
            ], _t("Sent Messages")),
            received: messageList([
                ["message_type", "=", "inbound"],
            ], _t("Received Messages")),
            failed_24h: messageList([
                ["state", "in", ["error", "bounced"]],
            ], _t("Failed Messages")),
            queued: messageList([
                ["state", "=", "outgoing"],
            ], _t("Queued Messages")),
            accounts: {
                type: "ir.actions.act_window",
                name: _t("WhatsApp Accounts"),
                res_model: "owa.account",
                views: [[false, "list"], [false, "form"]],
                target: "current",
            },
            campaigns_running: {
                type: "ir.actions.act_window",
                name: _t("Running Campaigns"),
                res_model: "owa.campaign",
                views: [[false, "list"], [false, "form"]],
                domain: [["state", "=", "sending"]],
                target: "current",
            },
            // Phase 21: incoming calls
            missed_calls_24h: {
                type: "ir.actions.act_window",
                name: _t("Missed Calls · last 24h"),
                res_model: "owa.call.log",
                views: [[false, "list"], [false, "form"]],
                domain: [
                    ["state", "in", ["missed", "rejected", "timeout"]],
                ],
                context: { search_default_last_24h: 1 },
                target: "current",
            },
            calls_total: {
                type: "ir.actions.act_window",
                name: _t("WhatsApp Calls"),
                res_model: "owa.call.log",
                views: [[false, "list"], [false, "form"]],
                target: "current",
            },
        };
        const a = actions[key];
        if (a) this.action.doAction(a);
    }

    openMessage(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "owa.message",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }

    openAccount(id) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "owa.account",
            res_id: id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("owa_dashboard", OwaDashboard);
