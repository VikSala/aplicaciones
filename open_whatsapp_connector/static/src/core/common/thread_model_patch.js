// v18-compat: v19 exports `fields.One/Many`; v18 uses `Record.one/many`.
import { Record } from "@mail/core/common/record";
import { Thread } from "@mail/core/common/thread_model";
import { patch } from "@web/core/utils/patch";
import { deserializeDateTime } from "@web/core/l10n/dates";

import { toRaw } from "@odoo/owl";

patch(Thread.prototype, {
    setup() {
        super.setup();
        this.owa_account_id = Record.one("owa.account");
        // Phase B3 — transient presence flags driven by the
        // `owa_presence` bus event. Not persisted; cleared on reload.
        this.owaOnline = false;
        this.owaTyping = false;
    },
    get importantCounter() {
        if (this.channel_type === "whatsapp") {
            return this.self_member_id?.message_unread_counter || this.message_needaction_counter;
        }
        return super.importantCounter;
    },
    get autoOpenChatWindowOnNewMessage() {
        return this.channel_type === "whatsapp" || super.autoOpenChatWindowOnNewMessage;
    },
    get canLeave() {
        return this.channel_type !== "whatsapp" && super.canLeave;
    },
    get allowedToUnpinChannelTypes() {
        return [...super.allowedToUnpinChannelTypes, "whatsapp"];
    },
    get avatarUrl() {
        if (this.channel_type === "whatsapp" && this.correspondent?.persona?.avatarUrl) {
            return this.correspondent.persona.avatarUrl;
        }
        return super.avatarUrl;
    },

    get isChatChannel() {
        return this.channel_type === "whatsapp" || super.isChatChannel;
    },

    get whatsappChannelValidUntilDatetime() {
        if (!this.whatsapp_channel_valid_until) {
            return undefined;
        }
        return toRaw(deserializeDateTime(this.whatsapp_channel_valid_until));
    },
});
