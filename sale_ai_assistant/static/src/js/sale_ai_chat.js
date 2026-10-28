/** @odoo-module **/

import { Component, onMounted, onPatched, onWillStart, onWillUnmount, useRef, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useBus, useService } from "@web/core/utils/hooks";
import { ConfirmationDialog } from "@web/core/confirmation_dialog/confirmation_dialog";
import { _t } from "@web/core/l10n/translation";

const STORAGE_KEY = "sale_ai_assistant_panel_width";

export class SaleAIChat extends Component {
    static template = "sale_ai_assistant.SaleAIChat";
    static props = {};

    setup() {
        this.orm = useService("orm");
        this.menu = useService("menu");
        this.action = useService("action");
        this.dialog = useService("dialog");
        this.notification = useService("notification");
        this.messageEnd = useRef("messageEnd");
        this.composerInput = useRef("composerInput");
        this.fileInput = useRef("fileInput");
        this.onPointerMove = this.onPointerMove.bind(this);
        this.onPointerUp = this.onPointerUp.bind(this);

        this.state = useState({
            allowed: false,
            isSalesApp: false,
            open: false,
            busy: false,
            sending: false,
            aiError: "",
            uploadError: "",
            width: this.readWidth(),
            mode: "chat", // chat, history, or mobile-only preview
            previewOpen: false,
            composer: "",
            pendingFiles: [],
            attachmentLimits: null,
            session: null,
            active: null,
            viewingHistory: false,
            history: [],
            historyLimit: 10,
            historyHasMore: false,
            availableModels: [],
        });

        useBus(this.env.bus, "MENUS:APP-CHANGED", () => this.syncSalesApp());
        useBus(this.env.bus, "ROUTE_CHANGE", () => this.syncSalesApp());
        onWillStart(async () => {
            // No dependency on the optional JS "user" service: the Odoo backend
            // checks the native Sales Administrator group and supplies a boolean.
            // Some installations do not expose the JS service in this component.
            this.syncSalesApp();
            await this.refreshBootstrap();
        });
        this.onComposerResize = () => this.resizeComposer();
        onMounted(() => {
            this.scrollToBottom();
            this.resizeComposer();
            window.addEventListener("resize", this.onComposerResize);
        });
        onPatched(() => { this.scrollToBottom(); this.resizeComposer(); });
        onWillUnmount(() => {
            this.cleanupResize();
            window.removeEventListener("resize", this.onComposerResize);
        });
    }

    openFilePicker() {
        if (!this.state.busy && !this.state.sending && !this.readonly) this.fileInput.el?.click();
    }

