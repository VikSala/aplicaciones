import { patch } from "@web/core/utils/patch";
import { ThreadAction } from "@mail/core/common/thread_actions";

// v18-compat: v19 exports a `ThreadAction` class; v18 only exports
// `threadActionsRegistry`. Skip the patch when the class isn't available
// (Create-Lead action on WhatsApp threads is the only feature affected).
if (ThreadAction && ThreadAction.prototype) {
    patch(ThreadAction.prototype, {
        _condition({ action, owner, store, thread }) {
            if (thread?.channel_type === "whatsapp") {
                if (
                    action.id === "create-lead" &&
                    store.has_access_create_lead &&
                    // optional-chain: v18 may call this with `owner` undefined
                    // (isDiscussSidebarChannelActions is a v19-only flag) —
                    // avoid crashing the ChatWindow render. (#calls/#discuss)
                    !owner?.isDiscussSidebarChannelActions
                ) {
                    return true;
                }
            }
            return super._condition(...arguments);
        },
    });
}
