// v18-compat: v19 exports `registerThreadAction(name, descriptor)`;
// v18 only exports `threadActionsRegistry` (a `registry.category(...)`).
// We probe for the v19 helper and fall back to the v18 registry pattern.
import * as threadActionsModule from "@mail/core/common/thread_actions";
import { _t } from "@web/core/l10n/translation";

const descriptor = {
    condition: ({ owner, thread }) =>
        thread?.channel_type === "whatsapp" &&
        thread.whatsapp_partner_id &&
        // v18 calls this condition in some chat-window contexts with `owner`
        // undefined (and `isDiscussSidebarChannelActions` is a v19-only flag
        // absent in v18) — optional-chain so an undefined owner doesn't throw
        // and crash the whole ChatWindow render. (#calls/#discuss)
        !owner?.isDiscussSidebarChannelActions,
    open: ({ store, thread }) => {
        if (store.env.isSmall) {
            store?.ChatWindow.get({ thread }).fold();
        } else {
            thread.openChatWindow({ focus: true });
        }
        store.env.services.action.doAction({
            type: "ir.actions.act_window",
            res_model: "res.partner",
            views: [[false, "form"]],
            res_id: thread.whatsapp_partner_id.id,
        });
    },
    icon: "fa fa-fw fa-address-book",
    name: _t("View Contact"),
    sequenceGroup: 1,
};

// Module-scoped id — Odoo's native `whatsapp` (Meta Cloud API) module
// also registers a `view-contact` thread action; using the same id would
// throw `it already exists` on installs that have both modules enabled.
const ACTION_ID = "owa-view-contact";

if (typeof threadActionsModule.registerThreadAction === "function") {
    threadActionsModule.registerThreadAction(ACTION_ID, descriptor);
} else if (threadActionsModule.threadActionsRegistry?.add) {
    threadActionsModule.threadActionsRegistry.add(ACTION_ID, descriptor);
}
