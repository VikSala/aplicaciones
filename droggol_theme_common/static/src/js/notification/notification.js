/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { Notification } from "@web/core/notifications/notification";

// better to have service :)
Notification.template = "droggol_theme_common.NotificationWowl";
patch(Notification.prototype, {
    setup() {
        this.templateToUse = this.props.templateToUse || "web.NotificationWowl";
    }
});
Notification.props['templateToUse'] = { type: String, optional: true };
