/**
 * Always-mounted listener + renderer for incoming WhatsApp call events.
 *
 * Subscribes to the `owa.call/ringing` and `owa.call/ended` bus channels
 * and renders a stack of call-style cards in the top-right of the chrome.
 * Each card has:
 *   - Avatar (or phone-initial fallback) with a pulsing ring animation
 *   - Caller name + phone + voice/video chip
 *   - Open  → opens the form view of the new owa.call.log row
 *   - Reject → calls owa.call.log.action_reject_call (gateway rejectCall)
 *   - × close → dismisses the toast locally
 *
 * Each card hard-caps at 60 s so a misbehaving sidecar can't strand a
 * permanent banner on screen.
 */
import { Component, onWillUnmount, useState } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

const RING_AUDIO_URL =
    "/open_whatsapp_connector/static/src/calls/ring.ogg";
const HARD_CAP_MS = 60_000;

export class OwaCallRingingNotifier extends Component {
    static props = {};
    static template = "open_whatsapp_connector.OwaCallRingingNotifier";

    setup() {
        this.bus = useService("bus_service");
        this.action = useService("action");
        this.orm = useService("orm");

        // Reactive map of call_log_id -> card data shown on screen.
        this.state = useState({ calls: {} });
        // Per-card timers (not in state — opaque to the template).
        this._capTimers = new Map();

        try {
            this._ring = new Audio(RING_AUDIO_URL);
            this._ring.preload = "auto";
            this._ring.volume = 0.6;
        } catch (_err) {
            this._ring = null;
        }

        const onRinging = (payload) => this.onRinging(payload);
        const onEnded = (payload) => this.onEnded(payload);
        this.bus.subscribe("owa.call/ringing", onRinging);
        this.bus.subscribe("owa.call/ended", onEnded);
        this.bus.start();

        onWillUnmount(() => {
            for (const t of this._capTimers.values()) {
                clearTimeout(t);
            }
            this._capTimers.clear();
        });
    }

    /* ---------- helpers ---------- */

    callList() {
        return Object.values(this.state.calls);
    }

    initialOf(name, phone) {
        const src = (name || phone || "?").trim();
        if (!src) return "?";
        const ch = src.replace(/^\+/, "").charAt(0).toUpperCase();
        return /[A-Z0-9]/.test(ch) ? ch : "?";
    }

    avatarUrl(payload) {
        if (payload.partner_id) {
            return `/web/image?model=res.partner&id=${payload.partner_id}&field=avatar_128`;
        }
        return null;
    }

    displayName(payload) {
        if (payload.partner_name) return payload.partner_name;
        const phone = payload.from_phone || "";
        if (!phone) return _t("Unknown caller");
        return phone.startsWith("+") ? phone : `+${phone}`;
    }

    kindLabel(payload) {
        return payload.is_video ? _t("Video call") : _t("Voice call");
    }

    accountLabel(payload) {
        return payload.account_name ? `· ${payload.account_name}` : "";
    }

    _playRing() {
        if (!this._ring) return;
        try {
            this._ring.currentTime = 0;
            const p = this._ring.play();
            if (p && typeof p.catch === "function") p.catch(() => {});
        } catch (_err) { /* swallow */ }
    }

    _dismiss(callLogId) {
        const t = this._capTimers.get(callLogId);
        if (t) clearTimeout(t);
        this._capTimers.delete(callLogId);
        if (this.state.calls[callLogId]) {
            delete this.state.calls[callLogId];
        }
    }

    /* ---------- bus handlers ---------- */

    onRinging(payload) {
        if (!payload || !payload.call_log_id) return;
        const id = payload.call_log_id;
        if (this.state.calls[id]) return; // already showing
        this.state.calls[id] = payload;
        this._capTimers.set(id, setTimeout(() => this._dismiss(id), HARD_CAP_MS));
        this._playRing();
    }

    onEnded(payload) {
        if (!payload || !payload.call_log_id) return;
        this._dismiss(payload.call_log_id);
    }

    /* ---------- template actions ---------- */

    onOpen(callLogId) {
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "owa.call.log",
            res_id: callLogId,
            views: [[false, "form"]],
            target: "current",
        });
        this._dismiss(callLogId);
    }

    async onReject(callLogId) {
        try {
            await this.orm.call(
                "owa.call.log",
                "action_reject_call",
                [[callLogId]],
            );
        } catch (_err) { /* server emits ended on success; close anyway */ }
        this._dismiss(callLogId);
    }

    onDismiss(callLogId) {
        this._dismiss(callLogId);
    }
}

registry.category("main_components").add("OwaCallRingingNotifier", {
    Component: OwaCallRingingNotifier,
});
