(function () {
    "use strict";

    var CONFIG_URL = "/ai/chat/appointments/config";
    var START_URL = "/ai/chat/appointments/start";
    var RESULT_URL = "/ai/chat/appointments/result";
    var POLL_INTERVAL_MS = 900;
    var MAX_POLLS = 1000;

    function pageContext() {
        return {
            pageUrl: window.location.href,
            pageTitle: document.title || ""
        };
    }

    function getSessionId() {
        var key = "odoo_ai_chat_appointments_session_id";
        var sessionId = window.localStorage.getItem(key);
        if (sessionId && !/^[A-Za-z0-9._:-]{1,160}$/.test(sessionId)) {
            sessionId = null;
        }
        if (!sessionId) {
            if (window.crypto && typeof window.crypto.randomUUID === "function") {
                sessionId = "web-" + window.crypto.randomUUID();
            } else {
                sessionId = "web-" + Math.random().toString(36).slice(2) + "-" + Date.now();
            }
            window.localStorage.setItem(key, sessionId);
        }
        return sessionId;
    }

    function sleep(ms) {
        return new Promise(function (resolve) {
            window.setTimeout(resolve, ms);
        });
    }

    async function postJson(url, payload) {
        var response = await fetch(url, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            credentials: "same-origin",
            body: JSON.stringify(payload || {})
        });

        var text = await response.text();
        var data = {};
        if (text) {
            try {
                data = JSON.parse(text);
            } catch (error) {
                data = {reply: text};
            }
        }
        return {response: response, data: data};
    }

    async function waitForResult(jobId) {
        for (var attempt = 0; attempt < MAX_POLLS; attempt += 1) {
            await sleep(POLL_INTERVAL_MS);
            var result = await postJson(RESULT_URL, {jobId: jobId});
            if (!result.response.ok) {
                return result;
            }
            if (result.data.status === "done" || result.data.status === "error") {
                return result;
            }
        }
        return {
            response: {ok: false},
            data: {reply: "La respuesta está tardando demasiado. Vuelve a intentarlo.", error: "poll_timeout"}
        };
    }

    function normalizeHexColor(value, fallback) {
        var color = String(value || "").trim();
        if (/^#[0-9a-fA-F]{3}$/.test(color)) {
            color = "#" + color.slice(1).split("").map(function (char) {
                return char + char;
            }).join("");
        }
        return /^#[0-9a-fA-F]{6}$/.test(color) ? color : fallback;
    }

    function hexToRgba(hex, alpha) {
        var normalized = normalizeHexColor(hex, "#ffffff");
        var value = parseInt(normalized.slice(1), 16);
        var red = (value >> 16) & 255;
        var green = (value >> 8) & 255;
        var blue = value & 255;
        return "rgba(" + red + ", " + green + ", " + blue + ", " + alpha + ")";
    }

    function applyTheme(root, config) {
        var primary = normalizeHexColor(config.primaryColor, "#0e273b");
        var secondary = normalizeHexColor(config.secondaryColor, "#4caf50");
        var text = normalizeHexColor(config.textColor, "#ffffff");

        root.style.setProperty("--ai-chat-primary", primary);
        root.style.setProperty("--ai-chat-secondary", secondary);
        root.style.setProperty("--ai-chat-text", text);
        root.style.setProperty("--ai-chat-input-bg", hexToRgba(text, 0.08));
        root.style.setProperty("--ai-chat-border", hexToRgba(text, 0.10));
        root.style.setProperty("--ai-chat-placeholder", hexToRgba(text, 0.55));
    }

    function addMessage(container, role, text, isError) {
        var message = document.createElement("div");
        message.className = "o_ai_chat_appointments_message";
        if (isError) {
            message.className += " o_ai_chat_appointments_message_error";
        }

        var sender = document.createElement("strong");
        sender.textContent = role === "user" ? "Tú: " : "IA: ";
        message.appendChild(sender);
        message.appendChild(document.createTextNode(String(text || "")));

        container.appendChild(message);
        container.scrollTop = container.scrollHeight;
        return message;
    }

    function createWidget(config) {
        if (document.querySelector(".o_ai_chat_appointments")) {
            return;
        }

        var root = document.createElement("div");
        root.className = "o_ai_chat_appointments";
        root.innerHTML = [
            '<section class="o_ai_chat_appointments_panel" aria-hidden="true">',
            '  <header class="o_ai_chat_appointments_header">',
            '    <div class="o_ai_chat_appointments_identity">',
            '      <div class="o_ai_chat_appointments_brand"><span class="o_ai_chat_appointments_title"></span> <small>IA</small></div>',
            '      <div class="o_ai_chat_appointments_status"><span>●</span> ACTIVO</div>',
            '    </div>',
            '    <button class="o_ai_chat_appointments_close" type="button" aria-label="Cerrar chat">×</button>',
            '  </header>',
            '  <div class="o_ai_chat_appointments_messages" aria-live="polite"></div>',
            '  <div class="o_ai_chat_appointments_footer">',
            '    <form class="o_ai_chat_appointments_form">',
            '      <div class="o_ai_chat_appointments_input_shell">',
            '        <input class="o_ai_chat_appointments_input" type="text" autocomplete="off" placeholder="Escribe tu mensaje..." aria-label="Mensaje">',
            '        <button class="o_ai_chat_appointments_send" type="submit" aria-label="Enviar mensaje">➔</button>',
            '      </div>',
            '    </form>',
            '    <p class="o_ai_chat_appointments_signature">Asistente de citas</p>',
            '  </div>',
            '</section>',
            '<button class="o_ai_chat_appointments_launcher" type="button" aria-label="Abrir chat" aria-expanded="false">IA</button>'
        ].join("");

        applyTheme(root, config);
        document.body.appendChild(root);

        var launcher = root.querySelector(".o_ai_chat_appointments_launcher");
        var panel = root.querySelector(".o_ai_chat_appointments_panel");
        var closeButton = root.querySelector(".o_ai_chat_appointments_close");
        var title = root.querySelector(".o_ai_chat_appointments_title");
        var messages = root.querySelector(".o_ai_chat_appointments_messages");
        var form = root.querySelector(".o_ai_chat_appointments_form");
        var input = root.querySelector(".o_ai_chat_appointments_input");
        var send = root.querySelector(".o_ai_chat_appointments_send");

        title.textContent = config.title || "Asistente";
        addMessage(
            messages,
            "assistant",
            config.resumeMessage || config.welcomeMessage || "Hola, soy tu asistente. ¿En qué puedo ayudarte?"
        );

        function setOpen(open) {
            panel.classList.toggle("is-open", open);
            panel.setAttribute("aria-hidden", open ? "false" : "true");
            launcher.setAttribute("aria-expanded", open ? "true" : "false");
            launcher.style.display = open ? "none" : "block";
            document.documentElement.classList.toggle("o_ai_chat_appointments_open", open);
            document.body.classList.toggle("o_ai_chat_appointments_open", open);
            if (open) {
                input.focus();
            }
        }

        launcher.addEventListener("click", function () {
            setOpen(true);
        });

        closeButton.addEventListener("click", function () {
            setOpen(false);
        });

        form.addEventListener("submit", async function (event) {
            event.preventDefault();
            var message = input.value.trim();
            if (!message || send.disabled) {
                return;
            }

            input.value = "";
            addMessage(messages, "user", message);
            var waiting = addMessage(messages, "assistant", "Procesando...");
            send.disabled = true;
            input.disabled = true;

            try {
                var context = pageContext();
                var start = await postJson(START_URL, {
                    message: message,
                    sessionId: getSessionId(),
                    pageUrl: context.pageUrl,
                    pageTitle: context.pageTitle
                });

                var result = start;
                if (start.response.ok && start.data.jobId) {
                    result = await waitForResult(start.data.jobId);
                }

                waiting.remove();
                addMessage(
                    messages,
                    "assistant",
                    result.data.reply || "No se ha recibido una respuesta.",
                    !result.response.ok || Boolean(result.data.error)
                );
            } catch (error) {
                waiting.remove();
                addMessage(messages, "assistant", "No se ha podido enviar el mensaje.", true);
            } finally {
                send.disabled = false;
                input.disabled = false;
                input.focus();
            }
        });
    }

    async function init() {
        try {
            var context = pageContext();
            var result = await postJson(CONFIG_URL, {
                pageUrl: context.pageUrl,
                sessionId: getSessionId()
            });
            if (result.response.ok && result.data && result.data.enabled) {
                createWidget(result.data);
            }
        } catch (error) {
            // Si la configuración no puede cargarse, el widget permanece oculto.
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
