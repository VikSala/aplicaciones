import { Component, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

export class OwaCampaignBusListener extends Component {
    static props = standardWidgetProps;
    static template = "open_whatsapp_connector.OwaCampaignBusListener";

    setup() {
        const busService = useService("bus_service");
        let active = true;
        const handler = ({ id }) => {
            if (!active) {
                return;
            }
            const record = this.props.record;
            if (record && record.resId === id) {
                record.load();
            }
        };
        busService.subscribe("owa.campaign/refresh", handler);
        busService.start();
        onWillUnmount(() => {
            active = false;
        });
    }
}

registry.category("view_widgets").add("owa_campaign_bus_listener", {
    component: OwaCampaignBusListener,
});
