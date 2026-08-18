(function () {
    "use strict";

    var lastInitialCustomerGreetingData = null;

    console.log("[odoo_ai_chat] ai_chat_v30.js cargado - ayuda modificar producto");

    var pendingCart = null;
    var pendingAdminProductCreate = false;
    var pendingAdminProductCreateAwaiting = null;
    var pendingAdminProductCreateClientAnswers = {};
    var MAX_PRODUCT_IMAGE_BYTES = 8 * 1024 * 1024;
    var CURRENT_WIDGET_VERSION = "2.10.15-fix30";
    var lastProductForCart = null;
    var lastUserNaturalReplyContext = null;
    // Marcador sin efecto usado para compatibilidad con flujos antiguos de creación de pedidos.
    var updateAdminOrderCreatePending = function () {};

    // Normaliza texto del navegador para detectar intenciones sin acentos.
    function normalizeIntentText(text) {
        return String(text || "")
            .toLowerCase()
            .normalize("NFD")
            .replace(/[\u0300-\u036f]/g, "");
    }

    // Detecta borrado/archivo de productos para no enviarlo al preflight de carrito.
    function isProductDeleteOrArchiveIntent(text) {
        var normalized = normalizeIntentText(text);
        if (!normalized) {
            return false;
        }
        var destructive = /\b(borrar|borra|eliminar|elimina|suprimir|suprime|archivar|archiva|desactivar|desactiva)\b/.test(normalized);
        var productRelated = /\b(producto|productos|articulo|articulos|referencia|ref|sku|codigo)\b/.test(normalized) || /\b\d{3,}\b/.test(normalized);
        return destructive && productRelated;
    }

    // Detecta si el mensaje requiere mostrar el botón de imagen.
    function isProductImagePrompt(text) {
        var normalized = normalizeIntentText(text);
        if (!normalized) {
            return false;
        }

        var hasImageWord = /\b(imagen|imagenes|foto|fotos|fotografia|fotografias)\b/.test(normalized) ||
            /\b(adjuntar|adjunta|subir|sube|cargar|carga)\b/.test(normalized);
        var hasProductWord = /\b(producto|productos|articulo|articulos|sku|referencia|ref)\b/.test(normalized) ||
            /\bmodelo\b/.test(normalized);
        var hasProductAction = /\b(crea|crear|nuevo|nueva|anadir|anade|agregar|agrega|asignar|asigna|poner|pon|cambiar|cambia|modificar|modifica|actualizar|actualiza|editar|edita|subir|sube|adjuntar|adjunta|cargar|carga)\b/.test(normalized);

        return hasImageWord && hasProductWord && hasProductAction;
    }

    // Mantiene un identificador estable del navegador para el flujo guiado.
    function getSessionId() {
        var key = "odoo_ai_session_id";
        var sessionId = window.localStorage.getItem(key);
        if (!sessionId) {
            sessionId = "web-" + Math.random().toString(36).slice(2) + "-" + Date.now();
            window.localStorage.setItem(key, sessionId);
        }
        return sessionId;
    }

    // Intenta extraer el texto visible cuando la IA devuelve envoltorios técnicos.
    function cleanAssistantReplyText(value, depth) {
        depth = depth || 0;
        if (depth > 4) {
            return String(value || "").trim();
        }
        if (value === null || value === undefined) {
            return "";
        }
        if (typeof value !== "string") {
            if (typeof value === "object") {
                var directKeys = ["reply", "output", "response", "answer", "text", "message", "content", "result"];
                for (var i = 0; i < directKeys.length; i += 1) {
                    if (typeof value[directKeys[i]] === "string" && value[directKeys[i]].trim()) {
                        return cleanAssistantReplyText(value[directKeys[i]], depth + 1);
                    }
                }
                try {
                    return JSON.stringify(value, null, 2);
                } catch (error) {
                    return String(value || "").trim();
                }
            }
            return String(value || "").trim();
        }

        var text = value.trim();
        if (!text) {
            return "";
        }

        var fenceMatch = text.match(/^```(?:json|javascript|js|text)?\s*([\s\S]*?)\s*```$/i);
        if (fenceMatch) {
            text = fenceMatch[1].trim();
        }

        var labelMatch = text.match(/^\s*(?:ia|ai|assistant|asistente)\s*:\s*([\[{][\s\S]*[\]}])\s*$/i);
        if (labelMatch) {
            text = labelMatch[1].trim();
        }

        var candidates = [text];
        var firstObject = text.indexOf("{");
        var lastObject = text.lastIndexOf("}");
        if (firstObject >= 0 && lastObject > firstObject) {
            candidates.push(text.slice(firstObject, lastObject + 1).trim());
        }
        var firstArray = text.indexOf("[");
        var lastArray = text.lastIndexOf("]");
        if (firstArray >= 0 && lastArray > firstArray) {
            candidates.push(text.slice(firstArray, lastArray + 1).trim());
        }

        for (var c = 0; c < candidates.length; c += 1) {
            var candidate = candidates[c];
            if (!candidate || (candidate.charAt(0) !== "{" && candidate.charAt(0) !== "[")) {
                continue;
            }
            try {
                var parsed = JSON.parse(candidate);
                var parsedReply = cleanAssistantReplyText(parsed, depth + 1);
                if (parsedReply && parsedReply !== candidate) {
                    return parsedReply;
                }
            } catch (errorJson) {
                // No era JSON estricto; seguimos con otros formatos.
            }
        }

        var quoted = text.match(/^\s*(?:reply|output|response|answer|text|message)\s*[:=]\s*(["'])([\s\S]*)\1\s*,?\s*$/i);
        if (quoted) {
            return cleanAssistantReplyText(quoted[2], depth + 1);
        }
        var unquoted = text.match(/^\s*(?:reply|output|response|answer|text|message)\s*[:=]\s*([\s\S]+?)\s*$/i);
        if (unquoted) {
            return cleanAssistantReplyText(unquoted[1].replace(/^['"]|['"]$/g, ""), depth + 1);
        }

        return text;
    }


    // Detecta respuestas técnicas que no deben mostrarse al usuario final: [123], ["ABC"], etc.
    function isTechnicalListReply(value) {
        var text = String(value === null || value === undefined ? "" : value).trim();
        if (!text) {
            return false;
        }
        if (/^\[\s*(?:["']?[\w\-.]+["']?\s*,\s*)*["']?[\w\-.]+["']?\s*\]$/.test(text)) {
            return true;
        }
        if (/^\d+$/.test(text)) {
            return true;
        }
        return false;
    }

    // Formatea la cantidad introducida para mostrarla de forma limpia en respuestas naturales.
    function formatQuantityForReply(quantityText) {
        var match = String(quantityText || "").match(/\d+(?:[\.,]\d+)?/);
        if (!match) {
            return "la cantidad indicada";
        }
        return match[0].replace(".", ",");
    }

    // Extrae el primer identificador útil de respuestas técnicas tipo lista o JSON.
    function firstTechnicalResultValue(value) {
        var text = String(value === null || value === undefined ? "" : value).trim();
        if (!text) {
            return "";
        }
        try {
            var parsed = JSON.parse(text);
            if (Array.isArray(parsed) && parsed.length) {
                return String(parsed[0] === null || parsed[0] === undefined ? "" : parsed[0]).trim();
            }
            if (typeof parsed === "number" || typeof parsed === "string") {
                return String(parsed).trim();
            }
        } catch (error) {
            // Si no es JSON estricto, seguimos con expresiones regulares.
        }
        var arrayMatch = text.match(/^\[\s*["']?([^"'\],\s]+)["']?/);
        if (arrayMatch) {
            return arrayMatch[1].trim();
        }
        if (/^\d+$/.test(text)) {
            return text;
        }
        return "";
    }

    // Obtiene el nombre de producto desde textos estructurados o respuestas del asistente.
    function extractProductNameFromText(text) {
        var raw = String(text || "").trim();
        if (!raw) {
            return "";
        }
        var patterns = [
            /(?:nombre|name)\s*[:=]\s*([^;\n,]+)/i,
            /(?:producto|articulo|artículo)\s+(?:llamado|llamada|con nombre|de nombre)\s+([^;\n,]+)/i,
            /(?:crear|crea|nuevo|nueva)\s+(?:un\s+|una\s+|el\s+|la\s+)?(?:producto|articulo|artículo)\s+([^;\n,]+)/i
        ];
        for (var i = 0; i < patterns.length; i += 1) {
            var match = raw.match(patterns[i]);
            if (match && match[1]) {
                return match[1].trim().replace(/[\.\s]+$/g, "");
            }
        }
        return "";
    }

    // Obtiene la referencia/código de producto desde textos estructurados o respuestas del asistente.
    function extractProductCodeFromText(text) {
        var raw = String(text || "").trim();
        if (!raw) {
            return "";
        }
        var explicit = raw.match(/(?:referencia|ref\.?|codigo|código|sku|producto)\s*[:#-]?\s*([A-Za-z0-9_.-]{2,})/i);
        if (explicit && explicit[1]) {
            return explicit[1].trim();
        }
        var anyCode = raw.match(/\b[A-Za-z0-9_.-]*\d{3,}[A-Za-z0-9_.-]*\b/);
        return anyCode ? anyCode[0].trim() : "";
    }

    // Detecta si el último mensaje del usuario corresponde a una modificación de producto.
    function isProductUpdateIntentText(text) {
        var normalized = normalizeIntentText(text);
        return /\b(modificar|modifica|cambiar|cambia|actualizar|actualiza|editar|edita|poner|pon|asignar|asigna)\b/.test(normalized) &&
            /\b(producto|articulo|referencia|ref|sku|codigo)\b/.test(normalized);
    }

    // Detecta cuando el usuario solo pide iniciar una modificación sin indicar referencia ni campo.
    // En ese caso mostramos el formato correcto en vez de enviarlo a n8n como búsqueda.
    function isBareProductUpdateHelpIntent(text) {
        var normalized = normalizeIntentText(text).trim().replace(/[¿?¡!.,;:]+$/g, "").replace(/\s+/g, " ");
        return /^(modificar|modifica|editar|edita|actualizar|actualiza) (producto|articulo|articulos)$/.test(normalized);
    }

    // Mensaje de ayuda para modificación de producto.
    function productUpdatePromptHelpReply() {
        return [
            "Para modificar un producto, escribe el SKU o referencia y el dato que quieres cambiar.",
            "Formato recomendado:",
            "modificar producto [SKU] [campo]: [nuevo valor]",
            "",
            "Ejemplos:",
            "- modificar producto 01505 nombre: Nuevo nombre",
            "- modificar producto 01505 precio: 12.50",
            "- modificar producto 01505 stock real: 20",
            "- modificar producto 01505 imagen"
        ].join("\n");
    }

    // Detecta si el último mensaje del usuario corresponde a una creación de producto.
    function isProductCreateIntentText(text) {
        var normalized = normalizeIntentText(text);
        return /\b(crear|crea|nuevo|nueva|alta|introducir|introduce|insertar|inserta)\b/.test(normalized) &&
            /\b(producto|articulo)\b/.test(normalized);
    }

    // Busca el nombre del producto dentro de las respuestas acumuladas del flujo guiado.
    function productNameFromAnswers(answers, fallbackText) {
        answers = answers || {};
        return String(
            answers.name || answers.nombre || answers.display_name || extractProductNameFromText(fallbackText) || ""
        ).trim();
    }

    // Busca la referencia del producto dentro de las respuestas del flujo guiado o del resultado técnico.
    function productCodeFromAnswers(answers, fallbackText, technicalReply) {
        answers = answers || {};
        return String(
            answers.default_code || answers.referencia || answers.ref || answers.codigo || answers["código"] ||
            extractProductCodeFromText(fallbackText) || firstTechnicalResultValue(technicalReply) || ""
        ).trim();
    }

    // Detecta en una respuesta de producto la referencia que puede quedar pendiente para carrito.
    function extractProductCartCandidate(text) {
        var raw = String(text || "");
        if (!raw) {
            return null;
        }
        var codeMatch = raw.match(/(?:Referencia|Ref\.?|SKU|Código|Codigo)\s*[:#-]?\s*([A-Za-z0-9_.-]{2,})/i);
        if (codeMatch) {
            return {code: codeMatch[1], label: codeMatch[1]};
        }
        var nameMatch = raw.match(/(?:Nombre|Producto localizado)\s*[:#-]?\s*([^\n.]+)/i);
        if (nameMatch) {
            return {code: "", label: nameMatch[1].trim()};
        }
        return null;
    }

    // Guarda temporalmente el último producto mostrado para interpretar luego una cantidad suelta.
    function rememberProductForCartFromReply(text) {
        var candidate = extractProductCartCandidate(text);
        if (candidate && (candidate.code || candidate.label)) {
            lastProductForCart = candidate;
        }
    }

    // Guarda el contexto del último mensaje para convertir resultados técnicos en texto humano.
    function setLastUserNaturalReplyContext(context) {
        lastUserNaturalReplyContext = Object.assign({createdAt: Date.now()}, context || {});
    }

    // Recupera el contexto reciente si todavía está dentro de la ventana temporal válida.
    function recentLastUserNaturalReplyContext() {
        if (!lastUserNaturalReplyContext) {
            return null;
        }
        if (Date.now() - (lastUserNaturalReplyContext.createdAt || 0) > 10 * 60 * 1000) {
            lastUserNaturalReplyContext = null;
            return null;
        }
        return lastUserNaturalReplyContext;
    }

    // Infiere un mensaje legible cuando el backend devuelve solo un identificador técnico.
    function inferNaturalReplyForTechnicalResult(text) {
        if (!isTechnicalListReply(text)) {
            return text;
        }
        var context = recentLastUserNaturalReplyContext() || {};
        var message = context.message || context.visibleUserText || "";
        var productLabel = context.productLabel || (lastProductForCart && (lastProductForCart.label || lastProductForCart.code)) || firstTechnicalResultValue(text) || "el producto";

        if (context.kind === "cart_add" || looksLikeQuantityForLastProduct(message)) {
            var cartReply = normalReplyForTechnicalResult(text, {
                kind: "cart_add",
                quantity: context.quantity || message,
                productLabel: productLabel
            });
            lastProductForCart = null;
            return cartReply;
        }

        if (context.kind === "product_update" || isProductUpdateIntentText(message)) {
            return normalReplyForTechnicalResult(text, {
                kind: "product_update",
                message: message,
                productCode: context.productCode || firstTechnicalResultValue(text) || "",
                answers: context.answers || {}
            });
        }

        if (context.kind === "product_create" || context.wasPendingProductCreate || context.wasImageStep || isProductCreateIntentText(message)) {
            return normalReplyForTechnicalResult(text, {
                kind: "product_create",
                message: message,
                productName: context.productName || "",
                productCode: context.productCode || firstTechnicalResultValue(text) || "",
                answers: context.answers || {}
            });
        }

        return normalReplyForTechnicalResult(text, {kind: "generic"});
    }

    // Reconoce respuestas de producto no encontrado para normalizar el mensaje mostrado al usuario.
    function isProductNotFoundReply(text) {
        var normalized = normalizeIntentText(text);
        if (!normalized) {
            return false;
        }
        var mentionsProduct = /producto|referencia|articulo|sku|codigo/.test(normalized);
        var notFound = /no (?:he )?(?:encontrado|localizado|identificado|hallado)/.test(normalized) ||
            /no se (?:encuentra|ha encontrado|ha localizado|localiza|identifica|existe)/.test(normalized) ||
            /producto (?:no encontrado|no localizado|inexistente)/.test(normalized) ||
            /referencia (?:no encontrada|no localizada|inexistente)/.test(normalized);
        return mentionsProduct && notFound;
    }

    // Devuelve el texto estándar de producto no encontrado.
    function productNotFoundReply() {
        return "No se encuentra el producto que está buscando, contacta con la empresa.";
    }

    // Comprueba si el mensaje actual es una cantidad aplicable al último producto mostrado.
    function looksLikeQuantityForLastProduct(message) {
        return Boolean(lastProductForCart && isQuantityAnswer(message));
    }

    // Convierte respuestas técnicas del backend en mensajes naturales según el contexto.
    function normalReplyForTechnicalResult(text, context) {
        if (isProductNotFoundReply(text)) {
            return productNotFoundReply();
        }
        context = context || {};
        if (!isTechnicalListReply(text)) {
            return text;
        }
        if (context.kind === "cart_add") {
            var qty = formatQuantityForReply(context.quantity || "");
            var label = (context.productLabel || (lastProductForCart && lastProductForCart.label) || "el producto").trim();
            return "Se han añadido " + qty + " unidades del producto " + label + " al carrito.";
        }
        if (context.kind === "product_update") {
            return "Se ha modificado correctamente.";
        }
        if (context.kind === "product_create") {
            var answers = context.answers || pendingAdminProductCreateClientAnswers || {};
            var name = (context.productName || productNameFromAnswers(answers, context.message) || "").trim();
            var code = (context.productCode || productCodeFromAnswers(answers, context.message, text) || "").trim();
            if (name && code && name !== code) {
                return "Se ha creado correctamente el producto " + name + " (" + code + ").";
            }
            if (name || code) {
                return "Se ha creado correctamente el producto " + (name || code) + ".";
            }
            return "Se ha creado correctamente el producto.";
        }
        return "Operación realizada correctamente.";
    }

    // Escapa texto antes de insertarlo en el DOM.
    function escapeHtml(text) {
        var div = document.createElement("div");
        div.textContent = text || "";
        return div.innerHTML;
    }

    // Valida URLs de botones generados por el backend.
    function isSafeActionUrl(url) {
        if (!url || typeof url !== "string") {
            return false;
        }
        return /^\/(?!\/)/.test(url) || url.indexOf(window.location.origin + "/") === 0;
    }

    // Normaliza el botón opcional asociado a una respuesta local de Odoo.
    // Puede ser un enlace seguro o una acción interna del widget.
    function normalizeActionButton(button) {
        if (!button || typeof button !== "object") {
            return null;
        }
        var label = String(button.label || "Abrir ficha").trim() || "Abrir ficha";
        var action = String(button.action || "").trim();
        if (action) {
            return {
                label: label,
                action: action,
                target: "_self"
            };
        }
        var url = String(button.url || "").trim();
        if (!isSafeActionUrl(url)) {
            return null;
        }
        return {
            label: label,
            url: url,
            target: button.target === "_self" ? "_self" : "_blank"
        };
    }

    // Añade debajo del texto uno o varios botones para abrir fichas o registros en Odoo.
    function appendActionButton(message, actionButton) {
        var buttons = Array.isArray(actionButton) ? actionButton : (actionButton ? [actionButton] : []);
        buttons = buttons.map(normalizeActionButton).filter(Boolean);
        if (!buttons.length) {
            return;
        }
        var row = document.createElement("div");
        row.style.marginTop = "8px";
        row.style.whiteSpace = "normal";
        row.style.display = "flex";
        row.style.flexWrap = "wrap";
        row.style.gap = "6px";

        buttons.slice(0, 8).forEach(function (button) {
            var element = button.action ? document.createElement("button") : document.createElement("a");
            if (button.action) {
                element.type = "button";
                element.dataset.aiChatAction = button.action;
                element.addEventListener("click", function () {
                    handleActionButtonClick(button.action, message);
                });
            } else {
                element.href = button.url;
                element.target = button.target;
                if (button.target === "_blank") {
                    element.rel = "noopener noreferrer";
                }
            }
            element.textContent = button.label;
            element.style.display = "inline-block";
            element.style.background = "#009557";
            element.style.color = "#fff";
            element.style.padding = "7px 11px";
            element.style.borderRadius = "6px";
            element.style.textDecoration = "none";
            element.style.fontWeight = "bold";
            element.style.fontSize = "13px";
            element.style.lineHeight = "16px";
            element.style.border = "none";
            element.style.cursor = "pointer";
            row.appendChild(element);
        });

        message.appendChild(row);
    }

    // Actualiza el contenido visual de un mensaje del chat.
    function setMessage(message, sender, text, isError, actionButton) {
        message.style.color = isError ? "#b00020" : "";
        var visibleText = sender === "Tú" ? text : cleanAssistantReplyText(text);
        // Protección específica para el saludo inicial: si por caché, sesión o una
        // respuesta heredada llega el texto genérico "Operación realizada correctamente"
        // junto a botones de historial/repetición, lo sustituimos por un saludo construido
        // con los datos estructurados del cliente conectado.
        if (!isError && sender !== "Tú" && isGenericOperationReply(visibleText) && lastInitialCustomerGreetingData) {
            visibleText = buildCustomerGreetingReply(lastInitialCustomerGreetingData);
        }
        if (!isError && sender !== "Tú") {
            if (isProductNotFoundReply(visibleText)) {
                visibleText = productNotFoundReply();
            } else if (isTechnicalListReply(visibleText)) {
                visibleText = inferNaturalReplyForTechnicalResult(visibleText);
            }
            rememberProductForCartFromReply(visibleText);
        }
        message.innerHTML = "<strong>" + escapeHtml(sender) + ":</strong> " + escapeHtml(visibleText);
        if (!isError && sender !== "Tú") {
            appendActionButton(message, actionButton);
        }
    }

    // Añade una nueva línea de conversación al chat.
    function addMessage(container, sender, text, isError) {
        var message = document.createElement("div");
        message.style.marginBottom = "10px";
        message.style.whiteSpace = "pre-wrap";
        setMessage(message, sender, text, isError);
        container.appendChild(message);
        container.scrollTop = container.scrollHeight;
        return message;
    }

    // Pausa la ejecución asíncrona durante el tiempo indicado.
    function sleep(ms) {
        return new Promise(function (resolve) {
            window.setTimeout(resolve, ms);
        });
    }

    // Lee una respuesta HTTP como JSON o texto plano.
    async function readResponse(response) {
        var text = await response.text();
        if (!text) {
            return {};
        }
        try {
            return JSON.parse(text);
        } catch (error) {
            return {reply: text};
        }
    }

    // Valida la imagen elegida y prepara sus metadatos.
    function readFileAsProductImageAttachment(file) {
        return new Promise(function (resolve, reject) {
            if (!file) {
                resolve(null);
                return;
            }
            var supportedMimetypes = {
                "image/jpeg": true,
                "image/jpg": true,
                "image/pjpeg": true,
                "image/png": true,
                "image/gif": true,
                "image/webp": true
            };
            var filename = file.name || "imagen_producto";
            var extension = filename.indexOf(".") >= 0 ? filename.split(".").pop().toLowerCase() : "";
            var extensionMimetype = {jpg: "image/jpeg", jpeg: "image/jpeg", png: "image/png", gif: "image/gif", webp: "image/webp"}[extension] || "";
            var mimetype = (file.type || extensionMimetype || "").toLowerCase();
            if (mimetype === "image/jpg" || mimetype === "image/pjpeg") {
                mimetype = "image/jpeg";
            }
            if (!supportedMimetypes[mimetype]) {
                reject(new Error("Solo puedes adjuntar imágenes JPG, PNG, GIF o WEBP."));
                return;
            }
            if (file.size > MAX_PRODUCT_IMAGE_BYTES) {
                reject(new Error("La imagen supera 8 MB. Usa una imagen más ligera."));
                return;
            }

            resolve({
                kind: "product_image",
                filename: filename,
                mimetype: mimetype || "image/jpeg",
                size: file.size || 0
            });
        });
    }

    // Detecta si el usuario respondió con una cantidad.
    function isQuantityAnswer(text) {
        return /^\s*\d+(?:[\.,]\d+)?\s*(?:uds?\.?|unidades?|metros?|m)?\s*$/i.test(text || "") ||
            /^\s*(?:cantidad|cant\.?)\s*[:=]?\s*\d+(?:[\.,]\d+)?\s*$/i.test(text || "");
    }

    // Detecta si el usuario cancela un flujo pendiente.
    function isCancelAnswer(text) {
        return /^\s*(?:cancelar|cancela|no|olvida|olvídalo|olvidalo|parar|salir)\s*$/i.test(text || "");
    }

    // Sincroniza el estado de carrito pendiente recibido del backend.
    function updatePendingCart(data) {
        if (!data) {
            return;
        }
        if (data.clearPendingCart || data.added) {
            pendingCart = null;
        }
        if (data.pendingCart) {
            pendingCart = data.pendingCart;
        }
    }

    // Sincroniza el alta guiada de producto recibida del backend.
    function updateAdminProductCreatePending(data, sentKey, sentValue) {
        if (!data) {
            return;
        }

        if (data.pendingAdminProductCreate && sentKey && data.adminProductCreateAwaiting !== sentKey) {
            pendingAdminProductCreateClientAnswers[sentKey] = sentValue || "";
        }

        if (data.clearPendingAdminProductCreate || data.productCreated) {
            pendingAdminProductCreate = false;
            pendingAdminProductCreateAwaiting = null;
            pendingAdminProductCreateClientAnswers = {};
        }
        if (data.pendingAdminProductCreate) {
            pendingAdminProductCreate = true;
            pendingAdminProductCreateAwaiting = data.adminProductCreateAwaiting || null;
        }
    }

    // Notifica a Odoo que el carrito se actualizó.
    function notifyCartUpdated(data) {
        try {
            window.dispatchEvent(new CustomEvent("odoo_ai_chat_cart_updated", {detail: data || {}}));
            document.body.dispatchEvent(new CustomEvent("website_sale_cart_updated", {detail: data || {}}));
        } catch (error) {
            // No todos los navegadores/temas usan estos eventos; el carrito queda añadido igualmente.
        }
    }

    // Envía peticiones JSON al backend del addon.
    async function postJson(url, payload) {
        var response = await fetch(url, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(payload || {}),
            credentials: "same-origin"
        });
        var data = await readResponse(response);
        return {response: response, data: data};
    }

    // Devuelve el botón estándar para abrir el carrito cuando una operación añade producto.
    function cartViewButton() {
        return {
            label: "Ver carrito",
            url: "/shop/cart",
            target: "_self"
        };
    }

    // Botones visibles para visitantes sin sesión. No ejecutan ninguna función interna:
    // solo llevan a las páginas estándar de Odoo para iniciar sesión o crear cuenta.
    function guestAuthButtons() {
        return [
            {label: "Login", url: "/web/login", target: "_self"},
            {label: "Crear cuenta", url: "/web/signup", target: "_self"}
        ];
    }

    // Muestra las capacidades de la cuenta actual. El backend decide qué botones
    // corresponden a visitante, cliente o admin; cada botón funcional escribe un prompt
    // en el campo de texto, sin enviarlo automáticamente.
    async function showAccountCapabilities(messages) {
        var waiting = addMessage(messages, "IA", "Consultando qué puede hacer esta cuenta...");
        try {
            var result = await postJson("/ai/account/capabilities", {
                sessionId: getSessionId(),
                pageUrl: window.location.href,
                pageTitle: document.title
            });
            var data = result && result.data ? result.data : {};
            var reply = data.reply || "Estas son las acciones disponibles para esta cuenta:";
            setMessage(waiting, "IA", reply, false, actionButtonsFromData(data));
        } catch (error) {
            console.error("[odoo_ai_chat] Error consultando capacidades", error);
            setMessage(waiting, "IA", "No he podido consultar las acciones disponibles. Inténtalo de nuevo.", false);
        }
    }

    // Añade el botón "Ver carrito" a las respuestas de añadido al carrito, sin duplicarlo
    // ni reemplazar otros botones que ya devuelva el backend.
    function addCartViewButtonIfNeeded(buttons, data) {
        if (!data || !data.added) {
            return buttons;
        }
        var list = [];
        if (Array.isArray(buttons)) {
            list = buttons.slice();
        } else if (buttons) {
            list = [buttons];
        }
        var alreadyHasCartButton = list.some(function (button) {
            return button && (button.url === "/shop/cart" || /ver\s+carrito/i.test(button.label || ""));
        });
        if (!alreadyHasCartButton) {
            list.push(cartViewButton());
        }
        return list.length ? list : null;
    }

    // Extrae uno o varios botones de acción desde la respuesta del backend.
    function actionButtonsFromData(data) {
        if (!data) {
            return null;
        }
        var buttons = null;
        if (Array.isArray(data.actionButtons) && data.actionButtons.length) {
            buttons = data.actionButtons;
        } else {
            buttons = data.actionButton || data.openButton || data.recordButton || null;
        }
        return addCartViewButtonIfNeeded(buttons, data);
    }

    // Detecta textos genéricos que nunca deben usarse como saludo personalizado.
    function isGenericOperationReply(text) {
        var value = String(text || "").trim();
        value = value.replace(/^\s*(?:ia|ai|assistant|asistente)\s*:\s*/i, "").trim();
        return /^(operaci[oó]n realizada(?: correctamente)?|carrito actualizado|ok|correcto)\.?$/i.test(value);
    }


    // Convierte errores técnicos de n8n/Odoo en un mensaje comprensible para el cliente.
    // No se aplica a mensajes de permisos ni a respuestas funcionales conocidas.
    function unknownQuestionReply() {
        return "No entiendo lo que has dicho, ¿podrías repetir la pregunta?";
    }

    function isPermissionDeniedReply(text) {
        return /por seguridad|solo la cuenta admin|privilegios|permisos/i.test(String(text || ""));
    }

    function isUnknownAIErrorReply(text) {
        var value = String(text || "").trim();
        if (!value || isPermissionDeniedReply(value) || isProductNotFoundReply(value)) {
            return false;
        }
        return /webhook|not registered|no est[aá] registrado|no se pudo contactar con el flujo|no se pudo leer el resultado|odoo no devolvi[oó] jobid|tardado demasiado|failed to fetch|networkerror|internal server error|traceback|exception/i.test(value);
    }

    function normalizeAIReply(reply) {
        return isUnknownAIErrorReply(reply) ? unknownQuestionReply() : reply;
    }

    // En el saludo inicial solo mostramos botones de pedido si el backend ha confirmado
    // que realmente existe un último pedido. Evita botones heredados junto a un texto genérico.
    function customerGreetingButtonsFromData(data) {
        data = data || {};
        var hasOrderContext = data.hasOrders === true || Number(data.orderCount || 0) > 0 || Boolean(data.lastOrderName || data.lastOrderId);
        if (!hasOrderContext) {
            return null;
        }
        return actionButtonsFromData(data);
    }

    // Pinta respuestas relacionadas con historial de pedidos del cliente.
    function renderCustomerOrderResponse(waitingMessage, data, responseOk) {
        if (data && data.added) {
            notifyCartUpdated(data);
        }
        var isError = !responseOk || (data && data.success === false);
        var reply = (data && data.reply) || (isError ? "No he podido consultar tu historial de pedidos." : "Operación realizada.");
        setMessage(
            waitingMessage,
            isError ? "Error" : "IA",
            reply,
            isError,
            actionButtonsFromData(data)
        );
    }

    // Construye el saludo del cliente desde campos estructurados del backend.
    // Es un refuerzo defensivo: evita que un valor técnico heredado se muestre como
    // "Operación realizada correctamente" en clientes distintos al primero probado.
    function buildCustomerGreetingReply(data) {
        data = data || {};
        var customerName = String(data.customerName || data.partnerName || data.name || "cliente").trim() || "cliente";

        function normalizeGreetingCandidate(value) {
            value = String(value || "").trim();
            value = value.replace(/^\s*(?:ia|ai|assistant|asistente)\s*:\s*/i, "").trim();
            return value;
        }

        // No reutilizamos respuestas genéricas ni técnicas en el saludo inicial.
        // El caso que se corrige aquí es el de clientes con un único pedido: podían
        // llegar botones correctos, pero el texto heredado era "Operación realizada correctamente".
        var genericGreeting = /^(operaci[oó]n realizada(?: correctamente)?|carrito actualizado|ok|correcto|pedido creado|historial localizado|\[[\s\S]*\])\.?$/i;
        function cleanGreeting(value) {
            value = normalizeGreetingCandidate(value);
            if (!value || genericGreeting.test(value)) {
                return "";
            }
            return value;
        }

        var hasOrders = data.hasOrders === true || Number(data.orderCount || 0) > 0 || Boolean(data.lastOrderName || data.lastOrderId) || Boolean(customerGreetingButtonsFromData(data));
        if (!hasOrders) {
            var noOrderCandidate = cleanGreeting(data.forceGreetingReply) || cleanGreeting(data.safeGreetingReply) || cleanGreeting(data.greetingReply) || cleanGreeting(data.reply);
            if (noOrderCandidate && !/tu\s+último\s+pedido|tu\s+ultimo\s+pedido|deseas\s+repetirlo/i.test(noOrderCandidate)) {
                return noOrderCandidate;
            }
            return "Hola, " + customerName + ". ¿En qué puedo ayudarte?";
        }

        var orderCount = Number(data.orderCount || 0);
        if (orderCount === 1 || data.singleOrderGreeting === true) {
            var singleLastOrderName = String(data.lastOrderName || "").trim();
            var singleLines = ["Hola, " + customerName + ". ¿En qué puedo ayudarte?"];
            if (singleLastOrderName) {
                singleLines.push("Tu último pedido es: " + singleLastOrderName);
            }
            return singleLines.join("\n");
        }

        // Para clientes con más de un pedido reconstruimos el saludo desde campos estructurados.
        // Solo aceptamos un texto del backend si ya contiene explícitamente el saludo
        // de último pedido. Así evitamos respuestas genéricas.
        var forcedGreeting = cleanGreeting(data.forceGreetingReply) || cleanGreeting(data.safeGreetingReply) || cleanGreeting(data.greetingReply) || cleanGreeting(data.reply);
        if (forcedGreeting && /tu\s+último\s+pedido|tu\s+ultimo\s+pedido|deseas\s+repetirlo/i.test(forcedGreeting)) {
            return forcedGreeting;
        }

        var lastOrderName = String(data.lastOrderName || "").trim();
        var topProductName = String(data.topProductName || "").trim();
        var lines = [
            "Hola, " + customerName + ".",
            "Tu último pedido fue " + (lastOrderName || "tu último pedido registrado") + ".",
            "¿Deseas repetirlo?"
        ];
        if (topProductName) {
            lines.push(
                "",
                "Tu producto más comprado es " + topProductName + ".",
                "¿Deseas añadirlo al carrito?"
            );
        }
        return lines.join("\n");
    }

    // Ejecuta botones internos del chat, por ejemplo mostrar historial o repetir último pedido.
    async function handleActionButtonClick(action, sourceMessage) {
        var messages = sourceMessage && sourceMessage.parentNode ? sourceMessage.parentNode : null;
        if (!messages) {
            return;
        }

        // Botones de ayuda: solo escriben el prompt sugerido en el campo de texto.
        // No envían ni ejecutan la acción automáticamente; el usuario decide cuándo pulsar Enviar.
        if (String(action || "").indexOf("send_prompt::") === 0) {
            var prompt = String(action || "").slice("send_prompt::".length);
            var chatInput = document.getElementById("odoo-ai-chat-input");
            if (chatInput) {
                chatInput.value = prompt;
                try {
                    chatInput.focus();
                    var cursorPosition = chatInput.value.length;
                    chatInput.setSelectionRange(cursorPosition, cursorPosition);
                } catch (error) {
                    // Algunos navegadores no permiten mover el cursor en determinados inputs.
                }
            }
            return;
        }

        var endpoint = "";
        var userLabel = "";
        if (action === "show_customer_orders") {
            endpoint = "/ai/customer/orders/history";
            userLabel = "Mostrar mi historial de pedidos";
        } else if (action === "repeat_last_order") {
            endpoint = "/ai/customer/orders/repeat_last";
            userLabel = "Repetir último pedido";
        } else if (action === "add_most_purchased_product") {
            endpoint = "/ai/customer/cart/add_most_purchased";
            userLabel = "Añadir mi producto más comprado al carrito";
        } else {
            return;
        }
        addMessage(messages, "Tú", userLabel);
        var waiting = addMessage(messages, "IA", action === "add_most_purchased_product" ? "Añadiendo producto al carrito..." : "Consultando tu historial de pedidos...");
        try {
            var result = await postJson(endpoint, {
                sessionId: getSessionId(),
                pageUrl: window.location.href,
                pageTitle: document.title
            });
            renderCustomerOrderResponse(waiting, result.data, result.response.ok);
        } catch (error) {
            setMessage(waiting, "Error", "No he podido realizar la acción. Detalle técnico: " + error.message, true);
        }
    }

    // Distingue si una consulta admin de historial se refiere a ventas o compras.
    function adminOrderHistoryKindFromText(text) {
        var value = normalizeIntentText(text || "");
        if (/compra|compras|proveedor|proveedores|purchase|rfq|sd[pq]|presupuesto/.test(value)) {
            return "purchase";
        }
        return "sale";
    }

    // Detecta consultas admin del historial de pedidos de un cliente/proveedor concreto.
    // Admite variantes naturales como:
    // - "historial pedidos ventas de Alba"
    // - "historial de pedidos de venta de Alba"
    // - "pedidos compra ChinaLuzLED"
    // La ruta del backend vuelve a validar que el usuario sea la cuenta admin.
    function isAdminCustomerOrderHistoryIntent(text) {
        var value = normalizeIntentText(text || "");
        if (!value) {
            return false;
        }
        var mentionsHistory = /historial|historico|pedidos/.test(value);
        var salesTarget = /(?:historial\s+)?(?:de\s+)?pedidos\s+(?:de\s+)?ventas?\s+(?:de\s+|para\s+)?.+|historial\s+(?:de\s+)?ventas?\s+(?:de\s+|para\s+)?.+/.test(value);
        var purchaseTarget = /(?:historial\s+)?(?:de\s+)?pedidos\s+(?:de\s+)?compras?\s+(?:de\s+|para\s+)?.+|historial\s+(?:de\s+)?compras?\s+(?:de\s+|para\s+)?.+/.test(value);
        var genericPartnerTarget = /historial\s+(?:de\s+)?pedidos\s+(?:de\s+|para\s+).+|pedidos\s+(?:de\s+|para\s+).+/.test(value);
        var mentionsTargetPartner = salesTarget || purchaseTarget || genericPartnerTarget;
        var genericOnly = /^(?:ver|mostrar|muestrame|mu[eé]strame|consultar|consulta)?\s*(?:el\s+)?(?:historial\s+)?(?:de\s+)?pedidos(?:\s+(?:de\s+)?(?:ventas?|compras?))?\s*$/.test(value) ||
            /^(?:ver|mostrar|muestrame|mu[eé]strame|consultar|consulta)?\s*(?:el\s+)?historial\s+(?:de\s+)?(?:ventas?|compras?)\s*$/.test(value);
        var isPersonalCustomerRequest = /mis pedidos|mis compras|mi historial|ultimo pedido|ultima compra|que he comprado/.test(value);
        return mentionsHistory && mentionsTargetPartner && !genericOnly && !isPersonalCustomerRequest;
    }

    // Detecta la orden genérica de admin para abrir el selector de clientes/proveedores.
    // Se aceptan frases con o sin "de":
    // - "historial pedidos ventas"
    // - "historial pedidos de ventas"
    // - "historial ventas"
    // - "historial pedidos compras"
    function isAdminOrderHistorySelectorIntent(text) {
        var value = normalizeIntentText(text || "");
        if (!value) {
            return false;
        }
        if (/mis pedidos|mis compras|mi historial|mi ultimo pedido|mi ultima compra/.test(value)) {
            return false;
        }
        // Acepta variantes equivalentes para abrir el selector de historial:
        // - "historial de ventas" / "ver historial de ventas"
        // - "historial ventas" / "ver historial ventas"
        // - "historial pedido de venta" / "historial pedidos de venta"
        // - equivalentes de compra/compras.
        return /^\s*(?:ver|mostrar|muestrame|mu[eé]strame|consultar|consulta)?\s*(?:el\s+)?historial\s+(?:de\s+)?pedidos?(?:\s+(?:de\s+)?(?:ventas?|compras?))?\s*$/.test(value) ||
            /^\s*(?:ver|mostrar|muestrame|mu[eé]strame|consultar|consulta)?\s*(?:el\s+)?historial\s+(?:de\s+)?(?:ventas?|compras?)\s*$/.test(value) ||
            /^\s*(?:ver|mostrar|muestrame|mu[eé]strame|consultar|consulta)?\s*(?:los?\s+)?pedidos?\s+(?:de\s+)?(?:ventas?|compras?)\s*$/.test(value) ||
            /^\s*(?:ver|mostrar|muestrame|mu[eé]strame|consultar|consulta)?\s*(?:los?\s+)?pedidos?\s*$/.test(value);
    }

    // Detecta preguntas del cliente sobre su historial o último pedido.
    function isCustomerOrderHistoryIntent(text) {
        var value = normalizeIntentText(text || "");
        if (!value) {
            return false;
        }
        var mentionsOrder = /\b(pedido|pedidos|compra|compras|historial|historico|ultimo pedido|ultima compra)\b/.test(value);
        var asksHistory = /historial|historico|mis pedidos|mis compras|ultimo pedido|ultima compra|pedido anterior|pedidos anteriores|que he comprado|qué he comprado/.test(value);
        return mentionsOrder && asksHistory;
    }

    // Detecta si el cliente quiere repetir el último pedido.
    function isRepeatLastOrderIntent(text) {
        var value = normalizeIntentText(text || "");
        if (!value) {
            return false;
        }
        return /(repetir|repite|volver a pedir|comprar otra vez|hacer de nuevo|mismo pedido)/.test(value) && /(ultimo pedido|último pedido|pedido anterior|ultima compra|última compra|compra anterior|pedido)/.test(value);
    }

    // Detecta la petición directa de abrir la página de cuenta del cliente conectado.
    // La usan los botones de ayuda: el botón escribe "mi cuenta" y el usuario decide
    // cuándo enviarlo. Al enviarlo, abrimos el portal estándar de Odoo.
    function isMyAccountIntent(text) {
        var value = normalizeIntentText(text || "");
        return /^(?:ver|abrir|mostrar|ir\s+a|entrar\s+a)?\s*(?:mi\s+)?cuenta$/.test(value) ||
            /^(?:mi\s+portal|portal\s+cliente|area\s+cliente|[aá]rea\s+cliente)$/.test(value);
    }

    // Pinta la respuesta del flujo de carrito.
    function renderCartResponse(waitingMessage, data, responseOk) {
        updatePendingCart(data);
        if (data && data.added) {
            notifyCartUpdated(data);
        }

        var isError = !responseOk || (data && data.success === false);
        var reply = (data && data.reply) || (isError ? "No he podido actualizar el carrito." : "Carrito actualizado.");
        if (isProductNotFoundReply(reply) || (isError && /identificar el producto|producto pendiente|referencia/i.test(reply))) {
            reply = productNotFoundReply();
        }
        if (!isError && data && (data.added || isTechnicalListReply(reply))) {
            reply = normalReplyForTechnicalResult(reply, {
                kind: "cart_add",
                quantity: data.addedQuantity || data.quantity || data.lineQuantity || "",
                productLabel: data.productName || data.productLabel || (pendingCart && (pendingCart.name || pendingCart.productCode)) || (lastProductForCart && (lastProductForCart.label || lastProductForCart.code)) || "el producto"
            });
            if (isTechnicalListReply(reply)) {
                reply = "Se han añadido " + formatQuantityForReply(data.quantity || data.addedQuantity || data.lineQuantity || "") + " unidades del producto al carrito.";
            }
            lastProductForCart = null;
        }
        setMessage(
            waitingMessage,
            isError && !isProductNotFoundReply(reply) ? "Error" : "IA",
            reply,
            isError && !isProductNotFoundReply(reply),
            actionButtonsFromData(data)
        );
    }

    // Consulta al backend si debe mostrarse el widget.
    async function isChatEnabledOnThisPage() {
        try {
            var response = await fetch("/ai/chat/status", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({
                    pageUrl: window.location.href,
                    pagePath: window.location.pathname
                }),
                credentials: "same-origin"
            });

            if (!response.ok) {
                console.error("[odoo_ai_chat] No se pudo comprobar la visibilidad del chat", response.status);
                return false;
            }

            var data = await readResponse(response);
            return Boolean(data.enabled);
        } catch (error) {
            console.error("[odoo_ai_chat] Error comprobando visibilidad", error);
            return false;
        }
    }

    // Consulta periódicamente el resultado de una ejecución de n8n.
    async function pollChatJob(jobId, waitingMessage, messages, sentAdminKey, sentAdminValue, sendContext) {
        var maxAttempts = 240; // 240 * 3s = 12 minutos
        for (var attempt = 0; attempt < maxAttempts; attempt += 1) {
            await sleep(3000);

            var response = await fetch("/ai/chat/result", {
                method: "POST",
                headers: {"Content-Type": "application/json"},
                body: JSON.stringify({jobId: jobId}),
                credentials: "same-origin"
            });
            var data = await readResponse(response);

            if (!response.ok) {
                var pollErrorReply = data.reply || data.error || "No se pudo leer el resultado del flujo de IA.";
                throw new Error(isUnknownAIErrorReply(pollErrorReply) ? unknownQuestionReply() : pollErrorReply);
            }

            if (data.status === "done") {
                sendContext = sendContext || {};
                var wasPendingProductCreate = Boolean(sendContext.wasPendingProductCreate || pendingAdminProductCreate);
                var answersBeforeProductCreateClear = Object.assign({}, sendContext.adminProductCreateClientAnswers || pendingAdminProductCreateClientAnswers || {});
                if ((wasPendingProductCreate || pendingAdminProductCreate) && sentAdminKey) {
                    answersBeforeProductCreateClear[sentAdminKey] = sentAdminValue || "";
                }
                updatePendingCart(data);
                updateAdminProductCreatePending(data, sentAdminKey, sentAdminValue);
                updateAdminOrderCreatePending(data);
                if (data.added) {
                    notifyCartUpdated(data);
                }
                var doneReply = data.reply || "No he recibido respuesta.";
                if (isProductNotFoundReply(doneReply)) {
                    doneReply = productNotFoundReply();
                } else {
                    doneReply = normalizeAIReply(doneReply);
                }
                if (!data.added && isTechnicalListReply(doneReply) && looksLikeQuantityForLastProduct(sentAdminValue || "")) {
                    doneReply = normalReplyForTechnicalResult(doneReply, {
                        kind: "cart_add",
                        quantity: sentAdminValue || "",
                        productLabel: (lastProductForCart && (lastProductForCart.label || lastProductForCart.code)) || "el producto"
                    });
                    lastProductForCart = null;
                } else if (!data.added && (data.productUpdated || (isTechnicalListReply(doneReply) && isProductUpdateIntentText(sentAdminValue || "")))) {
                    doneReply = normalReplyForTechnicalResult(doneReply, {
                        kind: "product_update",
                        message: sentAdminValue || "",
                        productCode: data.productCode || data.default_code || data.productRef || "",
                        answers: answersBeforeProductCreateClear
                    });
                } else if (!data.added && (data.productCreated || (wasPendingProductCreate && isTechnicalListReply(doneReply)))) {
                    doneReply = normalReplyForTechnicalResult(doneReply, {
                        kind: "product_create",
                        message: sentAdminValue || "",
                        productName: data.productName || data.name || "",
                        productCode: data.productCode || data.default_code || data.productRef || "",
                        answers: answersBeforeProductCreateClear
                    });
                } else if (data.added) {
                    doneReply = normalReplyForTechnicalResult(doneReply, {
                        kind: "cart_add",
                        quantity: data.addedQuantity || data.quantity || data.lineQuantity || "",
                        productLabel: data.productName || data.productLabel || ""
                    });
                } else if (isTechnicalListReply(doneReply) && (isProductCreateIntentText(sentAdminValue || "") || isProductUpdateIntentText(sentAdminValue || ""))) {
                    doneReply = normalReplyForTechnicalResult(doneReply, {
                        kind: isProductUpdateIntentText(sentAdminValue || "") ? "product_update" : "product_create",
                        message: sentAdminValue || ""
                    });
                }
                setMessage(waitingMessage, "IA", doneReply, false, actionButtonsFromData(data));
                messages.scrollTop = messages.scrollHeight;
                return;
            }

            if (data.status === "error") {
                var jobErrorReply = data.reply || data.error || "No se pudo contactar con el flujo de IA.";
                if (isUnknownAIErrorReply(jobErrorReply)) {
                    setMessage(waitingMessage, "IA", unknownQuestionReply(), false);
                } else {
                    setMessage(waitingMessage, "Error", jobErrorReply, true);
                }
                messages.scrollTop = messages.scrollHeight;
                return;
            }

            if (attempt === 10) {
                setMessage(waitingMessage, "IA", "Sigo esperando la respuesta de n8n. El flujo de IA puede tardar varios minutos...", false);
                messages.scrollTop = messages.scrollHeight;
            }
        }

        throw new Error("El flujo de IA ha tardado demasiado en responder. Revisa la ejecución de n8n.");
    }

    // Crea toda la interfaz flotante del asistente.
    function createChatWidget() {
        var existingBox = document.getElementById("odoo-ai-chat-box");
        var existingOpenButton = document.getElementById("odoo-ai-chat-open");
        var existingWrapper = document.getElementById("odoo-ai-chat-wrapper");

        // Si existe un widget antiguo creado por el bundle cacheado de Odoo,
        // lo sustituimos por esta versión. Así evitamos que quede visible siempre
        // el botón 📎 Imagen de versiones anteriores.
        if (existingWrapper && existingWrapper.getAttribute("data-odoo-ai-chat-version") === CURRENT_WIDGET_VERSION) {
            return;
        }
        if (existingBox || existingOpenButton || existingWrapper) {
            if (existingWrapper) {
                existingWrapper.remove();
            } else {
                if (existingBox) {
                    existingBox.remove();
                }
                if (existingOpenButton) {
                    existingOpenButton.remove();
                }
            }
        }

        // ==========================================
        // CONFIGURACIÓN DE MARCA (estilo visual 2.15)
        // ==========================================
        const CHAT_CONFIG = {
            primaryColor: '#0e273b',
            accentColor: '#4CAF50',
            textColor: '#ffffff',
            inputBg: 'rgba(255,255,255,0.08)',
            borderColor: 'rgba(255,255,255,0.1)',
            panelWidth: '31.625rem'
        };

        var style = document.createElement('style');
        style.innerHTML = `
            :root {
                --ai-chat-bg: ${CHAT_CONFIG.primaryColor};
                --ai-chat-accent: ${CHAT_CONFIG.accentColor};
                --ai-chat-text: ${CHAT_CONFIG.textColor};
                --ai-chat-input-bg: ${CHAT_CONFIG.inputBg};
                --ai-chat-border: ${CHAT_CONFIG.borderColor};
                --ai-chat-width: ${CHAT_CONFIG.panelWidth};
            }

            #odoo-ai-chat-box { width: 100%; transition: width 0.3s ease; }
            @media (min-width: 900px) {
                #odoo-ai-chat-box { width: var(--ai-chat-width) !important; }
            }
            #odoo-ai-chat-messages::-webkit-scrollbar { width: 6px; }
            #odoo-ai-chat-messages::-webkit-scrollbar-thumb {
                background: var(--ai-chat-border);
                border-radius: 10px;
            }
            #odoo-ai-chat-wrapper select option {
                color: #222;
                background: #fff;
            }
            #odoo-ai-chat-wrapper input::placeholder {
                color: rgba(255,255,255,0.55);
            }
        `;
        document.head.appendChild(style);

        var wrapper = document.createElement("div");
        wrapper.id = "odoo-ai-chat-wrapper";
        wrapper.setAttribute("data-odoo-ai-chat-version", CURRENT_WIDGET_VERSION);
        wrapper.innerHTML = `
            <div id="odoo-ai-chat-box" style="position:fixed;right:0;bottom:0;max-width:100vw;height:100vh;background:var(--ai-chat-bg);border-left:1px solid var(--ai-chat-border);border-radius:0;box-shadow:-5px 0 25px rgba(0,0,0,0.3);z-index:2147483000;font-family:Arial,sans-serif;overflow:hidden;display:none;flex-direction:column;color:var(--ai-chat-text);">
                <div style="background:var(--ai-chat-bg);color:var(--ai-chat-text);padding:20px 18px;padding-top: 40px;display:flex;justify-content:space-between;align-items:flex-start;border-bottom:1px solid var(--ai-chat-border);gap:10px;">
                    <div>
                        <span style="font-weight:bold;font-size:18px;letter-spacing:0.5px;">OPTIMA <small style="font-size:10px;opacity:0.6;vertical-align:top;">IA</small></span>
                        <div style="font-size:11px;color:var(--ai-chat-accent);margin-top:4px;display:flex;align-items:center;"><span style="margin-right:5px;">●</span> ACTIVO</div>
                    </div>
                    <div style="display:flex;align-items:flex-start;gap:10px;">
                        <button id="odoo-ai-chat-header-extra" type="button" aria-label="¿Qué puedo hacer?" title="Ver qué puede hacer esta cuenta" style="background:#009557;border:none;color:#fff;font-size:13px;line-height:16px;font-weight:bold;cursor:pointer;border-radius:6px;padding:7px 12px;white-space:nowrap;">¿Qué puedo hacer?</button>
                        <button id="odoo-ai-chat-close" aria-label="Cerrar chat" style="background:transparent;border:none;color:var(--ai-chat-text);font-size:24px;line-height:24px;cursor:pointer;opacity:0.7;">×</button>
                    </div>
                </div>

                <div id="odoo-ai-chat-messages" style="flex:1;overflow-y:auto;padding:15px;font-size:14px;background:var(--ai-chat-bg);"></div>

                <div style="border-top:1px solid var(--ai-chat-border);background:var(--ai-chat-bg);">
                    <div id="odoo-ai-chat-image-status" style="display:none;padding:6px 10px;border-bottom:1px solid var(--ai-chat-border);font-size:12px;opacity:0.7;background:rgba(0,0,0,0.2);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;"></div>

                    <div id="odoo-ai-chat-category-row" style="display:none;padding:10px;border-bottom:1px solid var(--ai-chat-border);background:rgba(0,0,0,0.1);">
                        <label id="odoo-ai-chat-category-label" for="odoo-ai-chat-category-select" style="display:block;font-size:11px;opacity:0.6;margin-bottom:6px;">Categoría del producto</label>
                        <select id="odoo-ai-chat-category-select" style="width:100%;border:1px solid var(--ai-chat-border);border-radius:6px;padding:8px;background:var(--ai-chat-input-bg);color:var(--ai-chat-text);font-size:13px;outline:none;">
                            <option value="">Sin categoría / omitir</option>
                        </select>
                        <div id="odoo-ai-chat-sale-category-multi" style="display:none;margin-top:8px;">
                            <button id="odoo-ai-chat-sale-category-toggle" type="button" style="width:100%;border:1px solid var(--ai-chat-border);border-radius:6px;padding:8px;background:var(--ai-chat-input-bg);color:var(--ai-chat-text);font-size:13px;text-align:left;cursor:pointer;outline:none;">Selecciona una o varias categorías</button>
                            <div id="odoo-ai-chat-sale-category-panel" style="display:none;margin-top:6px;max-height:none;overflow-y:visible;border:1px solid var(--ai-chat-border);border-radius:6px;background:var(--ai-chat-input-bg);padding:6px;"></div>
                            <input id="odoo-ai-chat-sale-category-search" type="text" placeholder="Buscar categoría de ventas..." style="display:none;margin-top:6px;width:100%;box-sizing:border-box;border:1px solid var(--ai-chat-border);border-radius:6px;padding:8px;background:var(--ai-chat-input-bg);color:var(--ai-chat-text);font-size:13px;outline:none;">
                        </div>
                    </div>

                    <div id="odoo-ai-chat-order-partner-row" style="display:none;padding:10px;border-bottom:1px solid var(--ai-chat-border);background:rgba(0,0,0,0.1);">
                        <label id="odoo-ai-chat-order-partner-label" for="odoo-ai-chat-order-partner-search" style="display:block;font-size:11px;opacity:0.6;margin-bottom:6px;">Selecciona clientes/proveedores</label>
                        <input id="odoo-ai-chat-order-partner-search" type="text" placeholder="Buscar..." style="width:100%;box-sizing:border-box;border:1px solid var(--ai-chat-border);border-radius:6px;padding:8px;background:var(--ai-chat-input-bg);color:var(--ai-chat-text);font-size:13px;outline:none;margin-bottom:6px;">
                        <div id="odoo-ai-chat-order-partner-panel" style="max-height:140px;overflow-y:auto;border:1px solid var(--ai-chat-border);border-radius:6px;background:var(--ai-chat-input-bg);padding:6px;margin-bottom:6px;"></div>
                        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap;">
                            <button id="odoo-ai-chat-order-create" type="button" style="border:none;background:var(--ai-chat-accent);color:#fff;padding:7px 12px;border-radius:6px;cursor:pointer;font-size:13px;font-weight:bold;">Crear</button>
                            <button id="odoo-ai-chat-order-cancel" type="button" style="border:1px solid var(--ai-chat-border);background:var(--ai-chat-input-bg);color:var(--ai-chat-text);padding:7px 12px;border-radius:6px;cursor:pointer;font-size:13px;">Cancelar</button>
                            <span id="odoo-ai-chat-order-partner-summary" style="font-size:12px;opacity:0.7;"></span>
                        </div>
                    </div>

                    <div style="display:flex;padding:15px;background:var(--ai-chat-bg);gap:8px;align-items:center;">
                        <input id="odoo-ai-chat-file" type="file" accept="image/jpeg,image/png,image/gif,image/webp,.jpg,.jpeg,.png,.gif,.webp" style="display:none;">
                        <button id="odoo-ai-chat-image" title="Adjuntar imagen del producto" style="display:none;border:none;background:var(--ai-chat-input-bg);color:var(--ai-chat-text);padding:8px 12px;border-radius:6px;cursor:pointer;white-space:nowrap;">📎</button>
                        <div style="flex:1;display:flex;background:var(--ai-chat-input-bg);border-radius:25px;padding:2px 15px;align-items:center;border:1px solid var(--ai-chat-border);">
                            <input id="odoo-ai-chat-input" type="text" placeholder="Escribe tu mensaje..." style="flex:1;border:none;padding:10px 0;outline:none;font-size:14px;background:transparent;color:var(--ai-chat-text);min-width:0;">
                            <button id="odoo-ai-chat-send" style="border:none;background:transparent;color:var(--ai-chat-accent);padding:0;cursor:pointer;font-size:18px;font-weight:bold;margin-left:10px;">➔</button>
                        </div>
                    </div>
                    <div style="padding-bottom:10px;text-align:center;">
                        <p style="font-size:9px;opacity:0.4;margin:0;">Chatbot IA - OPTIMA Style</p>
                    </div>
                </div>
            </div>
            <button id="odoo-ai-chat-open" style="display:block;position:fixed;right:25px;bottom:25px;background:var(--ai-chat-bg);color:var(--ai-chat-text);border:1px solid var(--ai-chat-border);border-radius:50%;width:60px;height:60px;box-shadow:0 6px 20px rgba(0,0,0,.4);cursor:pointer;z-index:2147483000;font-weight:bold;font-size:16px;">IA</button>
        `;

        document.body.appendChild(wrapper);

        var box = document.getElementById("odoo-ai-chat-box");
        var openButton = document.getElementById("odoo-ai-chat-open");
        var closeButton = document.getElementById("odoo-ai-chat-close");
        var headerExtraButton = document.getElementById("odoo-ai-chat-header-extra");
        var messages = document.getElementById("odoo-ai-chat-messages");
        var input = document.getElementById("odoo-ai-chat-input");
        var sendButton = document.getElementById("odoo-ai-chat-send");
        var imageButton = document.getElementById("odoo-ai-chat-image");
        var imageInput = document.getElementById("odoo-ai-chat-file");
        var imageStatus = document.getElementById("odoo-ai-chat-image-status");
        var categoryRow = document.getElementById("odoo-ai-chat-category-row");
        var categoryLabel = document.getElementById("odoo-ai-chat-category-label");
        var categorySelect = document.getElementById("odoo-ai-chat-category-select");
        var saleCategoryMulti = document.getElementById("odoo-ai-chat-sale-category-multi");
        var saleCategoryToggle = document.getElementById("odoo-ai-chat-sale-category-toggle");
        var saleCategoryPanel = document.getElementById("odoo-ai-chat-sale-category-panel");
        var saleCategorySearch = document.getElementById("odoo-ai-chat-sale-category-search");
        var orderPartnerRow = document.getElementById("odoo-ai-chat-order-partner-row");
        var orderPartnerLabel = document.getElementById("odoo-ai-chat-order-partner-label");
        var orderPartnerSearch = document.getElementById("odoo-ai-chat-order-partner-search");
        var orderPartnerPanel = document.getElementById("odoo-ai-chat-order-partner-panel");
        var orderCreateButton = document.getElementById("odoo-ai-chat-order-create");
        var orderCancelButton = document.getElementById("odoo-ai-chat-order-cancel");
        var orderPartnerSummary = document.getElementById("odoo-ai-chat-order-partner-summary");
        var selectedImageAttachment = null;
        var selectedImageFile = null;
        var imageModeActive = false;
        var categoryModeActive = false;
        var categoryModeKind = "product";
        var categoryOptionsLoadedByKind = {};
        var categoryOptionsLoadingByKind = {};
        var categoryOptionsByKind = {};
        var saleCategorySelectedById = {};
        var pendingAdminOrderCreate = false;
        var pendingAdminOrderHistory = false;
        var pendingAdminOrderKind = "sale";
        var orderPartnerOptionsByKind = {};
        var orderPartnerOptionsLoadingByKind = {};
        var orderPartnerSelectedById = {};
        var isSending = false;

        // Escapa texto para usarlo dentro de atributos HTML.
        function escapeAttribute(text) {
            return escapeHtml(text).replace(/"/g, "&quot;");
        }

        // Devuelve las categorías seleccionadas en el desplegable actual.
        function selectedCategoryIds() {
            if (categoryModeKind === "sale") {
                return Object.keys(saleCategorySelectedById).filter(function (id) {
                    return Boolean(saleCategorySelectedById[id]);
                });
            }
            if (!categorySelect || !categorySelect.value) {
                return [];
            }
            return [String(categorySelect.value || "")];
        }

        // Devuelve el texto visible de las categorías seleccionadas.
        function selectedCategoryLabel() {
            if (categoryModeKind === "sale") {
                return selectedCategoryIds().map(function (id) {
                    return saleCategorySelectedById[id] || "Categoría " + id;
                }).filter(Boolean).join(", ");
            }
            if (!categorySelect || !categorySelect.value) {
                return "";
            }
            var option = categorySelect.options[categorySelect.selectedIndex];
            return option ? option.textContent : "";
        }

        // Actualiza el botón/resumen de categorías de ventas seleccionadas.
        function updateSaleCategoryToggleText() {
            if (!saleCategoryToggle) {
                return;
            }
            var labels = selectedCategoryLabel();
            saleCategoryToggle.textContent = labels || "Selecciona una o varias categorías";
            saleCategoryToggle.title = labels || "Selecciona una o varias categorías";
        }

        // Limpia selección y búsqueda de categorías.
        function clearCategorySelection() {
            if (categorySelect) {
                categorySelect.value = "";
            }
            saleCategorySelectedById = {};
            if (saleCategorySearch) {
                saleCategorySearch.value = "";
            }
            if (saleCategoryPanel) {
                var checked = saleCategoryPanel.querySelectorAll('input[data-category-id]:checked');
                Array.prototype.forEach.call(checked, function (checkbox) {
                    checkbox.checked = false;
                });
            }
            updateSaleCategoryToggleText();
        }

        // Comprueba si el campo actual espera una categoría.
        function isCategoryAwaitingKey(key) {
            return key === "categ_id" || key === "public_categ_ids";
        }

        // Traduce el campo pendiente a tipo de categoría interna o ventas.
        function categoryKindForAwaiting(key) {
            return key === "public_categ_ids" ? "sale" : "product";
        }

        // Devuelve la etiqueta visible del tipo de categoría.
        function categoryLabelForKind(kind) {
            return kind === "sale" ? "Categorías de ventas" : "Categoría del producto";
        }

        // Devuelve el texto de opción vacía para categorías.
        function categoryEmptyLabelForKind(kind) {
            return kind === "sale" ? "Sin categorías de ventas / omitir" : "Sin categoría / omitir";
        }

        // Genera el prefijo que el backend entiende para categorías seleccionadas.
        function categoryPrefixForAwaiting(key) {
            return key === "public_categ_ids" ? "categoria_ventas_ids:" : "categoria_id:";
        }

        // Renderiza el selector de categorías internas o de ventas.
        function renderProductCategories(kind, categories) {
            if (!categorySelect) {
                return;
            }
            kind = kind === "sale" ? "sale" : "product";
            categories = categories || [];

            if (kind === "sale") {
                categorySelect.style.display = "none";
                if (saleCategoryMulti) {
                    saleCategoryMulti.style.display = "";
                }
                if (saleCategorySearch) {
                    saleCategorySearch.style.display = "";
                }
                if (saleCategoryPanel) {
                    saleCategoryPanel.style.display = "block";
                    saleCategoryPanel.innerHTML = "";
                    var searchText = saleCategorySearch ? (saleCategorySearch.value || "").trim().toLowerCase() : "";
                    var filteredCategories = categories.filter(function (category) {
                        if (!category || !category.id) {
                            return false;
                        }
                        if (!searchText) {
                            return true;
                        }
                        var categoryName = String(category.name || ("Categoría " + category.id)).toLowerCase();
                        return categoryName.indexOf(searchText) !== -1;
                    });
                    if (!categories.length) {
                        var empty = document.createElement("div");
                        empty.style.fontSize = "12px";
                        empty.style.color = "#777";
                        empty.textContent = "No hay categorías de ventas creadas.";
                        saleCategoryPanel.appendChild(empty);
                    } else if (!filteredCategories.length) {
                        var noResults = document.createElement("div");
                        noResults.style.fontSize = "12px";
                        noResults.style.color = "#777";
                        noResults.textContent = "No se encontraron categorías con esa búsqueda.";
                        saleCategoryPanel.appendChild(noResults);
                    }
                    filteredCategories.slice(0, 6).forEach(function (category) {
                        var categoryId = String(category.id);
                        var categoryName = category.name || ("Categoría " + category.id);
                        var label = document.createElement("label");
                        label.style.display = "flex";
                        label.style.gap = "6px";
                        label.style.alignItems = "flex-start";
                        label.style.padding = "4px 2px";
                        label.style.cursor = "pointer";
                        label.style.fontSize = "13px";
                        label.style.minHeight = "24px";
                        var checkbox = document.createElement("input");
                        checkbox.type = "checkbox";
                        checkbox.value = categoryId;
                        checkbox.checked = Boolean(saleCategorySelectedById[categoryId]);
                        checkbox.setAttribute("data-category-id", categoryId);
                        checkbox.setAttribute("data-category-name", categoryName);
                        checkbox.style.marginTop = "2px";
                        var span = document.createElement("span");
                        span.textContent = categoryName;
                        label.appendChild(checkbox);
                        label.appendChild(span);
                        saleCategoryPanel.appendChild(label);
                    });
                }
                updateSaleCategoryToggleText();
                return;
            }

            if (saleCategoryMulti) {
                saleCategoryMulti.style.display = "none";
            }
            if (saleCategoryPanel) {
                saleCategoryPanel.style.display = "none";
            }
            if (saleCategorySearch) {
                saleCategorySearch.style.display = "none";
            }
            categorySelect.style.display = "";
            categorySelect.innerHTML = '<option value="">' + categoryEmptyLabelForKind(kind) + '</option>';
            (categories || []).forEach(function (category) {
                if (!category || !category.id) {
                    return;
                }
                var option = document.createElement("option");
                option.value = String(category.id);
                option.textContent = category.name || ("Categoría " + category.id);
                categorySelect.appendChild(option);
            });
        }

        // Carga categorías desde Odoo bajo demanda.
        async function loadProductCategories(kind) {
            kind = kind === "sale" ? "sale" : "product";
            if (!categorySelect || categoryOptionsLoadingByKind[kind]) {
                return;
            }
            if (categoryOptionsLoadedByKind[kind]) {
                renderProductCategories(kind, categoryOptionsByKind[kind] || []);
                return;
            }
            categoryOptionsLoadingByKind[kind] = true;
            if (kind === "sale") {
                categorySelect.style.display = "none";
                if (saleCategoryMulti) {
                    saleCategoryMulti.style.display = "";
                }
                if (saleCategoryPanel) {
                    saleCategoryPanel.style.display = "block";
                    saleCategoryPanel.innerHTML = '<div style="font-size:12px;color:#777;">Cargando categorías...</div>';
                }
                if (saleCategorySearch) {
                    saleCategorySearch.style.display = "";
                }
                updateSaleCategoryToggleText();
            } else {
                categorySelect.style.display = "";
                categorySelect.innerHTML = '<option value="">Cargando categorías...</option>';
            }
            try {
                var response = await fetch("/ai/product/categories", {
                    method: "POST",
                    headers: {"Content-Type": "application/json"},
                    body: JSON.stringify({sessionId: getSessionId(), kind: kind}),
                    credentials: "same-origin"
                });
                var data = await readResponse(response);
                var categories = (data && data.categories) || [];
                if (!response.ok) {
                    throw new Error((data && (data.reply || data.error)) || "No se pudieron cargar las categorías.");
                }
                categoryOptionsByKind[kind] = categories;
                categoryOptionsLoadedByKind[kind] = true;
                renderProductCategories(kind, categories);
            } catch (error) {
                console.error("[odoo_ai_chat] Error cargando categorías", error);
                if (kind === "sale" && saleCategoryPanel) {
                    saleCategoryPanel.innerHTML = '<div style="font-size:12px;color:#b00020;">No se pudieron cargar las categorías</div>';
                } else {
                    categorySelect.innerHTML = '<option value="">No se pudieron cargar las categorías</option>';
                }
            } finally {
                categoryOptionsLoadingByKind[kind] = false;
            }
        }

        // Muestra u oculta los controles de categoría según el campo actual.
        function updateCategoryDropdownVisibility() {
            if (!categoryRow) {
                return;
            }
            var awaitingKind = categoryKindForAwaiting(pendingAdminProductCreateAwaiting);
            var activeKind = categoryModeActive ? categoryModeKind : awaitingKind;
            var show = Boolean(categoryModeActive || (pendingAdminProductCreate && isCategoryAwaitingKey(pendingAdminProductCreateAwaiting)));
            categoryRow.style.display = show ? "" : "none";
            if (show) {
                categoryModeKind = activeKind === "sale" ? "sale" : "product";
                if (categoryLabel) {
                    categoryLabel.textContent = categoryLabelForKind(categoryModeKind);
                }
                loadProductCategories(categoryModeKind);
            } else {
                clearCategorySelection();
                if (saleCategoryMulti) {
                    saleCategoryMulti.style.display = "none";
                }
                if (saleCategoryPanel) {
                    saleCategoryPanel.style.display = "none";
                }
                if (saleCategorySearch) {
                    saleCategorySearch.style.display = "none";
                }
                if (categorySelect) {
                    categorySelect.style.display = "";
                }
            }
        }

        // Activa el modo de selección de categoría.
        function activateProductCategoryMode(kind) {
            categoryModeActive = true;
            categoryModeKind = kind === "sale" ? "sale" : "product";
            updateCategoryDropdownVisibility();
        }

        // Desactiva el modo de selección de categoría.
        function deactivateProductCategoryMode() {
            categoryModeActive = false;
            updateCategoryDropdownVisibility();
        }

        // Muestra u oculta el botón de imagen según el contexto.
        function updateImageButtonVisibility() {
            if (!imageButton) {
                return;
            }
            var show = Boolean(
                imageModeActive ||
                selectedImageAttachment ||
                (pendingAdminProductCreate && pendingAdminProductCreateAwaiting === "image") ||
                isProductImagePrompt(input && input.value)
            );
            imageButton.style.display = show ? "" : "none";
            if (!show && imageStatus && !selectedImageAttachment) {
                imageStatus.style.display = "none";
                imageStatus.textContent = "";
            }
        }

        // Activa el modo de adjuntar imagen de producto.
        function activateProductImageMode(statusText) {
            imageModeActive = true;
            updateImageButtonVisibility();
            if (statusText) {
                updateImageStatus(statusText);
            }
        }

        // Desactiva el modo de adjuntar imagen.
        function deactivateProductImageMode() {
            imageModeActive = false;
            updateImageButtonVisibility();
        }

        // Actualiza el texto de estado de la imagen seleccionada.
        function updateImageStatus(text, isError) {
            if (!imageStatus) {
                return;
            }
            if (!text) {
                imageStatus.style.display = "none";
                imageStatus.textContent = "";
                return;
            }
            imageStatus.style.display = "block";
            imageStatus.style.color = isError ? "#b00020" : "#555";
            imageStatus.textContent = text;
        }

        // Limpia la imagen seleccionada en el widget.
        function clearSelectedImage() {
            selectedImageAttachment = null;
            selectedImageFile = null;
            if (imageInput) {
                imageInput.value = "";
            }
            updateImageStatus("");
            updateImageButtonVisibility();
        }

        // Devuelve los ids de clientes/proveedores seleccionados para pedidos.
        function selectedOrderPartnerIds() {
            return Object.keys(orderPartnerSelectedById).filter(function (id) {
                return Boolean(orderPartnerSelectedById[id]);
            });
        }

        // Devuelve las etiquetas visibles de los partners seleccionados.
        function selectedOrderPartnerLabels() {
            return selectedOrderPartnerIds().map(function (id) {
                return orderPartnerSelectedById[id] || ("Contacto " + id);
            });
        }

        // Actualiza el resumen del selector de pedidos.
        function updateOrderPartnerSummary() {
            if (!orderPartnerSummary) {
                return;
            }
            var count = selectedOrderPartnerIds().length;
            orderPartnerSummary.textContent = count ? (count + " seleccionado" + (count === 1 ? "" : "s")) : "Ninguno seleccionado";
        }

        // Pinta el panel de clientes/proveedores con filtro local.
        function renderOrderPartners() {
            if (!orderPartnerPanel) {
                return;
            }
            var kind = pendingAdminOrderKind === "purchase" ? "purchase" : "sale";
            var optionKey = pendingAdminOrderHistory ? ("history_" + kind) : kind;
            var options = orderPartnerOptionsByKind[optionKey] || orderPartnerOptionsByKind[kind] || [];
            var searchText = orderPartnerSearch ? normalizeIntentText(orderPartnerSearch.value || "") : "";
            orderPartnerPanel.innerHTML = "";
            var filtered = options.filter(function (partner) {
                if (!partner || !partner.id) {
                    return false;
                }
                if (!searchText) {
                    return true;
                }
                return normalizeIntentText((partner.label || partner.name || "") + " " + (partner.email || "") + " " + (partner.phone || "")).indexOf(searchText) !== -1;
            });

            if (!options.length) {
                var empty = document.createElement("div");
                empty.style.fontSize = "12px";
                empty.style.color = "#777";
                empty.textContent = pendingAdminOrderHistory ? (kind === "purchase" ? "No hay proveedores disponibles." : "No hay clientes disponibles.") : (kind === "purchase" ? "No hay proveedores disponibles." : "No hay clientes disponibles.");
                orderPartnerPanel.appendChild(empty);
                updateOrderPartnerSummary();
                return;
            }
            if (!filtered.length) {
                var noResults = document.createElement("div");
                noResults.style.fontSize = "12px";
                noResults.style.color = "#777";
                noResults.textContent = "No se encontraron contactos con esa búsqueda.";
                orderPartnerPanel.appendChild(noResults);
                updateOrderPartnerSummary();
                return;
            }

            filtered.slice(0, 6).forEach(function (partner) {
                var id = String(partner.id);
                var labelText = partner.label || partner.name || ("Contacto " + id);
                var label = document.createElement("label");
                label.style.display = "flex";
                label.style.gap = "6px";
                label.style.alignItems = "flex-start";
                label.style.padding = "4px 2px";
                label.style.cursor = "pointer";
                label.style.fontSize = "13px";
                var checkbox = document.createElement("input");
                checkbox.type = pendingAdminOrderHistory ? "radio" : "checkbox";
                checkbox.name = pendingAdminOrderHistory ? "odoo-ai-chat-history-partner" : "";
                checkbox.value = id;
                checkbox.checked = Boolean(orderPartnerSelectedById[id]);
                checkbox.setAttribute("data-order-partner-id", id);
                checkbox.setAttribute("data-order-partner-name", partner.name || labelText);
                checkbox.style.marginTop = "2px";
                var span = document.createElement("span");
                span.textContent = labelText;
                label.appendChild(checkbox);
                label.appendChild(span);
                orderPartnerPanel.appendChild(label);
            });
            updateOrderPartnerSummary();
        }

        // Carga clientes/proveedores para el selector de pedidos.
        async function loadOrderPartners(kind) {
            kind = kind === "purchase" ? "purchase" : "sale";
            var optionKey = pendingAdminOrderHistory ? ("history_" + kind) : kind;
            if (!orderPartnerPanel || orderPartnerOptionsLoadingByKind[optionKey]) {
                return;
            }
            if (orderPartnerOptionsByKind[optionKey]) {
                renderOrderPartners();
                return;
            }
            orderPartnerOptionsLoadingByKind[optionKey] = true;
            orderPartnerPanel.innerHTML = '<div style="font-size:12px;color:#777;">Cargando contactos...</div>';
            try {
                var result = await postJson("/ai/order/partners", {
                    kind: kind,
                    mode: pendingAdminOrderHistory ? "history" : "create",
                    sessionId: getSessionId()
                });
                if (!result.response.ok) {
                    throw new Error((result.data && (result.data.reply || result.data.error)) || "No se pudieron cargar los contactos.");
                }
                orderPartnerOptionsByKind[optionKey] = (result.data && result.data.partners) || [];
                renderOrderPartners();
            } catch (error) {
                console.error("[odoo_ai_chat] Error cargando clientes/proveedores", error);
                orderPartnerPanel.innerHTML = '<div style="font-size:12px;color:#b00020;">No se pudieron cargar los contactos</div>';
            } finally {
                orderPartnerOptionsLoadingByKind[optionKey] = false;
            }
        }

        // Activa el selector de pedido para admin.
        function activateAdminOrderPartnerMode(selection) {
            selection = selection || {};
            pendingAdminOrderCreate = true;
            pendingAdminOrderHistory = false;
            pendingAdminOrderKind = selection.kind === "purchase" ? "purchase" : "sale";
            orderPartnerSelectedById = {};
            if (orderPartnerRow) {
                orderPartnerRow.style.display = "";
            }
            if (orderPartnerLabel) {
                orderPartnerLabel.textContent = pendingAdminOrderKind === "purchase" ? "Proveedores del pedido de compra" : "Clientes del pedido de venta";
            }
            if (orderPartnerSearch) {
                orderPartnerSearch.value = "";
                orderPartnerSearch.placeholder = pendingAdminOrderKind === "purchase" ? "Buscar proveedor..." : "Buscar cliente...";
            }
            if (orderCreateButton) {
                orderCreateButton.textContent = pendingAdminOrderKind === "purchase" ? "Crear pedido de compra" : "Crear pedido de venta";
            }
            updateOrderPartnerSummary();
            loadOrderPartners(pendingAdminOrderKind);
        }

        // Activa el selector de clientes/proveedores para que admin abra el historial de ventas o compras.
        function activateAdminOrderHistoryPartnerMode(kind) {
            pendingAdminOrderCreate = false;
            pendingAdminOrderHistory = true;
            pendingAdminOrderKind = kind === "purchase" ? "purchase" : "sale";
            orderPartnerSelectedById = {};
            if (orderPartnerRow) {
                orderPartnerRow.style.display = "";
            }
            if (orderPartnerLabel) {
                orderPartnerLabel.textContent = pendingAdminOrderKind === "purchase" ? "Proveedores del historial de pedidos de compra" : "Clientes del historial de pedidos de venta";
            }
            if (orderPartnerSearch) {
                orderPartnerSearch.value = "";
                orderPartnerSearch.placeholder = pendingAdminOrderKind === "purchase" ? "Buscar proveedor..." : "Buscar cliente...";
            }
            if (orderCreateButton) {
                orderCreateButton.textContent = pendingAdminOrderKind === "purchase" ? "Ver historial de pedidos" : "Ver historial de pedidos";
            }
            updateOrderPartnerSummary();
            loadOrderPartners(pendingAdminOrderKind);
        }

        // Desactiva el selector de pedido/historial.
        function deactivateAdminOrderPartnerMode() {
            pendingAdminOrderCreate = false;
            pendingAdminOrderHistory = false;
            orderPartnerSelectedById = {};
            if (orderPartnerRow) {
                orderPartnerRow.style.display = "none";
            }
            if (orderPartnerSearch) {
                orderPartnerSearch.value = "";
            }
            updateOrderPartnerSummary();
        }

        // Sincroniza el selector de pedido según la respuesta del backend.
        updateAdminOrderCreatePending = function (data) {
            if (!data) {
                return;
            }
            if (data.clearPendingAdminOrderCreate || data.ordersCreated) {
                deactivateAdminOrderPartnerMode();
            }
            if (data.pendingAdminOrderCreate && data.orderPartnerSelection) {
                deactivateProductCategoryMode();
                deactivateProductImageMode();
                activateAdminOrderPartnerMode(data.orderPartnerSelection);
            }
            if (data.pendingAdminOrderHistory) {
                deactivateProductCategoryMode();
                deactivateProductImageMode();
                activateAdminOrderHistoryPartnerMode(data.orderPartnerSelection && data.orderPartnerSelection.kind);
            }
        };

        var welcomeMessage = addMessage(messages, "IA", "Hola, soy tu asistente. ¿En qué puedo ayudarte?");

        // Personaliza el saludo inicial para clientes conectados.
        // Si no hay sesión de cliente, o si es admin, mantiene el saludo estándar.
        postJson("/ai/customer/greeting_v24", {
            sessionId: getSessionId(),
            pageUrl: window.location.href,
            pageTitle: document.title
        }).then(function (result) {
            var data = result && result.data ? result.data : {};
            if (result.response && result.response.ok && data.showGuestActions) {
                var guestReply = String(data.reply || "Hola, soy tu asistente. ¿En qué puedo ayudarte?").trim();
                setMessage(welcomeMessage, "IA", guestReply, false, data.actionButtons || guestAuthButtons());
                return;
            }
            if (result.response && result.response.ok && data.showPersonalGreeting) {
                lastInitialCustomerGreetingData = data || {};
                var greetingReply = buildCustomerGreetingReply(data);
                if (!greetingReply || isGenericOperationReply(greetingReply)) {
                    var safeName = String((data && (data.customerName || data.partnerName || data.name)) || "cliente").trim() || "cliente";
                    var safeLastOrder = String((data && data.lastOrderName) || "").trim();
                    greetingReply = "Hola, " + safeName + ". ¿En qué puedo ayudarte?" + (safeLastOrder ? "\nTu último pedido es: " + safeLastOrder : "");
                }
                setMessage(welcomeMessage, "IA", greetingReply, false, customerGreetingButtonsFromData(data));
            }
        }).catch(function () {
            // El saludo automático no debe bloquear ni alterar el chat si falla.
        });

        closeButton.addEventListener("click", function () {
            box.style.display = "none";
            openButton.style.display = "block";
        });

        if (headerExtraButton) {
            headerExtraButton.addEventListener("click", function () {
                showAccountCapabilities(messages);
            });
        }

        openButton.addEventListener("click", function () {
            box.style.display = "flex";
            openButton.style.display = "none";
        });

        imageButton.addEventListener("click", function () {
            if (imageButton.style.display === "none") {
                return;
            }
            imageInput.click();
        });

        imageInput.addEventListener("change", async function () {
            var file = imageInput.files && imageInput.files[0];
            if (!file) {
                clearSelectedImage();
                return;
            }
            try {
                selectedImageAttachment = await readFileAsProductImageAttachment(file);
                selectedImageFile = file;
                updateImageButtonVisibility();
                updateImageStatus("Imagen adjunta para el siguiente mensaje: " + selectedImageAttachment.filename);
            } catch (error) {
                selectedImageAttachment = null;
                selectedImageFile = null;
                imageInput.value = "";
                updateImageButtonVisibility();
                updateImageStatus(error.message || "Imagen no válida.", true);
            }
        });

        if (saleCategoryToggle) {
            saleCategoryToggle.addEventListener("click", function () {
                if (!saleCategoryPanel || !saleCategoryMulti || saleCategoryMulti.style.display === "none") {
                    return;
                }
                saleCategoryPanel.style.display = saleCategoryPanel.style.display === "none" ? "block" : "none";
            });
        }

        if (saleCategoryPanel) {
            saleCategoryPanel.addEventListener("change", function (event) {
                var target = event.target;
                if (target && target.matches && target.matches('input[data-category-id]')) {
                    var id = String(target.getAttribute("data-category-id") || target.value || "");
                    var name = target.getAttribute("data-category-name") || ("Categoría " + id);
                    if (id) {
                        if (target.checked) {
                            saleCategorySelectedById[id] = name;
                        } else {
                            delete saleCategorySelectedById[id];
                        }
                    }
                }
                updateSaleCategoryToggleText();
            });
        }

        if (saleCategorySearch) {
            saleCategorySearch.addEventListener("input", function () {
                renderProductCategories("sale", categoryOptionsByKind.sale || []);
            });
            saleCategorySearch.addEventListener("keydown", function (event) {
                event.stopPropagation();
            });
        }

        if (orderPartnerPanel) {
            orderPartnerPanel.addEventListener("change", function (event) {
                var target = event.target;
                if (target && target.matches && target.matches('input[data-order-partner-id]')) {
                    var id = String(target.getAttribute("data-order-partner-id") || target.value || "");
                    var name = target.getAttribute("data-order-partner-name") || ("Contacto " + id);
                    if (id) {
                        if (target.checked) {
                            if (pendingAdminOrderHistory) {
                                orderPartnerSelectedById = {};
                            }
                            orderPartnerSelectedById[id] = name;
                        } else {
                            delete orderPartnerSelectedById[id];
                        }
                    }
                    updateOrderPartnerSummary();
                }
            });
        }

        if (orderPartnerSearch) {
            orderPartnerSearch.addEventListener("input", renderOrderPartners);
            orderPartnerSearch.addEventListener("keydown", function (event) {
                event.stopPropagation();
            });
        }

        if (orderCancelButton) {
            orderCancelButton.addEventListener("click", function () {
                var wasHistoryMode = pendingAdminOrderHistory;
                deactivateAdminOrderPartnerMode();
                addMessage(messages, "IA", wasHistoryMode ? "Perfecto, cancelo la consulta del historial." : "Perfecto, cancelo la creación del pedido.");
            });
        }

        // Ejecuta la selección actual del panel de clientes/proveedores.
        // Para historiales, solo consulta y muestra botones; no abre la vista automáticamente.
        async function submitAdminOrderPartnerSelection() {
            if (isSending || (!pendingAdminOrderCreate && !pendingAdminOrderHistory)) {
                return false;
            }
            var partnerIds = selectedOrderPartnerIds();
            if (!partnerIds.length) {
                updateOrderPartnerSummary();
                addMessage(messages, "IA", pendingAdminOrderHistory ? (pendingAdminOrderKind === "purchase" ? "Selecciona un proveedor." : "Selecciona un cliente.") : (pendingAdminOrderKind === "purchase" ? "Selecciona al menos un proveedor." : "Selecciona al menos un cliente."), true);
                return true;
            }
            var labels = selectedOrderPartnerLabels();
            var wasHistorySelection = Boolean(pendingAdminOrderHistory);
            addMessage(messages, "Tú", wasHistorySelection ? ((pendingAdminOrderKind === "purchase" ? "Ver historial de pedidos de compra de " : "Ver historial de pedidos de venta de ") + labels.join(", ")) : ((pendingAdminOrderKind === "purchase" ? "Crear pedido de compra para " : "Crear pedido de venta para ") + labels.join(", ")));
            isSending = true;
            if (orderCreateButton) {
                orderCreateButton.disabled = true;
            }
            sendButton.disabled = true;
            sendButton.textContent = "...";
            var waitingMessage = addMessage(messages, "IA", wasHistorySelection ? (pendingAdminOrderKind === "purchase" ? "Consultando historial de compras..." : "Consultando historial de ventas...") : "Creando pedido en Odoo...");
            try {
                var result;
                if (wasHistorySelection) {
                    result = await postJson("/ai/admin/orders/history", {
                        kind: pendingAdminOrderKind,
                        partnerId: partnerIds[0],
                        sessionId: getSessionId(),
                        pageUrl: window.location.href,
                        pageTitle: document.title
                    });
                    deactivateAdminOrderPartnerMode();
                } else {
                    result = await postJson("/ai/order/create", {
                        kind: pendingAdminOrderKind,
                        partnerIds: partnerIds,
                        sessionId: getSessionId()
                    });
                    updateAdminOrderCreatePending(result.data);
                }
                var isError = !result.response.ok || (result.data && result.data.success === false);
                setMessage(
                    waitingMessage,
                    isError ? "Error" : "IA",
                    (result.data && result.data.reply) || (isError ? (wasHistorySelection ? "No he podido consultar el historial." : "No he podido crear el pedido.") : (wasHistorySelection ? "Historial localizado." : "Pedido creado.")),
                    isError,
                    actionButtonsFromData(result.data)
                );
            } catch (error) {
                console.error("[odoo_ai_chat] Error en selector de pedidos/historial", error);
                setMessage(waitingMessage, "Error", error.message || "No he podido completar la acción.", true);
            } finally {
                isSending = false;
                if (orderCreateButton) {
                    orderCreateButton.disabled = false;
                }
                sendButton.disabled = false;
                sendButton.textContent = "Enviar";
                input.focus();
            }
            return true;
        }

        if (orderCreateButton) {
            orderCreateButton.addEventListener("click", function () {
                submitAdminOrderPartnerSelection();
            });
        }

        input.addEventListener("input", updateImageButtonVisibility);
        updateImageButtonVisibility();
        updateCategoryDropdownVisibility();

        // Envía mensajes al backend y evita dobles envíos o datos incompletos.
        async function sendMessage() {
            if (isSending) {
                return;
            }
            var text = input.value.trim();
            var selectedCategoryIdsList = selectedCategoryIds();
            var selectedCategoryName = selectedCategoryLabel();
            var categoryAwaitingKey = pendingAdminProductCreateAwaiting;
            var categorySelectionActive = Boolean(pendingAdminProductCreate && isCategoryAwaitingKey(categoryAwaitingKey) && selectedCategoryIdsList.length);
            var allowEmptyForAdminProduct = Boolean(
                pendingAdminProductCreate ||
                selectedImageAttachment ||
                imageModeActive ||
                pendingCart ||
                (pendingAdminOrderHistory && selectedOrderPartnerIds().length)
            );
            if (!text && !allowEmptyForAdminProduct) {
                return;
            }

            var productImageRequested = isProductImagePrompt(text) ||
                imageModeActive ||
                (pendingAdminProductCreate && pendingAdminProductCreateAwaiting === "image");

            var sentAdminProductCreateKey = pendingAdminProductCreate ? pendingAdminProductCreateAwaiting : null;
            var messageForServer = text;
            if (categorySelectionActive) {
                messageForServer = categoryPrefixForAwaiting(categoryAwaitingKey) + selectedCategoryIdsList.join(",");
            }
            if (!messageForServer && pendingCart && !pendingAdminProductCreate && !selectedImageAttachment && !categorySelectionActive) {
                // Si el usuario pulsa Enviar sin escribir cantidad cuando hay un carrito pendiente,
                // lo interpretamos como cancelar la operación pendiente, no como un mensaje vacío.
                messageForServer = "cancelar";
            }
            if (!messageForServer && pendingAdminProductCreate && selectedImageAttachment) {
                messageForServer = "[imagen adjunta]";
            } else if (!messageForServer && pendingAdminProductCreate && sentAdminProductCreateKey) {
                // Evita que un Enter vacío se pierda si la sesión de Odoo llega desincronizada.
                // El backend lo interpreta como omitir el campo opcional actual.
                messageForServer = "[sin dato]";
            }
            var sentAdminProductCreateValue = categorySelectionActive ? selectedCategoryIdsList.join(",") : text;
            var adminProductCreateClientAnswers = Object.assign({}, pendingAdminProductCreateClientAnswers || {});
            if (pendingAdminProductCreate && sentAdminProductCreateKey) {
                adminProductCreateClientAnswers[sentAdminProductCreateKey] = sentAdminProductCreateValue || "";
            }
            var sendContext = {
                wasPendingProductCreate: Boolean(pendingAdminProductCreate || productImageRequested),
                adminProductCreateClientAnswers: Object.assign({}, adminProductCreateClientAnswers || {}),
                originalMessage: messageForServer || text,
                cartQuantity: text
            };

            if (pendingAdminOrderCreate && text) {
                deactivateAdminOrderPartnerMode();
            }

            if (pendingAdminOrderHistory && selectedOrderPartnerIds().length && !text) {
                input.value = "";
                await submitAdminOrderPartnerSelection();
                return;
            }

            var visibleCategoryLabel = categoryAwaitingKey === "public_categ_ids" ? "Categorías de ventas: " : "Categoría: ";
            var visibleUserText = text || (
                pendingCart && messageForServer === "cancelar" ? "cancelar" :
                (categorySelectionActive ? (visibleCategoryLabel + selectedCategoryName) : (selectedImageAttachment ? "[Imagen adjunta]" : "[sin dato]"))
            );
            setLastUserNaturalReplyContext({
                kind: pendingCart && isQuantityAnswer(messageForServer || text) ? "cart_add" :
                    (!pendingAdminProductCreate && lastProductForCart && isQuantityAnswer(messageForServer || text) ? "cart_add" :
                    (isProductUpdateIntentText(messageForServer || text) ? "product_update" :
                    ((pendingAdminProductCreate || productImageRequested || isProductCreateIntentText(messageForServer || text)) ? "product_create" : ""))),
                message: messageForServer || text || visibleUserText,
                visibleUserText: visibleUserText,
                quantity: isQuantityAnswer(messageForServer || text) ? (messageForServer || text) : "",
                productLabel: (lastProductForCart && (lastProductForCart.label || lastProductForCart.code)) || "",
                wasPendingProductCreate: Boolean(pendingAdminProductCreate || productImageRequested),
                wasImageStep: Boolean(selectedImageAttachment || productImageRequested || visibleUserText === "[Imagen adjunta]"),
                answers: Object.assign({}, adminProductCreateClientAnswers || {})
            });
            addMessage(messages, "Tú", visibleUserText);
            input.value = "";
            isSending = true;
            sendButton.disabled = true;
            sendButton.textContent = "...";
            var waitingMessage = addMessage(messages, "IA", "Consultando la IA. Esto puede tardar varios minutos...");

            try {
                var cartMessage = messageForServer || text;

                if (!pendingAdminProductCreate && isBareProductUpdateHelpIntent(cartMessage)) {
                    setMessage(waitingMessage, "IA", productUpdatePromptHelpReply());
                    return;
                }

                if (!pendingAdminProductCreate && isAdminOrderHistorySelectorIntent(cartMessage)) {
                    var historyKind = adminOrderHistoryKindFromText(cartMessage);
                    var adminPartnerCheck = await postJson("/ai/order/partners", {
                        kind: historyKind,
                        mode: "history",
                        sessionId: getSessionId()
                    });
                    if (adminPartnerCheck.response.ok && !(adminPartnerCheck.data && adminPartnerCheck.data.error)) {
                        orderPartnerOptionsByKind["history_" + historyKind] = (adminPartnerCheck.data && adminPartnerCheck.data.partners) || [];
                        setMessage(waitingMessage, "IA", historyKind === "purchase" ? "Selecciona un proveedor para consultar su historial de pedidos de compra." : "Selecciona un cliente para consultar su historial de pedidos de venta.");
                        activateAdminOrderHistoryPartnerMode(historyKind);
                        return;
                    }
                    // Las consultas de compras son internas. Si el usuario no es admin,
                    // no dejamos que el texto continúe hacia n8n, porque podría interpretarse
                    // como búsqueda de producto y devolver resultados incorrectos.
                    if (historyKind === "purchase") {
                        renderCustomerOrderResponse(waitingMessage, adminPartnerCheck.data || {
                            reply: "Por seguridad, solo la cuenta Admin puede crear, modificar o borrar productos, cuentas de cliente y pedidos desde la IA. Con esta cuenta solo puedo ayudarte a buscar productos por referencia, código, nombre o categoría, consultar disponibilidad y añadir productos al carrito.",
                            buttons: []
                        }, adminPartnerCheck.response.ok);
                        return;
                    }
                }

                if (!pendingAdminProductCreate && isAdminCustomerOrderHistoryIntent(cartMessage)) {
                    var adminOrderHistoryResult = await postJson("/ai/admin/orders/history", {
                        kind: adminOrderHistoryKindFromText(cartMessage),
                        message: cartMessage,
                        sessionId: getSessionId(),
                        pageUrl: window.location.href,
                        pageTitle: document.title
                    });
                    renderCustomerOrderResponse(waitingMessage, adminOrderHistoryResult.data, adminOrderHistoryResult.response.ok);
                    return;
                }

                if (!pendingAdminProductCreate && isMyAccountIntent(cartMessage)) {
                    setMessage(waitingMessage, "IA", "Abriendo tu cuenta...", false, {
                        label: "Abrir mi cuenta",
                        url: "/my",
                        target: "_self"
                    });
                    setTimeout(function () {
                        try {
                            window.location.href = "/my";
                        } catch (error) {
                            // Si el navegador bloquea la navegación, queda disponible el botón.
                        }
                    }, 150);
                    return;
                }

                if (!pendingAdminProductCreate && isRepeatLastOrderIntent(cartMessage)) {
                    var repeatOrderResult = await postJson("/ai/customer/orders/repeat_last", {
                        message: cartMessage,
                        sessionId: getSessionId(),
                        pageUrl: window.location.href,
                        pageTitle: document.title
                    });
                    renderCustomerOrderResponse(waitingMessage, repeatOrderResult.data, repeatOrderResult.response.ok);
                    return;
                }

                if (!pendingAdminProductCreate && isCustomerOrderHistoryIntent(cartMessage)) {
                    var orderHistoryResult = await postJson("/ai/customer/orders/history", {
                        message: cartMessage,
                        sessionId: getSessionId(),
                        pageUrl: window.location.href,
                        pageTitle: document.title
                    });
                    renderCustomerOrderResponse(waitingMessage, orderHistoryResult.data, orderHistoryResult.response.ok);
                    return;
                }

                if (pendingCart && isCancelAnswer(cartMessage)) {
                    var cancelResult = await postJson("/ai/cart/intent", {
                        message: cartMessage,
                        sessionId: getSessionId(),
                        pageUrl: window.location.href,
                        pageTitle: document.title
                    });
                    renderCartResponse(waitingMessage, cancelResult.data, cancelResult.response.ok);
                    return;
                }

                if (pendingCart && isQuantityAnswer(cartMessage)) {
                    var pendingCartBeforeAdd = Object.assign({}, pendingCart || {});
                    var addResult = await postJson("/ai/cart/add", {
                        productId: pendingCart.productId,
                        productCode: pendingCart.productCode,
                        quantity: cartMessage,
                        sessionId: getSessionId(),
                        pageUrl: window.location.href,
                        pageTitle: document.title
                    });
                    if (addResult.data && !addResult.data.productLabel) {
                        addResult.data.productLabel = pendingCartBeforeAdd.name || pendingCartBeforeAdd.productCode || "";
                    }
                    if (addResult.data && !addResult.data.quantity) {
                        addResult.data.quantity = cartMessage;
                    }
                    renderCartResponse(waitingMessage, addResult.data, addResult.response.ok);
                    return;
                }

                if (!pendingCart && !pendingAdminProductCreate && lastProductForCart && isQuantityAnswer(cartMessage)) {
                    var rememberedProductText = lastProductForCart.code || lastProductForCart.label;
                    var rememberedCartResult = await postJson("/ai/cart/add", {
                        productId: lastProductForCart.productId || lastProductForCart.id || null,
                        productCode: lastProductForCart.code || rememberedProductText,
                        quantity: cartMessage,
                        sessionId: getSessionId(),
                        pageUrl: window.location.href,
                        pageTitle: document.title
                    });
                    if (rememberedCartResult.data) {
                        if (!rememberedCartResult.data.productLabel) {
                            rememberedCartResult.data.productLabel = lastProductForCart.label || rememberedProductText;
                        }
                        if (!rememberedCartResult.data.quantity) {
                            rememberedCartResult.data.quantity = cartMessage;
                        }
                    }
                    renderCartResponse(waitingMessage, rememberedCartResult.data, rememberedCartResult.response.ok);
                    return;
                }

                if (!pendingAdminProductCreate && !isProductDeleteOrArchiveIntent(cartMessage)) {
                    var cartResult = await postJson("/ai/cart/intent", {
                        message: cartMessage,
                        sessionId: getSessionId(),
                        pageUrl: window.location.href,
                        pageTitle: document.title
                    });

                    updatePendingCart(cartResult.data);

                    if (cartResult.data && cartResult.data.handled) {
                        renderCartResponse(waitingMessage, cartResult.data, cartResult.response.ok);
                        return;
                    }
                }

                var hasSelectedImage = Boolean(selectedImageAttachment && selectedImageFile);
                if (productImageRequested && !hasSelectedImage && !(pendingAdminProductCreate && pendingAdminProductCreateAwaiting === "image" && !text)) {
                    activateProductImageMode("Selecciona una imagen para el producto con el botón 📎 Imagen.");
                }

                var response;
                if (hasSelectedImage) {
                    var formData = new FormData();
                    formData.append("message", messageForServer || "[imagen adjunta]");
                    formData.append("sessionId", getSessionId());
                    formData.append("pageUrl", window.location.href);
                    formData.append("pageTitle", document.title);
                    formData.append("adminProductCreateAwaiting", sentAdminProductCreateKey || "");
                    formData.append("adminProductCreateClientAnswers", JSON.stringify(adminProductCreateClientAnswers || {}));
                    formData.append("attachment", selectedImageFile, selectedImageAttachment.filename || selectedImageFile.name || "imagen_producto");
                    deactivateProductImageMode();
                    clearSelectedImage();
                    response = await fetch("/ai/chat/start", {
                        method: "POST",
                        body: formData,
                        credentials: "same-origin"
                    });
                } else {
                    updateImageButtonVisibility();
                    response = await fetch("/ai/chat/start", {
                        method: "POST",
                        headers: {"Content-Type": "application/json"},
                        body: JSON.stringify({
                            message: messageForServer,
                            sessionId: getSessionId(),
                            pageUrl: window.location.href,
                            pageTitle: document.title,
                            attachments: [],
                            adminProductCreateAwaiting: sentAdminProductCreateKey,
                            adminProductCreateClientAnswers: adminProductCreateClientAnswers
                        }),
                        credentials: "same-origin"
                    });
                }

                var data = await readResponse(response);
                if (!response.ok) {
                    console.error("[odoo_ai_chat] Error backend start", response.status, data);
                    var startErrorReply = data.reply || data.error || "No se pudo contactar con el flujo de IA.";
                    if (isProductNotFoundReply(startErrorReply)) {
                        setMessage(waitingMessage, "IA", productNotFoundReply(), false);
                    } else if (isUnknownAIErrorReply(startErrorReply)) {
                        setMessage(waitingMessage, "IA", unknownQuestionReply(), false);
                    } else {
                        setMessage(waitingMessage, isPermissionDeniedReply(startErrorReply) ? "Error" : "IA", startErrorReply, !isPermissionDeniedReply(startErrorReply));
                    }
                    return;
                }

                // Compatibilidad por si el servidor devuelve respuesta directa.
                if (data.reply && !data.jobId) {
                    var wasPendingProductCreateDirect = Boolean(sendContext.wasPendingProductCreate || pendingAdminProductCreate);
                    var answersBeforeProductCreateClear = Object.assign({}, sendContext.adminProductCreateClientAnswers || pendingAdminProductCreateClientAnswers || {});
                    if ((wasPendingProductCreateDirect || pendingAdminProductCreate) && sentAdminProductCreateKey) {
                        answersBeforeProductCreateClear[sentAdminProductCreateKey] = sentAdminProductCreateValue || "";
                    }
                    updatePendingCart(data);
                    updateAdminProductCreatePending(data, sentAdminProductCreateKey, sentAdminProductCreateValue);
                    updateAdminOrderCreatePending(data);
                    if (data.pendingAdminOrderHistory && data.orderPartnerSelection) {
                        var pendingHistoryKind = adminOrderHistoryKindFromText(data.orderPartnerSelection.kind || cartMessage || messageForServer || text);
                        setMessage(
                            waitingMessage,
                            "IA",
                            pendingHistoryKind === "purchase" ? "Selecciona un proveedor para consultar su historial de pedidos de compra." : "Selecciona un cliente para consultar su historial de pedidos de venta."
                        );
                        return;
                    }
                    if (data.added) {
                        notifyCartUpdated(data);
                    }
                    if (data.needsProductCategory) {
                        activateProductCategoryMode(data.productCategoryKind || categoryKindForAwaiting(data.adminProductCreateAwaiting));
                    } else if (data.productCreated || data.clearPendingAdminProductCreate || data.success || !isCategoryAwaitingKey(data.adminProductCreateAwaiting)) {
                        deactivateProductCategoryMode();
                    } else {
                        updateCategoryDropdownVisibility();
                    }
                    if (data.needsProductImage) {
                        activateProductImageMode("Selecciona una imagen para el producto con el botón 📎 Imagen.");
                    } else if (data.productImageHandled || data.productCreated || data.clearPendingAdminProductCreate || data.success) {
                        deactivateProductImageMode();
                    } else {
                        updateImageButtonVisibility();
                    }
                    var directReply = data.reply;
                    if (isProductNotFoundReply(directReply)) {
                        directReply = productNotFoundReply();
                    } else {
                        directReply = normalizeAIReply(directReply);
                    }
                    if (!data.added && isTechnicalListReply(directReply) && looksLikeQuantityForLastProduct(cartMessage || messageForServer || text)) {
                        directReply = normalReplyForTechnicalResult(directReply, {
                            kind: "cart_add",
                            quantity: cartMessage || messageForServer || text,
                            productLabel: (lastProductForCart && (lastProductForCart.label || lastProductForCart.code)) || "el producto"
                        });
                        lastProductForCart = null;
                    } else if (data.added) {
                        directReply = normalReplyForTechnicalResult(directReply, {
                            kind: "cart_add",
                            quantity: data.addedQuantity || data.quantity || data.lineQuantity || sentAdminProductCreateValue || cartMessage || "",
                            productLabel: data.productName || data.productLabel || ""
                        });
                    } else if (data.productUpdated || (isTechnicalListReply(directReply) && isProductUpdateIntentText(cartMessage || messageForServer || text))) {
                        directReply = normalReplyForTechnicalResult(directReply, {
                            kind: "product_update",
                            message: cartMessage || messageForServer || text,
                            productCode: data.productCode || data.default_code || data.productRef || "",
                            answers: answersBeforeProductCreateClear
                        });
                    } else if (data.productCreated || (wasPendingProductCreateDirect && isTechnicalListReply(directReply)) || (isTechnicalListReply(directReply) && isProductCreateIntentText(cartMessage || messageForServer || text))) {
                        directReply = normalReplyForTechnicalResult(directReply, {
                            kind: "product_create",
                            message: cartMessage || messageForServer || text,
                            productName: data.productName || data.name || "",
                            productCode: data.productCode || data.default_code || data.productRef || "",
                            answers: answersBeforeProductCreateClear
                        });
                    }
                    setMessage(waitingMessage, "IA", directReply, false, actionButtonsFromData(data));
                    return;
                }

                if (!data.jobId) {
                    throw new Error("Odoo no devolvió jobId para consultar la respuesta.");
                }

                await pollChatJob(data.jobId, waitingMessage, messages, sentAdminProductCreateKey, sentAdminProductCreateValue, sendContext);
            } catch (error) {
                console.error("[odoo_ai_chat] Error fetch", error);
                var catchReply = error.message || "No se pudo contactar con el flujo de IA.";
                if (isUnknownAIErrorReply(catchReply) || catchReply === unknownQuestionReply()) {
                    setMessage(waitingMessage, "IA", unknownQuestionReply(), false);
                } else {
                    setMessage(waitingMessage, "Error", catchReply, true);
                }
            } finally {
                isSending = false;
                sendButton.disabled = false;
                sendButton.textContent = "Enviar";
                input.focus();
            }
        }

        sendButton.addEventListener("click", sendMessage);
        input.addEventListener("keydown", function (event) {
            if (event.key === "Enter") {
                event.preventDefault();
                if (!event.repeat) {
                    sendMessage();
                }
            }
        });
    }

    // Inicializa el chat solo en páginas habilitadas.
    async function initChatIfEnabled() {
        if (await isChatEnabledOnThisPage()) {
            createChatWidget();
        } else {
            console.log("[odoo_ai_chat] Chat no habilitado en esta página");
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", initChatIfEnabled);
    } else {
        initChatIfEnabled();
    }
})();
