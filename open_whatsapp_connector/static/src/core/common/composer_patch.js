import { Composer } from "@mail/core/common/composer";
import { _t } from "@web/core/l10n/translation";
import { patch } from "@web/core/utils/patch";

import { onWillDestroy, useEffect } from "@odoo/owl";

patch(Composer.prototype, {
    setup() {
        super.setup();
        this.composerDisableCheckTimeout = null;
        useEffect(
            () => {
                clearTimeout(this.composerDisableCheckTimeout);
                this.checkComposerDisabled();
            },
            () => [this.thread?.whatsapp_channel_valid_until]
        );
        onWillDestroy(() => clearTimeout(this.composerDisableCheckTimeout));
    },
    /**
     * True only for WhatsApp channels owned by THIS module. Odoo's native
     * `whatsapp` (Meta Cloud API) module also creates `channel_type ===
     * "whatsapp"` channels, but those have no `owa_account_id` — applying
     * our patches to them throws (e.g. `owa_account_id.name`). Gate every
     * WhatsApp-specific branch on this so native channels fall through to
     * `super`.
     */
    get isOwaWhatsappThread() {
        return this.thread?.channel_type === "whatsapp" && !!this.thread.owa_account_id;
    },
    get allowUpload() {
        if (
            this.isOwaWhatsappThread &&
            this.props.composer.attachments.length > 0
        ) {
            return false;
        }
        return super.allowUpload;
    },
    get areAllActionsDisabled() {
        if (
            this.isOwaWhatsappThread &&
            !this.state.active &&
            !this.isRevivingWhatsapp
        ) {
            return true;
        }
        return super.areAllActionsDisabled;
    },
    get isRevivingWhatsapp() {
        return false;
    },
    get isMultiUpload() {
        if (this.isOwaWhatsappThread) {
            return false;
        }
        return super.isMultiUpload;
    },
    get placeholder() {
        if (this.isOwaWhatsappThread) {
            if (!this.state.active && this.props.composer.threadExpired) {
                return _t("Conversation closed.");
            }
            return _t("Answer as %(whatsapp_account_name)s", {
                whatsapp_account_name: this.thread.owa_account_id.name,
            });
        }
        return super.placeholder;
    },

    checkComposerDisabled() {
        if (this.isOwaWhatsappThread) {
            const datetime = this.thread.whatsappChannelValidUntilDatetime;
            if (!datetime) {
                return;
            }
            const delta = datetime.ts - Date.now();
            if (delta <= 0) {
                this.state.active = false;
                this.props.composer.threadExpired = true;
            } else {
                this.state.active = true;
                this.props.composer.threadExpired = false;
                this.composerDisableCheckTimeout = setTimeout(() => {
                    this.checkComposerDisabled();
                }, delta);
            }
        }
    },

    /** @override */
    get isSendButtonDisabled() {
        const whatsappInactive = this.isOwaWhatsappThread && !this.state.active;
        return super.isSendButtonDisabled || whatsappInactive;
    },

    onclickWhatsAppChat() {
        this.action.doAction(
            {
                type: "ir.actions.act_window",
                name: _t("Send WhatsApp Message"),
                res_model: "owa.composer",
                view_mode: "form",
                views: [[false, "form"]],
                target: "new",
                context: {
                    active_model: "discuss.channel",
                    active_id: this.thread.id,
                    active_ids: [this.thread.id],
                    default_res_model: "discuss.channel",
                    default_res_ids: String(this.thread.id),
                    default_batch_mode: false,
                },
            },
            {
                onClose: () => {
                    this.thread.fetchMessages();
                },
            }
        );
    },

    onDropFile(ev) {
        this.processFileUploading(ev, super.onDropFile.bind(this));
    },

    onPaste(ev) {
        if (ev.clipboardData.files.length === 0) {
            return super.onPaste(ev);
        }
        this.processFileUploading(ev, super.onPaste.bind(this));
    },

    processFileUploading(ev, superCb) {
        if (
            this.isOwaWhatsappThread &&
            this.props.composer.attachments.length > 0
        ) {
            ev.preventDefault();
            this.env.services.notification.add(
                _t("Only one attachment is allowed for each message"),
                { type: "warning" }
            );
            return;
        }
        superCb(ev);
    },
});
