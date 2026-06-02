/** @odoo-module **/

import { describe, expect, test } from "@odoo/hoot";
import { OwaCampaignBusListener } from "@open_whatsapp_connector/core/web/owa_campaign_bus_listener";

describe("owa_campaign_bus_listener view widget", () => {
    test("is registered under the view_widgets registry", () => {
        const { registry } = odoo.loader.modules.get("@web/core/registry");
        const viewWidgets = registry.category("view_widgets");
        expect(viewWidgets.contains("owa_campaign_bus_listener")).toBe(true);
    });

    test("widget entry exposes the OwaCampaignBusListener component", () => {
        const { registry } = odoo.loader.modules.get("@web/core/registry");
        const widget = registry.category("view_widgets").get("owa_campaign_bus_listener");
        expect(widget.component).toBe(OwaCampaignBusListener);
    });
});
