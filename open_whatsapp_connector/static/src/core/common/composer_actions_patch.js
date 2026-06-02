// v18-compat: `@mail/core/common/composer_actions` is a v19-only module.
// Static `import { ComposerAction, registerComposerAction } from "..."` would
// fail at module-load time on v18 and crash the OWL boot. Instead we look up
// the module lazily via `odoo.loader.modules.get(...)`, which returns
// undefined on v18. Result: WhatsApp "Revive" action + disabled-action UI
// just don't appear on v18 (graceful degradation).
import { patch } from "@web/core/utils/patch";
import { _t } from "@web/core/l10n/translation";

const mod = odoo.loader.modules.get("@mail/core/common/composer_actions");
if (mod) {
    const { ComposerAction, registerComposerAction } = mod;

    if (typeof registerComposerAction === "function") {
        registerComposerAction("owa-revive-whatsapp-conversation", {
            condition: ({ composer, owner }) =>
                composer.thread?.channel_type === "whatsapp" && !owner.state.active,
            icon: "fa fa-whatsapp",
            name: _t("Revive WhatsApp Conversation"),
            onSelected: ({ owner }) => owner.onclickWhatsAppChat(),
            sequenceQuick: 10,
        });
    }

    if (ComposerAction && ComposerAction.prototype) {
        patch(ComposerAction.prototype, {
            _condition({ composer, owner }) {
                if (
                    ["upload-files", "voice-start"].includes(this.id) &&
                    composer.targetThread?.channel_type === "whatsapp" &&
                    (composer.attachments.length > 0 || owner.voiceRecorder?.recording)
                ) {
                    return false;
                }
                return super._condition(...arguments);
            },
            _disabledCondition({ composer, owner }) {
                const inactiveActions = ["owa-revive-whatsapp-conversation", "more-actions"];
                if (
                    composer.targetThread?.channel_type === "whatsapp" &&
                    owner.state &&
                    !owner.state.active &&
                    !inactiveActions.includes(this.id)
                ) {
                    return true;
                }
                return super._disabledCondition(...arguments);
            },
        });
    }
}
