/** @odoo-module **/

import { Component, useState, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { _t } from "@web/core/l10n/translation";

export class OwaCustomer360 extends Component {
    static template = "open_whatsapp_connector.OwaCustomer360";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            partner: null,
            events: [],
            total: 0,
            error: null,
        });
        this.partnerId = this.props?.action?.context?.default_partner_id
            || this.props?.action?.context?.partner_id;
        onMounted(() => this.load());
    }

    async load() {
        if (!this.partnerId) {
            this.state.error = _t("No partner specified.");
            this.state.loading = false;
            return;
        }
        this.state.loading = true;
        try {
            const data = await this.orm.call(
                "owa.customer360", "get_timeline_data",
                [this.partnerId],
            );
            this.state.partner = data.partner;
            this.state.events = data.events || [];
            this.state.total = data.total || 0;
        } catch (e) {
            this.state.error = String(e.message || e);
        } finally {
            this.state.loading = false;
        }
    }

    open(ev) {
        if (!ev.model || !ev.res_id) {
            return;
        }
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: ev.model,
            res_id: ev.res_id,
            views: [[false, "form"]],
            target: "current",
        });
    }
}

registry.category("actions").add("owa_customer360", OwaCustomer360);