    async selectFiles(event) {
        if (this.state.pendingFileSessionId !== this.state.session?.id) this.state.pendingFiles = [];
        const files = Array.from(event.target.files || []);
        event.target.value = "";
        const limits = this.state.attachmentLimits;
        // Config comes from the same company's server-side configuration.
        // A zero disables that module limit; the server always rechecks.
        // If bootstrap has not completed, do not invent client-side limits.
        if (limits) {
            const count = files.length + this.state.pendingFiles.length;
            if (limits.max_files > 0 && count > limits.max_files) {
                this.notification.add(`Límite configurado: ${limits.max_files} archivos por mensaje. Se cambia en Conexión Vercel IA.`, {type: "warning"});
                return;
            }
            for (const file of files) {
                const kind = /\.mp3$/i.test(file.name) ? "mp3" :
                    /\.(png|jpe?g|webp)$/i.test(file.name) ? "image" :
                    /\.pdf$/i.test(file.name) ? "pdf" :
                    /\.txt$/i.test(file.name) ? "txt" : null;
                if (!kind) {
                    this.notification.add("Formatos admitidos: TXT, PDF, PNG, JPG, WebP y MP3.", {type: "warning"});
                    return;
                }
                const maxMb = limits[`${kind}_mb`];
                if (maxMb > 0 && file.size > maxMb * 1024 * 1024) {
                    this.notification.add(`${file.name} supera el máximo configurado de ${maxMb} MiB para ${kind.toUpperCase()}.`, {type: "warning"});
                    return;
                }
            }
            const pendingBytes = this.state.pendingFiles.reduce(
                (sum, file) => sum + Math.floor((file.data || "").length * 3 / 4), 0);
            const selectedBytes = files.reduce((sum, file) => sum + file.size, 0);
            if (limits.total_mb > 0 && pendingBytes + selectedBytes > limits.total_mb * 1024 * 1024) {
                this.notification.add(`Los adjuntos superan el máximo conjunto configurado de ${limits.total_mb} MiB.`, {type: "warning"});
                return;
            }
        }
        const uploadSessionId = this.state.session?.id;
        this.state.busy = true;
        try {
            this.state.pendingFileSessionId = uploadSessionId;
            this.state.pendingFiles = this.state.pendingFiles.concat(await Promise.all(files.map(file => new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve({name: file.name, data: reader.result.split(",")[1]});
                reader.onerror = reject; reader.readAsDataURL(file);
            }))));
        } catch (_) { this.notification.add("No se pudo leer el archivo.", {type: "danger"}); } finally { this.state.busy = false; }
    }

    resizeComposer() {
        const input = this.composerInput.el;
        if (!input) return;
        const scrollTop = input.scrollTop;
        const maxHeight = Math.max(60, Math.min(240, Math.floor(window.innerHeight * 0.35)));
        input.style.height = "auto";
        input.style.maxHeight = `${maxHeight}px`;
        const height = Math.min(input.scrollHeight, maxHeight);
        input.style.height = `${height}px`;
        input.style.overflowY = input.scrollHeight > maxHeight ? "auto" : "hidden";
        input.scrollTop = scrollTop;
    }

    readWidth() {
        let stored = 0;
        try {
            stored = parseInt(window.localStorage.getItem(STORAGE_KEY), 10) || 0;
        } catch (_) {
            // Local storage can be disabled by browser privacy settings.
        }
        const desired = stored >= 340 && stored <= 1600 ? stored : Math.max(380, Math.round(window.innerWidth / 3));
        return Math.max(340, Math.min(Math.max(340, window.innerWidth - 260), desired));
    }

    syncSalesApp() {
        const app = this.menu.getCurrentApp();
        this.state.isSalesApp = Boolean(app && app.xmlid === "sale.sale_menu_root");
    }

    async refreshBootstrap() {
        try {
            const result = await this.orm.call("sale.ai.session", "assistant_panel_bootstrap", []);
            this.state.allowed = result.allowed === true;
            this.state.attachmentLimits = result.attachment_limits || null;
            if (!this.state.allowed) {
                return;
            }
            this.state.active = result.active || null;
            this.state.history = result.history || [];
            this.state.historyLimit = result.history_limit;
            this.state.historyHasMore = result.history_has_more;
            this.state.availableModels = result.models || [];
            if (!this.state.viewingHistory) {
                this.state.session = this.state.active;
            }
        } catch (error) {
            this.state.allowed = false;
            this.notifyError(_t("No se pudo cargar el asistente."), error);
        }
    }

    notifyError(message, error) {
        this.notification.add(message, { type: "danger" });
        // Odoo RPC service presents technical diagnostics in its own error dialog.
        console.error("sale_ai_assistant:", error);
    }

    async openPanel() {
        if (this.state.open || this.state.busy) return;
        this.state.open = true;
        if (!this.state.session) {
            await this.loadActive();
        }
    }

    closePanel() {
        // Closing the X never changes the session state or deletes anything.
        this.state.open = false;
    }

    async loadActive() {
        this.state.busy = true;
        try {
            const result = await this.orm.call("sale.ai.session", "assistant_panel_get_or_create", []);
            this.state.active = result;
            this.state.session = result;
            this.state.viewingHistory = false;
            this.state.mode = "chat";
            this.state.composer = "";
            this.state.pendingFiles = [];
            this.state.aiError = "";
            this.state.uploadError = "";
        } catch (error) {
            this.notifyError(_t("No se pudo abrir una nueva conversación."), error);
        } finally {
            this.state.busy = false;
        }
    }

    async returnToActive() {
        if (this.state.sending) return;
        if (this.state.active) {
            try {
                const data = await this.orm.call("sale.ai.session", "assistant_panel_open", [this.state.active.id]);
                this.state.session = data;
                this.state.active = data;
                this.state.mode = "chat";
                this.state.viewingHistory = false;
                this.state.aiError = "";
                return;
            } catch (error) {
                this.notifyError(_t("No se pudo recuperar la conversación activa."), error);
                return;
            }
        }
        await this.loadActive();
    }

    get selectedModelAvailable() {
        const id = this.state.session?.model_id;
        return this.state.availableModels.some((model) => model.id === id);
    }

    async changeModel(ev) {
        const target = this.state.session;
        const modelId = Number(ev.target.value);
        if (!target || this.readonly || this.state.sending || this.state.busy || !modelId ||
            !this.state.availableModels.some((item) => item.id === modelId)) {
            return;
        }
        if (target.model_id === modelId) return;
        this.state.busy = true;
        try {
            const result = await this.orm.call("sale.ai.session", "assistant_panel_select_model", [
                target.id, modelId,
            ]);
            target.model_id = result.model_id;
            target.model_name = result.model_name;
            if (this.state.active?.id === target.id) {
                this.state.active.model_id = result.model_id;
                this.state.active.model_name = result.model_name;
            }
        } catch (error) {
            this.notifyError(_t("No se pudo cambiar el modelo de esta conversación."), error);
            // Re-render resets the selected option to its server-confirmed value.
            ev.target.value = String(target.model_id || "");
        } finally {
            this.state.busy = false;
        }
    }

    /**
     * Convert numeric amounts in JavaScript rather than calling Number() in OWL
     * templates (where global constructors can resolve as undefined ctx props).
     * A malformed value should never crash the preview rendering.
     */
    formatAmount(value, digits = 2) {
        const numeric = Number(value);
        return (Number.isFinite(numeric) ? numeric : 0).toFixed(digits);
    }

    priceSourceLabel(source) {
        const names = {
            odoo: "Precio de lista Odoo",
            history: "Referencia histórica",
            estimate: "Precio estimado",
            user: "Precio indicado por usuario",
            external: "Referencia externa",
        };
        return names[source] || "Origen sin especificar";
    }

    get readonly() {
        return this.state.viewingHistory || (this.state.session && this.state.session.state !== "active");
    }

    get canRetry() {
        const messages = this.state.session?.messages || [];
        return !this.readonly && messages.length > 0 && messages[messages.length - 1].role === "user";
    }

    draftSignature(draft) {
        if (!draft) return "";
        // Compare real visible content, not the object identity supplied by RPC.
        return JSON.stringify({
            partner: draft.partner, description: draft.description,
            lines: draft.lines, estimate_details: draft.estimate_details,
            assumptions: draft.assumptions,
        });
    }

    showPreviewAfterDraftChange(before, after) {
        if (!after || this.draftSignature(before) === this.draftSignature(after)) return;
        if (window.innerWidth < 1080) {
            this.state.mode = "preview";
        } else {
            this.state.previewOpen = true;
            this.state.mode = "chat";
        }
    }

    prepareLineCommand(ev) {
        if (this.readonly || this.state.busy || this.state.sending) return;
        const kind = ev.currentTarget.dataset.kind;
        const label = {product: "Producto", section: "Sección", note: "Nota"}[kind];
        if (!label) return;
        // Prefix a typed message instead of destroying it. Switching buttons
        // replaces only an existing command prefix.
        const raw = this.state.composer || "";
        const previous = raw.match(/^\s*(?:Producto|Secci[oó]n|Nota):\s*/i);
        this.state.composer = `${label}: ` + (previous ? raw.slice(previous[0].length) : raw);
        this.composerInput.el?.focus();
    }

    undoLastChange() {
        if (this.readonly || this.state.busy || this.state.sending || !this.state.session) return;
        // Send a separate audit message without losing a partially typed draft.
        return this.submitContent("Deshacer: último cambio", true);
    }

    async proposalAction(action) {
        const target = this.state.session;
        if (!target?.proposal || this.readonly || this.state.busy || this.state.sending) return;
        this.state.busy = true;
        const before = target.draft;
        try {
            const result = await this.orm.call("sale.ai.session", "assistant_panel_proposal_action",
                [target.id, target.proposal.token, action,
                    action === "discard" ? null : target.proposal.text]);
            this.state.session = result;
            if (action === "improve") {
                this.state.composer = "Mejora la propuesta pendiente sin guardarla: ";
            }
            this.showPreviewAfterDraftChange(before, result.draft);
        } catch (error) {
            this.notifyError("No se ha podido procesar la propuesta.", error);
        } finally {
            this.state.busy = false;
        }
    }

    async sendMessage() {
        return this.submitContent(this.state.composer, false);
    }

    restoreFailedSubmission(target, temporaryId, content, preserveComposer) {
        const index = target.messages.findIndex((msg) => msg.id === temporaryId);
        if (index !== -1) target.messages.splice(index, 1);
        if (!preserveComposer) this.state.composer = content;
        // Never clear pendingFiles on error: the user must be able to retry.
    }

    async submitContent(raw, preserveComposer = false) {
        const content = (raw || "").trim();
        if (this.state.pendingFiles.length && this.state.pendingFileSessionId !== this.state.session?.id) {
            this.state.pendingFiles = [];
            this.notification.add("Vuelve a adjuntar los archivos en esta conversación.", {type: "warning"});
            return;
        }
        if (!content || this.state.sending || this.state.busy || this.readonly || !this.state.session) return;
        const target = this.state.session;
        const beforeDraft = this.draftSignature(target.draft);
        const temporaryId = `pending-${Date.now()}`;
        const optimistic = { id: temporaryId, role: "user", content };
        target.messages.push(optimistic);
        if (!preserveComposer) this.state.composer = "";
        this.state.sending = true;
        this.state.aiError = "";
        this.state.uploadError = "";
        try {
            const result = await this.orm.call("sale.ai.session", "assistant_panel_send", [target.id, content, this.state.pendingFiles]);
            if (result.file_error) {
                // The backend rolled back all partially prepared attachments and
                // intentionally did NOT save a user message. Keep everything.
                this.restoreFailedSubmission(target, temporaryId, content, preserveComposer);
                this.state.uploadError = result.file_error;
                this.notification.add(result.file_error, {type: "warning"});
                return;
            }
            // Only a successful acknowledged send consumes the queued files.
            this.state.pendingFiles = [];
            const index = target.messages.findIndex((msg) => msg.id === temporaryId);
            if (index !== -1) {
                target.messages.splice(index, 1, {
                    id: result.id, role: result.role, content: result.content,
                    created_at: result.created_at,
                });
            }
            if (result.session_name) target.name = result.session_name;
            if (result.assistant_message) target.messages.push(result.assistant_message);
            if ("proposal" in result) target.proposal = result.proposal;
            this.state.aiError = result.error || "";
            target.model_name = result.model_name || target.model_name;
            if (result.draft) {
                target.draft = result.draft;
                if (beforeDraft !== this.draftSignature(result.draft)) {
                    this.showPreviewAfterDraftChange(null, result.draft);
                }
            }
            target.has_work = true;
        } catch (error) {
            // A transport/proxy/Odoo exception may happen before the request
            // even reaches Python. Keep the prompt and attachment queue even if
            // the subsequent conversation refresh succeeds.
            this.restoreFailedSubmission(target, temporaryId, content, preserveComposer);
            this.state.uploadError = _t("Error de comunicación con Odoo. El mensaje y los adjuntos siguen preparados. Comprueba la conversación antes de reintentar; si persiste, consulta los logs del servidor.");
            this.notifyError(this.state.uploadError, error);
            try {
                const refreshed = await this.orm.call("sale.ai.session", "assistant_panel_open", [target.id]);
                this.state.session = refreshed;
                this.state.active = refreshed;
                if (beforeDraft !== this.draftSignature(refreshed.draft)) {
                    this.showPreviewAfterDraftChange(null, refreshed.draft);
                }
            } catch (refreshError) {
                console.error("sale_ai_assistant: refresh after failed send", refreshError);
            }
        } finally {
            this.state.sending = false;
        }
    }

    async retryLastReply() {
        if (this.state.sending || this.state.busy || this.readonly || !this.state.session) return;
        const beforeDraft = this.draftSignature(this.state.session.draft);
        this.state.sending = true;
        this.state.aiError = "";
        try {
            const result = await this.orm.call("sale.ai.session", "assistant_panel_retry", [this.state.session.id]);
            if ("proposal" in result) this.state.session.proposal = result.proposal;
            if (result.assistant_message) {
                this.state.session.messages.push(result.assistant_message);
            }
            if (result.draft) {
                this.state.session.draft = result.draft;
                if (beforeDraft !== this.draftSignature(result.draft)) {
                    this.showPreviewAfterDraftChange(null, result.draft);
                }
            }
            this.state.aiError = result.error || "";
        } catch (error) {
            this.notifyError(_t("No se pudo reintentar la respuesta."), error);
            const refreshed = await this.orm.call("sale.ai.session", "assistant_panel_open", [this.state.session.id]);
            this.state.session = refreshed;
            this.state.active = refreshed;
        } finally {
            this.state.sending = false;
        }
    }

    onComposerKeydown(ev) {
        if (ev.key === "Enter" && !ev.shiftKey && !ev.isComposing) {
            ev.preventDefault();
            this.sendMessage();
        }
    }

    async requestCreateQuotation() {
        if (this.readonly || this.state.busy || this.state.sending || !this.state.session?.id) return;
        const sessionId = this.state.session.id;
        this.state.busy = true;
        try {
            // The server validates access, company, customer, lines, pricelist
            // and returns a fingerprint bound to this exact provisional draft.
            const review = await this.orm.call(
                "sale.ai.session", "assistant_panel_quotation_preflight", [sessionId]
            );
            const currency = review.currency || "EUR";
            const message = [
                _t("Cliente: ") + review.partner,
                _t("Tarifa: ") + review.pricelist,
                _t("Líneas: ") + review.line_count + _t(" (partidas: ") + review.product_count + ")",
                _t("Base provisional sin impuestos: ") + this.formatAmount(review.amount_untaxed_estimate) + " " + currency,
                "",
                ...review.warnings,
                "",
                _t("Se creará un PRESUPUESTO EN BORRADOR. El chat se cerrará y quedará guardado en el historial. Debes revisar y ajustar el presupuesto en Odoo; no se confirmará la venta."),
            ].join("\n");
            this.dialog.add(ConfirmationDialog, {
                title: _t("Finalizar conversación y crear presupuesto"),
                body: message,
                confirmLabel: _t("Crear presupuesto en borrador"),
                cancelLabel: _t("Continuar editando"),
                confirm: () => this.confirmCreateQuotation(sessionId, review.signature),
            });
        } catch (error) {
            this.notifyError(_t("No se puede crear todavía el presupuesto. Comprueba cliente, líneas y tarifa."), error);
        } finally {
            this.state.busy = false;
        }
    }

    async confirmCreateQuotation(sessionId, signature) {
        if (this.state.busy || this.state.sending) return;
        this.state.busy = true;
        let result;
        try {
            result = await this.orm.call("sale.ai.session", "assistant_panel_create_quotation", [
                sessionId, signature, true,
            ]);
        } catch (error) {
            this.notifyError(_t("No se pudo crear el presupuesto. La conversación sigue disponible."), error);
            this.state.busy = false;
            return;
        }
        // Server commit completed. Hide the finished chat and refresh the
        // history; the NEXT conversation must start with fresh context.
        this.state.open = false;
        this.state.previewOpen = false;
        this.state.viewingHistory = false;
        this.state.session = null;
        this.state.active = null;
        this.state.mode = "chat";
        this.state.composer = "";
        this.state.aiError = "";
        try {
            await this.refreshBootstrap();
        } catch (_) {
            // Not a sale-order creation failure: keep the created document.
        }
        this.state.busy = false;
        this.notification.add(_t("Presupuesto ") + result.sale_order_name + _t(" creado en borrador. Revísalo antes de utilizarlo."), {
            type: "success",
        });
        try {
            await this.action.doAction({
                type: "ir.actions.act_window",
                res_model: "sale.order",
                res_id: result.sale_order_id,
                views: [[false, "form"]],
                target: "current",
            });
        } catch (error) {
            this.notifyError(_t("El presupuesto se ha creado, pero no se pudo abrir. Puedes acceder desde el historial."), error);
        }
    }

    requestNewConversation() {
        if (this.state.busy || this.state.sending) return;
        const current = this.state.active;
        const hasChanges = Boolean(current?.has_work);
        if (!hasChanges) {
            // Empty conversations are discarded silently, but a genuinely new
            // session is always created when the user requests a fresh chat.
            this.startNewConversation();
            return;
        }
        this.dialog.add(ConfirmationDialog, {
            title: _t("Descartar conversación"),
            body: _t("Se eliminarán los mensajes y el borrador provisional de esta conversación. No se podrá recuperar. ¿Quieres empezar otra?"),
            confirmLabel: _t("Descartar y empezar"),
            cancelLabel: _t("Conservar conversación"),
            confirm: () => this.startNewConversation(),
        });
    }

    async startNewConversation() {
        this.state.busy = true;
        try {
            const activeId = this.state.active?.id || false;
            const newSession = await this.orm.call("sale.ai.session", "assistant_panel_new", [activeId]);
            this.state.active = newSession;
            this.state.session = newSession;
            this.state.viewingHistory = false;
            this.state.mode = "chat";
            this.state.composer = "";
            this.state.pendingFiles = [];
            this.state.aiError = "";
        } catch (error) {
            this.notifyError(_t("No se pudo descartar la conversación."), error);
        } finally {
            this.state.busy = false;
        }
    }

    async showHistory() {
        if (this.state.sending) return;
        this.state.busy = true;
        try {
            await this.refreshBootstrap();
            this.state.mode = "history";
        } finally {
            this.state.busy = false;
        }
    }

    async loadMoreHistory() {
        if (!this.state.historyHasMore || this.state.busy) return;
        this.state.busy = true;
        try {
            const page = await this.orm.call("sale.ai.session", "assistant_panel_history_page", [this.state.history.length]);
            this.state.history.push(...page.history);
            this.state.historyHasMore = page.has_more;
        } catch (error) {
            this.notifyError(_t("No se pudo ampliar el historial."), error);
        } finally {
            this.state.busy = false;
        }
    }

    async loadOlderMessages() {
        const current = this.state.session;
        if (!current?.messages_has_more || !current.messages.length || this.state.busy) return;
        this.state.busy = true;
        this.skipNextAutoScroll = true;
        try {
            const page = await this.orm.call("sale.ai.session", "assistant_panel_older_messages", [
                current.id, current.messages[0].id,
            ]);
            current.messages.unshift(...page.messages);
            current.messages_has_more = page.has_more;
        } catch (error) {
            this.notifyError(_t("No se pudieron cargar los mensajes anteriores."), error);
        } finally {
            this.state.busy = false;
        }
    }

    async openHistoryItem(ev) {
        if (this.state.sending) return;
        const id = Number(ev.currentTarget.dataset.sessionId);
        if (!id || this.state.busy) return;
        this.state.busy = true;
        try {
            const item = await this.orm.call("sale.ai.session", "assistant_panel_open", [id]);
            this.state.session = item;
            this.state.viewingHistory = true;
            this.state.mode = "chat";
            this.state.aiError = "";
        } catch (error) {
            this.notifyError(_t("No se pudo leer la conversación del historial."), error);
        } finally {
            this.state.busy = false;
        }
    }

    showChat() {
        this.state.mode = "chat";
    }

    async refreshDraftPreview() {
        if (!this.state.session?.id || this.state.sending) return;
        try {
            const preview = await this.orm.call("sale.ai.session", "assistant_panel_preview", [
                this.state.session.id,
            ]);
            this.state.session.draft = preview;
        } catch (error) {
            this.notifyError(_t("No se pudo actualizar la vista previa."), error);
        }
    }

    togglePreview() {
        if (window.innerWidth < 1080) {
            this.state.mode = this.state.mode === "preview" ? "chat" : "preview";
            if (this.state.mode === "preview") this.refreshDraftPreview();
            return;
        }
        this.state.previewOpen = !this.state.previewOpen;
        this.state.mode = "chat";
        if (this.state.previewOpen) this.refreshDraftPreview();
    }

    openSaleOrder() {
        if (!this.state.session?.sale_order_id) return;
        const saleId = this.state.session.sale_order_id;
        this.closePanel();
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: "sale.order",
            res_id: saleId,
            views: [[false, "form"]],
            target: "current",
        });
    }

    scrollToBottom() {
        if (this.skipNextAutoScroll) {
            this.skipNextAutoScroll = false;
            return;
        }
        if (!this.state.open || this.state.mode !== "chat") return;
        this.messageEnd.el?.scrollIntoView({ block: "end", behavior: "auto" });
    }

    startResize(ev) {
        if (window.innerWidth <= 767 || ev.button !== 0) return;
        ev.preventDefault();
        window.addEventListener("pointermove", this.onPointerMove);
        window.addEventListener("pointerup", this.onPointerUp);
        document.body.classList.add("sale-ai-resizing");
    }

    onPointerMove(ev) {
        const proposed = window.innerWidth - ev.clientX;
        this.state.width = Math.round(Math.max(340, Math.min(window.innerWidth - 260, proposed)));
    }

    onPointerUp() {
        this.cleanupResize();
        try {
            window.localStorage.setItem(STORAGE_KEY, String(this.state.width));
        } catch (_) {
            // No persistent storage available.
        }
    }

    cleanupResize() {
        window.removeEventListener("pointermove", this.onPointerMove);
        window.removeEventListener("pointerup", this.onPointerUp);
        document.body.classList.remove("sale-ai-resizing");
    }
}

registry.category("main_components").add("sale_ai_assistant.chat", { Component: SaleAIChat });
