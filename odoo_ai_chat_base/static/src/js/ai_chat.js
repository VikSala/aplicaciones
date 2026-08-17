(function () {
    "use strict";

    var CONFIG_URL = "/ai/chat/base/config";
    var START_URL = "/ai/chat/base/start";
    var RESULT_URL = "/ai/chat/base/result";
    var POLL_INTERVAL_MS = 900;
    var MAX_POLLS = 1000;

    function pageContext() {
        return {
            pageUrl: window.location.href,
            pageTitle: document.title || ""
        };
    }

    function getSessionId() {
        var key = "odoo_ai_chat_base_session_id";
        var sessionId = window.localStorage.getItem(key);
        if (!sessionId) {
            sessionId = "web-" + Math.random().toString(36).slice(2) + "-" + Date.now();
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

    function addMessage(container, role, text, isError) {
        var row = document.createElement("div");
        row.className = "o_ai_chat_base_message o_ai_chat_base_message_" + role;
        if (isError) {
            row.className += " o_ai_chat_base_message_error";
        }

        var bubble = document.createElement("div");
        bubble.className = "o_ai_chat_base_bubble";
        bubble.textContent = String(text || "");
        row.appendChild(bubble);
        container.appendChild(row);
        container.scrollTop = container.scrollHeight;
        return row;
    }

    function createWidget(config) {
        var root = document.createElement("div");
        root.className = "o_ai_chat_base";
        root.innerHTML = [
            '<button class="o_ai_chat_base_launcher" type="button" aria-label="Abrir chat" aria-expanded="false">💬</button>',
            '<section class="o_ai_chat_base_panel" aria-hidden="true">',
            '  <header class="o_ai_chat_base_header">',
            '    <strong class="o_ai_chat_base_title"></strong>',
            '    <button class="o_ai_chat_base_close" type="button" aria-label="Cerrar chat">×</button>',
            '  </header>',
            '  <div class="o_ai_chat_base_messages" aria-live="polite"></div>',
            '  <form class="o_ai_chat_base_form">',
            '    <textarea class="o_ai_chat_base_input" rows="1" placeholder="Escribe tu mensaje..." aria-label="Mensaje"></textarea>',
            '    <button class="o_ai_chat_base_send" type="submit">Enviar</button>',
            '  </form>',
            '</section>'
        ].join("");

        document.body.appendChild(root);

        var launcher = root.querySelector(".o_ai_chat_base_launcher");
        var panel = root.querySelector(".o_ai_chat_base_panel");
        var closeButton = root.querySelector(".o_ai_chat_base_close");
        var title = root.querySelector(".o_ai_chat_base_title");
        var messages = root.querySelector(".o_ai_chat_base_messages");
        var form = root.querySelector(".o_ai_chat_base_form");
        var input = root.querySelector(".o_ai_chat_base_input");
        var send = root.querySelector(".o_ai_chat_base_send");

        title.textContent = config.title || "Asistente";
        addMessage(messages, "assistant", config.welcomeMessage || "Hola, ¿en qué puedo ayudarte?");

        function setOpen(open) {
            panel.classList.toggle("is-open", open);
            panel.setAttribute("aria-hidden", open ? "false" : "true");
            launcher.setAttribute("aria-expanded", open ? "true" : "false");
            if (open) {
                input.focus();
            }
        }

        launcher.addEventListener("click", function () {
            setOpen(!panel.classList.contains("is-open"));
        });

        closeButton.addEventListener("click", function () {
            setOpen(false);
        });

        input.addEventListener("keydown", function (event) {
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                form.requestSubmit();
            }
        });

        form.addEventListener("submit", async function (event) {
            event.preventDefault();
            var message = input.value.trim();
            if (!message || send.disabled) {
                return;
            }

            input.value = "";
            addMessage(messages, "user", message);
            var waiting = addMessage(messages, "assistant", "…");
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
            var result = await postJson(CONFIG_URL, {pageUrl: context.pageUrl});
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
