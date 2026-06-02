/** @odoo-module **/

import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardFieldProps } from "@web/views/fields/standard_field_props";

export class QrCodeWidget extends Component {
    static template = "open_whatsapp_connector.QrCodeWidget";
    static props = { ...standardFieldProps };

    setup() {
        this.orm = useService("orm");
        this.busService = useService("bus_service");
        this.state = useState({
            polling: false,
        });
        this._pollInterval = null;

        // Push from the sidecar (via controllers/main.py account_updated bus
        // channel) — reload this record immediately instead of waiting for the
        // 3s poll tick, so the form flips to Connected ~instantly. Best-effort:
        // only fires for users on the account's notify list; the poll stays as
        // a fallback. Also refreshes when not polling (e.g. reconnect from a
        // disconnected state). (#push_state)
        this._onAccountUpdated = (payload) => {
            if (!payload || payload.account_id !== this.props.record.resId) {
                return;
            }
            this.props.record.load().then(() => {
                const st = this.props.record.data.session_state;
                if (st === "connected" || st === "disconnected" || st === "logged_out") {
                    this._stopPolling();
                }
            }).catch(() => {});
        };
        this.busService.subscribe(
            "open_whatsapp_connector/account_updated", this._onAccountUpdated);

        onWillStart(() => {
            this._startPollingIfNeeded();
        });

        onWillUnmount(() => {
            this._stopPolling();
            this.busService.unsubscribe(
                "open_whatsapp_connector/account_updated", this._onAccountUpdated);
        });
    }

    get qrDataUrl() {
        return this.props.record.data[this.props.name] || "";
    }

    get sessionState() {
        return this.props.record.data.session_state || "disconnected";
    }

    get showQr() {
        return this.sessionState === "qr_pending" && this.qrDataUrl;
    }

    get showConnected() {
        return this.sessionState === "connected";
    }

    get showConnecting() {
        return this.sessionState === "connecting";
    }

    _startPollingIfNeeded() {
        if (this.sessionState === "qr_pending" || this.sessionState === "connecting") {
            this._startPolling();
        }
    }

    _startPolling() {
        if (this._pollInterval) return;
        this.state.polling = true;
        this._pollInterval = setInterval(async () => {
            try {
                const recordId = this.props.record.resId;
                if (recordId) {
                    await this.orm.call(
                        "owa.account",
                        "button_refresh_status",
                        [recordId]
                    );
                    // Reload the record to get updated values
                    await this.props.record.load();
                    // Stop polling if connected or disconnected
                    const newState = this.props.record.data.session_state;
                    if (newState === "connected" || newState === "disconnected" || newState === "logged_out") {
                        this._stopPolling();
                    }
                }
            } catch (e) {
                console.warn("QR polling error:", e);
            }
        }, 3000);
    }

    _stopPolling() {
        if (this._pollInterval) {
            clearInterval(this._pollInterval);
            this._pollInterval = null;
        }
        this.state.polling = false;
    }
}

QrCodeWidget.template = "open_whatsapp_connector.QrCodeWidget";

registry.category("fields").add("wa_qr_code", {
    component: QrCodeWidget,
    supportedTypes: ["text", "char"],
});
