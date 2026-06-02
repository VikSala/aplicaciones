/** @odoo-module **/

import { describe, expect, test } from "@odoo/hoot";
import { OwaDashboard } from "@open_whatsapp_connector/dashboard/owa_dashboard";

describe("owa.dashboard OWL component", () => {
    test("registers under the action registry tag 'owa_dashboard'", () => {
        // The module-level registration in owa_dashboard.js should have run by
        // the time this test runs (it's part of web.assets_backend).
        const { registry } = odoo.loader.modules.get("@web/core/registry");
        const actionRegistry = registry.category("actions");
        expect(actionRegistry.contains("owa_dashboard")).toBe(true);
        expect(actionRegistry.get("owa_dashboard")).toBe(OwaDashboard);
    });

    test("has the expected QWeb template name", () => {
        expect(OwaDashboard.template).toBe("open_whatsapp_connector.OwaDashboard");
    });
});
