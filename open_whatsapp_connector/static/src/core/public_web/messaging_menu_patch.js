import { MessagingMenu } from "@mail/core/public_web/messaging_menu";
import { ThreadIcon } from "@mail/core/common/thread_icon";
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

patch(MessagingMenu, {
    components: { ...MessagingMenu.components, ThreadIcon },
});

patch(MessagingMenu.prototype, {
    // v18 base exposes `get tabs()` (and the template iterates `tabs`); the
    // v19 name is `_tabs`. On v18 the `_tabs` override was never called, so the
    // WhatsApp tab never appeared in the mobile messaging menu. v18 also has no
    // `threadsWithCounter` on the category — count unread threads instead.
    // (#discuss/#coexist) — v19 keeps `_tabs`/`threadsWithCounter`.
    get tabs() {
        const items = super.tabs;
        const hasWhatsApp = Object.values(this.store.Thread.records).some(
            ({ channel_type }) => channel_type === "whatsapp"
        );
        if (hasWhatsApp) {
            const waThreads = this.store.discuss.whatsapp?.threads || [];
            items.push({
                counter: waThreads.filter((t) => t.importantCounter > 0).length,
                icon: "fa fa-whatsapp",
                id: "whatsapp",
                label: _t("WhatsApp"),
                sequence: 80,
            });
        }
        return items;
    },
});
