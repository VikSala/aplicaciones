import base64
import json
import logging
import os
import re
import threading
import time
import uuid
from urllib.parse import quote, urlparse, urlunparse

import requests
from werkzeug.wrappers import Response

from odoo import http
from odoo.http import request
from odoo.osv import expression

_logger = logging.getLogger(__name__)



_AI_CHAT_JOBS = {}
_AI_CHAT_JOBS_LOCK = threading.Lock()
_AI_CHAT_JOB_TTL_SECONDS = 60 * 30

# Estado de respaldo para el alta guiada de producto.
# Algunos despliegues/proxies pueden devolver turnos consecutivos con una sesión HTTP
# de Odoo parcialmente desincronizada. El widget envía además un sessionId estable;
# lo usamos como respaldo para no volver a preguntar campos ya contestados.
_AI_ADMIN_PRODUCT_CREATE_STATES = {}
_AI_ADMIN_PRODUCT_CREATE_STATES_LOCK = threading.Lock()
_AI_ADMIN_PRODUCT_CREATE_STATE_TTL_SECONDS = 60 * 60 * 4


# Limpia estados antiguos del alta guiada de producto cuando ya han caducado.
def _cleanup_old_admin_product_create_states_unlocked():
    now = time.time()
    for state_key, state in list(_AI_ADMIN_PRODUCT_CREATE_STATES.items()):
        updated_at = state.get("_updated_at") or state.get("started_at") or now
        if now - updated_at > _AI_ADMIN_PRODUCT_CREATE_STATE_TTL_SECONDS:
            _AI_ADMIN_PRODUCT_CREATE_STATES.pop(state_key, None)


# Limpia consultas antiguas de IA guardadas en memoria.
def _cleanup_old_jobs_unlocked():
    now = time.time()
    for job_id, job in list(_AI_CHAT_JOBS.items()):
        created_at = job.get("created_at") or now
        if now - created_at > _AI_CHAT_JOB_TTL_SECONDS:
            _AI_CHAT_JOBS.pop(job_id, None)


# Guarda o actualiza el estado de una consulta enviada a n8n.
def _set_chat_job(job_id, **values):
    with _AI_CHAT_JOBS_LOCK:
        job = _AI_CHAT_JOBS.setdefault(job_id, {})
        job.update(values)
        job["updated_at"] = time.time()


# Extrae el texto útil desde respuestas JSON con estructuras distintas.
def _extract_reply_value_from_payload(payload):
    if payload is None:
        return None

    if isinstance(payload, str):
        return payload

    if isinstance(payload, list):
        for item in payload:
            value = _extract_reply_value_from_payload(item)
            if value:
                return value
        return None

    if isinstance(payload, dict):
        # Formatos habituales de n8n / AI Agent / Respond to Webhook y modelos distintos
        # Gemini, Ollama, OpenAI-compatible, etc.
        direct_keys = (
            "reply", "output", "response", "answer", "text", "message",
            "content", "generated_text", "completion", "result",
        )
        for key in direct_keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, (dict, list)):
                nested_value = _extract_reply_value_from_payload(value)
                if nested_value:
                    return nested_value

        # Formatos anidados habituales:
        # - n8n: {body: {...}}, {json: {...}}, {data: [...]}
        # - Gemini: {candidates: [{content: {parts: [{text: "..."}]}}]}
        # - OpenAI compatible: {choices: [{message: {content: "..."}}]}
        nested_keys = (
            "body", "data", "json", "result", "results", "item", "items",
            "candidate", "candidates", "choice", "choices", "message",
            "content", "parts", "generations", "generationsByPrompt",
        )
        for key in nested_keys:
            if key in payload:
                value = _extract_reply_value_from_payload(payload.get(key))
                if value:
                    return value

    return None


# Limpia bloques Markdown tipo ```json ... ``` que a veces devuelven los agentes.
def _strip_reply_code_fence(text):
    value = (text or "").strip()
    fenced = re.match(r"^```(?:json|javascript|js|text)?\s*(.*?)\s*```$", value, flags=re.IGNORECASE | re.DOTALL)
    if fenced:
        return fenced.group(1).strip()
    return value


# Intenta convertir texto que realmente contiene JSON en el valor visible de la respuesta.
def _extract_reply_from_jsonish_text(text, depth=0):
    if depth > 4:
        return None

    candidate = _strip_reply_code_fence(text)
    if not candidate:
        return ""

    # Algunos modelos anteponen etiquetas antes del JSON: IA: {"reply": "..."}
    label_match = re.match(r"^\s*(?:ia|ai|assistant|asistente)\s*:\s*([\[{].*[\]}])\s*$", candidate, flags=re.IGNORECASE | re.DOTALL)
    if label_match:
        candidate = label_match.group(1).strip()

    json_candidates = [candidate]
    first_object = candidate.find("{")
    last_object = candidate.rfind("}")
    if first_object >= 0 and last_object > first_object:
        json_candidates.append(candidate[first_object:last_object + 1].strip())
    first_array = candidate.find("[")
    last_array = candidate.rfind("]")
    if first_array >= 0 and last_array > first_array:
        json_candidates.append(candidate[first_array:last_array + 1].strip())

    for json_candidate in json_candidates:
        if not json_candidate or json_candidate[:1] not in ("{", "["):
            continue
        try:
            payload = json.loads(json_candidate)
        except Exception:
            continue

        value = _extract_reply_value_from_payload(payload)
        if value is None:
            return "" if payload in ({}, []) else None

        value = str(value).strip()
        if not value:
            return ""
        if value == candidate:
            return value
        return _unwrap_labeled_reply_text(value, depth=depth + 1)

    return None


# Limpia respuestas generadas por modelos/agentes que devuelven formato técnico.
def _unwrap_labeled_reply_text(reply, depth=0):
    """Extrae solo el texto visible aunque n8n/modelo devuelva envoltorios técnicos.

    Cubre formatos como ``reply="mensaje"``, ``{"reply": "mensaje"}``,
    bloques Markdown JSON y respuestas anidadas del AI Agent.
    """
    if reply is None:
        return ""
    if depth > 4:
        return str(reply).strip()

    if isinstance(reply, (dict, list)):
        value = _extract_reply_value_from_payload(reply)
        if value is None:
            return ""
        return _unwrap_labeled_reply_text(value, depth=depth + 1)

    text = _strip_reply_code_fence(str(reply).strip())
    if not text:
        return ""

    jsonish_value = _extract_reply_from_jsonish_text(text, depth=depth)
    if jsonish_value is not None and jsonish_value != text:
        return jsonish_value.strip()

    keys = "reply|output|response|answer|text|message"
    if re.match(r"^\s*(?:%s)\s*[:=]" % keys, text, flags=re.IGNORECASE):
        text = text.replace('\\"', '"').replace("\\'", "'")

    # reply="texto" / reply='texto' / reply: "texto"
    quoted = re.match(
        r"^\s*(?:%s)\s*[:=]\s*([\"'])(.*)\1\s*,?\s*$" % keys,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if quoted:
        return _unwrap_labeled_reply_text(quoted.group(2).strip(), depth=depth + 1)

    # reply=texto sin comillas. Lo limitamos a cadenas que empiezan exactamente
    # por una de las claves esperadas para no alterar respuestas normales.
    unquoted = re.match(
        r"^\s*(?:%s)\s*[:=]\s*(.+?)\s*$" % keys,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if unquoted:
        return _unwrap_labeled_reply_text(unquoted.group(1).strip().strip('\"\''), depth=depth + 1)

    return text


# Elimina nombres técnicos de campos antes de mostrar la respuesta al visitante.
def _sanitize_reply_for_customer(reply):
    """Limpia nombres técnicos de campos antes de mostrar la respuesta al cliente."""
    if not reply:
        return ""

    text = _unwrap_labeled_reply_text(reply)

    replacements = [
        (r"\s*\(\s*qty_available\s*\)", ""),
        (r"\s*\(\s*x_transit_stock_custom\s*\)", ""),
        (r"\s*\(\s*x_almacen1_custom\s*\)", ""),
        (r"\s*\[\s*qty_available\s*\]", ""),
        (r"\s*\[\s*x_transit_stock_custom\s*\]", ""),
        (r"\s*\[\s*x_almacen1_custom\s*\]", ""),
    ]

    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)

    # Por si el modelo escribe frases explicativas con nombres internos.
    text = re.sub(
        r"\s*,?\s*(?:campo|field)\s+(?:t[eé]cnico\s+)?(?:qty_available|x_transit_stock_custom|x_almacen1_custom)",
        "",
        text,
        flags=re.IGNORECASE,
    )

    return text.strip()


# Convierte la respuesta HTTP de n8n en un texto limpio para el chat.
def _extract_reply_from_n8n_http_response(response):
    raw_text = (response.text or "").strip()
    if not raw_text:
        return ""

    try:
        payload = response.json()
    except ValueError:
        return _sanitize_reply_for_customer(raw_text)

    reply = _extract_reply_value_from_payload(payload)
    if isinstance(reply, str):
        return _sanitize_reply_for_customer(reply.strip())
    if reply is None:
        return ""
    return _sanitize_reply_for_customer(str(reply).strip())


# Normaliza la URL del webhook de n8n para Docker, test y producción.
def _normalize_n8n_webhook_url(webhook_url):
    """Convierte la URL de n8n a la forma correcta para Docker y producción.

    Ejemplo:
    - Entrada desde n8n UI: http://localhost:5678/webhook-test/odoo-ai-chat
    - Salida para Odoo Docker: http://n8n_local:5678/webhook/odoo-ai-chat
    """
    value = (webhook_url or "").strip()
    if not value:
        return ""

    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        return value

    path = parsed.path or ""
    if path.startswith("/webhook-test/"):
        path = path.replace("/webhook-test/", "/webhook/", 1)

    netloc = parsed.netloc
    hostname = parsed.hostname or ""
    if hostname in ("localhost", "127.0.0.1", "0.0.0.0") and (parsed.port in (5678, None)):
        netloc = "n8n_local:5678"

    return urlunparse((parsed.scheme, netloc, path, parsed.params, parsed.query, parsed.fragment))


# Obtiene la URL configurada del webhook de n8n.
def _get_configured_webhook_url():
    """Obtiene la URL del webhook; si no hay ajuste usa la URL de producción de n8n en Docker."""
    config = request.env["ir.config_parameter"].sudo()
    configured = (
        os.environ.get("ODOO_AI_CHAT_WEBHOOK_URL")
        or config.get_param("odoo_ai_chat.webhook_url")
        or "http://n8n_local:5678/webhook/odoo-ai-chat"
    )
    return _normalize_n8n_webhook_url(configured)


# Lanza la llamada a n8n en segundo plano para no bloquear el navegador.
def _call_n8n_in_background(job_id, webhook_url, payload):
    """Ejecuta la llamada a n8n fuera de la petición HTTP del navegador.

    La llamada síncrona anterior podía romper en Odoo cuando n8n tardaba más que
    el límite del worker/proxy, aunque n8n terminase correctamente. Con este job
    en memoria, Odoo responde rápido al navegador y el widget consulta el resultado.
    """
    _set_chat_job(job_id, status="running")
    try:
        _logger.info("Odoo AI Chat: llamando a n8n webhook: %s", webhook_url)
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Accept": "application/json"},
            timeout=(10, 900),
        )
        response_text_preview = (response.text or "")[:1000]
        if response.status_code >= 400:
            raise requests.HTTPError(
                "n8n devolvió HTTP %s: %s" % (response.status_code, response_text_preview)
            )

        reply = _extract_reply_from_n8n_http_response(response)
        if not reply:
            reply = "n8n respondió, pero no se encontró texto en la respuesta. Revisa el nodo Respond to Webhook."

        _set_chat_job(job_id, status="done", reply=reply, error=False)
    except Exception as error:
        _logger.exception("Error llamando a n8n en segundo plano")
        _set_chat_job(
            job_id,
            status="error",
            error=True,
            reply="No se pudo contactar con el flujo de IA. Detalle técnico: %s" % error,
        )


# Devuelve una respuesta HTTP JSON compatible con el widget.
def _json_response(payload, status=200):
    return Response(
        json.dumps(payload, ensure_ascii=False),
        status=status,
        content_type="application/json; charset=utf-8",
    )


# Quita etiquetas HTML y compacta espacios de un texto.
def _strip_html(value):
    if not value:
        return ""
    text = re.sub(r"<[^>]+>", " ", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text


# Controlador principal que agrupa las rutas públicas del widget de chat y las acciones auxiliares.
class OdooAIChatController(http.Controller):

    # Construye una URL segura a la ficha backend de un registro.
    def _backend_record_form_url(self, model, record_id, action_xmlids=None):
        record_id = int(record_id or 0)
        if not model or not record_id:
            return ""

        action_id = False
        for xmlid in (action_xmlids or ()):  # action opcional para abrir con el menú correcto
            try:
                action = request.env.ref(xmlid, raise_if_not_found=False)
            except TypeError:
                try:
                    action = request.env.ref(xmlid)
                except Exception:
                    action = False
            except Exception:
                action = False
            if action:
                action_id = action.id
                break

        parts = [
            "id=%s" % record_id,
            "model=%s" % model,
            "view_type=form",
        ]
        if action_id:
            parts.append("action=%s" % action_id)
        return "/web#" + "&".join(parts)

    # Devuelve los metadatos del botón que el widget pinta debajo de la respuesta.
    def _record_open_button(self, label, model, record_id, action_xmlids=None):
        url = self._backend_record_form_url(model, record_id, action_xmlids=action_xmlids)
        if not url:
            return False
        return {
            "label": label,
            "url": url,
            "model": model,
            "resId": int(record_id or 0),
            "target": "_blank",
        }

    # Devuelve únicamente botones válidos, preservando orden y evitando valores vacíos.
    def _valid_action_buttons(self, buttons):
        valid = []
        for button in (buttons or []):
            if not isinstance(button, dict) or not button.get("label"):
                continue
            # Los botones pueden abrir una URL segura o ejecutar una acción local del widget
            # como mostrar historial o repetir el último pedido.
            if button.get("url") or button.get("action"):
                valid.append(button)
        return valid

    # Añade el primer botón como actionButton y todos como actionButtons para mantener compatibilidad.
    def _with_action_buttons(self, payload, buttons):
        buttons = self._valid_action_buttons(buttons)
        if not buttons:
            return payload
        payload["actionButton"] = buttons[0]
        payload["actionButtons"] = buttons
        return payload

    # Devuelve la plantilla de producto asociada a una variante o plantilla.
    def _product_template_record(self, product):
        if not product:
            return False
        try:
            return product.product_tmpl_id.sudo() if getattr(product, "product_tmpl_id", False) else product.sudo()
        except Exception:
            return product

    # Devuelve el botón estándar para abrir la ficha backend de un producto.
    def _product_open_button(self, product):
        template = self._product_template_record(product)
        if not template:
            return False
        return self._record_open_button(
            "Ver producto",
            "product.template",
            template.id,
            action_xmlids=(
                "stock.product_template_action_product",
                "product.product_template_action",
                "product.product_template_action_all",
            ),
        )

    # Construye la URL de la ficha pública del producto dentro de la tienda web.
    def _website_product_page_url(self, product):
        template = self._product_template_record(product)
        if not template:
            return ""

        url = ""
        try:
            url = (getattr(template, "website_url", False) or "").strip()
        except Exception:
            url = ""

        if not url:
            try:
                from odoo.addons.http_routing.models.ir_http import slug
                url = "/shop/product/%s" % slug(template)
            except Exception:
                url = "/shop/product/%s" % template.id

        if url.startswith(("http://", "https://")):
            try:
                parsed = urlparse(url)
                url = parsed.path or "/"
                if parsed.query:
                    url += "?" + parsed.query
                if parsed.fragment:
                    url += "#" + parsed.fragment
            except Exception:
                url = ""

        if url and not url.startswith("/"):
            url = "/" + url
        return url

    # Devuelve el botón de producto para clientes/portal: ficha pública de la web.
    def _website_product_open_button(self, product):
        template = self._product_template_record(product)
        url = self._website_product_page_url(product)
        if not template or not url:
            return False
        return {
            "label": "Ver producto",
            "url": url,
            "model": "product.template",
            "resId": int(template.id or 0),
            "target": "_blank",
            "frontend": True,
        }

    # Devuelve el botón de producto correcto según el usuario actual.
    def _product_open_button_for_current_user(self, product):
        if self._is_admin_ai_operator():
            return self._product_open_button(product)
        return self._website_product_open_button(product)

    # Devuelve el botón estándar para abrir la ficha backend de un cliente/contacto.
    def _partner_open_button(self, partner, label="Ver cliente"):
        if not partner:
            return False
        return self._record_open_button(
            label or "Ver cliente",
            "res.partner",
            partner.id,
            action_xmlids=("contacts.action_contacts", "base.action_partner_form"),
        )

    # Devuelve el botón estándar para abrir un pedido de venta en el backend.
    def _sale_order_open_button(self, order, label=None):
        if not order:
            return False
        return self._record_open_button(
            label or "Ver pedido de venta",
            "sale.order",
            order.id,
            action_xmlids=("sale.action_orders", "sale.action_quotations", "sale.action_sale_order_form"),
        )

    # Devuelve el botón estándar para abrir un pedido de compra en el backend.
    def _purchase_order_open_button(self, order, label=None):
        if not order:
            return False
        return self._record_open_button(
            label or "Ver pedido de compra",
            "purchase.order",
            order.id,
            action_xmlids=("purchase.purchase_rfq", "purchase.purchase_form_action", "purchase.purchase_order_form_action"),
        )

    # Indica si el visitante actual tiene una sesión de cliente real.
    # No crea usuarios ni altera permisos: solo distingue portal/cliente de visitante público.
    def _is_authenticated_customer_user(self):
        try:
            user = request.env.user
            if not user or not user.exists():
                return False
            if hasattr(user, "_is_public") and user._is_public():
                return False
            return True
        except Exception:
            return False

    # Devuelve el partner comercial del cliente conectado para consultar sus pedidos.
    def _current_customer_commercial_partner(self):
        if not self._is_authenticated_customer_user():
            return False
        partner = request.env.user.sudo().partner_id
        return partner.commercial_partner_id if partner else False

    # Construye la URL de portal del pedido de venta cuando está disponible.
    def _customer_sale_order_portal_url(self, order):
        if not order:
            return ""
        try:
            url = order.sudo().get_portal_url()
        except Exception:
            url = "/my/orders/%s" % order.id
        if url and not url.startswith(("/", "http://", "https://")):
            url = "/" + url
        return url or "/my/orders"

    # Devuelve un botón seguro para abrir un pedido desde el portal del cliente.
    def _customer_sale_order_portal_button(self, order, label=None):
        url = self._customer_sale_order_portal_url(order)
        if not url:
            return False
        return {
            "label": label or "Ver pedido",
            "url": url,
            "target": "_self",
            "frontend": True,
        }

    # Extrae el nombre de cliente/proveedor desde frases administrativas de historial.
    # No ejecuta acciones: solo limpia texto para que la ruta busque el partner adecuado.
    def _extract_admin_order_history_partner_name(self, message, kind="sale"):
        text = (message or "").strip()
        if not text:
            return ""
        kind = "purchase" if kind == "purchase" else "sale"
        cleaned = re.sub(r"\s+", " ", text, flags=re.U).strip()

        if kind == "purchase":
            patterns = [
                r"(?i)^\s*(?:ver|mostrar|muestrame|mu[eé]strame|consultar|consulta)?\s*(?:el\s+)?historial\s+de\s+pedidos\s+de\s+compras?\s+de\s+(.+?)\s*$",
                r"(?i)^\s*(?:ver|mostrar|muestrame|mu[eé]strame|consultar|consulta)?\s*(?:el\s+)?historial\s+de\s+compras?\s+de\s+(.+?)\s*$",
                r"(?i)^\s*(?:ver|mostrar|muestrame|mu[eé]strame|consultar|consulta)?\s*(?:los\s+)?pedidos\s+de\s+compras?\s+de\s+(.+?)\s*$",
                r"(?i)^\s*(?:ver|mostrar|muestrame|mu[eé]strame|consultar|consulta)?\s*(?:los\s+)?pedidos\s+de\s+proveedor(?:es)?\s+de\s+(.+?)\s*$",
            ]
        else:
            patterns = [
                r"(?i)^\s*(?:ver|mostrar|muestrame|mu[eé]strame|consultar|consulta)?\s*(?:el\s+)?historial\s+de\s+pedidos\s+de\s+ventas?\s+de\s+(.+?)\s*$",
                r"(?i)^\s*(?:ver|mostrar|muestrame|mu[eé]strame|consultar|consulta)?\s*(?:el\s+)?historial\s+de\s+ventas?\s+de\s+(.+?)\s*$",
                r"(?i)^\s*(?:ver|mostrar|muestrame|mu[eé]strame|consultar|consulta)?\s*(?:el\s+)?historial\s+de\s+pedidos\s+de\s+(.+?)\s*$",
                r"(?i)^\s*(?:ver|mostrar|muestrame|mu[eé]strame|consultar|consulta)?\s*(?:los\s+)?pedidos\s+de\s+(.+?)\s*$",
                r"(?i)^\s*(?:historial|hist[oó]rico)\s+de\s+(.+?)\s*$",
            ]

        for pattern in patterns:
            match = re.match(pattern, cleaned, flags=re.U)
            if match:
                value = (match.group(1) or "").strip(" .,:;\t\n\r")
                # Evita que frases genéricas como "historial de pedidos de compras"
                # se interpreten como si "compras" fuera un cliente.
                if self._normalize_customer_portal_text(value) in ("compra", "compras", "venta", "ventas", "cliente", "clientes", "proveedor", "proveedores"):
                    return ""
                return value
        return ""

    # Compatibilidad con el nombre anterior usado por el flujo de ventas.
    def _extract_admin_order_history_customer_name(self, message):
        return self._extract_admin_order_history_partner_name(message, kind="sale")

    # Busca el partner por nombre para consultas administrativas de historial.
    # En ventas prioriza customer_rank/pedidos de venta; en compras prioriza supplier_rank/pedidos de compra.
    def _find_partner_for_admin_order_history(self, partner_name, kind="sale"):
        name = (partner_name or "").strip()
        if not name:
            return request.env["res.partner"].sudo().browse()
        kind = "purchase" if kind == "purchase" else "sale"
        Partner = request.env["res.partner"].sudo()
        exact = Partner.search([("name", "=ilike", name)], limit=1)
        if exact:
            return exact.commercial_partner_id or exact

        order_field = "supplier_rank desc" if kind == "purchase" else "customer_rank desc"
        try:
            candidates = Partner.search([("name", "ilike", name)], order="%s, name asc, id asc" % order_field, limit=10)
        except Exception:
            candidates = Partner.search([("name", "ilike", name)], order="name asc, id asc", limit=10)
        if not candidates:
            return Partner.browse()

        Order = request.env["purchase.order"].sudo() if kind == "purchase" else request.env["sale.order"].sudo()
        for partner in candidates:
            commercial = partner.commercial_partner_id or partner
            if Order.search_count([("partner_id", "child_of", commercial.id)]):
                return commercial
        return (candidates[0].commercial_partner_id or candidates[0])

    # Construye la URL de menú estándar de Odoo para historiales admin.
    # No se crea una acción nueva: el botón debe llevar al menú habitual
    # (/odoo/sales o /odoo/purchase) y el JS de backend aplica el filtro visual
    # de Cliente/Proveedor con el contacto elegido desde el chat.
    def _admin_order_history_action_url(self, partner, kind="sale"):
        if not partner:
            return ""
        kind = "purchase" if kind == "purchase" else "sale"
        base_url = "/odoo/purchase" if kind == "purchase" else "/odoo/sales"
        field_label = "Proveedor" if kind == "purchase" else "Cliente"
        partner_name = partner.display_name or partner.name or str(partner.id)
        return "%s?ai_chat_history_filter=1&ai_chat_history_kind=%s&ai_chat_partner_id=%s&ai_chat_partner_name=%s&ai_chat_partner_field=%s" % (
            base_url,
            quote(kind),
            partner.id,
            quote(partner_name),
            quote(field_label),
        )

    # Construye una URL backend con la lista de pedidos de venta filtrada por cliente.
    # El botón abre la misma vista de Ventas/Pedidos que usaría admin manualmente.
    def _admin_sale_orders_history_button(self, partner, label=None):
        if not partner:
            return False
        return {
            "label": label or "Ver historial de pedidos de venta",
            "url": self._admin_order_history_action_url(partner, kind="sale"),
            "target": "_blank",
        }

    # Construye una URL backend con la lista de pedidos de compra filtrada por proveedor.
    def _admin_purchase_orders_history_button(self, partner, label=None):
        if not partner:
            return False
        return {
            "label": label or "Ver historial de pedidos de compra",
            "url": self._admin_order_history_action_url(partner, kind="purchase"),
            "target": "_blank",
        }

    # Ruta local: permite solo a admin consultar el historial de pedidos de venta o compra por partner.
    @http.route("/ai/admin/orders/history", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_admin_order_history(self, **kwargs):
        try:
            if not self._is_admin_ai_operator():
                return _json_response({
                    "success": False,
                    "reply": "Por seguridad, solo la cuenta Admin puede consultar historiales de pedidos de otros contactos desde la IA.",
                }, status=200)

            raw_body = request.httprequest.data or b"{}"
            data = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            kind = self._admin_order_kind_from_text(data.get("kind") or data.get("orderKind") or data.get("message") or "sale")
            kind = "purchase" if kind == "purchase" else "sale"
            role_label = "proveedor" if kind == "purchase" else "cliente"
            role_plural = "proveedores" if kind == "purchase" else "clientes"
            history_label = "pedidos de compra" if kind == "purchase" else "pedidos de venta"

            # La consulta admin puede llegar por texto libre
            # ("historial de pedidos de ventas de Alba" / "historial de pedidos de compras de Azure")
            # o desde el selector visual del chat, que envía directamente el partnerId.
            partner_id = 0
            try:
                partner_id = int(data.get("partnerId") or 0)
            except Exception:
                partner_id = 0

            if partner_id:
                partner = request.env["res.partner"].sudo().browse(partner_id).exists()
                if partner:
                    partner = partner.commercial_partner_id or partner
                partner_name = partner.display_name if partner else str(partner_id)
            else:
                partner_name = (
                    data.get("partnerName")
                    or data.get("customerName")
                    or self._extract_admin_order_history_partner_name(data.get("message") or "", kind=kind)
                ).strip()
                if not partner_name:
                    return _json_response({
                        "success": False,
                        "reply": "Selecciona un %s para consultar su historial de %s." % (role_label, history_label),
                        "pendingAdminOrderHistory": True,
                        "orderPartnerSelection": {"kind": kind, "mode": "history"},
                    }, status=200)
                partner = self._find_partner_for_admin_order_history(partner_name, kind=kind)

            if not partner:
                return _json_response({
                    "success": False,
                    "reply": "No encuentro ningún %s que coincida con %s." % (role_label, partner_name),
                }, status=200)

            if kind == "purchase":
                Order = request.env["purchase.order"].sudo()
                button = self._admin_purchase_orders_history_button(partner, label="Ver historial de pedidos de compra")
            else:
                Order = request.env["sale.order"].sudo()
                button = self._admin_sale_orders_history_button(partner, label="Ver historial de pedidos de venta")

            order_domain = [("partner_id", "child_of", partner.id)]
            order_count = Order.search_count(order_domain)
            last_order = Order.search(order_domain, order="date_order desc, id desc", limit=1)

            if not order_count:
                reply = "He encontrado el %s %s, pero no tiene %s registrados." % (role_label, partner.display_name or partner.name, history_label)
            else:
                reply_lines = [
                    "Historial de %s de %s: %s pedido(s) encontrado(s)." % (history_label, partner.display_name or partner.name, order_count),
                ]
                if last_order:
                    reply_lines.append("Último pedido: %s por %.2f %s." % (
                        last_order.name or ("Pedido %s" % last_order.id),
                        last_order.amount_total or 0.0,
                        last_order.currency_id.name or "",
                    ))
                reply = "\n".join(reply_lines)

            return _json_response(self._with_action_buttons({
                "success": True,
                "reply": reply,
                "partnerId": partner.id,
                "orderKind": kind,
                "orderCount": order_count,
            }, [
                button,
                self._partner_open_button(partner, label=("Ver proveedor" if kind == "purchase" else "Ver cliente")),
            ]))
        except Exception as error:
            _logger.exception("Error en /ai/admin/orders/history")
            return _json_response({"success": False, "reply": "No he podido consultar el historial de pedidos. Detalle técnico: %s" % error}, status=500)

    # Localiza los últimos pedidos confirmados del cliente conectado.
    # Usa sale.order como historial nativo de Odoo; no duplica datos en tablas nuevas.
    def _get_current_customer_sale_orders(self, limit=10):
        partner = self._current_customer_commercial_partner()
        if not partner:
            return request.env["sale.order"].sudo().browse()
        domain = [
            ("partner_id", "child_of", partner.id),
            ("state", "in", ["sale", "done"]),
        ]
        return request.env["sale.order"].sudo().search(domain, order="date_order desc, id desc", limit=int(limit or 10))

    # Formatea una línea de pedido para mostrarla en el chat del cliente.
    def _format_customer_order_line(self, line):
        product_name = line.product_id.display_name or line.name or "Producto"
        qty = self._format_quantity(line.product_uom_qty) if hasattr(self, "_format_quantity") else ("%s" % line.product_uom_qty)
        return "- %s x %s" % (qty, product_name)

    # Formatea un resumen legible de pedido para el chat.
    def _format_customer_sale_order_summary(self, order, include_lines=True, max_lines=6):
        if not order:
            return ""
        try:
            amount = "%s %.2f" % (order.currency_id.symbol or "", order.amount_total or 0.0)
        except Exception:
            amount = "%.2f" % (order.amount_total or 0.0)
        date_label = ""
        try:
            if order.date_order:
                date_label = order.date_order.strftime("%d/%m/%Y")
        except Exception:
            date_label = ""
        lines = [
            "%s%s - Total: %s" % (order.name or ("Pedido %s" % order.id), (" del %s" % date_label) if date_label else "", amount.strip()),
        ]
        if include_lines:
            order_lines = order.order_line.filtered(lambda line: not line.display_type and line.product_id)[:max_lines]
            for line in order_lines:
                lines.append(self._format_customer_order_line(line))
            remaining = len(order.order_line.filtered(lambda line: not line.display_type and line.product_id)) - len(order_lines)
            if remaining > 0:
                lines.append("- ... y %s línea(s) más" % remaining)
        return "\n".join(lines)

    # Añade botones de historial/repetición a la respuesta de pedidos del cliente.
    def _customer_order_history_buttons(self, last_order=None):
        buttons = []
        if last_order:
            buttons.append({
                "label": "Repetir último pedido",
                "action": "repeat_last_order",
                "target": "_self",
            })
            buttons.append(self._customer_sale_order_portal_button(last_order, label="Ver último pedido"))
        buttons.append({"label": "Mostrar historial", "action": "show_customer_orders", "target": "_self"})
        buttons.append({"label": "Abrir mis pedidos", "url": "/my/orders", "target": "_self", "frontend": True})
        return self._valid_action_buttons(buttons) or [button for button in buttons if isinstance(button, dict) and button.get("action") and button.get("label")]

    # Ruta local: muestra el historial de pedidos del cliente conectado.
    @http.route("/ai/customer/orders/history", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_customer_order_history(self, **kwargs):
        try:
            if not self._is_authenticated_customer_user():
                return _json_response({
                    "success": False,
                    "reply": "Para consultar tu historial de pedidos, inicia sesión con tu cuenta de cliente.",
                    "actionButton": {"label": "Iniciar sesión", "url": "/web/login", "target": "_self"},
                }, status=200)

            orders = self._get_current_customer_sale_orders(limit=10)
            if not orders:
                return _json_response({
                    "success": True,
                    "reply": "No encuentro pedidos confirmados en tu historial de cliente.",
                    "actionButton": {"label": "Abrir mis pedidos", "url": "/my/orders", "target": "_self"},
                })

            last_order = orders[0]
            summary_lines = [
                "Tu último pedido registrado es:",
                self._format_customer_sale_order_summary(last_order, include_lines=True),
            ]
            if len(orders) > 1:
                summary_lines.append("\nÚltimos pedidos:")
                for order in orders[:5]:
                    summary_lines.append("- " + self._format_customer_sale_order_summary(order, include_lines=False))

            return _json_response(self._with_action_buttons({
                "success": True,
                "reply": "\n".join(summary_lines),
                "lastOrderId": last_order.id,
                "orderCount": len(orders),
            }, self._customer_order_history_buttons(last_order)))
        except Exception as error:
            _logger.exception("Error en /ai/customer/orders/history")
            return _json_response({"success": False, "reply": "No he podido consultar tu historial de pedidos. Detalle técnico: %s" % error}, status=500)

    # Devuelve el producto más comprado por el cliente conectado en pedidos confirmados.
    # Se calcula sobre las líneas reales de venta y no guarda datos nuevos ni altera permisos.
    def _current_customer_most_purchased_product(self, limit_orders=50):
        partner = self._current_customer_commercial_partner()
        if not partner:
            return False, 0.0
        orders = request.env["sale.order"].sudo().search([
            ("partner_id", "child_of", partner.id),
            ("state", "in", ["sale", "done"]),
        ], order="date_order desc, id desc", limit=int(limit_orders or 50))
        totals = {}
        products = {}
        for order in orders:
            for line in order.order_line.filtered(lambda item: not item.display_type and item.product_id):
                product = line.product_id.sudo()
                totals[product.id] = totals.get(product.id, 0.0) + float(line.product_uom_qty or 0.0)
                products[product.id] = product
        if not totals:
            return False, 0.0
        product_id = max(totals, key=lambda key: totals.get(key, 0.0))
        return products.get(product_id), totals.get(product_id, 0.0)

    # Ruta local: saludo contextual para clientes conectados.
    # Solo personaliza el primer mensaje del chat; no modifica ninguna función existente.
    @http.route("/ai/customer/greeting", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_customer_greeting(self, **kwargs):
        """Devuelve un saludo seguro para el cliente conectado.

        Esta ruta no ejecuta operaciones de negocio: solo lee pedidos del propio
        cliente autenticado para preparar el mensaje inicial del chat. Se ha hecho
        especialmente defensiva para que un fallo en botones, portal URL o cálculo
        de producto más comprado no sustituya nunca el saludo por textos genéricos
        como "Operación realizada correctamente".
        """
        try:
            if not self._is_authenticated_customer_user() or self._is_admin_ai_operator():
                return _json_response({"success": True, "showPersonalGreeting": False})

            partner = self._current_customer_commercial_partner()
            user = request.env.user.sudo()
            display_name = (partner.name or user.name or "") if partner else (user.name or "")
            customer_name = (display_name or "").strip() or "cliente"

            # Importante: calculamos también search_count.
            # Antes se asumía orderCount=1 cuando existía un único pedido; en algunos
            # clientes con un solo pedido Odoo/n8n devolvía un texto genérico aunque
            # hubiera botones. Mantener el contador real evita ese caso sin cambiar
            # ninguna operación de negocio ni privilegios.
            order_domain = [
                ("partner_id", "child_of", partner.id if partner else 0),
                ("state", "in", ["sale", "done"]),
            ]
            Order = request.env["sale.order"].sudo()
            orders = Order.search(order_domain, order="date_order desc, id desc", limit=1) if partner else Order.browse()
            order_count = Order.search_count(order_domain) if partner else 0

            if not orders:
                greeting_reply = "Hola, %s. ¿En qué puedo ayudarte?" % customer_name
                return _json_response({
                    "success": True,
                    "showPersonalGreeting": True,
                    "reply": greeting_reply,
                    "greetingReply": greeting_reply,
                    "safeGreetingReply": greeting_reply,
                    "forceGreetingReply": greeting_reply,
                    "greetingKind": "customer_without_orders",
                    "customerName": customer_name,
                    "partnerName": customer_name,
                    "customerId": partner.id if partner else False,
                    "orderCount": 0,
                    "hasOrders": False,
                    "actionButtons": [],
                })

            last_order = orders[0].sudo()
            last_order_name = last_order.name or ("Pedido %s" % last_order.id)

            top_product = False
            try:
                top_product, top_qty = self._current_customer_most_purchased_product(limit_orders=50)
                if top_product:
                    top_product = top_product.sudo()
            except Exception:
                top_product = False
                _logger.exception("No se pudo calcular el producto más comprado para el saludo del cliente %s", customer_name)

            reply_lines = [
                "Hola, %s." % customer_name,
                "Tu último pedido fue %s." % last_order_name,
                "¿Deseas repetirlo?",
            ]
            if top_product:
                product_label = top_product.display_name or top_product.name or "tu producto más comprado"
                reply_lines.extend([
                    "",
                    "Tu producto más comprado es %s." % product_label,
                    "¿Deseas añadirlo al carrito?",
                ])

            greeting_reply = "\n".join(reply_lines)

            buttons = []
            try:
                buttons.append({"label": "Repetir último pedido", "action": "repeat_last_order", "target": "_self"})
                portal_button = self._customer_sale_order_portal_button(last_order, label="Ver último pedido")
                if portal_button:
                    buttons.append(portal_button)
            except Exception:
                _logger.exception("No se pudieron construir botones del último pedido para %s", customer_name)

            if top_product:
                try:
                    buttons.append({
                        "label": "Añadir producto más comprado",
                        "action": "add_most_purchased_product",
                        "target": "_self",
                    })
                    product_button = self._product_open_button_for_current_user(top_product)
                    if product_button:
                        buttons.append(product_button)
                except Exception:
                    _logger.exception("No se pudieron construir botones del producto más comprado para %s", customer_name)

            payload = {
                "success": True,
                "showPersonalGreeting": True,
                "reply": greeting_reply,
                "greetingReply": greeting_reply,
                "safeGreetingReply": greeting_reply,
                "forceGreetingReply": greeting_reply,
                "customerName": customer_name,
                "partnerName": customer_name,
                "customerId": partner.id if partner else False,
                "orderCount": order_count or 1,
                "hasOrders": True,
                "lastOrderId": last_order.id,
                "lastOrderName": last_order_name,
                "topProductId": top_product.id if top_product else False,
                "topProductName": (top_product.display_name or top_product.name or "") if top_product else "",
                "greetingKind": "customer_with_orders",
            }
            return _json_response(self._with_action_buttons(payload, buttons))
        except Exception as error:
            _logger.exception("Error en /ai/customer/greeting")
            # Si ocurre un error inesperado, no mostramos una operación genérica ni
            # botones heredados. Como máximo, saludamos por el nombre del usuario.
            try:
                fallback_name = (request.env.user.sudo().partner_id.name or request.env.user.sudo().name or "cliente").strip()
            except Exception:
                fallback_name = "cliente"
            fallback_reply = "Hola, %s. ¿En qué puedo ayudarte?" % (fallback_name or "cliente")
            return _json_response({
                "success": True,
                "showPersonalGreeting": True,
                "reply": fallback_reply,
                "greetingReply": fallback_reply,
                "safeGreetingReply": fallback_reply,
                "forceGreetingReply": fallback_reply,
                "customerName": fallback_name or "cliente",
                "hasOrders": False,
                "orderCount": 0,
                "actionButtons": [],
                "error": str(error),
            }, status=200)


    # Ruta local v15: saludo contextual robusto para clientes conectados.
    # Esta versión evita el fallo observado en clientes con un único pedido:
    # no depende de respuestas genéricas ni de cálculos externos para construir el texto.
    @http.route(["/ai/customer/greeting_v15", "/ai/customer/greeting_v17", "/ai/customer/greeting_v18", "/ai/customer/greeting_v24"], type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_customer_greeting_v18(self, **kwargs):
        """Devuelve el saludo inicial del cliente conectado sin alterar flujos existentes.

        Solo lee datos del propio cliente autenticado. No crea, modifica ni confirma
        registros. Los privilegios de admin y el resto de rutas permanecen intactos.
        """
        try:
            # Visitante público: no tiene historial ni permisos de cliente, pero el chat
            # debe ofrecer accesos claros para iniciar sesión o crear cuenta.
            # No modifica privilegios ni ejecuta acciones de negocio.
            if not self._is_authenticated_customer_user():
                guest_reply = "Hola, soy tu asistente. ¿En qué puedo ayudarte?"
                return _json_response(self._with_action_buttons({
                    "success": True,
                    "showPersonalGreeting": False,
                    "showGuestActions": True,
                    "reply": guest_reply,
                    "greetingReply": guest_reply,
                    "hasOrders": False,
                    "orderCount": 0,
                }, [
                    {"label": "Login", "url": "/web/login", "target": "_self"},
                    {"label": "Crear cuenta", "url": "/web/signup", "target": "_self"},
                ]))

            if self._is_admin_ai_operator():
                return _json_response({"success": True, "showPersonalGreeting": False})

            user = request.env.user.sudo()
            partner = self._current_customer_commercial_partner()
            customer_name = ((partner.name if partner else "") or user.name or "cliente").strip() or "cliente"

            Order = request.env["sale.order"].sudo()
            order_domain = [
                ("partner_id", "child_of", partner.id if partner else 0),
                ("state", "in", ["sale", "done"]),
            ]
            orders = Order.search(order_domain, order="date_order desc, id desc", limit=50) if partner else Order.browse()
            order_count = len(orders)

            if not orders:
                reply = "Hola, %s. ¿En qué puedo ayudarte?" % customer_name
                return _json_response({
                    "success": True,
                    "showPersonalGreeting": True,
                    "reply": reply,
                    "greetingReply": reply,
                    "safeGreetingReply": reply,
                    "forceGreetingReply": reply,
                    "customerName": customer_name,
                    "partnerName": customer_name,
                    "customerId": partner.id if partner else False,
                    "hasOrders": False,
                    "orderCount": 0,
                    "greetingKind": "customer_without_orders",
                    "actionButtons": [],
                })

            last_order = orders[0].sudo()
            last_order_name = last_order.name or ("Pedido %s" % last_order.id)

            # Caso especial solicitado: si el cliente tiene exactamente un pedido,
            # el saludo debe ser simple, pero conservar solo las acciones de último pedido.
            # No se calcula producto más comprado para evitar respuestas genéricas en cuentas
            # con un único pedido.
            if order_count == 1:
                # Caso especial solicitado para clientes con un único pedido:
                # saludo simple + referencia al único pedido + solo botones de último pedido.
                # No se calcula producto más comprado en este caso para no activar respuestas
                # genéricas ni botones de producto.
                reply = "Hola, %s. ¿En qué puedo ayudarte?\nTu último pedido es: %s" % (customer_name, last_order_name)
                buttons = [
                    {"label": "Repetir último pedido", "action": "repeat_last_order", "target": "_self"},
                ]
                try:
                    portal_button = self._customer_sale_order_portal_button(last_order, label="Ver último pedido")
                    if portal_button:
                        buttons.append(portal_button)
                except Exception:
                    _logger.exception("No se pudo crear botón Ver último pedido en saludo v18 para %s", customer_name)
                payload = {
                    "success": True,
                    "showPersonalGreeting": True,
                    "reply": reply,
                    "greetingReply": reply,
                    "safeGreetingReply": reply,
                    "forceGreetingReply": reply,
                    "customerName": customer_name,
                    "partnerName": customer_name,
                    "customerId": partner.id if partner else False,
                    "hasOrders": True,
                    "orderCount": order_count,
                    "singleOrderGreeting": True,
                    "lastOrderId": last_order.id,
                    "lastOrderName": last_order_name,
                    "topProductId": False,
                    "topProductName": "",
                    "greetingKind": "customer_with_one_order_v18",
                }
                return _json_response(self._with_action_buttons(payload, buttons))

            # Producto más comprado calculado de forma local y tolerante.
            # En cuentas con un único pedido, una lista vacía o una línea especial no debe
            # impedir el saludo del último pedido.
            product_totals = {}
            product_records = {}
            try:
                for order in orders:
                    for line in order.order_line.sudo():
                        if getattr(line, "display_type", False) or not line.product_id:
                            continue
                        product = line.product_id.sudo()
                        qty = float(line.product_uom_qty or 0.0)
                        product_totals[product.id] = product_totals.get(product.id, 0.0) + qty
                        product_records[product.id] = product
            except Exception:
                _logger.exception("No se pudo calcular producto más comprado en saludo v15 para %s", customer_name)
                product_totals = {}
                product_records = {}

            top_product = False
            if product_totals:
                top_product_id = max(product_totals, key=lambda product_id: product_totals.get(product_id, 0.0))
                top_product = product_records.get(top_product_id)

            reply_lines = [
                "Hola, %s." % customer_name,
                "Tu último pedido fue %s." % last_order_name,
                "¿Deseas repetirlo?",
            ]
            if top_product:
                top_product_name = top_product.display_name or top_product.name or "tu producto más comprado"
                reply_lines += [
                    "",
                    "Tu producto más comprado es %s." % top_product_name,
                    "¿Deseas añadirlo al carrito?",
                ]
            else:
                top_product_name = ""

            reply = "\n".join(reply_lines)

            buttons = [
                {"label": "Repetir último pedido", "action": "repeat_last_order", "target": "_self"},
            ]
            try:
                portal_button = self._customer_sale_order_portal_button(last_order, label="Ver último pedido")
                if portal_button:
                    buttons.append(portal_button)
            except Exception:
                _logger.exception("No se pudo crear botón Ver último pedido en saludo v15 para %s", customer_name)

            if top_product:
                buttons.append({"label": "Añadir producto más comprado", "action": "add_most_purchased_product", "target": "_self"})
                try:
                    product_button = self._product_open_button_for_current_user(top_product)
                    if product_button:
                        buttons.append(product_button)
                except Exception:
                    _logger.exception("No se pudo crear botón Ver producto en saludo v15 para %s", customer_name)

            payload = {
                "success": True,
                "showPersonalGreeting": True,
                "reply": reply,
                "greetingReply": reply,
                "safeGreetingReply": reply,
                "forceGreetingReply": reply,
                "customerName": customer_name,
                "partnerName": customer_name,
                "customerId": partner.id if partner else False,
                "hasOrders": True,
                "orderCount": order_count,
                "lastOrderId": last_order.id,
                "lastOrderName": last_order_name,
                "topProductId": top_product.id if top_product else False,
                "topProductName": top_product_name,
                "greetingKind": "customer_with_orders_v15",
            }
            return _json_response(self._with_action_buttons(payload, buttons))
        except Exception as error:
            _logger.exception("Error en /ai/customer/greeting_v18")
            try:
                fallback_name = (request.env.user.sudo().partner_id.name or request.env.user.sudo().name or "cliente").strip()
            except Exception:
                fallback_name = "cliente"
            reply = "Hola, %s. ¿En qué puedo ayudarte?" % (fallback_name or "cliente")
            return _json_response({
                "success": True,
                "showPersonalGreeting": True,
                "reply": reply,
                "greetingReply": reply,
                "safeGreetingReply": reply,
                "forceGreetingReply": reply,
                "customerName": fallback_name or "cliente",
                "hasOrders": False,
                "orderCount": 0,
                "actionButtons": [],
                "error": str(error),
            }, status=200)

    # Ruta local: añade una unidad del producto más comprado por el cliente conectado al carrito.
    @http.route("/ai/customer/cart/add_most_purchased", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_customer_add_most_purchased_product(self, **kwargs):
        try:
            if not self._is_authenticated_customer_user():
                return _json_response({
                    "success": False,
                    "reply": "Para añadir tu producto más comprado al carrito, inicia sesión con tu cuenta de cliente.",
                    "actionButton": {"label": "Iniciar sesión", "url": "/web/login", "target": "_self"},
                }, status=200)

            product, _qty = self._current_customer_most_purchased_product(limit_orders=50)
            if not product:
                return _json_response({
                    "success": False,
                    "reply": "Todavía no encuentro un producto más comprado en tu historial.",
                    "actionButton": {"label": "Mostrar historial", "action": "show_customer_orders", "target": "_self"},
                })

            result = self._add_product_to_cart_response(product, 1.0)
            if result.get("success"):
                result["reply"] = "He añadido 1 unidad de %s al carrito." % (product.display_name or product.name or "tu producto más comprado")
            return _json_response(result, status=200 if result.get("success") else 400)
        except Exception as error:
            _logger.exception("Error en /ai/customer/cart/add_most_purchased")
            return _json_response({"success": False, "reply": "No he podido añadir tu producto más comprado al carrito. Detalle técnico: %s" % error}, status=500)

    # Ruta local: repite el último pedido confirmado añadiendo sus productos al carrito actual.
    @http.route("/ai/customer/orders/repeat_last", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_customer_repeat_last_order(self, **kwargs):
        try:
            if not self._is_authenticated_customer_user():
                return _json_response({
                    "success": False,
                    "reply": "Para repetir tu último pedido, inicia sesión con tu cuenta de cliente.",
                    "actionButton": {"label": "Iniciar sesión", "url": "/web/login", "target": "_self"},
                }, status=200)

            orders = self._get_current_customer_sale_orders(limit=1)
            if not orders:
                return _json_response({
                    "success": False,
                    "reply": "No encuentro pedidos confirmados para repetir.",
                    "actionButton": {"label": "Abrir mis pedidos", "url": "/my/orders", "target": "_self"},
                })

            source_order = orders[0]
            website = request.website
            cart_order = website.sale_get_order(force_create=True)
            if not cart_order:
                raise Exception("No se pudo crear o recuperar el carrito de la sesión.")
            request.session["sale_order_id"] = cart_order.id

            added_lines = []
            skipped_lines = []
            for line in source_order.order_line.filtered(lambda item: not item.display_type and item.product_id):
                product = line.product_id.sudo()
                qty = float(line.product_uom_qty or 0.0)
                if qty <= 0:
                    continue
                if not self._is_product_sellable(product):
                    skipped_lines.append("%s no está marcado como vendible" % (product.display_name or line.name))
                    continue
                availability = self._get_cart_availability(product)
                if availability.get("available_qty", 0.0) < qty:
                    skipped_lines.append("%s: stock insuficiente" % (product.display_name or line.name))
                    continue
                try:
                    cart_order.sudo()._cart_update(product_id=product.id, add_qty=qty)
                    added_lines.append("%s x %s" % (self._format_quantity(qty), product.display_name or line.name))
                except Exception as line_error:
                    _logger.exception("No se pudo repetir una línea del pedido %s", source_order.id)
                    skipped_lines.append("%s: %s" % (product.display_name or line.name, line_error))

            cart_order = request.env["sale.order"].sudo().browse(cart_order.id).exists()
            cart_quantity = self._get_cart_total_quantity(cart_order) if cart_order else 0.0
            request.session["website_sale_cart_quantity"] = cart_quantity

            if not added_lines:
                return _json_response({
                    "success": False,
                    "reply": "No he podido repetir el último pedido porque no hay líneas disponibles para añadir al carrito." + (("\n" + "\n".join(skipped_lines[:6])) if skipped_lines else ""),
                    "actionButton": self._customer_sale_order_portal_button(source_order, label="Ver último pedido"),
                })

            reply = [
                "He añadido al carrito los productos disponibles del último pedido %s." % (source_order.name or source_order.id),
                "Productos añadidos:",
            ]
            reply.extend(["- " + item for item in added_lines[:10]])
            if len(added_lines) > 10:
                reply.append("- ... y %s línea(s) más" % (len(added_lines) - 10))
            if skipped_lines:
                reply.append("\nNo se han añadido estas líneas:")
                reply.extend(["- " + item for item in skipped_lines[:6]])

            return _json_response(self._with_action_buttons({
                "success": True,
                "added": True,
                "cartQuantity": cart_quantity,
                "cartUrl": "/shop/cart",
                "reply": "\n".join(reply),
            }, [
                {"label": "Ver carrito", "url": "/shop/cart", "target": "_self"},
                self._customer_sale_order_portal_button(source_order, label="Ver pedido repetido"),
            ]))
        except Exception as error:
            _logger.exception("Error en /ai/customer/orders/repeat_last")
            return _json_response({"success": False, "reply": "No he podido repetir tu último pedido. Detalle técnico: %s" % error}, status=500)

    # Construye el botón de producto desde el estado pendiente de carrito.
    def _product_open_button_from_pending_cart(self, pending_cart):
        product = self._get_product_from_cart_payload(pending_cart or {})
        if not product:
            return False
        return self._product_open_button_for_current_user(product)

    # Comprueba si el chat debe mostrarse en la página actual.
    @http.route("/ai/chat/status", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_chat_status(self, **kwargs):
        """Devuelve si el widget debe mostrarse en la página actual."""
        try:
            raw_body = request.httprequest.data or b"{}"
            data = json.loads(raw_body.decode("utf-8"))
            enabled = self._is_chat_enabled_for_request(
                page_url=data.get("pageUrl"),
                page_path=data.get("pagePath"),
            )
            return _json_response({"enabled": enabled})
        except Exception as error:
            _logger.exception("Error en /ai/chat/status")
            return _json_response({"enabled": False, "error": str(error)}, status=500)

    # Devuelve al widget las categorías internas o de ventas disponibles.
    @http.route("/ai/product/categories", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_product_categories(self, **kwargs):
        """Devuelve categorías existentes para los desplegables del alta guiada.

        ``kind=product`` devuelve las categorías internas de inventario
        (``product.category`` / campo ``categ_id``).
        ``kind=sale`` devuelve las categorías de ventas/eCommerce
        (``product.public.category`` / campo ``public_categ_ids``).
        """
        try:
            if not self._is_admin_ai_operator():
                return _json_response({"categories": [], "error": "not_allowed"}, status=403)

            try:
                raw_body = request.httprequest.data or b"{}"
                payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except Exception:
                payload = {}
            kind = self._normalize_customer_portal_text(payload.get("kind") or payload.get("categoryKind") or "product")

            if kind in ("sale", "sales", "ventas", "venta", "web", "website", "ecommerce", "public", "publica"):
                categories = self._admin_public_product_category_options(limit=300)
                return _json_response({"categories": categories, "kind": "sale"})

            categories = self._admin_product_category_options(limit=300)
            return _json_response({"categories": categories, "kind": "product"})
        except Exception as error:
            _logger.exception("Error en /ai/product/categories")
            return _json_response({"categories": [], "error": str(error)}, status=500)

    # Devuelve clientes o proveedores para el selector guiado de pedidos.
    @http.route("/ai/order/partners", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_order_partners(self, **kwargs):
        try:
            if not self._is_admin_ai_operator():
                denied = self._admin_permission_denied_response(source="odoo_admin_order_manager")
                denied["partners"] = []
                denied["error"] = "not_allowed"
                return _json_response(denied, status=403)

            try:
                raw_body = request.httprequest.data or b"{}"
                payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except Exception:
                payload = {}

            kind = self._admin_order_kind_from_text(payload.get("kind") or payload.get("orderKind") or "sale") or "sale"
            search = (payload.get("search") or "").strip()
            mode = (payload.get("mode") or "").strip().lower()
            # Para historial de compras el widget debe mostrar una lista corta de proveedores.
            # El buscador local seguirá funcionando sobre esos primeros resultados.
            limit = 6 if mode == "history" and kind == "purchase" else 300
            partners = self._admin_order_partner_options(kind=kind, search=search, limit=limit)
            return _json_response({"partners": partners, "kind": kind, "mode": mode})
        except Exception as error:
            _logger.exception("Error en /ai/order/partners")
            return _json_response({"partners": [], "error": str(error)}, status=500)

    # Crea pedidos de venta o compra desde la selección guiada del widget.
    @http.route("/ai/order/create", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_order_create(self, **kwargs):
        try:
            if not self._is_admin_ai_operator():
                return _json_response(self._admin_permission_denied_response(source="odoo_admin_order_manager"), status=403)

            try:
                raw_body = request.httprequest.data or b"{}"
                payload = json.loads(raw_body.decode("utf-8")) if raw_body else {}
            except Exception:
                payload = {}

            kind = self._admin_order_kind_from_text(payload.get("kind") or payload.get("orderKind") or "sale") or "sale"
            partner_ids = payload.get("partnerIds") or payload.get("partners") or []
            if isinstance(partner_ids, str):
                partner_ids = re.findall(r"\d+", partner_ids)
            clean_partner_ids = []
            for value in partner_ids:
                try:
                    partner_id = int(value)
                except Exception:
                    partner_id = 0
                if partner_id > 0 and partner_id not in clean_partner_ids:
                    clean_partner_ids.append(partner_id)

            result = self._admin_create_order_for_partners_response(kind=kind, partner_ids=clean_partner_ids)
            status = 200 if result.get("success") else 400
            return _json_response(result, status=status)
        except Exception as error:
            _logger.exception("Error en /ai/order/create")
            return _json_response({
                "reply": "No he podido crear el pedido. Detalle técnico: %s" % error,
                "handledLocally": True,
                "source": "odoo_admin_order_manager",
                "success": False,
                "clearPendingCart": True,
            }, status=500)

    # Lee datos JSON o multipart enviados por el widget.
    def _read_chat_request_data(self):
        """Lee la petición del chat en JSON o multipart/form-data.

        Para adjuntar imágenes de producto usamos multipart/form-data. Enviar la
        imagen como base64 dentro de JSON puede romper el parseo del body o la
        sesión cuando la imagen pesa varios MB. Esta lectura mantiene el binario
        fuera del JSON y lo normaliza después al formato interno del addon.
        """
        content_type = (getattr(request.httprequest, "content_type", "") or "").lower()
        has_files = False
        try:
            has_files = bool(request.httprequest.files)
        except Exception:
            has_files = False

        if "multipart/form-data" in content_type or has_files:
            data = {}
            try:
                form = request.httprequest.form
                for key in form.keys():
                    data[key] = form.get(key)
            except Exception:
                data = {}

            for key in ("adminProductCreateClientAnswers", "attachments", "productImage"):
                value = data.get(key)
                if isinstance(value, str):
                    stripped = value.strip()
                    if stripped and stripped[0:1] in ("{", "["):
                        try:
                            data[key] = json.loads(stripped)
                        except Exception:
                            pass

            upload_attachments = self._normalize_uploaded_files_as_chat_attachments()
            if upload_attachments:
                existing = data.get("attachments") or []
                if isinstance(existing, dict):
                    existing = [existing]
                if not isinstance(existing, list):
                    existing = []
                data["attachments"] = existing + upload_attachments
            return data

        raw_body = request.httprequest.data or b"{}"
        if not raw_body:
            return {}
        return json.loads(raw_body.decode("utf-8"))

    # Convierte archivos subidos en adjuntos internos del chat.
    def _normalize_uploaded_files_as_chat_attachments(self):
        """Convierte ficheros multipart en adjuntos internos base64.

        El backend mantiene el mismo formato que ya usa _admin_get_product_image_attachment,
        pero la transferencia desde navegador ya no viaja como JSON gigante.
        """
        attachments = []
        max_raw_size = 8 * 1024 * 1024
        try:
            files = request.httprequest.files
        except Exception:
            files = None
        if not files:
            return attachments

        for field_name in files.keys():
            try:
                uploaded_items = files.getlist(field_name)
            except Exception:
                uploaded_items = [files.get(field_name)]
            for upload in uploaded_items:
                if not upload:
                    continue
                filename = (getattr(upload, "filename", "") or "imagen_producto").strip() or "imagen_producto"
                mimetype = (
                    getattr(upload, "mimetype", "")
                    or getattr(upload, "content_type", "")
                    or ""
                ).strip()
                try:
                    raw = upload.read(max_raw_size + 1)
                except Exception:
                    raw = b""
                if not raw:
                    continue
                if len(raw) > max_raw_size:
                    raise ValueError("La imagen adjunta supera 8 MB. Usa una imagen más ligera.")
                attachments.append({
                    "kind": "product_image",
                    "filename": filename,
                    "mimetype": mimetype,
                    "data": base64.b64encode(raw).decode("ascii"),
                    "size": len(raw),
                })
        return attachments

    # Ruta principal: filtra peticiones locales y solo manda a n8n lo necesario.
    @http.route("/ai/chat/start", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_chat_start(self, **kwargs):
        """Inicia una consulta a n8n y devuelve un job_id inmediatamente.

        Esto evita que el navegador/Odoo espere bloqueado varios minutos mientras
        n8n ejecuta el AI Agent.
        """
        try:
            data = self._read_chat_request_data()

            user_message = (data.get("message") or "").strip()
            session_id = data.get("sessionId") or "odoo-public"
            self._set_request_client_session_id(session_id)
            self._set_request_admin_product_create_client_state(data)
            page_url = data.get("pageUrl") or ""
            page_title = data.get("pageTitle") or ""
            attachments = self._normalize_chat_attachments(data.get("attachments") or data.get("productImage") or [])

            if not self._is_chat_enabled_for_request(page_url=page_url):
                return _json_response({
                    "reply": "El chat no está habilitado en esta página.",
                    "error": "disabled_on_page",
                }, status=403)

            client_state_for_empty = self._get_request_admin_product_create_client_state()
            has_client_product_create_state = bool(
                self._admin_product_create_is_valid_field_key(str(client_state_for_empty.get("awaiting") or "").strip())
                or (client_state_for_empty.get("answers") if isinstance(client_state_for_empty.get("answers"), dict) else {})
            )
            if not user_message and not self._get_session_pending_admin_product_create() and not has_client_product_create_state and not attachments:
                return _json_response({"reply": "No he recibido ningún mensaje."}, status=400)

            current_user_reply = self._try_handle_current_user_turn(user_message=user_message)
            if current_user_reply:
                return _json_response(current_user_reply)

            lightweight_reply = self._try_handle_lightweight_local_turn(user_message=user_message)
            if lightweight_reply:
                return _json_response(lightweight_reply)

            # El alta de cuenta/usuario portal debe evaluarse antes que la
            # gestión administrativa genérica de clientes. Si no, frases como
            # "crear cuenta" acaban creando solo un res.partner y se pierde el
            # flujo guiado que pide nombre, email y contraseña.
            customer_portal_reply = self._try_handle_customer_portal_turn(user_message=user_message)
            if customer_portal_reply:
                return _json_response(customer_portal_reply)

            admin_management_reply = self._try_handle_admin_management_turn(
                user_message=user_message,
                page_title=page_title,
                page_url=page_url,
                attachments=attachments,
            )
            if admin_management_reply:
                return _json_response(admin_management_reply)

            cart_reply = self._try_handle_cart_turn(
                user_message=user_message,
                page_title=page_title,
                page_url=page_url,
            )
            if cart_reply:
                return _json_response(cart_reply)

            local_reply = self._try_build_local_product_reply(
                user_message=user_message,
                page_title=page_title,
                page_url=page_url,
            )
            if local_reply:
                if isinstance(local_reply, dict):
                    payload = dict(local_reply)
                    payload.setdefault("reply", "")
                    payload.setdefault("handledLocally", True)
                    payload.setdefault("source", "odoo_inventory")
                else:
                    payload = {
                        "reply": local_reply,
                        "handledLocally": True,
                        "source": "odoo_inventory",
                    }
                pending_cart = self._get_session_pending_cart()
                if pending_cart:
                    payload["pendingCart"] = pending_cart
                    # Al consultar un producto, mostramos el acceso directo correcto:
                    # admin abre ficha backend; clientes/portal/público abren ficha web.
                    action_button = self._product_open_button_from_pending_cart(pending_cart)
                    if action_button:
                        payload["actionButton"] = action_button
                return _json_response(payload)

            webhook_url = _get_configured_webhook_url()
            if not webhook_url:
                return _json_response({
                    "reply": "La URL del webhook de n8n no está configurada en Ajustes → Odoo AI Chat.",
                    "error": "missing_webhook_url",
                }, status=500)

            product_context = self._build_ai_product_context_if_needed(user_message=user_message)
            enriched_message = self._build_prompt(user_message, page_url, page_title, product_context)
            current_user_context = self._build_current_user_context_payload()
            payload = {
                "message": enriched_message,
                "userMessage": user_message,
                "sessionId": session_id,
                "pageUrl": page_url,
                "pageTitle": page_title,
                "odooCurrentUser": current_user_context,
                "odooAiPermissions": self._build_ai_permissions_payload(),
                "odooProductContext": product_context if self._should_include_product_context_for_ai(user_message) else "",
                "odooProductSource": "Inventario → Productos / product.product" if self._should_include_product_context_for_ai(user_message) else "",
                "odooAttachments": self._build_attachment_context_for_n8n(attachments),
                "source": "odoo_ai_chat",
                "expectedResponseField": "reply",
            }

            job_id = uuid.uuid4().hex
            with _AI_CHAT_JOBS_LOCK:
                _cleanup_old_jobs_unlocked()
                _AI_CHAT_JOBS[job_id] = {
                    "status": "pending",
                    "reply": "",
                    "error": False,
                    "created_at": time.time(),
                    "updated_at": time.time(),
                }

            thread = threading.Thread(
                target=_call_n8n_in_background,
                args=(job_id, webhook_url, payload),
                daemon=True,
            )
            thread.start()

            return _json_response({"jobId": job_id, "status": "pending"})

        except Exception as error:
            _logger.exception("Error en /ai/chat/start")
            detail = str(error or "error desconocido")
            return _json_response({
                "reply": "Ha ocurrido un error al iniciar la consulta con el flujo de IA. Detalle técnico: %s" % detail,
                "error": detail,
            }, status=500)

    # Devuelve al navegador el resultado de una consulta a n8n en segundo plano.
    @http.route("/ai/chat/result", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_chat_result(self, **kwargs):
        """Devuelve el estado o resultado de una consulta iniciada con /ai/chat/start."""
        try:
            raw_body = request.httprequest.data or b"{}"
            data = json.loads(raw_body.decode("utf-8"))
            job_id = (data.get("jobId") or "").strip()
            if not job_id:
                return _json_response({"status": "error", "reply": "Falta jobId.", "error": "missing_job_id"}, status=400)

            with _AI_CHAT_JOBS_LOCK:
                _cleanup_old_jobs_unlocked()
                job = dict(_AI_CHAT_JOBS.get(job_id) or {})

            if not job:
                return _json_response({
                    "status": "error",
                    "reply": "La consulta ha caducado o no existe. Vuelve a enviar el mensaje.",
                    "error": "job_not_found",
                }, status=404)

            return _json_response({
                "status": job.get("status") or "pending",
                "reply": job.get("reply") or "",
                "error": job.get("error") or False,
            })

        except Exception as error:
            _logger.exception("Error en /ai/chat/result")
            return _json_response({
                "status": "error",
                "reply": "Ha ocurrido un error al leer la respuesta del flujo de IA.",
                "error": str(error),
            }, status=500)

    # Ruta heredada de chat que mantiene compatibilidad con llamadas síncronas.
    @http.route("/ai/chat", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_chat(self, **kwargs):
        try:
            data = self._read_chat_request_data()

            user_message = (data.get("message") or "").strip()
            session_id = data.get("sessionId") or "odoo-public"
            self._set_request_client_session_id(session_id)
            self._set_request_admin_product_create_client_state(data)
            page_url = data.get("pageUrl") or ""
            page_title = data.get("pageTitle") or ""
            attachments = self._normalize_chat_attachments(data.get("attachments") or data.get("productImage") or [])

            if not self._is_chat_enabled_for_request(page_url=page_url):
                return _json_response({
                    "reply": "El chat no está habilitado en esta página.",
                    "error": "disabled_on_page",
                }, status=403)

            client_state_for_empty = self._get_request_admin_product_create_client_state()
            has_client_product_create_state = bool(
                self._admin_product_create_is_valid_field_key(str(client_state_for_empty.get("awaiting") or "").strip())
                or (client_state_for_empty.get("answers") if isinstance(client_state_for_empty.get("answers"), dict) else {})
            )
            if not user_message and not self._get_session_pending_admin_product_create() and not has_client_product_create_state and not attachments:
                return _json_response({"reply": "No he recibido ningún mensaje."})

            current_user_reply = self._try_handle_current_user_turn(user_message=user_message)
            if current_user_reply:
                return _json_response(current_user_reply)

            lightweight_reply = self._try_handle_lightweight_local_turn(user_message=user_message)
            if lightweight_reply:
                return _json_response(lightweight_reply)

            # El alta de cuenta/usuario portal debe evaluarse antes que la
            # gestión administrativa genérica de clientes. Si no, frases como
            # "crear cuenta" acaban creando solo un res.partner y se pierde el
            # flujo guiado que pide nombre, email y contraseña.
            customer_portal_reply = self._try_handle_customer_portal_turn(user_message=user_message)
            if customer_portal_reply:
                return _json_response(customer_portal_reply)

            admin_management_reply = self._try_handle_admin_management_turn(
                user_message=user_message,
                page_title=page_title,
                page_url=page_url,
                attachments=attachments,
            )
            if admin_management_reply:
                return _json_response(admin_management_reply)

            cart_reply = self._try_handle_cart_turn(
                user_message=user_message,
                page_title=page_title,
                page_url=page_url,
            )
            if cart_reply:
                return _json_response(cart_reply)

            local_reply = self._try_build_local_product_reply(
                user_message=user_message,
                page_title=page_title,
                page_url=page_url,
            )
            if local_reply:
                if isinstance(local_reply, dict):
                    payload = dict(local_reply)
                    payload.setdefault("reply", "")
                    payload.setdefault("handledLocally", True)
                    payload.setdefault("source", "odoo_inventory")
                else:
                    payload = {
                        "reply": local_reply,
                        "handledLocally": True,
                        "source": "odoo_inventory",
                    }
                pending_cart = self._get_session_pending_cart()
                if pending_cart:
                    payload["pendingCart"] = pending_cart
                    # Al consultar un producto, mostramos el acceso directo correcto:
                    # admin abre ficha backend; clientes/portal/público abren ficha web.
                    action_button = self._product_open_button_from_pending_cart(pending_cart)
                    if action_button:
                        payload["actionButton"] = action_button
                return _json_response(payload)

            webhook_url = _get_configured_webhook_url()
            if not webhook_url:
                return _json_response({
                    "reply": "La URL del webhook de n8n no está configurada en Ajustes → Odoo AI Chat.",
                    "error": "missing_webhook_url",
                }, status=500)

            product_context = self._build_ai_product_context_if_needed(user_message=user_message)
            enriched_message = self._build_prompt(user_message, page_url, page_title, product_context)
            include_product_context = self._should_include_product_context_for_ai(user_message)

            _logger.info("Odoo AI Chat: llamando a n8n webhook legacy: %s", webhook_url)
            response = requests.post(
                webhook_url,
                json={
                    "message": enriched_message,
                    "userMessage": user_message,
                    "sessionId": session_id,
                    "pageUrl": page_url,
                    "pageTitle": page_title,
                    "odooCurrentUser": self._build_current_user_context_payload(),
                    "odooAiPermissions": self._build_ai_permissions_payload(),
                    "odooProductContext": product_context if include_product_context else "",
                    "odooProductSource": "Inventario → Productos / product.product" if include_product_context else "",
                    "odooAttachments": self._build_attachment_context_for_n8n(attachments),
                    "source": "odoo_ai_chat",
                    "expectedResponseField": "reply",
                },
                # El flujo de n8n con IA puede tardar más de 120 segundos.
                # Usamos timeout separado: 10s para conectar y 300s para leer respuesta.
                timeout=(10, 900),
            )
            response.raise_for_status()

            reply = self._extract_reply_from_n8n_response(response)
            if not reply:
                reply = "No he podido generar una respuesta."

            return _json_response({"reply": reply})

        except Exception as error:
            _logger.exception("Error en /ai/chat")
            return _json_response({
                "reply": "Ha ocurrido un error al contactar con el flujo de IA.",
                "error": str(error),
            }, status=500)

    # Valida y normaliza los adjuntos recibidos desde el widget.
    def _normalize_chat_attachments(self, attachments):
        """Normaliza los adjuntos enviados por el widget para uso local.

        El widget envía las imágenes como base64 puro para poder asignarlas a
        campos binarios de Odoo, por ejemplo product.template.image_1920.
        """
        if not attachments:
            return []
        if isinstance(attachments, dict):
            attachments = [attachments]
        if not isinstance(attachments, list):
            return []

        normalized = []
        for item in attachments:
            if not isinstance(item, dict):
                continue
            data = item.get("data") or item.get("base64") or item.get("content") or ""
            if isinstance(data, str) and data.startswith("data:") and "," in data:
                header, data = data.split(",", 1)
                if not item.get("mimetype") and ";" in header:
                    item = dict(item, mimetype=header.split(";", 1)[0].replace("data:", ""))
            normalized.append({
                "kind": item.get("kind") or item.get("type") or "attachment",
                "filename": item.get("filename") or item.get("name") or "imagen_producto",
                "mimetype": item.get("mimetype") or item.get("mimeType") or item.get("contentType") or "",
                "data": data,
                "size": item.get("size") or 0,
            })
        return normalized

    # Resume adjuntos para que n8n conozca su existencia sin recibir archivos pesados.
    def _build_attachment_context_for_n8n(self, attachments):
        """Envía a n8n solo metadatos, no el binario completo."""
        context = []
        for attachment in self._normalize_chat_attachments(attachments):
            context.append({
                "kind": attachment.get("kind") or "attachment",
                "filename": attachment.get("filename") or "",
                "mimetype": attachment.get("mimetype") or "",
                "size": attachment.get("size") or 0,
                "hasData": bool(attachment.get("data")),
            })
        return context

    # Adaptador de compatibilidad para extraer texto desde respuestas de n8n.
    def _extract_reply_from_n8n_response(self, response):
        """Extrae la respuesta de n8n aunque venga en formatos distintos."""
        return _extract_reply_from_n8n_http_response(response)

    # Adaptador de compatibilidad para extraer valores de respuesta.
    def _extract_reply_value(self, payload):
        return _extract_reply_value_from_payload(payload)

    # Lee las páginas configuradas donde se permite mostrar el chat.
    def _get_selected_page_ids(self):
        raw_page_ids = request.env["ir.config_parameter"].sudo().get_param("odoo_ai_chat.page_ids", default="") or ""
        page_ids = []
        for value in raw_page_ids.split(","):
            value = value.strip()
            if value.isdigit():
                page_ids.append(int(value))
        return raw_page_ids.strip(), page_ids

    # Normaliza rutas y URLs para compararlas con páginas de Odoo.
    def _normalize_path(self, value):
        if not value:
            return "/"

        value = str(value).strip()
        if value.startswith("http://") or value.startswith("https://"):
            value = urlparse(value).path or "/"
        else:
            value = value.split("?", 1)[0].split("#", 1)[0] or "/"

        if not value.startswith("/"):
            value = "/" + value

        if len(value) > 1 and value.endswith("/"):
            value = value.rstrip("/")

        return value or "/"

    # Obtiene de forma segura el sitio web actual.
    def _get_current_website_id(self):
        try:
            website = getattr(request, "website", False)
            if website:
                return website.id
        except Exception:
            pass
        return False

    # Valida si la página solicitada tiene habilitado el chatbot.
    def _is_chat_enabled_for_request(self, page_url=None, page_path=None):
        raw_page_ids, page_ids = self._get_selected_page_ids()

        # Modo estricto: el chat solo se muestra en páginas seleccionadas.
        # Si no hay páginas configuradas, no se muestra en ninguna página.
        if not raw_page_ids:
            return False

        pages = request.env["website.page"].sudo().browse(page_ids).exists()
        if not pages:
            return False

        current_path = self._normalize_path(page_path or page_url or request.httprequest.path)
        current_website_id = self._get_current_website_id()

        for page in pages:
            page_path = self._normalize_path(page.url)
            if current_path != page_path:
                continue

            # En multiwebsite puede haber varias páginas con la misma URL, por ejemplo
            # Home en / para b2b.optimaluz y Home en / para efectoled. Comparamos también
            # la web para que no se active en otra web que tenga la misma ruta.
            page_website_id = page.website_id.id if page.website_id else False
            if page_website_id and current_website_id and page_website_id != current_website_id:
                continue

            return True

        return False

    # -------------------------------------------------------------------------
    # Identificación del usuario actual desde el chat
    # -------------------------------------------------------------------------

    # Detecta preguntas sobre el usuario autenticado actual.
    def _looks_like_current_user_question(self, message):
        """Detecta preguntas del visitante sobre la sesión/usuario actual."""
        normalized = self._normalize_customer_portal_text(message or "")
        if not normalized:
            return False

        explicit_phrases = (
            "quien soy", "quien soy yo", "dime quien soy", "dime quien soy yo",
            "identificame", "identifica mi usuario", "mi usuario actual",
            "usuario actual", "usuario conectado", "usuario logueado",
            "usuario logado", "usuario de esta sesion", "usuario de la sesion",
            "con que usuario estoy", "con que usuario estoy trabajando",
            "que usuario soy", "que usuario tengo", "cual es mi usuario",
            "cual es el usuario actual", "con que cuenta estoy",
            "con que cuenta estoy trabajando", "cuenta actual", "mi cuenta",
            "que cuenta soy", "cual es mi cuenta", "estoy conectado",
            "estoy logueado", "estoy logado", "sesion actual",
            "dime mi login", "cual es mi login", "mi login",
        )
        if self._contains_customer_portal_phrase(normalized, explicit_phrases):
            return True

        return bool(re.search(
            r"\b(?:quien\s+soy|que\s+usuario\s+soy|cual\s+es\s+mi\s+usuario|con\s+que\s+(?:usuario|cuenta)\s+estoy)\b",
            normalized,
            flags=re.IGNORECASE,
        ))

    # Comprueba permisos/grupos de usuario sin romper si falla el XML ID.
    def _safe_has_group(self, user, group_xml_id):
        try:
            return bool(user.has_group(group_xml_id))
        except Exception:
            return False

    # Busca una referencia XML de Odoo sin lanzar excepción si no existe.
    def _env_ref_safe(self, xml_id):
        try:
            return request.env.ref(xml_id, raise_if_not_found=False)
        except TypeError:
            try:
                return request.env.ref(xml_id)
            except Exception:
                return False
        except Exception:
            return False

    # Detecta si el usuario actual es el usuario público del sitio web.
    def _is_public_website_user(self, user):
        if not user:
            return True
        try:
            if hasattr(user, "_is_public") and user._is_public():
                return True
        except Exception:
            pass
        try:
            website = getattr(request, "website", False)
            website_public_user = website.user_id if website else False
            if website_public_user and user.id == website_public_user.id:
                return True
        except Exception:
            pass
        public_user = self._env_ref_safe("base.public_user")
        try:
            if public_user and user.id == public_user.id:
                return True
        except Exception:
            pass
        return False

    # Genera una etiqueta legible para el tipo de usuario actual.
    def _current_user_type_label(self, user):
        if self._is_public_website_user(user):
            return "Visitante público"
        if self._safe_has_group(user, "base.group_user"):
            return "Usuario interno"
        if self._safe_has_group(user, "base.group_portal"):
            return "Usuario de portal"
        return "Usuario externo"

    # Responde localmente a preguntas sobre el usuario sin llamar a n8n.
    def _try_handle_current_user_turn(self, user_message=None):
        """Responde localmente quién es el usuario conectado en la sesión web."""
        text = (user_message or "").strip()
        if not self._looks_like_current_user_question(text):
            return None

        # Al cambiar de intención, limpiamos operaciones locales pendientes para
        # que el chat no quede esperando cantidad, email, contraseña, etc.
        self._clear_session_pending_cart()
        self._clear_session_pending_customer_portal()
        self._clear_session_pending_admin_product_create()

        user = request.env.user
        if self._is_public_website_user(user):
            return {
                "reply": (
                    "Ahora mismo estás navegando como visitante público. "
                    "No hay ningún usuario de cliente autenticado en esta sesión."
                ),
                "handledLocally": True,
                "source": "odoo_current_user",
                "clearPendingCart": True,
                "clearPendingCustomerPortal": True,
                "clearPendingAdminProductCreate": True,
            }

        sudo_user = user.sudo()
        partner = sudo_user.partner_id.sudo() if getattr(sudo_user, "partner_id", False) else False
        name = sudo_user.name or (partner.name if partner else "") or sudo_user.login or "Usuario sin nombre"
        login = sudo_user.login or ""
        email = sudo_user.email or (partner.email if partner else "") or ""
        user_type = self._current_user_type_label(user)

        lines = [
            "Estás trabajando con este usuario de Odoo:",
            f"Nombre: {name}",
        ]
        if login:
            lines.append(f"Login: {login}")
        if email:
            lines.append(f"Email: {email}")
        lines.append(f"Tipo: {user_type}")

        return {
            "reply": "\n".join(lines),
            "handledLocally": True,
            "source": "odoo_current_user",
            "userId": sudo_user.id,
            "partnerId": partner.id if partner else False,
            "userType": user_type,
            "clearPendingCart": True,
            "clearPendingCustomerPortal": True,
            "clearPendingAdminProductCreate": True,
            "clearPendingAdminOrderCreate": True,
        }

    # -------------------------------------------------------------------------
    # Respuestas locales ligeras para reducir consumo de IA
    # -------------------------------------------------------------------------

    # Detecta saludos y preguntas simples para ahorrar tokens de IA.
    def _looks_like_lightweight_local_message(self, message):
        """Detecta saludos/preguntas simples para no enviar contexto grande a n8n."""
        normalized = self._normalize_customer_portal_text(message or "")
        if not normalized:
            return False

        # Mensajes muy habituales que no necesitan IA ni contexto de inventario.
        exact_messages = {
            "hola", "buenas", "buenos dias", "buenas tardes", "buenas noches",
            "hello", "hi", "hey", "saludos", "ok", "vale", "gracias", "muchas gracias",
        }
        if normalized in exact_messages:
            return True

        greeting_patterns = (
            r"^(hola|buenas|buenos dias|buenas tardes|buenas noches|saludos)[\s,!\.¿?]*$",
            r"^(hola|buenas|saludos).{0,35}(puedes ayudar|ayuda|que haces|en que me puedes ayudar)",
            r"^(en que me puedes ayudar|que puedes hacer|como me puedes ayudar|ayuda)$",
        )
        return any(re.search(pattern, normalized, flags=re.IGNORECASE) for pattern in greeting_patterns)

    # Contesta localmente mensajes simples y evita llamar a n8n.
    def _try_handle_lightweight_local_turn(self, user_message=None):
        """Contesta saludos y ayuda básica sin llamar a n8n.

        Esto evita consumos elevados de tokens en mensajes simples como "hola", porque
        no se manda el inventario completo ni el contexto de Odoo al modelo.
        """
        if not self._looks_like_lightweight_local_message(user_message):
            return None

        self._clear_session_pending_cart()
        self._clear_session_pending_customer_portal()
        self._clear_session_pending_admin_product_create()

        is_admin = self._is_admin_ai_operator()
        if is_admin:
            reply = (
                "Hola, ¿en qué puedo ayudarte?\n"
                "Puedo ayudarte con consultas de productos y stock, carrito, clientes y creación o modificación de productos en Odoo."
            )
        else:
            reply = (
                "Hola, ¿en qué puedo ayudarte?\n"
                "Puedo ayudarte con información de productos, disponibilidad y carrito."
            )

        return {
            "reply": reply,
            "handledLocally": True,
            "source": "odoo_lightweight_local",
            "skipAI": True,
            "clearPendingCart": True,
            "clearPendingCustomerPortal": True,
            "clearPendingAdminProductCreate": True,
        }

    # -------------------------------------------------------------------------
    # Administración desde el chat para usuario admin
    # -------------------------------------------------------------------------

    # Comprueba si el usuario tiene permiso para acciones administrativas desde IA.
    def _is_admin_ai_operator(self):
        """Permite operaciones administrativas únicamente a la cuenta con login admin."""
        try:
            user = request.env.user
            if self._is_public_website_user(user):
                return False
            sudo_user = user.sudo()
            login = (sudo_user.login or "").strip().lower()
            return login == "admin"
        except Exception:
            return False

    # Respuesta única para intentos administrativos sin permisos.
    def _admin_permission_denied_response(self, source="odoo_admin_manager"):
        self._clear_session_pending_cart()
        self._clear_session_pending_customer_portal()
        self._clear_session_pending_admin_product_create()
        return {
            "reply": (
                "Por seguridad, solo la cuenta Admin puede crear, modificar o borrar "
                "productos, cuentas de cliente y pedidos desde la IA. "
                "Con esta cuenta solo puedo ayudarte a buscar productos por referencia, "
                "código, nombre o categoría, consultar disponibilidad y añadir productos al carrito."
            ),
            "handledLocally": True,
            "source": source,
            "success": False,
            "securityBlocked": True,
            "clearPendingCart": True,
            "clearPendingCustomerPortal": True,
            "clearPendingAdminProductCreate": True,
        }

    # Devuelve las acciones disponibles para la cuenta actual. Lo usa el botón
    # "¿Qué puedo hacer?" del frontend. No ejecuta ninguna acción de negocio:
    # solo genera botones que lanzan prompts existentes, respetando privilegios.
    @http.route("/ai/account/capabilities", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_account_capabilities(self, **kwargs):
        try:
            def prompt_button(label, prompt):
                return {"label": label, "action": "send_prompt::%s" % prompt, "target": "_self"}

            if self._is_public_website_user(request.env.user):
                return _json_response(self._with_action_buttons({
                    "success": True,
                    "reply": "No has iniciado sesión. Puedes iniciar sesión, crear una cuenta o buscar productos.",
                    "source": "odoo_ai_capabilities",
                }, [
                    {"label": "Login", "url": "/web/login", "target": "_self"},
                    {"label": "Crear cuenta", "url": "/web/signup", "target": "_self"},
                    prompt_button("Buscar producto", "SKU: "),
                ]))

            if self._is_admin_ai_operator():
                return _json_response(self._with_action_buttons({
                    "success": True,
                    "reply": "Con la cuenta Admin puedo ayudarte con estas funciones:",
                    "source": "odoo_ai_capabilities",
                }, [
                    prompt_button("Buscar producto", "SKU: "),
                    prompt_button("Crear producto", "crear producto"),
                    prompt_button("Modificar producto", "modificar producto"),
                    prompt_button("Crear cliente", "crear cliente"),
                    prompt_button("Crear pedido de venta", "Crear pedido de venta"),
                    prompt_button("Crear pedido de compra", "Crear pedido de compra"),
                    prompt_button("Historial pedido de venta", "historial pedido de venta"),
                    prompt_button("Historial pedido de compra", "historial pedido de compra"),
                ]))

            return _json_response(self._with_action_buttons({
                "success": True,
                "reply": "Con esta cuenta puedo ayudarte con estas funciones:",
                "source": "odoo_ai_capabilities",
            }, [
                prompt_button("Buscar producto", "SKU: "),
                prompt_button("Mi cuenta", "mi cuenta"),
                prompt_button("Mi historial de pedidos", "historial pedidos"),
                prompt_button("Repetir último pedido", "repetir último pedido"),
                {"label": "Ver carrito", "url": "/shop/cart", "target": "_self"},
            ]))
        except Exception:
            _logger.exception("Error en /ai/account/capabilities")
            return _json_response({
                "success": False,
                "reply": "No he podido consultar las acciones disponibles para esta cuenta.",
            }, status=500)

    # Construye un resumen del usuario actual para el contexto de IA.
    def _build_current_user_context_payload(self):
        """Contexto estructurado del usuario para n8n y para auditoría local."""
        try:
            user = request.env.user
            if self._is_public_website_user(user):
                return {
                    "authenticated": False,
                    "name": "Visitante público",
                    "login": "",
                    "email": "",
                    "userType": "Visitante público",
                    "isAdminAIAllowed": False,
                }

            sudo_user = user.sudo()
            partner = sudo_user.partner_id.sudo() if getattr(sudo_user, "partner_id", False) else False
            company = sudo_user.company_id.sudo() if getattr(sudo_user, "company_id", False) else request.env.company.sudo()
            return {
                "authenticated": True,
                "id": sudo_user.id,
                "name": sudo_user.name or (partner.name if partner else "") or sudo_user.login or "",
                "login": sudo_user.login or "",
                "email": sudo_user.email or (partner.email if partner else "") or "",
                "userType": self._current_user_type_label(user),
                "isAdminAIAllowed": self._is_admin_ai_operator(),
                "partner": {
                    "id": partner.id if partner else False,
                    "name": partner.name if partner else "",
                    "email": partner.email if partner else "",
                },
                "company": {
                    "id": company.id if company else False,
                    "name": company.name if company else "",
                },
                "lang": sudo_user.lang or request.env.lang or "",
            }
        except Exception as error:
            _logger.exception("No se pudo construir contexto de usuario actual")
            return {
                "authenticated": False,
                "name": "No disponible",
                "login": "",
                "email": "",
                "userType": "No disponible",
                "isAdminAIAllowed": False,
                "error": str(error),
            }

    # Permisos efectivos que también se envían a n8n para que el workflow no ejecute acciones prohibidas.
    def _build_ai_permissions_payload(self):
        is_admin = self._is_admin_ai_operator()
        return {
            "canManageProducts": is_admin,
            "canDeleteProducts": False,
            "canManageCustomers": is_admin,
            "canCreatePortalUsers": is_admin,
            "canCreateSaleOrders": is_admin,
            "canCreatePurchaseOrders": is_admin,
            "canSearchProducts": True,
            "canReadProductAvailability": True,
            "canAddToCart": True,
            "adminPolicy": "Solo el usuario con login admin puede crear o modificar productos, gestionar cuentas de cliente y crear pedidos de venta o compra desde la IA. El borrado o archivado de productos está bloqueado para todos: debe responder que contacte con la empresa.",
        }

    # Formatea el usuario actual dentro del prompt enviado a n8n.
    def _format_current_user_context_for_prompt(self):
        context = self._build_current_user_context_payload()
        if not context.get("authenticated"):
            return "Usuario no autenticado: visitante público."

        lines = [
            "Usuario autenticado en Odoo:",
            "- Nombre: %s" % (context.get("name") or "No disponible"),
            "- Login: %s" % (context.get("login") or "No disponible"),
            "- Email: %s" % (context.get("email") or "No disponible"),
            "- Tipo: %s" % (context.get("userType") or "No disponible"),
            "- Permisos administrativos IA: %s" % ("sí" if context.get("isAdminAIAllowed") else "no"),
        ]
        partner = context.get("partner") or {}
        if partner.get("id"):
            lines.append("- Partner vinculado: %s [ID %s]" % (partner.get("name") or "", partner.get("id")))
        company = context.get("company") or {}
        if company.get("id"):
            lines.append("- Compañía: %s [ID %s]" % (company.get("name") or "", company.get("id")))
        return "\n".join(lines)

    # Detecta si el mensaje pide una acción administrativa en Odoo.
    def _looks_like_admin_management_intent(self, message):
        # Las acciones de carrito son permitidas para clientes/portal/público y
        # deben llegar al gestor de carrito, no al bloqueo administrativo.
        if self._is_cart_intent(message or ""):
            return False

        normalized = self._normalize_customer_portal_text(message or "")
        if not normalized:
            return False

        product_terms = (
            "producto", "productos", "articulo", "articulos", "inventario", "stock", "existencias", "referencia",
            "sku", "precio", "coste", "costo", "categoria", "publicar", "despublicar",
        )
        customer_terms = (
            "cliente", "clientes", "contacto", "contactos", "cuenta", "cuentas",
            "cuenta de cliente", "cuentas de clientes", "usuario cliente", "partner",
        )
        order_terms = (
            "pedido", "pedidos", "presupuesto", "presupuestos", "orden de venta",
            "ordenes de venta", "órdenes de venta", "pedido de venta", "pedidos de venta",
            "pedido de ventas", "pedidos de ventas", "pedido de compra", "pedidos de compra",
            "orden de compra", "ordenes de compra", "órdenes de compra", "rfq", "solicitud de presupuesto",
        )
        action_terms = (
            "crear", "crea", "nuevo", "nueva", "alta", "dar de alta", "introducir",
            "introduce", "insertar", "inserta", "generar", "genera", "preparar",
            "prepara", "hacer", "haz", "modificar", "modifica", "cambiar",
            "cambia", "actualizar", "actualiza", "editar", "edita", "poner", "pon",
            "establecer", "establece", "asignar", "asigna", "subir", "sube",
            "adjuntar", "adjunta", "cargar", "carga", "borrar", "borra",
            "eliminar", "elimina", "suprimir", "suprime", "archivar", "archiva",
        )
        has_action = any(term in normalized for term in action_terms)
        has_product = any(term in normalized for term in product_terms)
        has_customer = any(term in normalized for term in customer_terms)
        has_order = any(term in normalized for term in order_terms)
        customer_query_terms = (
            "consultar", "consulta", "buscar", "busca", "ver", "mostrar", "muestra",
            "informacion", "información", "datos", "ficha",
        )
        has_customer_query = has_customer and any(term in normalized for term in customer_query_terms)

        # Consultar listados/historiales de compras es una operación interna.
        # Sin esta condición, frases de portal como "ver pedidos compras" podían
        # pasar al buscador de productos y devolver un producto accidentalmente.
        purchase_order_terms = (
            "pedido compra", "pedido compras", "pedidos compra", "pedidos compras",
            "pedido de compra", "pedidos de compra", "orden de compra", "ordenes de compra",
            "órdenes de compra", "compra", "compras", "rfq", "solicitud de presupuesto",
        )
        order_query_terms = (
            "consultar", "consulta", "buscar", "busca", "ver", "mostrar", "muestra",
            "historial", "listado", "lista", "abrir",
        )
        has_purchase_order_query = (
            has_order
            and any(term in normalized for term in purchase_order_terms)
            and any(term in normalized for term in order_query_terms)
        )

        return bool((has_action and (has_product or has_customer or has_order)) or has_customer_query or has_purchase_order_query)

    # Detecta intenciones administrativas que solo un usuario interno puede ejecutar.
    def _looks_like_admin_only_management_intent(self, message):
        """Intenciones que nunca debe ejecutar un visitante público o portal."""
        if self._is_cart_intent(message or ""):
            return False
        normalized = self._normalize_customer_portal_text(message or "")
        if not normalized:
            return False
        if any(term in normalized for term in ("stock", "inventario", "producto", "productos", "articulo", "articulos", "precio", "sku", "referencia")):
            return any(term in normalized for term in (
                "crear", "crea", "nuevo", "modificar", "modifica", "cambiar", "cambia",
                "actualizar", "actualiza", "editar", "edita", "poner", "pon", "establecer",
                "asignar", "subir", "sube", "adjuntar", "adjunta", "cargar", "carga",
                "borrar", "borra", "eliminar", "elimina", "archivar", "archiva",
            ))
        if any(term in normalized for term in ("pedido", "pedidos", "presupuesto", "presupuestos", "orden de venta", "pedido de venta", "pedido de ventas", "orden de compra", "pedido de compra", "rfq")):
            return any(term in normalized for term in ("crear", "crea", "nuevo", "nueva", "alta", "generar", "genera"))
        if any(term in normalized for term in ("borrar", "borra", "eliminar", "elimina", "modificar", "modifica", "actualizar", "actualiza", "editar", "edita")):
            return any(term in normalized for term in ("cliente", "clientes", "contacto", "contactos", "cuenta", "cuentas", "cuenta de cliente"))
        return False

    # Clasifica la acción administrativa solicitada: crear, modificar, borrar o consultar.
    def _admin_action_from_text(self, message):
        normalized = self._normalize_customer_portal_text(message or "")
        if any(term in normalized for term in ("borrar", "borra", "eliminar", "elimina", "suprimir", "suprime", "quitar", "archivar", "archiva")):
            return "delete"
        if any(term in normalized for term in ("crear", "crea", "nuevo", "nueva", "alta", "dar de alta", "introducir", "introduce", "insertar", "inserta", "generar", "genera")):
            return "create"
        if any(term in normalized for term in ("modificar", "modifica", "cambiar", "cambia", "actualizar", "actualiza", "editar", "edita", "poner", "pon", "establecer", "establece", "asignar", "asigna", "subir", "sube", "adjuntar", "adjunta", "cargar", "carga")):
            return "update"
        if any(term in normalized for term in ("consultar", "consulta", "buscar", "busca", "ver", "mostrar", "muestra", "informacion", "información", "datos", "ficha")):
            return "query"
        return "help"

    # Detecta solicitudes para iniciar un alta guiada de producto.
    def _looks_like_new_admin_product_create_request(self, message):
        normalized = self._normalize_customer_portal_text(message or "")
        if not normalized:
            return False
        has_create = any(term in normalized for term in (
            "crear", "crea", "nuevo", "nueva", "alta", "dar de alta",
            "introducir", "introduce", "insertar", "inserta",
        ))
        has_product = any(term in normalized for term in (
            "producto", "productos", "articulo", "articulos", "referencia", "sku",
        ))
        return bool(has_create and has_product)

    # Ejecuta localmente acciones administrativas y evita que n8n las invente.
    def _try_handle_admin_management_turn(self, user_message=None, page_title=None, page_url=None, attachments=None):
        text = (user_message or "").strip()

        # Las acciones de carrito son funcionalidad comercial permitida para usuarios no admin.
        if self._is_cart_intent(text):
            return None

        # No debe interceptar respuestas de un alta de cuenta portal pendiente
        # ni solicitudes explícitas de cuenta/acceso portal. Ese flujo se valida
        # en _try_handle_customer_portal_turn, donde también se aplica la misma
        # restricción de seguridad: solo login admin.
        if self._get_session_pending_customer_portal() or self._looks_like_customer_portal_intent(text):
            return None

        pending_product_create = self._get_session_pending_admin_product_create()
        client_state = self._get_request_admin_product_create_client_state()
        client_pending_product_create = bool(
            self._admin_product_create_is_valid_field_key(str(client_state.get("awaiting") or "").strip())
            or (client_state.get("answers") if isinstance(client_state.get("answers"), dict) else {})
        )
        has_admin_intent = self._looks_like_admin_management_intent(text)
        if not pending_product_create and not client_pending_product_create and not has_admin_intent:
            return None

        is_admin = self._is_admin_ai_operator()
        if not is_admin:
            return self._admin_permission_denied_response(source="odoo_admin_manager")

        if pending_product_create or client_pending_product_create:
            self._clear_session_pending_cart()
            self._clear_session_pending_customer_portal()
            try:
                if self._looks_like_new_admin_product_create_request(text):
                    # Si había un alta de producto antigua bloqueada y el usuario vuelve a pedir
                    # crear un producto/artículo, reiniciamos el asistente guiado en lugar de
                    # interpretar esa frase como respuesta al campo pendiente.
                    self._clear_session_pending_admin_product_create()
                    return self._admin_create_product_response(text, attachments=attachments)
                return self._admin_continue_product_create_flow(text, attachments=attachments)
            except Exception as error:
                _logger.exception("Error continuando el alta guiada de producto")
                return self._admin_product_create_error_response(pending_product_create, error)

        normalized = self._normalize_customer_portal_text(text)

        # Si el admin pide explícitamente crear acceso portal, mantenemos el flujo ya existente.
        if any(term in normalized for term in ("portal", "acceso al portal", "cuenta web", "usuario portal", "password", "contrasena", "contraseña")):
            if any(term in normalized for term in ("cliente", "contacto", "cuenta")) and self._admin_action_from_text(text) == "create":
                return None

        self._clear_session_pending_cart()
        self._clear_session_pending_customer_portal()
        self._clear_session_pending_admin_product_create()

        try:
            if self._looks_like_admin_order_intent(text):
                action = self._admin_action_from_text(text)
                if action == "create":
                    return self._admin_start_order_create_response(text)

            if self._looks_like_admin_stock_intent(text):
                return self._admin_update_stock_response(text, page_title=page_title, page_url=page_url)

            if self._looks_like_admin_product_intent(text):
                action = self._admin_action_from_text(text)
                if action == "create":
                    return self._admin_create_product_response(text, attachments=attachments)
                if action == "delete":
                    return self._admin_delete_product_response(text, page_title=page_title, page_url=page_url)
                if action == "update":
                    return self._admin_update_product_response(text, page_title=page_title, page_url=page_url, attachments=attachments)

            if self._looks_like_admin_customer_intent(text):
                action = self._admin_action_from_text(text)
                if action == "create":
                    return self._admin_create_customer_response(text)
                if action == "delete":
                    return self._admin_delete_customer_response(text)
                if action == "update":
                    return self._admin_update_customer_response(text)
                if action == "query":
                    return self._admin_query_customer_response(text)

            return self._admin_help_response()
        except Exception as error:
            _logger.exception("Error ejecutando acción administrativa desde la IA")
            return {
                "reply": "No he podido ejecutar la acción administrativa. Detalle técnico: %s" % error,
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": False,
                "clearPendingCart": True,
                "clearPendingCustomerPortal": True,
            }

    # Detecta mensajes administrativos relacionados con pedidos de venta o compra.
    def _looks_like_admin_order_intent(self, message):
        normalized = self._normalize_customer_portal_text(message or "")
        if not normalized:
            return False
        has_order = any(term in normalized for term in (
            "pedido", "pedidos", "presupuesto", "presupuestos", "orden de venta",
            "pedido de venta", "pedido de ventas", "orden de compra", "pedido de compra",
            "rfq", "solicitud de presupuesto",
        ))
        has_action = any(term in normalized for term in (
            "crear", "crea", "nuevo", "nueva", "alta", "generar", "genera",
            "preparar", "prepara", "hacer", "haz",
        ))
        return bool(has_order and has_action)

    # Distingue pedido de venta y pedido de compra a partir del texto o del payload del widget.
    def _admin_order_kind_from_text(self, text):
        normalized = self._normalize_customer_portal_text(text or "")
        if any(term in normalized for term in ("purchase", "compra", "compras", "proveedor", "proveedores", "rfq", "solicitud de presupuesto")):
            return "purchase"
        if any(term in normalized for term in ("sale", "venta", "ventas", "cliente", "clientes", "presupuesto")):
            return "sale"
        return "sale"

    # Devuelve la etiqueta humana del tipo de pedido.
    def _admin_order_kind_label(self, kind):
        return "compra" if kind == "purchase" else "venta"

    # Devuelve el modelo de partner que debe mostrarse en el selector.
    def _admin_order_partner_role_label(self, kind, plural=False):
        if kind == "purchase":
            return "proveedores" if plural else "proveedor"
        return "clientes" if plural else "cliente"

    # Construye la lista de clientes/proveedores disponibles para crear pedidos.
    def _admin_order_partner_options(self, kind="sale", search="", limit=300):
        Partner = request.env["res.partner"].sudo()
        domain = [("active", "=", True)] if "active" in Partner._fields else []
        kind = "purchase" if kind == "purchase" else "sale"

        if kind == "purchase" and "supplier_rank" in Partner._fields:
            domain.append(("supplier_rank", ">", 0))
        elif kind == "sale" and "customer_rank" in Partner._fields:
            domain.append(("customer_rank", ">", 0))

        search = (search or "").strip()
        if search:
            search_domain = ["|", "|", ("name", "ilike", search), ("email", "ilike", search), ("phone", "ilike", search)]
            domain = expression.AND([domain, search_domain]) if domain else search_domain

        partners = Partner.search(domain, order="name asc", limit=limit)

        # Si todavía no hay rankings de cliente/proveedor, mostramos contactos activos como respaldo.
        if not partners and not search:
            fallback_domain = [("active", "=", True)] if "active" in Partner._fields else []
            partners = Partner.search(fallback_domain, order="name asc", limit=limit)

        options = []
        for partner in partners:
            name = partner.display_name or partner.name or "Contacto %s" % partner.id
            extra_parts = []
            if getattr(partner, "email", False):
                extra_parts.append(partner.email)
            if getattr(partner, "phone", False):
                extra_parts.append(partner.phone)
            label = name + (" — " + " · ".join(extra_parts) if extra_parts else "")
            options.append({
                "id": partner.id,
                "name": name,
                "email": getattr(partner, "email", "") or "",
                "phone": getattr(partner, "phone", "") or "",
                "label": label,
            })
        return options

    # Inicia el selector de clientes/proveedores para crear pedidos desde la IA.
    def _admin_start_order_create_response(self, text):
        kind = self._admin_order_kind_from_text(text)
        role_plural = self._admin_order_partner_role_label(kind, plural=True)
        order_label = self._admin_order_kind_label(kind)
        self._clear_session_pending_cart()
        self._clear_session_pending_customer_portal()
        self._clear_session_pending_admin_product_create()
        return {
            "reply": (
                "Selecciona uno o varios %s en el buscador inferior y pulsa Crear para generar "
                "el pedido de %s en Odoo." % (role_plural, order_label)
            ),
            "handledLocally": True,
            "source": "odoo_admin_order_manager",
            "success": True,
            "pendingAdminOrderCreate": True,
            "orderPartnerSelection": {
                "kind": kind,
                "partnerRole": self._admin_order_partner_role_label(kind, plural=False),
                "partnerRolePlural": role_plural,
                "orderLabel": order_label,
            },
            "clearPendingCart": True,
            "clearPendingCustomerPortal": True,
            "clearPendingAdminProductCreate": True,
        }

    # Crea uno o varios pedidos de venta/compra para los partners seleccionados.
    def _admin_create_order_for_partners_response(self, kind="sale", partner_ids=None):
        kind = "purchase" if kind == "purchase" else "sale"
        partner_ids = partner_ids or []
        role_singular = self._admin_order_partner_role_label(kind, plural=False)
        role_plural = self._admin_order_partner_role_label(kind, plural=True)
        order_kind_label = self._admin_order_kind_label(kind)

        if not partner_ids:
            return {
                "reply": "Selecciona al menos un %s antes de pulsar Crear." % role_singular,
                "handledLocally": True,
                "source": "odoo_admin_order_manager",
                "success": False,
                "pendingAdminOrderCreate": True,
            }

        Partner = request.env["res.partner"].sudo()
        partners = Partner.browse(partner_ids).exists()
        if not partners:
            return {
                "reply": "No he encontrado los %s seleccionados. Recarga la lista y vuelve a intentarlo." % role_plural,
                "handledLocally": True,
                "source": "odoo_admin_order_manager",
                "success": False,
            }

        created_orders = []
        if kind == "purchase":
            Order = request.env["purchase.order"].sudo()
            for partner in partners:
                vals = {"partner_id": partner.id}
                if "origin" in Order._fields:
                    vals["origin"] = "Creado desde IA"
                order = Order.create(vals)
                created_orders.append(order)
        else:
            Order = request.env["sale.order"].sudo()
            for partner in partners:
                vals = {"partner_id": partner.id}
                if "origin" in Order._fields:
                    vals["origin"] = "Creado desde IA"
                order = Order.create(vals)
                created_orders.append(order)

        if not created_orders:
            return {
                "reply": "No se ha creado ningún pedido.",
                "handledLocally": True,
                "source": "odoo_admin_order_manager",
                "success": False,
            }

        if len(created_orders) == 1:
            order = created_orders[0]
            partner = order.partner_id.sudo() if getattr(order, "partner_id", False) else False
            reply = "Pedido de %s creado correctamente: %s para %s." % (
                order_kind_label,
                order.name or ("ID %s" % order.id),
                partner.display_name if partner else role_singular,
            )
        else:
            lines = ["Pedidos de %s creados correctamente:" % order_kind_label]
            for order in created_orders:
                partner = order.partner_id.sudo() if getattr(order, "partner_id", False) else False
                lines.append("- %s para %s" % (order.name or ("ID %s" % order.id), partner.display_name if partner else role_singular))
            reply = "\n".join(lines)

        buttons = []
        for order in created_orders[:8]:
            label = "Ver pedido" if len(created_orders) == 1 else "Ver %s" % (order.name or ("pedido %s" % order.id))
            buttons.append(self._purchase_order_open_button(order, label=label) if kind == "purchase" else self._sale_order_open_button(order, label=label))

        payload = {
            "reply": reply,
            "handledLocally": True,
            "source": "odoo_admin_order_manager",
            "success": True,
            "orderKind": kind,
            "orderIds": [order.id for order in created_orders],
            "ordersCreated": True,
            "clearPendingCart": True,
            "clearPendingAdminOrderCreate": True,
        }
        return self._with_action_buttons(payload, buttons)

    # Detecta mensajes administrativos relacionados con stock.
    def _looks_like_admin_stock_intent(self, message):
        normalized = self._normalize_customer_portal_text(message or "")
        return "stock" in normalized and any(term in normalized for term in (
            "cambiar", "cambia", "modificar", "modifica", "actualizar", "actualiza",
            "poner", "pon", "establecer", "establece", "asignar", "asigna", "dejar", "deja",
        ))

    # Detecta mensajes administrativos relacionados con productos.
    def _looks_like_admin_product_intent(self, message):
        normalized = self._normalize_customer_portal_text(message or "")
        return any(term in normalized for term in ("producto", "productos", "articulo", "articulos", "referencia", "sku", "precio")) and any(term in normalized for term in (
            "crear", "crea", "nuevo", "nueva", "introducir", "introduce", "modificar", "modifica",
            "cambiar", "cambia", "actualizar", "actualiza", "editar", "edita", "subir", "sube",
            "adjuntar", "adjunta", "cargar", "carga", "borrar", "borra",
            "eliminar", "elimina", "archivar", "archiva",
        ))

    # Detecta mensajes administrativos relacionados con clientes/contactos.
    def _looks_like_admin_customer_intent(self, message):
        normalized = self._normalize_customer_portal_text(message or "")
        return any(term in normalized for term in ("cliente", "clientes", "contacto", "contactos", "cuenta", "cuentas", "cuenta de cliente", "cuentas de clientes")) and any(term in normalized for term in (
            "crear", "crea", "nuevo", "nueva", "alta", "modificar", "modifica", "cambiar", "cambia",
            "actualizar", "actualiza", "editar", "edita", "borrar", "borra", "eliminar", "elimina", "archivar", "archiva",
            "consultar", "consulta", "buscar", "busca", "ver", "mostrar", "muestra", "informacion", "información", "datos", "ficha",
        ))

    # Devuelve ayuda de comandos administrativos disponibles.
    def _admin_help_response(self):
        return {
            "reply": (
                "Puedo ejecutar acciones administrativas porque estás conectado como admin. Ejemplos:\n"
                "- Cambia el stock del producto REF001 a 25\n"
                "- Cambia el stock nacional del producto REF001 a 100\n"
                "- Crea producto nombre: Tira LED 24V; referencia: LED-24; precio: 12,50; coste: 8,25; stock: 30 y adjunta una imagen\n"
                "- Modifica producto REF001 precio: 15; nombre: Nuevo nombre\n"
                "- Cambia la imagen del producto REF001 adjuntando una imagen\n"
                "- Crea cliente nombre: Juan Pérez; email: juan@prueba.es; teléfono: 600000000\n"
                "- Modifica cliente Juan Pérez email: nuevo@prueba.es\n"
                "- Crear pedido de venta\n"
                "- Crear pedido de compra\n"
                "- Borra cliente juan@prueba.es"
            ),
            "handledLocally": True,
            "source": "odoo_admin_manager",
            "success": True,
            "clearPendingCart": True,
            "clearPendingCustomerPortal": True,
        }

    # Convierte textos numéricos con coma, punto o símbolo de euro en decimal.
    def _admin_parse_decimal(self, value):
        if value is None:
            return None
        text = str(value).strip()
        text = text.replace("€", "").replace("$", "").replace("%", "")
        text = re.sub(r"[^0-9,\.\-]", "", text)
        if not text or text in ("-", ".", ","):
            return None
        # Si aparecen punto y coma decimal española, quitamos separadores de millar.
        if "," in text and "." in text:
            if text.rfind(",") > text.rfind("."):
                text = text.replace(".", "").replace(",", ".")
            else:
                text = text.replace(",", "")
        else:
            text = text.replace(",", ".")
        try:
            return float(text)
        except Exception:
            return None

    # Convierte respuestas de sí/no en valores booleanos.
    def _admin_parse_bool(self, value):
        text = self._normalize_customer_portal_text(value or "")
        if text in ("si", "sí", "true", "1", "yes", "activo", "activa", "publicado", "publicada"):
            return True
        if text in ("no", "false", "0", "inactivo", "inactiva", "despublicado", "despublicada"):
            return False
        return None

    # Detecta si el usuario quiere adjuntar o cambiar una imagen de producto.
    def _admin_product_image_requested(self, text):
        normalized = self._normalize_customer_portal_text(text or "")
        return any(term in normalized for term in (
            "imagen", "foto", "fotografia", "fotografía", "adjunto", "adjunta",
            "adjuntar", "subir imagen", "sube imagen", "cargar imagen", "con imagen",
            "con foto", "esta imagen", "esta foto",
        ))

    # Obtiene la imagen de producto desde los adjuntos normalizados.
    def _admin_get_product_image_attachment(self, attachments):
        """Devuelve la primera imagen válida lista para escribir en image_1920."""
        normalized = self._normalize_chat_attachments(attachments)
        max_raw_size = 8 * 1024 * 1024
        allowed_mimetypes = {"image/jpeg", "image/png", "image/gif", "image/webp"}

        extension_mimetypes = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "webp": "image/webp",
        }

        for attachment in normalized:
            mimetype = (attachment.get("mimetype") or "").strip().lower()
            filename = (attachment.get("filename") or "imagen_producto").strip()
            data = attachment.get("data") or ""
            if mimetype in ("image/jpg", "image/pjpeg"):
                mimetype = "image/jpeg"
            if not mimetype and "." in filename:
                extension = filename.rsplit(".", 1)[-1].lower()
                mimetype = extension_mimetypes.get(extension, "")
            if not data or not isinstance(data, str):
                continue
            if mimetype and not mimetype.startswith("image/"):
                continue

            clean_data = re.sub(r"\s+", "", data)
            missing_padding = len(clean_data) % 4
            if missing_padding:
                clean_data += "=" * (4 - missing_padding)
            try:
                raw = base64.b64decode(clean_data, validate=True)
            except Exception:
                raise ValueError("La imagen adjunta no se pudo leer. Adjunta una imagen JPG, PNG, GIF o WEBP válida.")

            if not raw:
                continue
            if len(raw) > max_raw_size:
                raise ValueError("La imagen adjunta supera 8 MB. Usa una imagen más ligera.")

            detected_mimetype = mimetype
            if raw.startswith(b"\xff\xd8\xff"):
                detected_mimetype = "image/jpeg"
            elif raw.startswith(b"\x89PNG\r\n\x1a\n"):
                detected_mimetype = "image/png"
            elif raw.startswith((b"GIF87a", b"GIF89a")):
                detected_mimetype = "image/gif"
            elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
                detected_mimetype = "image/webp"

            if detected_mimetype not in allowed_mimetypes:
                raise ValueError("Formato de imagen no soportado. Usa JPG, PNG, GIF o WEBP.")

            return {
                "filename": filename,
                "mimetype": detected_mimetype,
                "data": base64.b64encode(raw).decode("ascii"),
                "size": len(raw),
            }

        return False

    # Guarda la imagen en el producto o plantilla de producto.
    def _admin_write_product_image(self, template, product, image_attachment):
        if not image_attachment:
            return False
        data = image_attachment.get("data")
        if not data:
            return False
        if template and "image_1920" in template._fields:
            template.sudo().write({"image_1920": data})
            return True
        if product and "image_1920" in product._fields:
            product.sudo().write({"image_1920": data})
            return True
        raise ValueError("Este Odoo no tiene el campo image_1920 en productos.")

    # Extrae un correo electrónico desde un texto.
    def _admin_extract_email(self, text):
        match = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text or "", flags=re.IGNORECASE)
        return match.group(0).strip() if match else ""

    # Extrae pares clave/valor escritos por el usuario.
    def _admin_extract_key_values(self, text):
        aliases = (
            "nombre", "name", "email", "correo electronico", "correo", "mail", "telefono", "teléfono",
            "movil", "móvil", "phone", "mobile", "referencia", "ref", "codigo", "código", "sku",
            "barcode", "ean", "codigo de barras", "código de barras", "precio", "pvp", "precio de venta",
            "coste", "costo", "descripcion", "descripción", "descripcion venta", "descripción venta",
            "categoria", "categoría", "stock", "stock real", "stock nacional", "stock internacional",
            "calle", "direccion", "dirección", "ciudad", "cp", "c.p.", "codigo postal", "código postal",
            "pais", "país", "nif", "cif", "vat", "web", "website", "publicado", "publicado web",
            "se vende", "se compra", "imagen", "foto", "fotografia", "fotografía",
        )
        alias_pattern = "|".join(sorted((re.escape(alias) for alias in aliases), key=len, reverse=True))
        result = {}
        pattern = r"(?<!\w)(%s)\s*[:=]\s*(.+?)(?=(?:\s*[\n;]\s*(?:%s)\s*[:=])|(?:\s*,\s*(?:%s)\s*[:=])|[\n;]|$)" % (alias_pattern, alias_pattern, alias_pattern)
        for match in re.finditer(pattern, text or "", flags=re.IGNORECASE):
            key = self._normalize_customer_portal_text(match.group(1))
            value = match.group(2).strip().strip("'\"")
            if value:
                result[key] = value
        return result

    # Extrae cantidades cercanas a palabras clave de stock.
    def _admin_extract_quantity_after_keywords(self, text, keywords):
        normalized_keywords = "|".join(re.escape(keyword) for keyword in keywords)
        patterns = [
            # Ej.: "stock del producto REF001 a 25" o "stock nacional REF001 en 100"
            r"(?:%s).*?(?:a|en|=|:|dejar\s+en|poner\s+en)\s*(-?\d+(?:[\.,]\d+)?)" % normalized_keywords,
            # Ej.: "stock: 25" o "stock 25"
            r"(?:%s)\s*(?:=|:)?\s*(-?\d+(?:[\.,]\d+)?)" % normalized_keywords,
            # Ej.: "25 unidades de stock"
            r"(-?\d+(?:[\.,]\d+)?)\s*(?:uds?\.?|unidades?|metros?|m)?\s+(?:de\s+)?(?:%s)" % normalized_keywords,
        ]
        for pattern in patterns:
            match = re.search(pattern, text or "", flags=re.IGNORECASE)
            if match:
                return self._admin_parse_decimal(match.group(1))
        return None

    # Extrae una pista de entidad después de palabras clave.
    def _admin_extract_entity_hint(self, text, entity_words, stop_words=None):
        stop_words = stop_words or ()
        entity_pattern = "|".join(re.escape(word) for word in entity_words)
        stop_pattern = "|".join(re.escape(word) for word in stop_words)
        if stop_pattern:
            pattern = r"(?:%s)\s+(?:llamado\s+|llamada\s+|con\s+nombre\s+|de\s+nombre\s+|a\s+nombre\s+de\s+)?(.+?)(?=\s+(?:%s)\b|[,;\n]|$)" % (entity_pattern, stop_pattern)
        else:
            pattern = r"(?:%s)\s+(?:llamado\s+|llamada\s+|con\s+nombre\s+|de\s+nombre\s+|a\s+nombre\s+de\s+)?(.+?)(?=[,;\n]|$)" % entity_pattern
        match = re.search(pattern, text or "", flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip().strip("'\".,;:")
            value = re.sub(r"\s+", " ", value)
            value = re.sub(r"^(?:de|del|de la|para|a|al)\s+", "", value, flags=re.IGNORECASE).strip()
            if value and len(value) >= 2:
                return value
        quoted = re.search(r"['\"]([^'\"]{2,80})['\"]", text or "")
        if quoted:
            return quoted.group(1).strip()
        return ""

    # Escoge un valor válido de un campo selection de producto.
    def _admin_product_selection_value(self, field, preferred_values):
        try:
            selection = field.selection
            if isinstance(selection, str):
                selection_method = getattr(request.env["product.template"], selection, None)
                if selection_method:
                    selection = selection_method()
            elif callable(selection):
                selection = selection(request.env["product.template"])
            keys = [item[0] for item in (selection or []) if isinstance(item, (list, tuple)) and item]
            for value in preferred_values:
                if value in keys:
                    return value
        except Exception:
            pass
        return False

    # Determina el campo y valor correctos para crear un producto almacenable.
    def _admin_product_type_value(self, ProductTemplate):
        fields_map = ProductTemplate._fields
        # En Odoo 18 la casilla "Rastrear inventario" se controla con
        # is_storable. En ese caso no forzamos type='consu', porque podría
        # anular el producto almacenable aunque is_storable=True.
        if "is_storable" in fields_map:
            if "detailed_type" in fields_map:
                value = self._admin_product_selection_value(fields_map["detailed_type"], ("product", "storable", "stockable"))
                if value:
                    return "detailed_type", value
            if "type" in fields_map:
                value = self._admin_product_selection_value(fields_map["type"], ("product", "storable", "stockable"))
                if value:
                    return "type", value
            return False, False
        if "detailed_type" in fields_map:
            return "detailed_type", self._admin_product_selection_value(fields_map["detailed_type"], ("product", "consu")) or "product"
        if "type" in fields_map:
            return "type", self._admin_product_selection_value(fields_map["type"], ("product", "consu")) or "consu"
        return False, False

    # Lista categorías internas de producto para el desplegable.
    def _admin_product_category_options(self, limit=300):
        Category = request.env["product.category"].sudo()
        order = "complete_name, name" if "complete_name" in Category._fields else "name"
        categories = Category.search([], order=order, limit=limit)
        options = []
        for category in categories:
            label = getattr(category, "complete_name", False) or category.display_name or category.name or "Categoría %s" % category.id
            options.append({
                "id": category.id,
                "name": label,
            })
        return options

    # Busca una categoría interna de producto por nombre.
    def _admin_find_product_category(self, category_name):
        """Busca una categoría existente sin crear categorías nuevas."""
        name = (category_name or "").strip()
        if not name:
            return False
        Category = request.env["product.category"].sudo()
        category = Category.search([("complete_name", "=ilike", name)], limit=1)
        if not category:
            category = Category.search([("name", "=ilike", name)], limit=1)
        return category

    # Interpreta la respuesta del usuario como categoría interna.
    def _admin_find_product_category_from_answer(self, answer):
        """Interpreta la respuesta del desplegable de categoría.

        Acepta principalmente IDs enviados por el widget: ``categoria_id: 12``.
        También admite nombre exacto como respaldo, pero nunca crea categorías.
        """
        raw = str(answer or "").strip()
        if not raw:
            return False

        Category = request.env["product.category"].sudo()
        match = re.search(r"(?:categ_id|categoria_id|categoría_id|categoria|categoría|id)\s*[:=]\s*(\d+)", raw, flags=re.IGNORECASE)
        category_id = 0
        if match:
            category_id = int(match.group(1))
        elif re.match(r"^\d+$", raw):
            category_id = int(raw)

        if category_id:
            category = Category.browse(category_id).exists()
            return category[:1] if category else False

        name = re.sub(r"^(?:categ_id|categoria_id|categoría_id|categoria|categoría)\s*[:=]\s*", "", raw, flags=re.IGNORECASE).strip()
        name = name.strip("'\".,;:")
        if not name:
            return False
        return self._admin_find_product_category(name)

    # Lista categorías públicas o de ventas para el desplegable.
    def _admin_public_product_category_options(self, limit=300):
        """Devuelve categorías de venta/eCommerce ya creadas.

        En Odoo estas categorías suelen pertenecer al modelo
        ``product.public.category`` y se guardan en ``public_categ_ids``.
        """
        try:
            PublicCategory = request.env["product.public.category"].sudo()
        except Exception:
            return []
        order = "complete_name, name" if "complete_name" in PublicCategory._fields else "name"
        categories = PublicCategory.search([], order=order, limit=limit)
        options = []
        for category in categories:
            label = getattr(category, "complete_name", False) or category.display_name or category.name or "Categoría ventas %s" % category.id
            options.append({
                "id": category.id,
                "name": label,
            })
        return options

    # Busca una categoría pública/de ventas por nombre.
    def _admin_find_public_product_category(self, category_name):
        """Busca una categoría de venta/eCommerce existente sin crear nuevas."""
        name = (category_name or "").strip()
        if not name:
            return False
        try:
            PublicCategory = request.env["product.public.category"].sudo()
        except Exception:
            return False
        category = PublicCategory.search([("complete_name", "=ilike", name)], limit=1) if "complete_name" in PublicCategory._fields else PublicCategory.browse()
        if not category:
            category = PublicCategory.search([("name", "=ilike", name)], limit=1)
        return category

    # Interpreta una o varias categorías de ventas desde la respuesta.
    def _admin_find_public_product_categories_from_answer(self, answer):
        """Interpreta una o varias categorías de ventas seleccionadas.

        El widget envía IDs separados por coma, por ejemplo:
        ``categoria_ventas_ids: 3,7,9``. También acepta un único ID o nombres
        exactos separados por coma como respaldo.
        """
        try:
            PublicCategory = request.env["product.public.category"].sudo()
        except Exception:
            return False

        if isinstance(answer, (list, tuple, set)):
            raw = ",".join(str(item) for item in answer)
        else:
            raw = str(answer or "").strip()

        if not raw:
            return False

        ids = []
        match = re.search(
            r"(?:public_categ_ids|public_categ_id|categoria_ventas_ids|categoría_ventas_ids|categoria_ventas_id|categoría_ventas_id|categoria_venta_ids|categoría_venta_ids|categoria_venta_id|categoría_venta_id|categoria_web_ids|categoría_web_ids|categoria_web_id|categoría_web_id|categoria_ecommerce_ids|categoría_ecommerce_ids|categoria_ecommerce_id|categoría_ecommerce_id|id)\s*[:=]\s*([0-9,;|\s]+)",
            raw,
            flags=re.IGNORECASE,
        )
        if match:
            ids = [int(value) for value in re.findall(r"\d+", match.group(1))]
        elif re.match(r"^\s*\d+(?:\s*[,;|]\s*\d+)*\s*$", raw):
            ids = [int(value) for value in re.findall(r"\d+", raw)]

        seen = set()
        ids = [category_id for category_id in ids if category_id and not (category_id in seen or seen.add(category_id))]
        if ids:
            categories = PublicCategory.browse(ids).exists()
            return categories if categories else False

        name_text = re.sub(
            r"^(?:public_categ_ids|public_categ_id|categoria_ventas_ids|categoría_ventas_ids|categoria_ventas_id|categoría_ventas_id|categoria\s+de\s+ventas|categoría\s+de\s+ventas|categorias\s+de\s+ventas|categorías\s+de\s+ventas|categoria\s+ventas|categoría\s+ventas|categorias\s+ventas|categorías\s+ventas|categoria\s+web|categoría\s+web|categorias\s+web|categorías\s+web|categoria\s+ecommerce|categoría\s+ecommerce|categorias\s+ecommerce|categorías\s+ecommerce)\s*[:=]\s*",
            "",
            raw,
            flags=re.IGNORECASE,
        ).strip()
        name_text = name_text.strip("\'\".,;:")
        if not name_text:
            return False

        categories = PublicCategory.browse()
        for name in re.split(r"\s*[,;|]\s*", name_text):
            clean_name = name.strip().strip("\'\".,;:")
            if not clean_name:
                continue
            category = self._admin_find_public_product_category(clean_name)
            if category:
                categories |= category[:1]
        return categories if categories else False

    # Mantiene compatibilidad devolviendo una sola categoría de ventas.
    def _admin_find_public_product_category_from_answer(self, answer):
        """Interpreta la respuesta del desplegable de categoría de ventas."""
        categories = self._admin_find_public_product_categories_from_answer(answer)
        return categories[:1] if categories else False

    # Guarda las categorías de ventas en el formato many2many de Odoo.
    def _admin_store_public_product_category_value(self, values, categories):
        """Guarda categorías de ventas en un formato seguro para sesión JSON."""
        if values is None or not categories:
            return values
        category_ids = []
        try:
            for category in categories:
                if getattr(category, "id", False):
                    category_ids.append(int(category.id))
        except TypeError:
            if getattr(categories, "id", False):
                category_ids.append(int(categories.id))
            else:
                try:
                    category_ids.append(int(categories))
                except Exception:
                    pass
        except Exception:
            try:
                category_ids.append(int(categories.id))
            except Exception:
                pass

        seen = set()
        category_ids = [category_id for category_id in category_ids if category_id and not (category_id in seen or seen.add(category_id))]
        if category_ids:
            values["public_categ_ids"] = category_ids
        return values

    # Prepara valores de creación con categorías de ventas compatibles.
    def _admin_prepare_public_category_create_values(self, ProductTemplate, values):
        """Convierte IDs guardados en sesión en comandos Many2many para create/write."""
        values = dict(values or {})
        if "public_categ_ids" not in values or "public_categ_ids" not in ProductTemplate._fields:
            return values

        raw_ids = values.get("public_categ_ids") or []
        category_ids = []
        if isinstance(raw_ids, int):
            category_ids = [raw_ids]
        elif isinstance(raw_ids, str) and raw_ids.strip().isdigit():
            category_ids = [int(raw_ids.strip())]
        elif isinstance(raw_ids, (list, tuple)):
            # Ya está en formato comando Odoo; lo dejamos intacto.
            if raw_ids and isinstance(raw_ids[0], (list, tuple)):
                return values
            for item in raw_ids:
                try:
                    category_ids.append(int(item))
                except Exception:
                    continue

        category_ids = [category_id for category_id in category_ids if category_id]
        if category_ids:
            values["public_categ_ids"] = [(6, 0, category_ids)]
        else:
            values.pop("public_categ_ids", None)
        return values

    # Extrae campos de producto desde texto libre o respuestas guiadas.
    def _admin_extract_product_values(self, text, for_create=False):
        kv = self._admin_extract_key_values(text)
        values = {}
        stock_qty = None
        stock_nacional = None
        stock_internacional = None

        # Devuelve el primer valor existente entre varias claves posibles.
        def first_value(*keys):
            for key in keys:
                norm = self._normalize_customer_portal_text(key)
                if norm in kv:
                    return kv[norm]
            return None

        name = first_value("nombre", "name")
        if not name and for_create:
            match = re.search(
                r"(?:crear|crea|nuevo|nueva|introducir|introduce|insertar|inserta)\s+(?:un\s+|una\s+|el\s+|la\s+)?(?:producto|articulo)(?:\s+nuevo)?(?:\s+llamado|\s+llamada|\s+con\s+nombre|\s+de\s+nombre)?\s+(.+?)(?=\s+(?:referencia|ref|codigo|código|sku|precio|pvp|coste|costo|stock|categoria|categoría)\b|[,;\n]|$)",
                text or "",
                flags=re.IGNORECASE,
            )
            if match:
                name = match.group(1).strip().strip("'\".,;:")
        if name:
            values["name"] = name

        reference = first_value("referencia", "ref", "codigo", "código", "sku")
        if not reference:
            match = re.search(r"(?:referencia|ref|codigo|código|sku)\s*(?:=|:|es|será|sera)?\s*([A-Za-z0-9._\-/]{2,64})", text or "", flags=re.IGNORECASE)
            if match:
                reference = match.group(1).strip().strip(".,;:")
        if reference:
            values["default_code"] = reference

        barcode = first_value("barcode", "ean", "codigo de barras", "código de barras")
        if barcode:
            values["barcode"] = barcode

        price_value = first_value("precio", "pvp", "precio de venta")
        if price_value is None:
            for pattern in (
                r"(?:precio(?:\s+de\s+venta)?|pvp)\s*(?:=|:)\s*(-?\d+(?:[\.,]\d+)?)",
                r"(?:precio(?:\s+de\s+venta)?|pvp).*?(?:a|en|=|:)\s*(-?\d+(?:[\.,]\d+)?)",
            ):
                match = re.search(pattern, text or "", flags=re.IGNORECASE)
                if match:
                    price_value = match.group(1)
                    break
        price = self._admin_parse_decimal(price_value)
        if price is not None:
            values["list_price"] = price

        cost_value = first_value("coste", "costo")
        cost = self._admin_parse_decimal(cost_value)
        if cost is not None:
            values["standard_price"] = cost

        description = first_value("descripcion", "descripción", "descripcion venta", "descripción venta")
        if description:
            values["description_sale"] = description

        sale_category_name = first_value(
            "categoria de ventas", "categoría de ventas", "categoria ventas", "categoría ventas",
            "categoria venta", "categoría venta", "categoria web", "categoría web",
            "categoria ecommerce", "categoría ecommerce", "categoria tienda", "categoría tienda",
        )
        if sale_category_name:
            sale_categories = self._admin_find_public_product_categories_from_answer(sale_category_name)
            if sale_categories:
                self._admin_store_public_product_category_value(values, sale_categories)

        category_name = first_value("categoria", "categoría")
        if category_name:
            category = self._admin_find_product_category(category_name)
            if category:
                values["categ_id"] = category.id

        sale_ok = self._admin_parse_bool(first_value("se vende"))
        if sale_ok is not None:
            values["sale_ok"] = sale_ok
        purchase_ok = self._admin_parse_bool(first_value("se compra"))
        if purchase_ok is not None:
            values["purchase_ok"] = purchase_ok
        website_published = self._admin_parse_bool(first_value("publicado", "publicado web"))
        if website_published is not None:
            values["website_published"] = website_published

        normalized_text = self._normalize_customer_portal_text(text or "")
        stock_qty = self._admin_parse_decimal(first_value("stock", "stock real"))
        if stock_qty is None:
            has_exact_stock_real = "stock real" in normalized_text or bool(re.search(r"(?<!\w)stock\s*[:=]", text or "", flags=re.IGNORECASE))
            has_only_extra_stock = ("stock nacional" in normalized_text or "stock internacional" in normalized_text) and not has_exact_stock_real
            if not has_only_extra_stock:
                stock_qty = self._admin_extract_quantity_after_keywords(text, ("stock real", "stock"))
        stock_nacional = self._admin_parse_decimal(first_value("stock nacional"))
        if stock_nacional is None and "nacional" in self._normalize_customer_portal_text(text or ""):
            stock_nacional = self._admin_extract_quantity_after_keywords(text, ("stock nacional", "nacional"))
        stock_internacional = self._admin_parse_decimal(first_value("stock internacional"))
        if stock_internacional is None and "internacional" in self._normalize_customer_portal_text(text or ""):
            stock_internacional = self._admin_extract_quantity_after_keywords(text, ("stock internacional", "internacional"))

        return values, stock_qty, stock_nacional, stock_internacional

    # Busca productos por referencia, código, URL o nombre.
    def _admin_find_product(self, text, page_title=None, page_url=None):
        Product = request.env["product.product"].sudo()
        combined_text = " ".join(value for value in (text, page_title, page_url) if value)
        codes = self._extract_product_codes(combined_text, limit=12)
        products, _not_found = self._search_products_by_codes(Product, codes, limit=10)
        if len(products) == 1:
            return products[0], products
        if len(products) > 1:
            return False, products

        hint = self._admin_extract_entity_hint(
            text,
            ("producto", "productos", "articulo", "articulos", "referencia", "sku"),
            stop_words=(
                "stock", "precio", "coste", "costo", "nombre", "referencia", "ref", "codigo", "código",
                "sku", "a", "en", "con", "por", "para", "categoria", "categoría",
            ),
        )
        if hint:
            domains = [[("name", "ilike", hint)]]
            if "default_code" in Product._fields:
                domains.append([("default_code", "ilike", hint)])
            if "barcode" in Product._fields:
                domains.append([("barcode", "ilike", hint)])
            products = Product.search(expression.OR(domains), limit=10)
            if len(products) == 1:
                return products[0], products
            if len(products) > 1:
                return False, products

        return False, Product.browse()

    # Obtiene una ubicación interna de stock para ajustes iniciales.
    def _admin_get_stock_location(self):
        Warehouse = request.env["stock.warehouse"].sudo()
        warehouse = Warehouse.search([("company_id", "=", request.env.company.id)], limit=1)
        if not warehouse:
            warehouse = Warehouse.search([], limit=1)
        if warehouse and warehouse.lot_stock_id:
            return warehouse.lot_stock_id.sudo()
        location = self._env_ref_safe("stock.stock_location_stock")
        return location.sudo() if location else False

    # Ajusta el stock real del producto mediante quants de Odoo.
    def _admin_set_real_stock(self, product, quantity):
        location = self._admin_get_stock_location()
        if not location:
            raise ValueError("No se encontró una ubicación interna de stock.")
        product = product.sudo()
        current_qty = product.with_context(location=location.id).qty_available
        difference = float(quantity or 0.0) - float(current_qty or 0.0)
        request.env["stock.quant"].sudo()._update_available_quantity(product, location, difference)
        product.invalidate_recordset()
        return current_qty, product.with_context(location=location.id).qty_available, location

    # Escribe campos personalizados de stock nacional o internacional.
    def _admin_write_extra_stock_field(self, product, field_name, quantity):
        target = product.sudo()
        if field_name not in target._fields and getattr(product, "product_tmpl_id", False):
            target = product.product_tmpl_id.sudo()
        if field_name not in target._fields:
            raise ValueError("El campo %s no existe en este Odoo." % field_name)
        target.write({field_name: float(quantity or 0.0)})
        return target

    # Actualiza stock de producto y devuelve un mensaje de confirmación.
    def _admin_update_stock_response(self, text, page_title=None, page_url=None):
        product, products = self._admin_find_product(text, page_title=page_title, page_url=page_url)
        if not product:
            if products:
                return {
                    "reply": "He encontrado varios productos posibles. Indícame la referencia exacta:\n" + "\n".join("- %s" % self._short_product_label(item) for item in products[:8]),
                    "handledLocally": True,
                    "source": "odoo_admin_manager",
                    "success": False,
                    "clearPendingCart": True,
                }
            return {
                "reply": "No he encontrado el producto. Indícame la referencia exacta, por ejemplo: cambia el stock del producto REF001 a 25.",
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": False,
                "clearPendingCart": True,
            }

        normalized = self._normalize_customer_portal_text(text)
        quantity = self._admin_extract_quantity_after_keywords(text, ("stock internacional", "stock nacional", "stock real", "stock"))
        if quantity is None:
            return {
                "reply": "Indícame la cantidad nueva de stock. Ejemplo: cambia el stock del producto %s a 25." % (product.default_code or product.display_name),
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": False,
                "clearPendingCart": True,
            }

        if "internacional" in normalized:
            self._admin_write_extra_stock_field(product, "x_almacen1_custom", quantity)
            return {
                "reply": "Stock internacional actualizado para %s: %s." % (self._short_product_label(product), self._format_quantity(quantity)),
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": True,
                "productId": product.id,
                "templateId": product.product_tmpl_id.id if getattr(product, "product_tmpl_id", False) else product.id,
                "actionButton": self._product_open_button(product),
                "clearPendingCart": True,
            }
        if "nacional" in normalized:
            self._admin_write_extra_stock_field(product, "x_transit_stock_custom", quantity)
            return {
                "reply": "Stock nacional actualizado para %s: %s." % (self._short_product_label(product), self._format_quantity(quantity)),
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": True,
                "productId": product.id,
                "templateId": product.product_tmpl_id.id if getattr(product, "product_tmpl_id", False) else product.id,
                "actionButton": self._product_open_button(product),
                "clearPendingCart": True,
            }

        before, after, location = self._admin_set_real_stock(product, quantity)
        return {
            "reply": (
                "Stock real actualizado para %s.\n"
                "Ubicación: %s.\n"
                "Antes: %s.\n"
                "Ahora: %s."
            ) % (self._short_product_label(product), location.display_name, self._format_quantity(before), self._format_quantity(after)),
            "handledLocally": True,
            "source": "odoo_admin_manager",
            "success": True,
            "productId": product.id,
            "templateId": product.product_tmpl_id.id if getattr(product, "product_tmpl_id", False) else product.id,
            "actionButton": self._product_open_button(product),
            "clearPendingCart": True,
        }

    # Guarda el sessionId del navegador durante la petición actual.
    def _set_request_client_session_id(self, session_id):
        try:
            safe_session_id = str(session_id or "").strip() or "odoo-public"
            request.httprequest.environ["odoo_ai_chat_client_session_id"] = safe_session_id[:160]
        except Exception:
            pass

    # Guarda el estado local del alta guiada enviado por el navegador.
    def _set_request_admin_product_create_client_state(self, data):
        """Guarda en la petición el estado local que conoce el widget.

        El navegador sabe cuál fue el último campo preguntado aunque la sesión
        HTTP de Odoo se haya quedado atrasada. Este respaldo evita tratar
        "precio: 2,25" como si fuera un código cuando el backend conserva un
        estado antiguo.
        """
        try:
            payload = data or {}
            awaiting = str(payload.get("adminProductCreateAwaiting") or "").strip()
            answers = payload.get("adminProductCreateClientAnswers") or {}
            if isinstance(answers, str):
                try:
                    answers = json.loads(answers.strip() or "{}")
                except Exception:
                    answers = {}
            if not isinstance(answers, dict):
                answers = {}
            request.httprequest.environ["odoo_ai_chat_admin_product_create_client_state"] = {
                "awaiting": awaiting,
                "answers": answers,
            }
        except Exception:
            pass

    # Lee el estado local del alta guiada de la petición actual.
    def _get_request_admin_product_create_client_state(self):
        try:
            state = request.httprequest.environ.get("odoo_ai_chat_admin_product_create_client_state") or {}
            return state if isinstance(state, dict) else {}
        except Exception:
            return {}

    # Calcula la clave estable para guardar el alta guiada del producto.
    def _admin_product_create_state_key(self):
        """Clave estable para el alta guiada.

        En versiones anteriores se mezclaba el sessionId del navegador con el SID
        interno de Odoo. Si Odoo regeneraba el SID entre peticiones, el estado de
        respaldo se guardaba en una clave distinta y el asistente podía volver a
        preguntar código/precio. Ahora, si el widget envía sessionId, esa es la
        fuente principal.
        """
        try:
            db_name = str(getattr(request.env.cr, "dbname", "") or "")
        except Exception:
            db_name = ""
        try:
            client_session_id = str(request.httprequest.environ.get("odoo_ai_chat_client_session_id") or "").strip()
        except Exception:
            client_session_id = ""
        try:
            odoo_sid = str(getattr(request.session, "sid", "") or "").strip()
        except Exception:
            odoo_sid = ""

        if client_session_id:
            raw = "|".join(part for part in (db_name, "client", client_session_id) if part)
        elif odoo_sid:
            raw = "|".join(part for part in (db_name, "odoo", odoo_sid) if part)
        else:
            raw = "|".join(part for part in (db_name, "odoo-public") if part)
        return re.sub(r"[^A-Za-z0-9_.:\-|]", "_", raw)[:220]

    # Calcula qué estado de alta guiada parece más completo.
    def _admin_product_create_state_score(self, data):
        if not isinstance(data, dict) or not data:
            return -1
        values = data.get("values") or {}
        skipped = data.get("skipped") or []
        completed = data.get("completed") or []
        score = int(data.get("_state_rev") or 0) * 1000
        score += len(values) * 20 + len(skipped) * 10 + len(completed) * 15
        for key in ("stock_qty", "stock_nacional", "stock_internacional", "image_attachment", "image_skipped"):
            if key in data and data.get(key) not in (None, False, ""):
                score += 8
        field_order = [item["key"] for item in self._admin_product_create_field_specs()]
        awaiting = data.get("awaiting") or ""
        if awaiting in field_order:
            score += field_order.index(awaiting)
        return score

    # Recupera el alta guiada pendiente desde sesión o respaldo por sessionId.
    def _get_session_pending_admin_product_create(self):
        session_data = {}
        memory_data = {}
        try:
            data = request.session.get("odoo_ai_chat_pending_admin_product_create") or {}
            if isinstance(data, dict):
                session_data = dict(data)
        except Exception:
            session_data = {}

        try:
            state_key = self._admin_product_create_state_key()
            with _AI_ADMIN_PRODUCT_CREATE_STATES_LOCK:
                _cleanup_old_admin_product_create_states_unlocked()
                data = _AI_ADMIN_PRODUCT_CREATE_STATES.get(state_key) or {}
                if isinstance(data, dict):
                    memory_data = dict(data)
        except Exception:
            memory_data = {}

        if self._admin_product_create_state_score(memory_data) > self._admin_product_create_state_score(session_data):
            return memory_data
        if self._admin_product_create_state_score(memory_data) == self._admin_product_create_state_score(session_data):
            if (memory_data.get("_updated_at") or 0) > (session_data.get("_updated_at") or 0):
                return memory_data
        return session_data if isinstance(session_data, dict) else {}

    # Guarda el estado del alta guiada en sesión y respaldo.
    def _set_session_pending_admin_product_create(self, payload):
        payload = dict(payload or {})
        try:
            payload["_state_rev"] = int(payload.get("_state_rev") or 0) + 1
        except Exception:
            payload["_state_rev"] = 1
        payload["_updated_at"] = time.time()

        try:
            request.session["odoo_ai_chat_pending_admin_product_create"] = payload
            request.session.modified = True
        except Exception:
            pass

        try:
            state_key = self._admin_product_create_state_key()
            with _AI_ADMIN_PRODUCT_CREATE_STATES_LOCK:
                _cleanup_old_admin_product_create_states_unlocked()
                _AI_ADMIN_PRODUCT_CREATE_STATES[state_key] = dict(payload)
        except Exception:
            pass
        return payload or {}

    # Limpia el alta guiada pendiente del producto.
    def _clear_session_pending_admin_product_create(self):
        try:
            request.session.pop("odoo_ai_chat_pending_admin_product_create", None)
            request.session.modified = True
        except Exception:
            pass
        try:
            state_key = self._admin_product_create_state_key()
            with _AI_ADMIN_PRODUCT_CREATE_STATES_LOCK:
                _AI_ADMIN_PRODUCT_CREATE_STATES.pop(state_key, None)
        except Exception:
            pass

    # Detecta si la respuesta significa omitir el campo actual.
    def _admin_product_create_is_skip_answer(self, text):
        normalized = self._normalize_customer_portal_text(text or "")
        normalized = normalized.strip(" [](){}")
        return normalized in (
            "", "no", "no tengo", "no lo tengo", "sin dato", "sin datos", "ningun dato",
            "ninguno", "ninguna", "saltar", "salta", "omitir", "omite", "skip", "-",
        )

    # Detecta si la respuesta cancela el alta guiada.
    def _admin_product_create_is_cancel_answer(self, text):
        normalized = self._normalize_customer_portal_text(text or "")
        return normalized in ("cancelar", "cancela", "salir", "parar", "olvida", "olvidalo", "olvídalo")

    # Define el orden, etiquetas y validaciones del alta guiada de producto.
    def _admin_product_create_field_specs(self):
        return [
            {
                "key": "name",
                "required": True,
                "reply": "¿Cuál es el nombre del producto?",
                "error": "El nombre del producto es obligatorio. Indícame el nombre para continuar.",
            },
            {
                "key": "default_code",
                "required": False,
                "reply": "Indícame el código o referencia interna del producto. Si no lo tienes, pulsa Enter y pasaré al siguiente dato.",
            },
            {
                "key": "list_price",
                "required": False,
                "reply": "Indícame el precio de venta del producto. Si no lo tienes, pulsa Enter y pasaré al siguiente dato.",
                "error": "El precio debe ser un número, por ejemplo 12,50. Indícalo de nuevo o pulsa Enter para omitirlo.",
            },
            {
                "key": "standard_price",
                "required": False,
                "reply": "Indícame el coste del producto. Si no lo tienes, pulsa Enter y pasaré al siguiente dato.",
                "error": "El coste debe ser un número, por ejemplo 8,25. Indícalo de nuevo o pulsa Enter para omitirlo.",
            },
            {
                "key": "categ_id",
                "required": False,
                "reply": "Selecciona la categoría del producto en el desplegable. Si no quieres asignar una categoría, pulsa Enter y pasaré al siguiente dato.",
                "error": "La categoría seleccionada no existe. Selecciona una categoría del desplegable o pulsa Enter para omitirla.",
            },
            {
                "key": "public_categ_ids",
                "required": False,
                "reply": "Selecciona una o varias categorías de ventas del producto en el desplegable. Cuando termines, pulsa Enviar. Si no quieres asignar categorías de ventas, pulsa Enter y pasaré al siguiente dato.",
                "error": "La categoría de ventas seleccionada no existe. Selecciona una o varias categorías del desplegable o pulsa Enter para omitirlas.",
            },
            {
                "key": "stock_nacional",
                "required": False,
                "reply": "Indícame el stock nacional. Si no lo tienes, pulsa Enter y pasaré al siguiente dato.",
                "error": "El stock nacional debe ser un número. Indícalo de nuevo o pulsa Enter para omitirlo.",
            },
            {
                "key": "stock_internacional",
                "required": False,
                "reply": "Indícame el stock internacional. Si no lo tienes, pulsa Enter y pasaré al siguiente dato.",
                "error": "El stock internacional debe ser un número. Indícalo de nuevo o pulsa Enter para omitirlo.",
            },
            {
                "key": "stock_qty",
                "required": False,
                "reply": "Indícame el stock real inicial del producto. Si no lo tienes, pulsa Enter y pasaré al siguiente dato.",
                "error": "El stock real debe ser un número. Indícalo de nuevo o pulsa Enter para omitirlo.",
            },
            {
                "key": "image",
                "required": False,
                "reply": "Adjunta la imagen del producto con el botón 📎 Imagen y envía el mensaje. Si no quieres añadir imagen, pulsa Enter para crear el producto sin imagen.",
            },
        ]

    # Comprueba si un campo obligatorio u opcional sigue pendiente.
    def _admin_product_create_field_missing(self, pending, key):
        values = pending.get("values") or {}
        skipped = set(pending.get("skipped") or [])
        completed = set(pending.get("completed") or [])

        # Regla anti-bucle: si el asistente ya avanzó por un campo opcional,
        # no volvemos hacia atrás aunque una sesión antigua no conserve el valor.
        # Así evita el ciclo código ↔ precio que puede darse con sesiones desincronizadas.
        if key in completed:
            return False

        if key == "stock_qty":
            return "stock_qty" not in pending and key not in skipped
        if key == "stock_nacional":
            return "stock_nacional" not in pending and key not in skipped
        if key == "stock_internacional":
            return "stock_internacional" not in pending and key not in skipped
        if key == "image":
            return not pending.get("image_attachment") and not pending.get("image_skipped")
        return key not in values and key not in skipped

    # Marca un campo del alta guiada como completado.
    def _admin_product_create_mark_completed(self, completed, key):
        if key and key not in completed:
            completed.append(key)
        return completed

    # Marca campos anteriores para evitar volver atrás en el flujo.
    def _admin_product_create_mark_prior_fields_completed(self, pending, current_key):
        completed = list(pending.get("completed") or [])
        field_order = [item["key"] for item in self._admin_product_create_field_specs()]
        if current_key in field_order:
            for key in field_order[:field_order.index(current_key)]:
                # El nombre sigue siendo obligatorio; no se marca como completado si no existe.
                if key == "name" and not (pending.get("values") or {}).get("name"):
                    continue
                self._admin_product_create_mark_completed(completed, key)
        pending["completed"] = completed
        return completed

    # Devuelve el orden de campos del alta guiada.
    def _admin_product_create_field_order(self):
        return [item["key"] for item in self._admin_product_create_field_specs()]

    # Valida si una clave pertenece al alta guiada de producto.
    def _admin_product_create_is_valid_field_key(self, key):
        return key in self._admin_product_create_field_order()

    # Detecta si el usuario respondió indicando explícitamente el campo.
    def _admin_product_create_detect_explicit_field(self, text):
        normalized = self._normalize_customer_portal_text(text or "")
        if not normalized:
            return ""
        if re.search(r"(?<!\w)(?:nombre|name)\s*[:=]", text or "", flags=re.IGNORECASE):
            return "name"
        if re.search(r"(?<!\w)(?:referencia|ref|codigo|código|sku)\s*[:=]", text or "", flags=re.IGNORECASE):
            return "default_code"
        if re.search(r"(?<!\w)(?:precio(?:\s+de\s+venta)?|pvp)\s*[:=]", text or "", flags=re.IGNORECASE):
            return "list_price"
        if re.search(r"(?<!\w)(?:coste|costo|precio\s+de\s+coste|precio\s+de\s+costo|cost)\s*[:=]", text or "", flags=re.IGNORECASE):
            return "standard_price"
        if re.search(r"(?<!\w)(?:public_categ_ids|public_categ_id|categoria_ventas_ids|categoría_ventas_ids|categoria_ventas_id|categoría_ventas_id|categoria\s+de\s+ventas|categoría\s+de\s+ventas|categorias\s+de\s+ventas|categorías\s+de\s+ventas|categoria\s+ventas|categoría\s+ventas|categorias\s+ventas|categorías\s+ventas|categoria\s+web|categoría\s+web|categorias\s+web|categorías\s+web|categoria\s+ecommerce|categoría\s+ecommerce|categorias\s+ecommerce|categorías\s+ecommerce)\s*[:=]", text or "", flags=re.IGNORECASE):
            return "public_categ_ids"
        if re.search(r"(?<!\w)(?:categoria|categoría|categoria_id|categoría_id|categ_id)\s*[:=]", text or "", flags=re.IGNORECASE):
            return "categ_id"
        if "stock nacional" in normalized or re.search(r"(?<!\w)nacional\s*[:=]", text or "", flags=re.IGNORECASE):
            return "stock_nacional"
        if "stock internacional" in normalized or re.search(r"(?<!\w)internacional\s*[:=]", text or "", flags=re.IGNORECASE):
            return "stock_internacional"
        if "stock real" in normalized or re.search(r"(?<!\w)stock\s*[:=]", text or "", flags=re.IGNORECASE):
            return "stock_qty"
        if any(word in normalized for word in ("imagen", "foto", "fotografia")):
            return "image"
        return ""

    # Limpia prefijos como código o referencia antes de guardar el SKU.
    def _admin_clean_product_reference_answer(self, text):
        values, _stock_qty, _stock_nacional, _stock_internacional = self._admin_extract_product_values(text, for_create=False)
        reference = (values or {}).get("default_code")
        if not reference:
            match = re.search(r"(?:referencia|ref|codigo|código|sku)\s*(?:=|:|es)?\s*(.+)$", text or "", flags=re.IGNORECASE)
            if match:
                reference = match.group(1)
            else:
                reference = text
        reference = str(reference or "").strip().strip("'\".,;:")
        # Evita guardar una etiqueta completa si el usuario escribe "código: 01405".
        reference = re.sub(r"^(?:referencia|ref|codigo|código|sku)\s*(?:=|:|es)?\s*", "", reference, flags=re.IGNORECASE).strip()
        return reference

    # Omite campos opcionales anteriores cuando el usuario responde a uno posterior.
    def _admin_product_create_skip_prior_optional_fields(self, pending, current_key):
        field_order = self._admin_product_create_field_order()
        if current_key not in field_order:
            return pending
        skipped = list(pending.get("skipped") or [])
        completed = list(pending.get("completed") or [])
        for key in field_order[:field_order.index(current_key)]:
            if key == "name":
                continue
            if self._admin_product_create_field_missing(pending, key):
                if key not in skipped:
                    skipped.append(key)
            self._admin_product_create_mark_completed(completed, key)
        pending["skipped"] = skipped
        pending["completed"] = completed
        return pending

    # Reconcilia respuestas guardadas en el navegador con el estado del backend.
    def _admin_product_create_apply_client_answers(self, pending, client_answers):
        if not isinstance(client_answers, dict) or not client_answers:
            return pending

        values = dict(pending.get("values") or {})
        skipped = list(pending.get("skipped") or [])
        completed = list(pending.get("completed") or [])

        # Marca internamente un campo opcional como omitido.
        def mark_skipped(key):
            if key != "name" and key not in skipped:
                skipped.append(key)
            self._admin_product_create_mark_completed(completed, key)

        for key in self._admin_product_create_field_order():
            if key not in client_answers:
                continue
            raw_value = client_answers.get(key)
            if key == "image":
                continue
            if self._admin_product_create_is_skip_answer(raw_value):
                if key == "name":
                    continue
                if key in values:
                    values.pop(key, None)
                if key in ("stock_qty", "stock_nacional", "stock_internacional"):
                    pending.pop(key, None)
                mark_skipped(key)
                continue

            raw_text = str(raw_value or "").strip()
            if not raw_text:
                continue

            if key == "name":
                parsed = (values.get("name") or raw_text).strip()
                if parsed:
                    values["name"] = parsed
                    self._admin_product_create_mark_completed(completed, "name")
            elif key == "default_code":
                parsed = self._admin_clean_product_reference_answer(raw_text)
                if parsed:
                    values["default_code"] = parsed
                    if "default_code" in skipped:
                        skipped.remove("default_code")
                    self._admin_product_create_mark_completed(completed, "default_code")
            elif key in ("list_price", "standard_price"):
                parsed_values, _sq, _sn, _si = self._admin_extract_product_values(raw_text, for_create=False)
                price = (parsed_values or {}).get(key)
                if price is None:
                    price = self._admin_parse_decimal(raw_text)
                if price is not None:
                    values[key] = price
                    if key in skipped:
                        skipped.remove(key)
                    self._admin_product_create_mark_completed(completed, key)
            elif key == "categ_id":
                category = self._admin_find_product_category_from_answer(raw_text)
                if category:
                    values["categ_id"] = category.id
                    if "categ_id" in skipped:
                        skipped.remove("categ_id")
                    self._admin_product_create_mark_completed(completed, "categ_id")
            elif key == "public_categ_ids":
                categories = self._admin_find_public_product_categories_from_answer(raw_text)
                if categories:
                    self._admin_store_public_product_category_value(values, categories)
                    if "public_categ_ids" in skipped:
                        skipped.remove("public_categ_ids")
                    self._admin_product_create_mark_completed(completed, "public_categ_ids")
            elif key in ("stock_nacional", "stock_internacional", "stock_qty"):
                parsed_values, stock_qty, stock_nacional, stock_internacional = self._admin_extract_product_values(raw_text, for_create=False)
                quantity_by_key = {
                    "stock_qty": stock_qty,
                    "stock_nacional": stock_nacional,
                    "stock_internacional": stock_internacional,
                }
                quantity = quantity_by_key.get(key)
                if quantity is None:
                    quantity = self._admin_parse_decimal(raw_text)
                if quantity is not None:
                    pending[key] = quantity
                    if key in skipped:
                        skipped.remove(key)
                    self._admin_product_create_mark_completed(completed, key)

        pending["values"] = values
        pending["skipped"] = skipped
        pending["completed"] = completed
        return pending

    # Construye la pregunta siguiente del alta guiada de producto.
    def _admin_product_create_prompt_response(self, pending, spec, extra_reply=None):
        pending["awaiting"] = spec["key"]
        self._set_session_pending_admin_product_create(pending)
        reply = extra_reply or spec["reply"]
        return {
            "reply": reply,
            "handledLocally": True,
            "source": "odoo_admin_product_create_flow",
            "success": False,
            "pendingAdminProductCreate": True,
            "adminProductCreateAwaiting": spec["key"],
            "needsProductImage": spec["key"] == "image",
            "needsProductCategory": spec["key"] in ("categ_id", "public_categ_ids"),
            "productCategoryKind": "sale" if spec["key"] == "public_categ_ids" else ("product" if spec["key"] == "categ_id" else ""),
            "allowEmptyMessage": not spec.get("required"),
            "clearPendingCart": True,
            "clearPendingCustomerPortal": True,
        }

    # Devuelve un error recuperable del alta guiada.
    def _admin_product_create_error_response(self, pending, error):
        pending = dict(pending or self._get_session_pending_admin_product_create() or {})
        awaiting = (pending.get("awaiting") or "image").strip()
        if not self._admin_product_create_is_valid_field_key(awaiting):
            awaiting = "image"
        if pending:
            pending["awaiting"] = awaiting
            self._set_session_pending_admin_product_create(pending)

        detail = str(error or "error desconocido")
        if awaiting == "image":
            reply = (
                "No he podido procesar la imagen o terminar la creación del producto. "
                "Adjunta una imagen JPG, PNG, GIF o WEBP válida y envía de nuevo, "
                "o pulsa Enter para crear el producto sin imagen.\n"
                "Detalle técnico: %s"
            ) % detail
        else:
            reply = (
                "No he podido continuar con la creación del producto. "
                "Puedes corregir el dato solicitado o escribir cancelar para salir.\n"
                "Detalle técnico: %s"
            ) % detail

        return {
            "reply": reply,
            "handledLocally": True,
            "source": "odoo_admin_product_create_flow",
            "success": False,
            "pendingAdminProductCreate": True,
            "adminProductCreateAwaiting": awaiting,
            "needsProductImage": awaiting == "image",
            "needsProductCategory": awaiting in ("categ_id", "public_categ_ids"),
            "productCategoryKind": "sale" if awaiting == "public_categ_ids" else ("product" if awaiting == "categ_id" else ""),
            "allowEmptyMessage": True,
            "clearPendingCart": True,
            "clearPendingCustomerPortal": True,
        }

    # Avanza al siguiente campo o crea el producto al completar el flujo.
    def _admin_product_create_next_or_finish_response(self, pending):
        for spec in self._admin_product_create_field_specs():
            if self._admin_product_create_field_missing(pending, spec["key"]):
                return self._admin_product_create_prompt_response(pending, spec)

        values = dict(pending.get("values") or {})
        stock_qty = pending.get("stock_qty") if "stock_qty" in pending else None
        stock_nacional = pending.get("stock_nacional") if "stock_nacional" in pending else None
        stock_internacional = pending.get("stock_internacional") if "stock_internacional" in pending else None
        image_attachment = pending.get("image_attachment") or False
        try:
            response = self._admin_create_product_with_values_response(
                values,
                stock_qty=stock_qty,
                stock_nacional=stock_nacional,
                stock_internacional=stock_internacional,
                image_attachment=image_attachment,
            )
        except Exception as error:
            _logger.exception("Error creando producto desde alta guiada")
            return self._admin_product_create_error_response(pending, error)

        if response and response.get("success"):
            self._clear_session_pending_admin_product_create()
        else:
            self._set_session_pending_admin_product_create(pending)
        return response

    # Inicializa el alta guiada de producto.
    def _admin_start_product_create_flow(self, text, attachments=None):
        values, stock_qty, stock_nacional, stock_internacional = self._admin_extract_product_values(text, for_create=True)
        image_attachment = self._admin_get_product_image_attachment(attachments)
        pending = {
            "values": values or {},
            "skipped": [],
            "completed": [],
            "awaiting": "",
            "started_at": time.time(),
        }
        if stock_qty is not None:
            pending["stock_qty"] = stock_qty
        if stock_nacional is not None:
            pending["stock_nacional"] = stock_nacional
        if stock_internacional is not None:
            pending["stock_internacional"] = stock_internacional
        if image_attachment:
            pending["image_attachment"] = image_attachment
        return self._admin_product_create_next_or_finish_response(pending)

    # Reconstruye el alta guiada si Odoo perdió la sesión.
    def _admin_rebuild_pending_product_create_from_client_state(self, client_state):
        """Reconstruye el alta guiada con las respuestas que conserva el navegador.

        Esto cubre dos casos frecuentes: sesión HTTP regenerada y Enter vacío en
        un campo opcional cuando el servidor perdió el estado, especialmente en
        el paso de imagen.
        """
        if not isinstance(client_state, dict):
            return {}
        awaiting = str(client_state.get("awaiting") or "").strip()
        answers = client_state.get("answers") or {}
        if isinstance(answers, str):
            try:
                answers = json.loads(answers.strip() or "{}")
            except Exception:
                answers = {}
        if not isinstance(answers, dict):
            answers = {}
        if not awaiting and not answers:
            return {}

        pending = {
            "values": {},
            "skipped": [],
            "completed": [],
            "awaiting": awaiting if self._admin_product_create_is_valid_field_key(awaiting) else "",
            "started_at": time.time(),
            "rebuilt_from_client_state": True,
        }
        pending = self._admin_product_create_apply_client_answers(pending, answers)
        if self._admin_product_create_is_valid_field_key(awaiting):
            pending = self._admin_product_create_skip_prior_optional_fields(pending, awaiting)
            pending["awaiting"] = awaiting
            self._admin_product_create_mark_prior_fields_completed(pending, awaiting)
        return pending

    # Procesa la respuesta actual del alta guiada y avanza el flujo.
    def _admin_continue_product_create_flow(self, text, attachments=None):
        pending = self._get_session_pending_admin_product_create()
        client_state = self._get_request_admin_product_create_client_state()
        if not pending:
            pending = self._admin_rebuild_pending_product_create_from_client_state(client_state)
            if pending:
                self._set_session_pending_admin_product_create(pending)
        if not pending:
            return None

        if self._admin_product_create_is_cancel_answer(text):
            self._clear_session_pending_admin_product_create()
            return {
                "reply": "He cancelado la creación del producto pendiente.",
                "handledLocally": True,
                "source": "odoo_admin_product_create_flow",
                "success": False,
                "clearPendingAdminProductCreate": True,
                "clearPendingCart": True,
                "clearPendingCustomerPortal": True,
            }

        client_state = self._get_request_admin_product_create_client_state()
        client_answers = client_state.get("answers") or {}
        pending = self._admin_product_create_apply_client_answers(pending, client_answers)

        values = dict(pending.get("values") or {})
        skipped = list(pending.get("skipped") or [])
        server_awaiting = pending.get("awaiting") or ""
        awaiting = server_awaiting

        field_order = self._admin_product_create_field_order()
        client_awaiting = str(client_state.get("awaiting") or "").strip()
        if not self._admin_product_create_is_valid_field_key(client_awaiting):
            client_awaiting = ""
        explicit_awaiting = self._admin_product_create_detect_explicit_field(text)

        # El campo que dice el navegador tiene prioridad sobre una sesión de Odoo
        # atrasada. Si además el usuario escribe una etiqueta explícita
        # (precio:, código:, stock nacional:), usamos esa etiqueta para no guardar
        # el valor en el campo equivocado.
        if client_awaiting:
            awaiting = client_awaiting
        if explicit_awaiting:
            awaiting = explicit_awaiting

        if awaiting and awaiting in field_order and server_awaiting in field_order:
            if field_order.index(awaiting) > field_order.index(server_awaiting):
                pending = self._admin_product_create_skip_prior_optional_fields(pending, awaiting)
        elif awaiting and awaiting in field_order:
            pending = self._admin_product_create_skip_prior_optional_fields(pending, awaiting)

        pending["awaiting"] = awaiting
        values = dict(pending.get("values") or {})
        skipped = list(pending.get("skipped") or [])
        completed = self._admin_product_create_mark_prior_fields_completed(pending, awaiting)
        image_attachment = self._admin_get_product_image_attachment(attachments)
        if image_attachment:
            pending["image_attachment"] = image_attachment

        skip_answer = self._admin_product_create_is_skip_answer(text)

        # El usuario puede contestar con varios campos de golpe, por ejemplo:
        # "codigo: ABC; precio: 12,50; stock nacional: 5".
        if text and not skip_answer:
            extra_values, extra_stock_qty, extra_stock_nacional, extra_stock_internacional = self._admin_extract_product_values(text, for_create=False)
            values.update(extra_values or {})
            for parsed_key in (extra_values or {}).keys():
                if parsed_key in ("name", "default_code", "list_price", "standard_price", "categ_id", "public_categ_ids"):
                    self._admin_product_create_mark_completed(completed, parsed_key)
            if extra_stock_qty is not None:
                pending["stock_qty"] = extra_stock_qty
                self._admin_product_create_mark_completed(completed, "stock_qty")
            if extra_stock_nacional is not None:
                pending["stock_nacional"] = extra_stock_nacional
                self._admin_product_create_mark_completed(completed, "stock_nacional")
            if extra_stock_internacional is not None:
                pending["stock_internacional"] = extra_stock_internacional
                self._admin_product_create_mark_completed(completed, "stock_internacional")

        if awaiting == "name":
            if skip_answer:
                spec = next(item for item in self._admin_product_create_field_specs() if item["key"] == "name")
                return self._admin_product_create_prompt_response(pending, spec, spec["error"])
            parsed_name = (values.get("name") or text).strip()
            values["name"] = parsed_name
            if "name" in skipped:
                skipped.remove("name")
            self._admin_product_create_mark_completed(completed, "name")

        elif awaiting == "default_code":
            if skip_answer:
                if "default_code" not in skipped:
                    skipped.append("default_code")
                values.pop("default_code", None)
            else:
                # Acepta tanto "01405" como "código: 01405" sin guardar la etiqueta.
                parsed_reference = values.get("default_code")
                if not parsed_reference:
                    parsed_reference = self._admin_clean_product_reference_answer(text)
                values["default_code"] = str(parsed_reference).strip()
                if "default_code" in skipped:
                    skipped.remove("default_code")
            self._admin_product_create_mark_completed(completed, "default_code")

        elif awaiting == "list_price":
            if skip_answer:
                if "list_price" not in skipped:
                    skipped.append("list_price")
                values.pop("list_price", None)
            else:
                price = values.get("list_price")
                if price is None:
                    price = self._admin_parse_decimal(text)
                if price is None:
                    spec = next(item for item in self._admin_product_create_field_specs() if item["key"] == "list_price")
                    return self._admin_product_create_prompt_response(pending, spec, spec.get("error"))
                values["list_price"] = price
                if "list_price" in skipped:
                    skipped.remove("list_price")
            self._admin_product_create_mark_completed(completed, "list_price")

        elif awaiting == "standard_price":
            if skip_answer:
                if "standard_price" not in skipped:
                    skipped.append("standard_price")
                values.pop("standard_price", None)
            else:
                cost = values.get("standard_price")
                if cost is None:
                    cost = self._admin_parse_decimal(text)
                if cost is None:
                    spec = next(item for item in self._admin_product_create_field_specs() if item["key"] == "standard_price")
                    return self._admin_product_create_prompt_response(pending, spec, spec.get("error"))
                values["standard_price"] = cost
                if "standard_price" in skipped:
                    skipped.remove("standard_price")
            self._admin_product_create_mark_completed(completed, "standard_price")

        elif awaiting == "categ_id":
            if skip_answer:
                if "categ_id" not in skipped:
                    skipped.append("categ_id")
                values.pop("categ_id", None)
            else:
                category = self._admin_find_product_category_from_answer(text)
                if not category and values.get("categ_id"):
                    category = request.env["product.category"].sudo().browse(int(values.get("categ_id"))).exists()
                if not category:
                    spec = next(item for item in self._admin_product_create_field_specs() if item["key"] == "categ_id")
                    return self._admin_product_create_prompt_response(pending, spec, spec.get("error"))
                values["categ_id"] = category.id
                if "categ_id" in skipped:
                    skipped.remove("categ_id")
            self._admin_product_create_mark_completed(completed, "categ_id")

        elif awaiting == "public_categ_ids":
            if skip_answer:
                if "public_categ_ids" not in skipped:
                    skipped.append("public_categ_ids")
                values.pop("public_categ_ids", None)
            else:
                categories = self._admin_find_public_product_categories_from_answer(text)
                if not categories and values.get("public_categ_ids"):
                    raw_public_ids = values.get("public_categ_ids") or []
                    if isinstance(raw_public_ids, int):
                        raw_public_ids = [raw_public_ids]
                    if isinstance(raw_public_ids, (list, tuple)) and raw_public_ids:
                        try:
                            clean_ids = [int(item) for item in raw_public_ids if str(item).strip().isdigit()]
                            categories = request.env["product.public.category"].sudo().browse(clean_ids).exists() if clean_ids else False
                        except Exception:
                            categories = False
                if not categories:
                    spec = next(item for item in self._admin_product_create_field_specs() if item["key"] == "public_categ_ids")
                    return self._admin_product_create_prompt_response(pending, spec, spec.get("error"))
                self._admin_store_public_product_category_value(values, categories)
                if "public_categ_ids" in skipped:
                    skipped.remove("public_categ_ids")
            self._admin_product_create_mark_completed(completed, "public_categ_ids")

        elif awaiting in ("stock_nacional", "stock_internacional", "stock_qty"):
            if skip_answer:
                if awaiting not in skipped:
                    skipped.append(awaiting)
                pending.pop(awaiting, None)
            else:
                quantity = pending.get(awaiting)
                if quantity is None:
                    quantity = self._admin_parse_decimal(text)
                if quantity is None:
                    spec = next(item for item in self._admin_product_create_field_specs() if item["key"] == awaiting)
                    return self._admin_product_create_prompt_response(pending, spec, spec.get("error"))
                pending[awaiting] = quantity
                if awaiting in skipped:
                    skipped.remove(awaiting)
            self._admin_product_create_mark_completed(completed, awaiting)

        elif awaiting == "image":
            if pending.get("image_attachment"):
                pending["image_skipped"] = False
            elif skip_answer:
                pending["image_skipped"] = True
            else:
                spec = next(item for item in self._admin_product_create_field_specs() if item["key"] == "image")
                return self._admin_product_create_prompt_response(
                    pending,
                    spec,
                    "No he recibido ninguna imagen. Adjunta una imagen con el botón 📎 Imagen y envía el mensaje, o pulsa Enter para crear el producto sin imagen.",
                )
            self._admin_product_create_mark_completed(completed, "image")

        pending["values"] = values
        pending["skipped"] = skipped
        pending["completed"] = completed
        return self._admin_product_create_next_or_finish_response(pending)

    # Fuerza valores necesarios para que el producto rastree inventario.
    def _admin_force_inventory_tracking_values(self, ProductTemplate, values):
        """Activa la casilla 'Rastrear inventario' al crear productos desde el chat.

        En Odoo 18 esa casilla suele ser el campo ``is_storable``. En versiones
        anteriores el comportamiento equivalente depende de ``type`` o
        ``detailed_type`` con valor ``product``. Aplicamos los campos disponibles
        para que luego stock.quant pueda crear la cantidad real inicial.
        """
        values = dict(values or {})
        fields_map = ProductTemplate._fields

        if "is_storable" in fields_map:
            values["is_storable"] = True

        for field_name in ("detailed_type", "type"):
            field = fields_map.get(field_name)
            if not field:
                continue
            try:
                storable_value = self._admin_product_selection_value(field, ("product", "storable", "stockable"))
            except Exception:
                storable_value = False
            if storable_value:
                values[field_name] = storable_value
                break

        return values

    # Activa el rastreo de inventario tras crear el producto.
    def _admin_enable_product_inventory_tracking(self, template, product):
        """Reafirma el rastreo de inventario después de crear la plantilla.

        Algunos Odoo recalculan el tipo del producto durante ``create``. Antes
        de ajustar stock real, volvemos a activar el campo si existe.
        """
        ProductTemplate = request.env["product.template"].sudo()
        template = template.sudo()
        product = product.sudo()
        write_values = {}
        fields_map = ProductTemplate._fields

        if "is_storable" in fields_map and not getattr(template, "is_storable", False):
            write_values["is_storable"] = True

        for field_name in ("detailed_type", "type"):
            field = fields_map.get(field_name)
            if not field:
                continue
            storable_value = self._admin_product_selection_value(field, ("product", "storable", "stockable"))
            if storable_value and getattr(template, field_name, None) != storable_value:
                write_values[field_name] = storable_value
                break

        if write_values:
            template.write(write_values)
            product.invalidate_recordset()
            template.invalidate_recordset()
            return True
        return bool(getattr(template, "is_storable", False) or getattr(product, "type", "") == "product")

    # Crea el producto y aplica coste, stock, categorías e imagen.
    def _admin_create_product_with_values_response(self, values, stock_qty=None, stock_nacional=None, stock_internacional=None, image_attachment=None):
        ProductTemplate = request.env["product.template"].sudo()
        values = dict(values or {})
        if not values.get("name"):
            return {
                "reply": "No puedo crear el producto sin nombre. Indícame el nombre del producto.",
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": False,
                "clearPendingCart": True,
                "clearPendingCustomerPortal": True,
            }

        type_field, type_value = self._admin_product_type_value(ProductTemplate)
        if type_field and type_value and type_field not in values:
            values[type_field] = type_value
        values = self._admin_force_inventory_tracking_values(ProductTemplate, values)
        values = self._admin_prepare_public_category_create_values(ProductTemplate, values)
        values.setdefault("sale_ok", True)
        values.setdefault("purchase_ok", True)

        filtered_values = {key: value for key, value in values.items() if key in ProductTemplate._fields}
        template = ProductTemplate.create(filtered_values)
        product = template.product_variant_id.sudo()

        notes = ["Producto creado: %s" % self._short_product_label(product)]
        try:
            if template.categ_id:
                notes.append("Categoría: %s." % (getattr(template.categ_id, "complete_name", False) or template.categ_id.display_name or template.categ_id.name))
        except Exception:
            pass
        try:
            public_categories = getattr(template, "public_categ_ids", False)
            if public_categories:
                names = ", ".join(
                    getattr(category, "complete_name", False) or category.display_name or category.name
                    for category in public_categories
                )
                if names:
                    notes.append("Categoría de ventas: %s." % names)
        except Exception:
            pass
        inventory_tracking_enabled = False
        try:
            inventory_tracking_enabled = self._admin_enable_product_inventory_tracking(template, product)
        except Exception as error:
            _logger.exception("Producto creado, pero no se pudo activar Rastrear inventario")
            inventory_tracking_enabled = False

        if inventory_tracking_enabled:
            notes.append("Rastrear inventario: activado.")
        warnings = []
        image_changed = False

        if image_attachment:
            try:
                self._admin_write_product_image(template, product, image_attachment)
                image_changed = True
                notes.append("Imagen asignada: %s." % (image_attachment.get("filename") or "imagen adjunta"))
            except Exception as error:
                _logger.exception("Producto creado, pero no se pudo asignar la imagen")
                warnings.append("No se pudo asignar la imagen: %s" % error)

        if stock_qty is not None:
            try:
                before, after, location = self._admin_set_real_stock(product, stock_qty)
                notes.append("Stock real inicial: %s en %s." % (self._format_quantity(after), location.display_name))
            except Exception as error:
                _logger.exception("Producto creado, pero no se pudo ajustar el stock real")
                warnings.append("No se pudo ajustar el stock real inicial: %s" % error)

        if stock_nacional is not None:
            try:
                self._admin_write_extra_stock_field(product, "x_transit_stock_custom", stock_nacional)
                notes.append("Stock nacional: %s." % self._format_quantity(stock_nacional))
            except Exception as error:
                _logger.exception("Producto creado, pero no se pudo guardar el stock nacional")
                warnings.append("No se pudo guardar el stock nacional: %s" % error)

        if stock_internacional is not None:
            try:
                self._admin_write_extra_stock_field(product, "x_almacen1_custom", stock_internacional)
                notes.append("Stock internacional: %s." % self._format_quantity(stock_internacional))
            except Exception as error:
                _logger.exception("Producto creado, pero no se pudo guardar el stock internacional")
                warnings.append("No se pudo guardar el stock internacional: %s" % error)

        if warnings:
            notes.append("Avisos:\n- " + "\n- ".join(warnings))

        return {
            "reply": "\n".join(notes),
            "handledLocally": True,
            "source": "odoo_admin_manager",
            "success": True,
            "productCreated": True,
            "productId": product.id,
            "templateId": template.id,
            "actionButton": self._record_open_button(
                "Ver producto",
                "product.template",
                template.id,
                action_xmlids=(
                    "stock.product_template_action_product",
                    "product.product_template_action",
                    "product.product_template_action_all",
                ),
            ),
            "productImageHandled": image_changed,
            "clearPendingAdminProductCreate": True,
            "clearPendingCart": True,
            "clearPendingCustomerPortal": True,
        }

    # Inicia o ejecuta la creación administrativa de producto.
    def _admin_create_product_response(self, text, attachments=None):
        return self._admin_start_product_create_flow(text, attachments=attachments)

    # Modifica datos de un producto existente.
    def _admin_update_product_response(self, text, page_title=None, page_url=None, attachments=None):
        product, products = self._admin_find_product(text, page_title=page_title, page_url=page_url)
        if not product:
            if products:
                return {
                    "reply": "He encontrado varios productos posibles. Indícame la referencia exacta:\n" + "\n".join("- %s" % self._short_product_label(item) for item in products[:8]),
                    "handledLocally": True,
                    "source": "odoo_admin_manager",
                    "success": False,
                    "clearPendingCart": True,
                }
            return {
                "reply": "No he encontrado el producto que quieres modificar. Indícame la referencia exacta.",
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": False,
                "clearPendingCart": True,
            }

        values, _stock_qty, stock_nacional, stock_internacional = self._admin_extract_product_values(text, for_create=False)
        image_attachment = self._admin_get_product_image_attachment(attachments)
        if self._admin_product_image_requested(text) and not image_attachment:
            return {
                "reply": "Para cambiar la imagen del producto, adjunta una imagen con el botón 📎 Imagen y vuelve a enviar la instrucción.",
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": False,
                "needsProductImage": True,
                "clearPendingCart": True,
            }

        # En modificaciones, si se menciona una referencia para localizar el producto,
        # no la cambiamos salvo que venga como campo explícito referencia/ref/código/sku: valor.
        kv = self._admin_extract_key_values(text)
        if "referencia" not in kv and "ref" not in kv and "codigo" not in kv and "código" not in kv and "sku" not in kv:
            values.pop("default_code", None)
        if "nombre" not in kv and "name" not in kv:
            values.pop("name", None)

        template = product.product_tmpl_id.sudo()

        # Odoo expone varios campos comerciales del producto tanto en product.product
        # como en product.template. Escribirlos sobre la variante puede provocar
        # errores poco legibles, por ejemplo respuestas como "[80008]". Para cambios
        # de ficha (precio, coste, nombre, categoría, publicado, descripción, etc.)
        # escribimos preferentemente en la plantilla; los campos de variante como
        # referencia interna o código de barras se escriben sobre product.product.
        template_preferred_fields = {
            "name", "list_price", "standard_price", "description_sale", "categ_id",
            "sale_ok", "purchase_ok", "website_published", "public_categ_ids",
            "is_published", "available_in_pos", "taxes_id", "supplier_taxes_id",
        }
        variant_preferred_fields = {"default_code", "barcode"}
        product_values = {}
        template_values = {}
        for key, value in values.items():
            if key in template_preferred_fields and key in template._fields:
                template_values[key] = value
            elif key in variant_preferred_fields and key in product._fields:
                product_values[key] = value
            elif key in template._fields:
                template_values[key] = value
            elif key in product._fields:
                product_values[key] = value

        field_labels = {
            "name": "nombre",
            "default_code": "referencia interna",
            "barcode": "código de barras",
            "list_price": "precio de venta",
            "standard_price": "coste",
            "description_sale": "descripción",
            "categ_id": "categoría",
            "public_categ_ids": "categoría de ventas",
            "sale_ok": "se vende",
            "purchase_ok": "se compra",
            "website_published": "publicado web",
            "is_published": "publicado web",
            "available_in_pos": "disponible en TPV",
        }

        changed = []
        try:
            if template_values:
                template.write(template_values)
                changed.extend(template_values.keys())
            if product_values:
                product.sudo().write(product_values)
                changed.extend(product_values.keys())

            image_changed = False
            if image_attachment:
                self._admin_write_product_image(template, product, image_attachment)
                image_changed = True
                changed.append("imagen")
            if stock_nacional is not None:
                self._admin_write_extra_stock_field(product, "x_transit_stock_custom", stock_nacional)
                changed.append("stock nacional")
            if stock_internacional is not None:
                self._admin_write_extra_stock_field(product, "x_almacen1_custom", stock_internacional)
                changed.append("stock internacional")
        except Exception as error:
            _logger.exception("Error modificando producto desde la IA")
            detail = str(error or "error desconocido").strip()
            if re.match(r"^\s*\[[\s\S]*\]\s*$", detail):
                detail = "Odoo rechazó la actualización del producto. Revisa la ficha del producto o prueba a cambiar ese campo desde Inventario."
            return {
                "reply": "No he podido modificar el producto %s. %s" % (self._short_product_label(product), detail),
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": False,
                "clearPendingCart": True,
            }

        if not changed:
            return {
                "reply": "No he detectado qué campo del producto quieres modificar. Usa formato campo: valor, por ejemplo: modifica producto REF001 precio: 15; nombre: Nuevo nombre.",
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": False,
                "clearPendingCart": True,
            }

        changed_labels = []
        seen_changed = set()
        for field_name in changed:
            label = field_labels.get(field_name, field_name)
            if label not in seen_changed:
                seen_changed.add(label)
                changed_labels.append(label)

        return {
            "reply": "Producto modificado correctamente: %s. Campos modificados: %s." % (self._short_product_label(product), ", ".join(changed_labels)),
            "handledLocally": True,
            "source": "odoo_admin_manager",
            "success": True,
            "productId": product.id,
            "templateId": template.id,
            "productUpdated": True,
            "actionButton": self._record_open_button(
                "Ver producto",
                "product.template",
                template.id,
                action_xmlids=(
                    "stock.product_template_action_product",
                    "product.product_template_action",
                    "product.product_template_action_all",
                ),
            ),
            "clearPendingCart": True,
        }

    # Bloquea el borrado/archivado de productos desde la IA.
    def _admin_delete_product_response(self, text, page_title=None, page_url=None):
        """No elimina ni archiva productos desde el chat, ni siquiera para admin.

        El borrado de productos en Odoo puede afectar inventario, trazabilidad,
        pedidos y registros contables. Por política de seguridad, el asistente
        solo informa al usuario y no ejecuta unlink(), write(active=False) ni
        ninguna otra acción destructiva sobre product.product/product.template.
        """
        self._clear_session_pending_cart()
        self._clear_session_pending_admin_product_create()
        return self._blocked_product_delete_payload(source="odoo_admin_manager", handled_locally=True)

    # Extrae valores de cliente/contacto desde texto libre.
    def _admin_extract_customer_values(self, text, for_create=False):
        kv = self._admin_extract_key_values(text)
        values = {}

        # Devuelve el primer valor existente entre varias claves posibles.
        def first_value(*keys):
            for key in keys:
                norm = self._normalize_customer_portal_text(key)
                if norm in kv:
                    return kv[norm]
            return None

        name = first_value("nombre", "name")
        if not name and for_create:
            match = re.search(
                r"(?:crear|crea|nuevo|nueva|alta|dar\s+de\s+alta)\s+(?:un\s+|una\s+)?(?:cliente|contacto|cuenta\s+de\s+cliente)(?:\s+llamado|\s+llamada|\s+con\s+nombre|\s+de\s+nombre)?\s+(.+?)(?=\s+(?:email|correo|mail|telefono|teléfono|movil|móvil|nif|cif|vat|calle|direccion|dirección|ciudad|pais|país)\b|[,;\n]|$)",
                text or "",
                flags=re.IGNORECASE,
            )
            if match:
                name = match.group(1).strip().strip("'\".,;:")
        if name:
            values["name"] = name

        email = first_value("email", "correo electronico", "correo", "mail") or self._admin_extract_email(text)
        if email:
            values["email"] = email
        phone = first_value("telefono", "teléfono", "phone")
        if phone:
            values["phone"] = phone
        mobile = first_value("movil", "móvil", "mobile")
        if mobile:
            values["mobile"] = mobile
        street = first_value("calle", "direccion", "dirección")
        if street:
            values["street"] = street
        city = first_value("ciudad")
        if city:
            values["city"] = city
        zip_value = first_value("cp", "c.p.", "codigo postal", "código postal")
        if zip_value:
            values["zip"] = zip_value
        vat = first_value("nif", "cif", "vat")
        if vat:
            values["vat"] = vat
        website = first_value("web", "website")
        if website:
            values["website"] = website
        country_name = first_value("pais", "país")
        if country_name:
            country = request.env["res.country"].sudo().search([("name", "ilike", country_name)], limit=1)
            if country:
                values["country_id"] = country.id

        return values

    # Busca un cliente o contacto por email, teléfono o nombre.
    def _admin_find_customer(self, text):
        Partner = request.env["res.partner"].sudo()
        # Para modificaciones de email, preferimos el nombre que viene después de "cliente" y no el email nuevo.
        hint = self._admin_extract_entity_hint(
            text,
            ("cliente", "clientes", "contacto", "contactos", "cuenta", "cuentas", "cuenta de cliente"),
            stop_words=(
                "email", "correo", "mail", "telefono", "teléfono", "movil", "móvil", "nombre", "nif", "cif",
                "vat", "calle", "direccion", "dirección", "ciudad", "pais", "país", "a", "con", "por",
            ),
        )
        if hint and "@" not in hint:
            partners = Partner.search([("name", "ilike", hint)], limit=10)
            if len(partners) == 1:
                return partners[0], partners
            if len(partners) > 1:
                return False, partners

        email = self._admin_extract_email(text)
        if email:
            partners = Partner.search([("email", "=ilike", email)], limit=10)
            if len(partners) == 1:
                return partners[0], partners
            if len(partners) > 1:
                return False, partners

        if hint:
            partners = Partner.search([("name", "ilike", hint)], limit=10)
            if len(partners) == 1:
                return partners[0], partners
            if len(partners) > 1:
                return False, partners

        return False, Partner.browse()

    # Crea un cliente/contacto desde el chat administrativo.
    def _admin_create_customer_response(self, text):
        values = self._admin_extract_customer_values(text, for_create=True)
        name = (values.get("name") or "").strip()
        if not name:
            return {
                "reply": "Indícame el nombre del cliente. Ejemplo: crea cliente nombre: Juan Pérez; email: juan@prueba.es; teléfono: 600000000.",
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": False,
                "clearPendingCart": True,
            }

        Partner = request.env["res.partner"].sudo()
        values.setdefault("company_type", "person")
        values.setdefault("is_company", False)
        if "customer_rank" in Partner._fields:
            values.setdefault("customer_rank", 1)
        if "lang" in Partner._fields:
            values.setdefault("lang", request.env.lang or request.env.user.lang or "es_ES")

        filtered_values = {key: value for key, value in values.items() if key in Partner._fields}
        partner = Partner.create(filtered_values)
        return {
            "reply": "Cliente creado como Individuo: %s%s." % (partner.name, " <%s>" % partner.email if partner.email else ""),
            "handledLocally": True,
            "source": "odoo_admin_manager",
            "success": True,
            "partnerId": partner.id,
            "actionButton": self._record_open_button(
                "Ver cliente",
                "res.partner",
                partner.id,
                action_xmlids=("contacts.action_contacts", "base.action_partner_form"),
            ),
            "clearPendingCart": True,
        }

    # Actualiza datos de un cliente/contacto existente.
    def _admin_update_customer_response(self, text):
        partner, partners = self._admin_find_customer(text)
        if not partner:
            if partners:
                return {
                    "reply": "He encontrado varios clientes posibles. Indícame el email o nombre exacto:\n" + "\n".join("- %s%s" % (item.display_name, " <%s>" % item.email if item.email else "") for item in partners[:8]),
                    "handledLocally": True,
                    "source": "odoo_admin_manager",
                    "success": False,
                    "clearPendingCart": True,
                }
            return {
                "reply": "No he encontrado el cliente que quieres modificar. Indícame el nombre o email exacto.",
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": False,
                "clearPendingCart": True,
            }

        values = self._admin_extract_customer_values(text, for_create=False)
        kv = self._admin_extract_key_values(text)
        if "nombre" not in kv and "name" not in kv:
            values.pop("name", None)
        if not values:
            return {
                "reply": "No he detectado qué campo del cliente quieres modificar. Usa formato campo: valor, por ejemplo: modifica cliente Juan Pérez email: nuevo@prueba.es.",
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": False,
                "clearPendingCart": True,
            }

        filtered_values = {key: value for key, value in values.items() if key in partner._fields}
        partner.write(filtered_values)
        return {
            "reply": "Cliente actualizado: %s. Campos modificados: %s." % (partner.display_name, ", ".join(filtered_values.keys())),
            "handledLocally": True,
            "source": "odoo_admin_manager",
            "success": True,
            "partnerId": partner.id,
            "actionButton": self._partner_open_button(partner),
            "clearPendingCart": True,
        }

    # Consulta datos de un cliente/contacto existente.
    def _admin_query_customer_response(self, text):
        partner, partners = self._admin_find_customer(text)
        if not partner:
            if partners:
                return {
                    "reply": "He encontrado varios clientes posibles. Indícame el email o nombre exacto:\n" + "\n".join("- %s%s" % (item.display_name, " <%s>" % item.email if item.email else "") for item in partners[:8]),
                    "handledLocally": True,
                    "source": "odoo_admin_manager",
                    "success": False,
                    "clearPendingCart": True,
                }
            return {
                "reply": "No he encontrado el cliente. Indícame el nombre o email exacto.",
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": False,
                "clearPendingCart": True,
            }

        lines = [
            "Te paso la información del cliente:",
            "",
            "- Nombre: %s" % (partner.display_name or partner.name or "sin nombre"),
        ]
        if getattr(partner, "email", False):
            lines.append("- Email: %s" % partner.email)
        if getattr(partner, "phone", False):
            lines.append("- Teléfono: %s" % partner.phone)
        if getattr(partner, "mobile", False):
            lines.append("- Móvil: %s" % partner.mobile)
        if getattr(partner, "vat", False):
            lines.append("- NIF/CIF: %s" % partner.vat)
        try:
            if partner.company_type:
                lines.append("- Tipo: %s" % ("Empresa" if partner.company_type == "company" else "Individuo"))
        except Exception:
            pass
        address_parts = []
        for value in (getattr(partner, "street", False), getattr(partner, "zip", False), getattr(partner, "city", False)):
            if value:
                address_parts.append(value)
        try:
            if partner.country_id:
                address_parts.append(partner.country_id.name)
        except Exception:
            pass
        if address_parts:
            lines.append("- Dirección: %s" % ", ".join(address_parts))

        return {
            "reply": "\n".join(lines),
            "handledLocally": True,
            "source": "odoo_admin_manager",
            "success": True,
            "partnerId": partner.id,
            "actionButton": self._partner_open_button(partner),
            "clearPendingCart": True,
        }

    # Elimina o archiva un cliente/contacto encontrado.
    def _admin_delete_customer_response(self, text):
        partner, partners = self._admin_find_customer(text)
        if not partner:
            if partners:
                return {
                    "reply": "He encontrado varios clientes posibles. Indícame el email o nombre exacto antes de borrar:\n" + "\n".join("- %s%s" % (item.display_name, " <%s>" % item.email if item.email else "") for item in partners[:8]),
                    "handledLocally": True,
                    "source": "odoo_admin_manager",
                    "success": False,
                    "clearPendingCart": True,
                }
            return {
                "reply": "No he encontrado el cliente que quieres borrar. Indícame el nombre o email exacto.",
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": False,
                "clearPendingCart": True,
            }

        if request.env.user.partner_id and partner.id == request.env.user.partner_id.id:
            return {
                "reply": "No puedo borrar el contacto vinculado al usuario con el que estás trabajando.",
                "handledLocally": True,
                "source": "odoo_admin_manager",
                "success": False,
                "clearPendingCart": True,
            }

        label = "%s%s" % (partner.display_name, " <%s>" % partner.email if partner.email else "")
        try:
            if getattr(partner, "user_ids", False):
                partner.user_ids.sudo().write({"active": False})
            partner.unlink()
            action = "borrado"
        except Exception:
            if "active" in partner._fields:
                partner.write({"active": False})
                action = "archivado porque Odoo no permitió borrarlo definitivamente"
            else:
                raise
        return {
            "reply": "Cliente %s: %s." % (label, action),
            "handledLocally": True,
            "source": "odoo_admin_manager",
            "success": True,
            "clearPendingCart": True,
        }


    # -------------------------------------------------------------------------
    # Alta de clientes con acceso al portal desde el chat
    # -------------------------------------------------------------------------

    # Recupera el alta guiada de cliente portal pendiente.
    def _get_session_pending_customer_portal(self):
        try:
            data = request.session.get("odoo_ai_chat_pending_customer_portal") or {}
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    # Guarda el alta guiada de cliente portal pendiente.
    def _set_session_pending_customer_portal(self, payload):
        try:
            request.session["odoo_ai_chat_pending_customer_portal"] = payload or {}
        except Exception:
            pass
        return payload or {}

    # Limpia el alta guiada de cliente portal.
    def _clear_session_pending_customer_portal(self):
        try:
            request.session.pop("odoo_ai_chat_pending_customer_portal", None)
        except Exception:
            pass

    # Detecta si el usuario cancela el alta de cliente portal.
    def _is_cancel_customer_portal_answer(self, text):
        return bool(re.match(
            r"^\s*(?:cancelar|cancela|no|olvida|olvídalo|olvidalo|parar|salir)\s*$",
            text or "",
            flags=re.IGNORECASE,
        ))

    # Normaliza texto para detectar intenciones sin depender de acentos.
    def _normalize_customer_portal_text(self, message):
        text = (message or "").lower()
        replacements = {
            "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u",
            "à": "a", "è": "e", "ì": "i", "ò": "o", "ù": "u",
            "ä": "a", "ë": "e", "ï": "i", "ö": "o", "ü": "u",
            "ñ": "n",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    # Comprueba frases clave dentro del texto normalizado.
    def _contains_customer_portal_phrase(self, normalized_text, phrases):
        return any(phrase in normalized_text for phrase in phrases)

    # Detecta solicitudes para crear una cuenta de cliente portal.
    def _looks_like_customer_portal_intent(self, message):
        """Detecta distintas formas de pedir alta de cuenta/cliente portal.

        La intención se resuelve localmente para que no dependa de que n8n o el
        modelo usen una frase exacta. Soporta frases como:
        - crea un cliente
        - dar de alta una cuenta
        - registrar usuario de portal
        - crear acceso web para un cliente
        - activar portal a un contacto
        """
        normalized = self._normalize_customer_portal_text(message)

        action_phrases = (
            "crear", "crea", "creame", "crearme", "creale", "crearles",
            "nuevo", "nueva", "alta", "dar de alta", "dame de alta",
            "registrar", "registra", "registrame", "registrale", "registralo",
            "registrarla", "activar", "activa", "activame", "activale",
            "habilitar", "habilita", "habilitame", "habilitale",
            "otorgar", "conceder", "preparar", "prepara", "generar", "genera",
            "abrir", "abre", "hacer", "haz", "sacar", "saca",
        )
        subject_phrases = (
            "cliente", "contacto", "usuario", "cuenta", "cuenta cliente",
            "cuenta de cliente", "cuenta web", "cuenta del portal",
            "cuenta portal", "login", "acceso", "portal", "comprador",
            "cliente web", "usuario web", "usuario portal",
        )
        portal_phrases = (
            "portal", "acceso", "web", "login", "inicio de sesion",
            "contrasena", "password", "clave", "pass", "credencial", "credenciales",
            "entrar", "iniciar sesion",
        )

        explicit_phrases = (
            # Intenciones inequívocas de crear una CUENTA de cliente/portal.
            # En este addon, crear un cliente desde la IA debe crear una cuenta
            # completa de cliente/portal, no un partner vacío solo con nombre.
            "dar de alta una cuenta", "crear cuenta", "crea cuenta",
            "crear una cuenta", "crea una cuenta", "abrir una cuenta",
            "hacer una cuenta", "haz una cuenta", "crear cuenta de cliente",
            "crear cuenta cliente", "crear cuenta web", "crear cuenta portal",
            "crear acceso", "crear acceso web", "dar acceso", "darle acceso",
            "otorgar acceso", "otorgar acceso al portal", "activar portal",
            "habilitar portal", "acceso al portal", "usuario de portal",
            "usuario portal", "crear usuario portal", "crear usuario de portal",
            "registrar usuario de portal",
        )
        if self._contains_customer_portal_phrase(normalized, explicit_phrases):
            return True

        has_action = self._contains_customer_portal_phrase(normalized, action_phrases)
        has_subject = self._contains_customer_portal_phrase(normalized, subject_phrases)
        has_portal_context = self._contains_customer_portal_phrase(normalized, portal_phrases)
        has_email = bool(self._extract_email(message))
        has_password_hint = self._contains_customer_portal_phrase(
            normalized,
            ("contrasena", "password", "clave", "pass", "credencial", "credenciales"),
        )

        # Caso típico: "crea una cuenta para Ana con email ... y clave ...".
        if has_action and has_subject and has_portal_context:
            return True

        # Caso abreviado cuando el usuario aporta todos los datos en un único prompt.
        if has_email and has_password_hint and has_subject:
            return True

        # En este flujo, una petición genérica de crear cliente/contacto/usuario/cuenta
        # también debe entrar en el alta guiada de cuenta completa. Así evitamos que
        # "crea cliente Ana" cree un res.partner vacío sin email ni contraseña.
        # Se excluyen frases que hablan de productos/stock para no capturar altas de producto
        # que mencionen un cliente de forma contextual.
        product_context_terms = (
            "producto", "productos", "articulo", "articulos", "referencia",
            "sku", "stock", "inventario", "precio", "categoria",
        )
        customer_account_terms = (
            "cliente", "clientes", "contacto", "contactos", "usuario", "usuarios",
            "cuenta", "cuentas", "cuenta cliente", "cuenta de cliente",
        )
        has_product_context = self._contains_customer_portal_phrase(normalized, product_context_terms)
        has_customer_account_subject = self._contains_customer_portal_phrase(normalized, customer_account_terms)
        if has_action and has_customer_account_subject and not has_product_context:
            return True

        return False

    # Extrae correos electrónicos de mensajes de clientes.
    def _extract_email(self, text):
        match = re.search(r"[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", text or "", flags=re.IGNORECASE)
        return match.group(0).strip().lower() if match else ""

    # Valida el formato mínimo de un correo electrónico.
    def _is_valid_email(self, email):
        return bool(re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email or ""))

    # Limpia nombres de cliente extraídos desde texto libre.
    def _clean_extracted_customer_name(self, value):
        name = (value or "").strip()
        if not name:
            return ""
        name = re.sub(r"[\r\n]+", " ", name)
        name = re.sub(r"\s+", " ", name)
        name = re.sub(
            r"\s+(?:y\s+)?(?:con\s+)?(?:email|e-mail|correo|correo\s+electronico|mail|contraseña|contrasena|password|clave|pass|login|acceso)\b.*$",
            "",
            name,
            flags=re.IGNORECASE,
        )
        name = re.sub(
            r"^(?:para\s+|al\s+cliente\s+|a\s+nombre\s+de\s+|nombre\s+de\s+|(?:cliente|contacto|usuario|cuenta)\s*[:=-]\s*)",
            "",
            name,
            flags=re.IGNORECASE,
        )
        name = name.strip(" ,.;:'\"()[]{}")
        if not name or "@" in name:
            return ""
        normalized = self._normalize_customer_portal_text(name)
        invalid_values = {
            "cliente", "contacto", "usuario", "portal", "cuenta", "acceso",
            "web", "nuevo", "nueva", "individual", "persona", "person",
            "un cliente", "una cuenta", "cuenta cliente", "cuenta de cliente",
        }
        if normalized in invalid_values:
            return ""
        if len(name) > 160:
            name = name[:160].strip()
        return name

    # Extrae el nombre del cliente desde el mensaje.
    def _extract_customer_name_from_message(self, text):
        value = text or ""
        patterns = [
            r"(?:^|[\n,;])\s*(?:nombre|nombre\s+del\s+cliente|cliente|contacto|usuario|cuenta)\s*[:=]\s*([^\n,;]+)",
            r"(?:se\s+llama|se\s+llame|se\s+llamara|se\s+llamará|llamado|llamada|con\s+nombre|a\s+nombre\s+de)\s+([^\n,;]+)",
            r"(?:crear|crea|creame|crearme|registrar|registra|alta|dar\s+de\s+alta|nuevo|nueva|abrir|abre|hacer|haz|preparar|prepara|generar|genera|activar|activa|habilitar|habilita)\s+(?:un\s+|una\s+)?(?:cliente|contacto|usuario(?:\s+de\s+portal)?|cuenta(?:\s+de\s+cliente|\s+cliente|\s+web|\s+portal)?|acceso(?:\s+web|\s+portal)?)\s+(?:para\s+|a\s+|de\s+|llamado\s+|llamada\s+|con\s+nombre\s+|a\s+nombre\s+de\s+)?([^\n,;]+)",
            r"(?:para|a\s+nombre\s+de|al\s+cliente|cliente|contacto|usuario)\s+([^\n,;]+?)\s+(?:con\s+|email\b|e-mail\b|correo\b|mail\b|contraseña\b|contrasena\b|password\b|clave\b|pass\b)",
            r"(?:cliente|contacto|usuario|cuenta)\s+(?:es|sera|será)\s+([^\n,;]+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, value, flags=re.IGNORECASE)
            if match:
                cleaned = self._clean_extracted_customer_name(match.group(1))
                if cleaned:
                    return cleaned
        return ""

    # Extrae la contraseña deseada para el usuario portal.
    def _extract_password_from_message(self, text):
        value = text or ""
        patterns = [
            r"(?:nueva\s+)?(?:contraseña|contrasena|password|clave|pass)(?:\s+(?:nueva|del\s+portal|de\s+acceso))?\s*[:=]\s*(.+?)(?=$|[\n,;])",
            r"(?:con\s+|la\s+|una\s+|su\s+)?(?:nueva\s+)?(?:contraseña|contrasena|password|clave|pass)\s+(?:es\s+|sera\s+|será\s+)?(.+?)(?=$|[\n,;])",
            r"(?:pon(?:le)?|asigna(?:le)?|establece|definir|define)\s+(?:como\s+)?(?:contraseña|contrasena|password|clave|pass)\s*(?:es\s+|:|=)?\s*(.+?)(?=$|[\n,;])",
        ]
        for pattern in patterns:
            match = re.search(pattern, value, flags=re.IGNORECASE)
            if match:
                password = (match.group(1) or "").strip().strip("'\"")
                if password:
                    return password
        return ""

    # Extrae nombre, email y contraseña para crear usuario portal.
    def _extract_customer_portal_details(self, text):
        return {
            "name": self._extract_customer_name_from_message(text),
            "email": self._extract_email(text),
            "password": self._extract_password_from_message(text),
        }

    # Detecta qué datos faltan en el alta de cliente portal.
    def _missing_customer_portal_fields(self, values):
        missing = []
        if not (values or {}).get("name"):
            missing.append("name")
        if not self._is_valid_email((values or {}).get("email") or ""):
            missing.append("email")
        if not (values or {}).get("password"):
            missing.append("password")
        return missing

    # Devuelve la etiqueta visible de cada campo de cliente portal.
    def _field_label_for_customer_portal(self, field_name):
        return {
            "name": "nombre del cliente",
            "email": "correo electrónico",
            "password": "nueva contraseña",
        }.get(field_name, field_name)

    # Pregunta el siguiente dato necesario del cliente portal.
    def _ask_next_customer_portal_field(self, values):
        missing = self._missing_customer_portal_fields(values)
        if not missing:
            return None

        next_field = missing[0]
        self._set_session_pending_customer_portal({
            "active": True,
            "values": values or {},
            "awaiting": next_field,
        })

        if next_field == "name":
            return "Perfecto. Indícame el nombre del cliente que quieres crear."
        if next_field == "email":
            return "Indícame el correo electrónico del cliente."
        if next_field == "password":
            return "Indícame la nueva contraseña para el acceso al portal."
        return "Indícame el dato que falta: %s." % self._field_label_for_customer_portal(next_field)

    # Fusiona respuestas nuevas con el estado pendiente del portal.
    def _merge_customer_portal_values_from_pending(self, pending, user_message):
        values = dict((pending or {}).get("values") or {})
        awaiting = (pending or {}).get("awaiting") or ""
        extracted = self._extract_customer_portal_details(user_message or "")

        for key in ("name", "email", "password"):
            if extracted.get(key):
                values[key] = extracted[key]

        raw_text = (user_message or "").strip()
        if awaiting == "name" and not values.get("name"):
            values["name"] = self._clean_extracted_customer_name(raw_text)
        elif awaiting == "email" and not values.get("email"):
            values["email"] = self._extract_email(raw_text)
        elif awaiting == "password" and not values.get("password"):
            # En este paso el texto completo se considera la contraseña, salvo que venga etiquetada.
            values["password"] = raw_text.strip().strip("'\"")

        return values

    # Gestiona localmente el alta de usuarios portal sin pasar por n8n.
    def _try_handle_customer_portal_turn(self, user_message=None):
        """Crea un cliente Individual y su usuario de Portal desde el chat.

        El flujo replica por backend los pasos que antes se hacían en la interfaz:
        Clientes → Nuevo, contacto Individual, Otorgar acceso al portal,
        Ajustes → Gestionar usuarios → Cambiar contraseña.
        """
        text = (user_message or "").strip()
        if not text:
            return None

        pending = self._get_session_pending_customer_portal()
        has_portal_intent = self._looks_like_customer_portal_intent(text)

        if pending and self._is_cancel_customer_portal_answer(text):
            self._clear_session_pending_customer_portal()
            return {
                "reply": "Perfecto, cancelo la creación del cliente con acceso al portal.",
                "handledLocally": True,
                "source": "odoo_customer_portal",
                "clearPendingCustomerPortal": True,
            }

        if (pending or has_portal_intent) and not self._is_admin_ai_operator():
            return self._admin_permission_denied_response(source="odoo_customer_portal")

        if pending:
            values = self._merge_customer_portal_values_from_pending(pending, text)
            if values.get("email") and not self._is_valid_email(values.get("email")):
                values["email"] = ""
            missing_reply = self._ask_next_customer_portal_field(values)
            if missing_reply:
                return {
                    "reply": missing_reply,
                    "handledLocally": True,
                    "source": "odoo_customer_portal",
                    "needsCustomerPortalData": True,
                }
            return self._create_customer_portal_response(values)

        if not has_portal_intent:
            return None

        values = self._extract_customer_portal_details(text)
        if values.get("email") and not self._is_valid_email(values.get("email")):
            values["email"] = ""

        missing_reply = self._ask_next_customer_portal_field(values)
        if missing_reply:
            return {
                "reply": missing_reply,
                "handledLocally": True,
                "source": "odoo_customer_portal",
                "needsCustomerPortalData": True,
            }

        return self._create_customer_portal_response(values)

    # Prepara los valores del partner de Odoo para un cliente portal.
    def _prepare_customer_partner_values(self, name, email):
        Partner = request.env["res.partner"].sudo()
        fields_map = Partner._fields
        vals = {
            "name": name,
            "email": email,
        }
        if "company_type" in fields_map:
            vals["company_type"] = "person"
        if "is_company" in fields_map:
            vals["is_company"] = False
        if "customer_rank" in fields_map:
            vals["customer_rank"] = 1
        if "company_id" in fields_map:
            vals["company_id"] = request.env.company.id
        if "lang" in fields_map:
            try:
                vals["lang"] = request.env.lang or request.env.user.lang or "es_ES"
            except Exception:
                vals["lang"] = "es_ES"
        return vals

    # Busca si ya existe un partner para ese email.
    def _find_existing_partner_for_customer_portal(self, email):
        Partner = request.env["res.partner"].sudo()
        return Partner.search([("email", "=ilike", email)], limit=1)

    # Crea o reutiliza el partner asociado a un usuario portal.
    def _ensure_customer_partner(self, name, email):
        Partner = request.env["res.partner"].sudo()
        values = self._prepare_customer_partner_values(name, email)
        partner = self._find_existing_partner_for_customer_portal(email)
        created = False

        if partner:
            # Si ya existía como compañía, lo normalizamos a individuo como pidió el flujo.
            partner.write(values)
        else:
            partner = Partner.create(values)
            created = True

        return partner, created

    # Obtiene el grupo Portal de Odoo.
    def _get_portal_group(self):
        try:
            return request.env.ref("base.group_portal", raise_if_not_found=False)
        except TypeError:
            try:
                return request.env.ref("base.group_portal")
            except Exception:
                return False
        except Exception:
            return False

    # Obtiene el grupo Usuario interno para evitar asignarlo al portal.
    def _get_internal_user_group(self):
        try:
            return request.env.ref("base.group_user", raise_if_not_found=False)
        except TypeError:
            try:
                return request.env.ref("base.group_user")
            except Exception:
                return False
        except Exception:
            return False

    # Crea el usuario portal y le asigna credenciales y grupo correcto.
    def _create_portal_user_for_partner(self, partner, email, password):
        User = request.env["res.users"].sudo()
        existing_user = User.search([("login", "=", email)], limit=1)
        if existing_user:
            raise ValueError(
                "Ya existe un usuario con ese correo como inicio de sesión. Usa otro correo o modifica el usuario existente."
            )

        portal_group = self._get_portal_group()
        if not portal_group:
            raise ValueError("No se encontró el grupo de Portal en Odoo. Revisa que el módulo Portal esté instalado.")

        company = request.env.company
        user_values = {
            "name": partner.name,
            "login": email,
            "email": email,
            "partner_id": partner.id,
            "groups_id": [(6, 0, [portal_group.id])],
        }
        if "company_id" in User._fields and company:
            user_values["company_id"] = company.id
        if "company_ids" in User._fields and company:
            user_values["company_ids"] = [(6, 0, [company.id])]
        if "active" in User._fields:
            user_values["active"] = True

        user = User.with_context(no_reset_password=True, mail_create_nosubscribe=True).create(user_values)

        internal_group = self._get_internal_user_group()
        group_commands = [(4, portal_group.id)]
        if internal_group and internal_group in user.groups_id:
            group_commands.append((3, internal_group.id))
        if group_commands:
            user.write({"groups_id": group_commands})

        user.write({"password": password})
        return user

    # Finaliza la creación de usuario portal y responde al chat.
    def _create_customer_portal_response(self, values):
        name = self._clean_extracted_customer_name((values or {}).get("name") or "")
        email = ((values or {}).get("email") or "").strip().lower()
        password = ((values or {}).get("password") or "").strip()

        if not name:
            return {
                "reply": self._ask_next_customer_portal_field({"email": email, "password": password}),
                "handledLocally": True,
                "source": "odoo_customer_portal",
                "needsCustomerPortalData": True,
            }
        if not self._is_valid_email(email):
            return {
                "reply": self._ask_next_customer_portal_field({"name": name, "password": password}),
                "handledLocally": True,
                "source": "odoo_customer_portal",
                "needsCustomerPortalData": True,
            }
        if not password:
            return {
                "reply": self._ask_next_customer_portal_field({"name": name, "email": email}),
                "handledLocally": True,
                "source": "odoo_customer_portal",
                "needsCustomerPortalData": True,
            }

        try:
            partner, partner_created = self._ensure_customer_partner(name, email)
            user = self._create_portal_user_for_partner(partner, email, password)
            self._clear_session_pending_customer_portal()

            created_text = "creado" if partner_created else "actualizado"
            return {
                "success": True,
                "handledLocally": True,
                "source": "odoo_customer_portal",
                "partnerId": partner.id,
                "userId": user.id,
                "actionButton": self._record_open_button(
                    "Ver cliente",
                    "res.partner",
                    partner.id,
                    action_xmlids=("contacts.action_contacts", "base.action_partner_form"),
                ),
                "clearPendingCustomerPortal": True,
                "reply": (
                    f"Cliente {created_text} correctamente como Individuo.\n"
                    f"Nombre: {partner.name}\n"
                    f"Email: {email}\n"
                    "Acceso al portal: otorgado.\n"
                    "Contraseña: establecida correctamente."
                ),
            }
        except Exception as error:
            _logger.exception("No se pudo crear cliente con acceso al portal")
            self._clear_session_pending_customer_portal()
            return {
                "success": False,
                "handledLocally": True,
                "source": "odoo_customer_portal",
                "clearPendingCustomerPortal": True,
                "reply": "No he podido crear el cliente con acceso al portal. Detalle técnico: %s" % error,
            }

    # Extrae referencias, códigos o SKUs desde un mensaje.
    def _extract_product_codes(self, message, limit=12):
        """Extrae posibles referencias internas/barcodes escritas por el visitante.

        Soporta formatos habituales como [10927], 10927, DC12V-001, ABC/123, etc.
        La búsqueda real se hace contra product.product.default_code y product.product.barcode.
        """
        text = message or ""
        # Evita que URL, dominios o títulos del sitio se interpreten como referencias
        # de producto cuando el usuario solo ha escrito una cantidad o una pregunta general.
        text = re.sub(r"https?://\S+", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"\b(?:www\.)?[a-z0-9][a-z0-9-]*(?:\.[a-z0-9][a-z0-9-]*)+(?::\d+)?(?:/\S*)?", " ", text, flags=re.IGNORECASE)
        candidates = []

        for value in re.findall(r"\[([^\]]{2,64})\]", text):
            candidates.append(value.strip())

        for value in re.findall(r"(?<!\w)[A-Za-z0-9][A-Za-z0-9._\-/]{2,63}(?!\w)", text):
            candidates.append(value.strip())

        # Evita buscar palabras normales como si fueran códigos.
        stopwords = {
            "stock", "real", "producto", "productos", "precio", "precios", "referencia",
            "referencias", "codigo", "código", "cod", "hay", "tienes", "teneis", "tenéis",
            "dime", "sacar", "dame", "cantidad", "unidades", "inventario", "odoo",
            "carrito", "cesta", "añade", "anade", "añadir", "anadir", "agrega",
            "agregar", "mete", "pon", "comprar", "compra", "quiero", "necesito",
            "http", "https", "www", "localhost", "local", "shop", "page", "home",
            "crear", "crea", "generar", "genera", "nuevo", "nueva",
            "pedido", "pedidos", "venta", "ventas", "compra", "compras",
            "presupuesto", "presupuestos", "orden", "ordenes", "órdenes", "rfq",
        }

        normalized = []
        seen = set()
        for candidate in candidates:
            candidate = candidate.strip().strip(".,;:(){}<>¡!¿?\"'")
            if not candidate:
                continue
            if candidate.lower() in stopwords:
                continue
            key = candidate.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(candidate)
            if len(normalized) >= limit:
                break

        return normalized

    # Detecta si el mensaje requiere información de productos o inventario.
    def _looks_like_product_question(self, message):
        raw_text = message or ""
        # Una respuesta como "2 unidades" normalmente es la cantidad de un carrito
        # pendiente, no una nueva consulta de inventario. Si no hay carrito pendiente,
        # tampoco debe activar búsqueda por URL/título de la página.
        if re.match(r"^\s*\d+(?:[\.,]\d+)?\s*(?:uds?\.?|unidades?|metros?|metro|m)?\s*$", raw_text, flags=re.IGNORECASE):
            return False

        text = raw_text.lower()
        keywords = (
            "producto", "productos", "stock", "inventario", "existencias", "existencia",
            "precio", "referencia", "código", "codigo", "cod", "sku", "unidades",
            "categoria", "categoría", "categorias", "categorías",
            "disponible", "disponibilidad", "hay", "tienes", "tenéis", "teneis",
        )
        return any(keyword in text for keyword in keywords)

    # Formatea cantidades sin decimales innecesarios.
    def _format_quantity(self, value):
        try:
            value = float(value or 0.0)
            if value.is_integer():
                return str(int(value))
            return f"{value:.2f}".rstrip("0").rstrip(".")
        except Exception:
            return str(value)

    # Lee campos estándar o personalizados de forma segura.
    def _get_field_value(self, record, field_name, default=0.0):
        """Lee un campo personalizado de forma segura.

        En algunas bases los campos x_transit_stock_custom y x_almacen1_custom
        están en product.template; en otras pueden estar disponibles también
        desde product.product por herencia delegada. Este método evita errores
        si el campo no existe en uno de los modelos.
        """
        try:
            if record and field_name in record._fields:
                return getattr(record, field_name) or default, True
        except Exception:
            pass
        return default, False

    # Obtiene stock nacional e internacional del producto.
    def _get_product_stock_breakdown(self, product):
        """Devuelve el desglose de stock adicional del producto.

        stock_real se mantiene como product.product.qty_available.
        stock_nacional y stock_internacional se leen de los campos personalizados:
        - x_transit_stock_custom
        - x_almacen1_custom
        """
        template = product.product_tmpl_id if getattr(product, "product_tmpl_id", False) else False

        stock_nacional, found_nacional = self._get_field_value(product, "x_transit_stock_custom")
        if not found_nacional and template:
            stock_nacional, _ = self._get_field_value(template, "x_transit_stock_custom")

        stock_internacional, found_internacional = self._get_field_value(product, "x_almacen1_custom")
        if not found_internacional and template:
            stock_internacional, _ = self._get_field_value(template, "x_almacen1_custom")

        return stock_nacional, stock_internacional

    # Resume un producto en una línea compacta para contexto o respuesta.
    def _format_product_line(self, product, currency=None):
        fields_map = product._fields
        name = product.display_name or product.name or "Producto sin nombre"

        code = getattr(product, "default_code", False)
        code_text = f" - Ref: {code}" if code else ""

        barcode = getattr(product, "barcode", False) if "barcode" in fields_map else False
        barcode_text = f" - Barcode: {barcode}" if barcode else ""

        price = getattr(product, "lst_price", None)
        price_text = ""
        if price is not None:
            symbol = currency.symbol if currency else ""
            price_text = f" - Precio: {float(price):.2f} {symbol}".strip()

        uom = product.uom_id.name if getattr(product, "uom_id", False) else "uds"
        qty_available = getattr(product, "qty_available", 0.0)
        stock_text = f" - Stock real: {self._format_quantity(qty_available)} {uom}"

        stock_nacional, stock_internacional = self._get_product_stock_breakdown(product)
        stock_nacional_text = f" - Stock nacional 48h: {self._format_quantity(stock_nacional)} {uom}"
        stock_internacional_text = f" - Stock internacional 7d: {self._format_quantity(stock_internacional)} {uom}"

        free_qty_text = ""
        if "free_qty" in fields_map:
            free_qty_text = f" - Disponible: {self._format_quantity(product.free_qty)} {uom}"

        virtual_text = ""
        if "virtual_available" in fields_map:
            virtual_text = f" - Previsto: {self._format_quantity(product.virtual_available)} {uom}"

        template = product.product_tmpl_id if getattr(product, "product_tmpl_id", False) else False
        sale_ok = template.sale_ok if template else getattr(product, "sale_ok", False)
        sale_text = " - Vendible: sí" if sale_ok else " - Vendible: no"

        return f"- {name}{code_text}{barcode_text}{price_text}{stock_text}{stock_nacional_text}{stock_internacional_text}{free_qty_text}{virtual_text}{sale_text}"

    # Busca productos por códigos exactos y después por coincidencia parcial.
    def _search_products_by_codes(self, Product, codes, limit=25):
        if not codes:
            return Product.browse(), []

        fields_map = Product._fields
        exact_domains = [("default_code", "in", codes)]
        if "barcode" in fields_map:
            exact_domains.append(("barcode", "in", codes))

        domain = expression.OR([[d] for d in exact_domains])
        products = Product.search(domain, limit=limit)

        found_values = set()
        for product in products:
            if product.default_code:
                found_values.add(product.default_code.lower())
            if "barcode" in fields_map and product.barcode:
                found_values.add(product.barcode.lower())

        not_found = [code for code in codes if code.lower() not in found_values]

        # Segundo intento: búsqueda parcial, útil si el usuario omite ceros iniciales
        # o escribe una referencia incompleta.
        if not products and codes:
            ilike_domains = []
            for code in codes[:5]:
                ilike_domains.append([("default_code", "ilike", code)])
                if "barcode" in fields_map:
                    ilike_domains.append([("barcode", "ilike", code)])
            products = Product.search(expression.OR(ilike_domains), limit=limit)
            if products:
                not_found = []

        return products, not_found

    # Decide si se debe enviar contexto de inventario al prompt de n8n.
    def _should_include_product_context_for_ai(self, user_message=None):
        """Decide si merece la pena enviar inventario a n8n.

        La mayoría de consultas de producto/stock ya se contestan localmente antes de
        llegar al webhook. Solo enviamos una muestra compacta de inventario si el texto
        realmente parece una pregunta de producto y la lógica local no la pudo resolver.
        """
        message = user_message or ""
        if not message.strip():
            return False
        if self._is_cart_intent(message):
            return False
        if self._looks_like_admin_management_intent(message):
            return False
        if self._looks_like_customer_portal_intent(message):
            return False
        return bool(self._looks_like_product_question(message))

    # Construye o bloquea el contexto de productos para reducir tokens.
    def _build_ai_product_context_if_needed(self, user_message=None):
        if not self._should_include_product_context_for_ai(user_message):
            return "No se incluye inventario: la pregunta no parece referirse a productos, precios, referencias ni stock."
        # Límite bajo para no enviar cientos de líneas al modelo. Las consultas exactas
        # por referencia se resuelven localmente antes de llamar a n8n.
        return self._build_product_context(user_message=user_message, limit=8)

    # Construye una muestra limitada de inventario para el prompt de n8n.
    def _build_product_context(self, user_message=None, limit=8):
        """Construye contexto desde Inventario → Productos, no desde páginas web.

        Antes se usaban product.template publicados en web. Ahora se consultan variantes
        reales de inventario: product.product, incluyendo referencia interna y stock real.
        """
        try:
            Product = request.env["product.product"].sudo()
            fields_map = Product._fields

            currency = None
            try:
                currency = request.website.currency_id
            except Exception:
                currency = request.env.company.currency_id

            codes = self._extract_product_codes(user_message or "")
            products, not_found = self._search_products_by_codes(Product, codes, limit=limit)

            header_lines = [
                "Fuente: Inventario de Odoo → Productos.",
                "Cada línea de producto incluye Stock real, Stock nacional 48h y Stock internacional 7d.",
                "No se filtra por páginas web ni por productos publicados en ecommerce.",
                "Importante: no muestres nombres técnicos de campos en la respuesta al visitante.",
            ]

            if codes:
                header_lines.append("Referencias detectadas en la pregunta: " + ", ".join(codes))

            if not products:
                # Si no hay código exacto, damos una muestra útil del inventario interno.
                # Esto permite responder preguntas generales de catálogo sin depender del website.
                domain = [("active", "=", True)] if "active" in fields_map else []
                products = Product.search(domain, limit=limit, order="default_code asc, name asc")

            if not products:
                return "\n".join(header_lines + ["No hay productos activos disponibles en Inventario → Productos."])

            lines = [self._format_product_line(product, currency=currency) for product in products]

            if not_found:
                lines.append(
                    "Referencias no encontradas en product.product.default_code ni barcode: "
                    + ", ".join(not_found)
                )

            return "\n".join(header_lines + lines)
        except Exception as error:
            _logger.exception("No se pudo construir el contexto de productos desde Inventario")
            return f"No se pudo leer Inventario → Productos de Odoo. Error interno: {error}"


    # Responde localmente fichas de producto y evita usar IA.
    def _try_build_local_product_reply(self, user_message=None, page_title=None, page_url=None):
        """Responde desde Odoo las consultas de producto/stock sin depender del modelo IA.

        Esto hace que cambiar de Ollama a Gemini, o a cualquier otro modelo en n8n,
        no altere el formato ni la exactitud de stock, precio o disponibilidad.
        Las acciones de carrito se tratan en /ai/cart/intent antes de llegar aquí.
        """
        try:
            if not user_message:
                return None

            if self._is_cart_intent(user_message):
                return None

            if not self._looks_like_product_question(user_message):
                return None

            product, products, codes = self._find_product_for_information(
                user_message=user_message,
                page_title=page_title,
                page_url=page_url,
            )

            if product:
                # Al mostrar una ficha de producto a clientes/portal/público, dejamos
                # preparada la operación de carrito para que respuestas cortas como
                # "2 unidades" o "añade 2" se resuelvan en Odoo sin depender de n8n.
                # Para la cuenta admin no se solicita añadir al carrito ni se deja un
                # carrito pendiente, porque admin usa el chat principalmente para
                # consultas y gestión interna.
                if self._is_admin_ai_operator():
                    self._clear_session_pending_cart()
                    payload = {
                        "reply": self._format_product_details_reply(product, include_cart_prompt=False),
                        "actionButton": self._product_open_button(product),
                    }
                    return payload
                self._set_session_pending_cart(product)
                return self._format_product_details_reply(product, include_cart_prompt=True)

            if products and len(products) > 1:
                options = [self._short_product_label(item) for item in products[:5]]
                return "He encontrado varios productos posibles. Indícame la referencia exacta:\n" + "\n".join(
                    f"- {option}" for option in options
                )

            if codes:
                return "No he encontrado ningún producto con la referencia: " + ", ".join(codes) + "."

            return None
        except Exception:
            _logger.exception("No se pudo construir respuesta local de producto")
            return None

    # Localiza el producto sobre el que se solicita información.
    def _find_product_for_information(self, user_message=None, page_title=None, page_url=None):
        Product = request.env["product.product"].sudo()
        combined_text = " ".join(value for value in (user_message, page_title, page_url) if value)
        codes = self._extract_product_codes(combined_text, limit=12)
        products, _not_found = self._search_products_by_codes(Product, codes, limit=10)

        if len(products) == 1:
            return products[0], products, codes
        if len(products) > 1:
            return False, products, codes

        name_products = self._search_products_by_name_for_cart(Product, user_message or "", limit=5)
        if len(name_products) == 1:
            return name_products[0], name_products, codes
        if len(name_products) > 1:
            return False, name_products, codes

        category_products = self._search_products_by_category_for_customer(Product, user_message or "", limit=8)
        if len(category_products) == 1:
            return category_products[0], category_products, codes
        if len(category_products) > 1:
            return False, category_products, codes

        return False, Product.browse(), codes

    # Limpia el nombre público del producto.
    def _get_product_display_name_clean(self, product):
        template = product.product_tmpl_id if getattr(product, "product_tmpl_id", False) else False
        if template and template.name:
            return template.name
        return product.name or product.display_name or "Producto sin nombre"

    # Formatea el precio de venta con moneda para el visitante.
    def _format_price_for_customer(self, product):
        try:
            currency = request.website.currency_id
        except Exception:
            currency = request.env.company.currency_id

        price = getattr(product, "lst_price", None)
        if price is None:
            return None

        symbol = currency.symbol if currency else "€"
        try:
            return f"{float(price):.2f} {symbol}".strip()
        except Exception:
            return f"{price} {symbol}".strip()

    # Convierte booleanos en sí o no.
    def _format_yes_no(self, value):
        return "sí" if bool(value) else "no"

    # Genera una ficha breve del producto para el chat.
    def _format_product_details_reply(self, product, include_cart_prompt=True):
        availability = self._get_cart_availability(product)
        fields_map = product._fields
        code = product.default_code or "sin referencia"
        price = self._format_price_for_customer(product)
        sale_ok = self._is_product_sellable(product)

        lines = [
            "Te paso la información del producto en inventario:",
            "",
            f"- Nombre: {self._get_product_display_name_clean(product)}",
            f"- Referencia: {code}",
        ]

        if price:
            lines.append(f"- Precio: {price}")

        lines.extend([
            f"- Stock real: {self._format_quantity(availability['stock_real'])} {availability['uom']}",
            f"- Stock nacional 48h: {self._format_quantity(availability['stock_nacional'])} {availability['uom']}",
            f"- Stock internacional 7d: {self._format_quantity(availability['stock_internacional'])} {availability['uom']}",
            f"- Disponible: {self._format_quantity(availability['available_qty'])} {availability['uom']}",
        ])

        if "virtual_available" in fields_map:
            lines.append(f"- Previsto: {self._format_quantity(product.virtual_available)} {availability['uom']}")

        lines.append(f"- Vendible: {self._format_yes_no(sale_ok)}")
        if include_cart_prompt:
            lines.append("")
            lines.append("Si quieres, puedo añadirlo al carrito. Indícame la cantidad.")
        return _sanitize_reply_for_customer("\n".join(lines))


    # Recupera la operación de carrito pendiente.
    def _get_session_pending_cart(self):
        """Recupera una operación de carrito pendiente guardada en la sesión web.

        Esto hace que el flujo funcione aunque el navegador aún tenga una versión
        antigua del JavaScript o aunque cambie el proveedor de IA en n8n. La
        decisión de añadir al carrito queda en Odoo, no en Gemini/Ollama.
        """
        try:
            data = request.session.get("odoo_ai_chat_pending_cart") or {}
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    # Guarda una operación de carrito pendiente.
    def _set_session_pending_cart(self, product):
        payload = self._pending_cart_payload(product)
        try:
            request.session["odoo_ai_chat_pending_cart"] = payload
        except Exception:
            pass
        return payload

    # Limpia la operación de carrito pendiente.
    def _clear_session_pending_cart(self):
        try:
            request.session.pop("odoo_ai_chat_pending_cart", None)
        except Exception:
            pass

    # Gestiona intención de carrito localmente antes de llamar a n8n.
    def _try_handle_cart_turn(self, user_message=None, page_title=None, page_url=None):
        """Gestiona el carrito completamente desde Odoo.

        El widget JS también llama a /ai/cart/intent y /ai/cart/add, pero este
        método se ejecuta además en /ai/chat/start y /ai/chat. Así, si el JS está
        en caché o se cambia de Ollama a Gemini en n8n, la compra no depende del
        texto que genere el modelo: Odoo detecta intención, pregunta cantidad,
        valida disponibilidad y modifica el pedido real de website_sale.
        """
        text = (user_message or "").strip()
        if not text:
            return None

        if self._is_product_delete_or_archive_intent(text):
            self._clear_session_pending_cart()
            return self._blocked_product_delete_payload(source="odoo_cart", handled_locally=True)

        pending = self._get_session_pending_cart()
        pending_product = self._get_product_from_cart_payload(pending) if pending else False

        if pending_product:
            if self._is_cancel_cart_answer(text):
                self._clear_session_pending_cart()
                return {
                    "reply": "Perfecto, cancelo la operación de carrito.",
                    "handledLocally": True,
                    "source": "odoo_cart",
                    "clearPendingCart": True,
                }

            if self._is_cart_quantity_answer(text):
                quantity = self._parse_quantity_value(text)
                if quantity is not None:
                    result = self._add_product_to_cart_response(pending_product, quantity)
                    result.update({"handledLocally": True, "source": "odoo_cart"})
                    return result

            # Compatibilidad: después de consultar una ficha, el usuario puede responder
            # "añade 2". Lo tratamos como cantidad del producto pendiente solo si no
            # menciona explícitamente otra referencia. Si menciona otra referencia, se
            # cancela el pendiente antiguo y se procesa el mensaje actual como nueva acción.
            pending_code = (pending_product.default_code or "").strip()
            message_codes = self._extract_product_codes(text, limit=5)
            mentions_other_product = bool(message_codes and (not pending_code or pending_code not in message_codes))
            if self._is_cart_intent(text) and not mentions_other_product:
                quantity = self._parse_requested_quantity(text, product_codes=[pending_code] if pending_code else [])
                if quantity is not None:
                    result = self._add_product_to_cart_response(pending_product, quantity)
                    result.update({"handledLocally": True, "source": "odoo_cart"})
                    return result

            # Si había un carrito pendiente y el usuario escribe otra cosa
            # (otra búsqueda, una pregunta, una acción administrativa, etc.), cancelamos
            # el pendiente en silencio y dejamos que el mensaje continúe por su flujo normal.
            self._clear_session_pending_cart()

        if not self._is_cart_intent(text):
            return None

        product, products, codes = self._find_cart_product(text, page_title=page_title, page_url=page_url)
        if not product:
            if products and len(products) > 1:
                options = [self._short_product_label(item) for item in products[:5]]
                return {
                    "reply": "He encontrado varios productos posibles. Indícame la referencia exacta:\n" + "\n".join(f"- {option}" for option in options),
                    "handledLocally": True,
                    "source": "odoo_cart",
                    "success": False,
                }
            return {
                "reply": "Claro. Indícame la referencia del producto y la cantidad que quieres añadir al carrito.",
                "handledLocally": True,
                "source": "odoo_cart",
                "success": False,
            }

        quantity = self._parse_requested_quantity(text, product_codes=codes)
        if quantity is None:
            availability = self._get_cart_availability(product)
            return {
                "reply": (
                    f"Producto localizado: {self._short_product_label(product)}.\n"
                    f"Disponibilidad actual: {self._format_quantity(availability['available_qty'])} {availability['uom']}.\n"
                    f"Stock real: {self._format_quantity(availability['stock_real'])} {availability['uom']}.\n"
                    f"Stock nacional 48h: {self._format_quantity(availability['stock_nacional'])} {availability['uom']}.\n"
                    f"Stock internacional 7d: {self._format_quantity(availability['stock_internacional'])} {availability['uom']}.\n"
                    "¿Qué cantidad quieres añadir al carrito?"
                ),
                "handledLocally": True,
                "source": "odoo_cart",
                "success": True,
                "needsQuantity": True,
                "pendingCart": self._set_session_pending_cart(product),
                "actionButton": self._product_open_button_for_current_user(product),
            }

        result = self._add_product_to_cart_response(product, quantity)
        result.update({"handledLocally": True, "source": "odoo_cart"})
        return result

    # Detecta cancelaciones del flujo de carrito.
    def _is_cancel_cart_answer(self, text):
        return bool(re.match(r"^\s*(?:cancelar|cancela|no|olvida|olvídalo|olvidalo|parar|salir)\s*$", text or "", flags=re.IGNORECASE))


    # Ruta que detecta intención de añadir al carrito.
    @http.route("/ai/cart/intent", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_cart_intent(self, **kwargs):
        """Detecta peticiones de carrito antes de enviar el mensaje a n8n."""
        try:
            raw_body = request.httprequest.data or b"{}"
            data = json.loads(raw_body.decode("utf-8"))
            user_message = (data.get("message") or "").strip()
            self._set_request_client_session_id(data.get("sessionId") or "odoo-public")
            page_title = data.get("pageTitle") or ""
            page_url = data.get("pageUrl") or ""

            if self._is_product_delete_or_archive_intent(user_message):
                self._clear_session_pending_cart()
                payload = self._blocked_product_delete_payload(source="odoo_cart", handled_locally=True)
                payload["handled"] = True
                return _json_response(payload)

            if self._get_session_pending_admin_product_create():
                return _json_response({"handled": False})

            pending = self._get_session_pending_cart()
            pending_product = self._get_product_from_cart_payload(pending) if pending else False
            if pending_product:
                if self._is_cancel_cart_answer(user_message):
                    self._clear_session_pending_cart()
                    return _json_response({
                        "handled": True,
                        "success": True,
                        "reply": "Perfecto, cancelo la operación de carrito.",
                        "clearPendingCart": True,
                    })

                if self._is_cart_quantity_answer(user_message):
                    quantity = self._parse_quantity_value(user_message)
                    if quantity is not None:
                        result = self._add_product_to_cart_response(pending_product, quantity)
                        result["handled"] = True
                        return _json_response(result)

                pending_code = (pending_product.default_code or "").strip()
                message_codes = self._extract_product_codes(user_message, limit=5)
                mentions_other_product = bool(message_codes and (not pending_code or pending_code not in message_codes))
                if self._is_cart_intent(user_message) and not mentions_other_product:
                    quantity = self._parse_requested_quantity(user_message, product_codes=[pending_code] if pending_code else [])
                    if quantity is not None:
                        result = self._add_product_to_cart_response(pending_product, quantity)
                        result["handled"] = True
                        return _json_response(result)

                # El usuario no ha dado una cantidad válida para el producto pendiente.
                # Cancelamos el pendiente y permitimos que el mensaje actual siga hacia
                # el flujo normal: otra búsqueda, una consulta general o una acción nueva.
                self._clear_session_pending_cart()
                return _json_response({"handled": False, "clearPendingCart": True})

            if not user_message or not self._is_cart_intent(user_message):
                return _json_response({"handled": False})

            product, products, codes = self._find_cart_product(user_message, page_title=page_title, page_url=page_url)
            if not product:
                if products and len(products) > 1:
                    options = [self._short_product_label(item) for item in products[:5]]
                    return _json_response({
                        "handled": True,
                        "success": False,
                        "reply": "He encontrado varios productos posibles. Indícame la referencia exacta:\n" + "\n".join(f"- {option}" for option in options),
                    })
                return _json_response({
                    "handled": True,
                    "success": False,
                    "reply": "Claro. Indícame la referencia del producto y la cantidad que quieres añadir al carrito.",
                })

            quantity = self._parse_requested_quantity(user_message, product_codes=codes)
            if quantity is None:
                availability = self._get_cart_availability(product)
                return _json_response({
                    "handled": True,
                    "success": True,
                    "needsQuantity": True,
                    "pendingCart": self._set_session_pending_cart(product),
                    "actionButton": self._product_open_button_for_current_user(product),
                    "reply": (
                        f"Producto localizado: {self._short_product_label(product)}.\n"
                        f"Disponibilidad actual: {self._format_quantity(availability['available_qty'])} {availability['uom']}.\n"
                        f"Stock nacional 48h: {self._format_quantity(availability['stock_nacional'])} {availability['uom']}.\n"
                        f"Stock internacional 7d: {self._format_quantity(availability['stock_internacional'])} {availability['uom']}.\n"
                        "¿Qué cantidad quieres añadir al carrito?"
                    ),
                })

            return _json_response(self._add_product_to_cart_response(product, quantity))

        except Exception as error:
            _logger.exception("Error en /ai/cart/intent")
            return _json_response({
                "handled": True,
                "success": False,
                "reply": "Ha ocurrido un error al preparar el carrito.",
                "error": str(error),
            }, status=500)

    # Ruta que añade el producto al carrito con la cantidad elegida.
    @http.route("/ai/cart/add", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_cart_add(self, **kwargs):
        """Añade al carrito un producto pendiente después de que el usuario indique cantidad."""
        try:
            raw_body = request.httprequest.data or b"{}"
            data = json.loads(raw_body.decode("utf-8"))

            product = self._get_product_from_cart_payload(data)
            if not product:
                return _json_response({
                    "success": False,
                    "reply": "No he podido identificar el producto pendiente. Indícame de nuevo la referencia y la cantidad.",
                    "clearPendingCart": True,
                }, status=400)

            quantity = self._parse_quantity_value(data.get("quantity") or data.get("message") or "")
            if quantity is None:
                self._clear_session_pending_cart()
                return _json_response({
                    "success": False,
                    "reply": (
                        "Respuesta no válida para la cantidad. "
                        "He cancelado la operación de carrito pendiente. "
                        "Vuelve a pedirme lo que necesitas con una nueva instrucción."
                    ),
                    "clearPendingCart": True,
                }, status=400)

            return _json_response(self._add_product_to_cart_response(product, quantity))

        except Exception as error:
            _logger.exception("Error en /ai/cart/add")
            return _json_response({
                "success": False,
                "reply": "Ha ocurrido un error al añadir el producto al carrito.",
                "error": str(error),
            }, status=500)

    # Detecta cantidades puras para continuar un carrito pendiente.
    def _is_cart_quantity_answer(self, text):
        return bool(
            re.match(r"^\s*\d+(?:[\.,]\d+)?\s*(?:uds?\.?|unidades?|metros?|m)?\s*$", text or "", flags=re.IGNORECASE)
            or re.match(r"^\s*(?:cantidad|cant\.?)\s*[:=]?\s*\d+(?:[\.,]\d+)?\s*$", text or "", flags=re.IGNORECASE)
        )

    # Detecta solicitudes de borrado/archivo de producto para bloquearlas antes del carrito.
    def _is_product_delete_or_archive_intent(self, message):
        normalized = self._normalize_customer_portal_text(message or "")
        if not normalized:
            return False
        destructive = ("borrar", "borra", "eliminar", "elimina", "suprimir", "suprime", "archivar", "archiva", "desactivar", "desactiva")
        if not any(term in normalized for term in destructive):
            return False
        product_terms = ("producto", "productos", "articulo", "articulos", "referencia", "ref", "sku", "codigo", "código")
        has_product_term = any(term in normalized for term in product_terms)
        has_product_code = bool(self._extract_product_codes(message or "", limit=1))
        return bool(has_product_term or has_product_code)

    # Respuesta única para bloqueo de borrado/archivo de productos desde la IA.
    def _blocked_product_delete_payload(self, source="odoo_admin_manager", handled_locally=True):
        return {
            "reply": "No puedo borrar ni archivar productos desde la IA. Para eliminar o desactivar un producto, contacta con la empresa.",
            "handledLocally": handled_locally,
            "source": source,
            "success": True,
            "productDeleteBlocked": True,
            "clearPendingCart": True,
            "clearPendingAdminProductCreate": True,
        }

    # Detecta mensajes de compra o añadir al carrito.
    def _is_cart_intent(self, message):
        """Detecta si el visitante está pidiendo comprar/añadir un producto.

        Se ejecuta antes de n8n para que el carrito se gestione directamente con
        la sesión de website_sale de Odoo. Así la IA puede pedir cantidad y el
        backend valida disponibilidad antes de tocar el carrito.
        """
        text = (message or "").lower()

        # No confundimos la creación administrativa de pedidos de venta/compra
        # con una intención de añadir productos al carrito. Palabras como
        # "pedido" y "compra" también se usan en carrito, pero en frases como
        # "crear pedido de venta" deben llegar al gestor admin de pedidos.
        order_management_phrases = (
            "pedido de venta", "pedidos de venta", "pedido de ventas", "pedidos de ventas",
            "orden de venta", "ordenes de venta", "órdenes de venta",
            "pedido de compra", "pedidos de compra", "orden de compra",
            "ordenes de compra", "órdenes de compra", "solicitud de presupuesto",
            "crear pedido", "crea pedido", "generar pedido", "genera pedido",
            "crear presupuesto", "crea presupuesto", "generar presupuesto", "genera presupuesto",
        )
        if any(phrase in text for phrase in order_management_phrases):
            return False

        add_words = (
            "añade", "añademe", "añádeme", "anade", "anademe", "agrega", "agrégame",
            "mete", "méteme", "meteme", "pon", "poner", "añadir", "anadir", "agregar",
            "comprar", "compra", "quiero comprar", "necesito comprar", "pedir", "pedido",
            "lo quiero", "me llevo",
        )
        cart_words = ("carrito", "cesta", "bolsa", "checkout", "pedido", "comprar", "compra")
        product_words = ("producto", "referencia", "ref", "código", "codigo", "sku", "artículo", "articulo")

        has_add = any(word in text for word in add_words)
        has_cart = any(word in text for word in cart_words)
        has_product = any(word in text for word in product_words)
        has_reference_like_code = bool(self._extract_product_codes(message or "", limit=3))
        has_add_with_quantity = bool(re.search(r"\b(?:añade|añademe|añádeme|anade|anademe|agrega|agrégame|mete|méteme|meteme|pon|quiero|comprar|compra)\s+\d+(?:[\.,]\d+)?\b", text, flags=re.IGNORECASE))

        # No confundimos peticiones informativas con acciones de carrito.
        info_only = any(phrase in text for phrase in (
            "información del producto", "informacion del producto", "dame información", "dame informacion",
            "toda la información", "toda la informacion", "stock del producto", "disponibilidad del producto",
            "dime el stock", "consulta", "consultar", "ver disponibilidad",
        ))
        if info_only and not has_cart and "comprar" not in text and "compra" not in text:
            return False

        explicit_cart_phrase = "añadir al carrito" in text or "anadir al carrito" in text or "agregar al carrito" in text

        # Casos soportados:
        # - "Añade al carrito el producto 10903"
        # - "Añade el producto 10903" / "Méteme 2 uds de 10903"
        # - "Comprar referencia 10903"
        # - "Añádelo al carrito" en una página de producto, usando el título/URL para localizarlo.
        return (
            explicit_cart_phrase
            or (has_add and has_cart)
            or (has_cart and has_product)
            or (has_add and has_product)
            or (has_add and has_reference_like_code)
            or has_add_with_quantity
        )

    # Busca el producto adecuado para una acción de carrito.
    def _find_cart_product(self, message, page_title=None, page_url=None):
        Product = request.env["product.product"].sudo()
        combined_text = " ".join(value for value in (message, page_title, page_url) if value)
        codes = self._extract_product_codes(combined_text, limit=12)
        products, _not_found = self._search_products_by_codes(Product, codes, limit=10)

        if len(products) == 1:
            return products[0], products, codes
        if len(products) > 1:
            return False, products, codes

        name_products = self._search_products_by_name_for_cart(Product, message, limit=5)
        if len(name_products) == 1:
            return name_products[0], name_products, codes
        if len(name_products) > 1:
            return False, name_products, codes

        category_products = self._search_products_by_category_for_customer(Product, message, limit=8)
        if len(category_products) == 1:
            return category_products[0], category_products, codes
        if len(category_products) > 1:
            return False, category_products, codes

        return False, Product.browse(), codes

    # Busca productos vendibles por nombre para carrito.
    def _search_products_by_name_for_cart(self, Product, message, limit=5):
        text = (message or "").lower()
        text = re.sub(r"[^a-záéíóúüñ0-9\s\-/]", " ", text, flags=re.IGNORECASE)
        stopwords = {
            "añade", "anade", "añadir", "anadir", "agrega", "agregar", "mete", "pon", "poner",
            "carrito", "cesta", "bolsa", "compra", "comprar", "quiero", "necesito", "producto",
            "productos", "referencia", "ref", "codigo", "código", "sku", "cantidad", "unidades",
            "unidad", "uds", "metros", "metro", "del", "de", "la", "el", "los", "las", "al", "un", "una",
            "por", "favor", "me", "puedes", "puede",
        }
        tokens = []
        for token in text.split():
            token = token.strip()
            if len(token) < 3 or token in stopwords or token.isdigit():
                continue
            tokens.append(token)

        if not tokens:
            return Product.browse()

        domain = []
        for token in tokens[:5]:
            domain.append(("name", "ilike", token))

        try:
            return Product.search(domain, limit=limit)
        except Exception:
            return Product.browse()

    # Extrae posibles nombres de categoría en consultas comerciales del cliente.
    def _extract_customer_category_terms(self, message):
        text = (message or "").strip()
        if not text:
            return []
        normalized = self._normalize_customer_portal_text(text)
        if "categoria" not in normalized and "categoría" not in text.lower():
            return []

        terms = []
        patterns = (
            r"(?:categoria|categoría|categorias|categorías)\s*(?:de\s+(?:productos?|ventas|web|ecommerce))?\s*(?:=|:|es|llamada|llamado|denominada|denominado|de)?\s*([^,.;\n?]{2,80})",
            r"(?:productos?|art[ií]culos?)\s+(?:de|en|por)\s+(?:la\s+)?(?:categoria|categoría)\s+([^,.;\n?]{2,80})",
        )
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                term = match.group(1).strip().strip("'\".,;:")
                term = re.sub(
                    r"\b(?:por\s+favor|quiero|necesito|buscar|busca|buscame|búscame|mostrar|muestra|dime|ver|consultar|consulta|añade|anade|agrega|mete|pon|carrito|cesta|producto|productos|articulo|artículos?)\b",
                    " ",
                    term,
                    flags=re.IGNORECASE,
                )
                term = re.sub(r"\s+", " ", term).strip().strip("'\".,;:")
                if len(term) >= 2:
                    terms.append(term)

        seen = set()
        clean_terms = []
        for term in terms:
            key = self._normalize_customer_portal_text(term)
            if key and key not in seen:
                seen.add(key)
                clean_terms.append(term)
        return clean_terms[:3]

    # Busca productos por categoría interna o categoría de ventas/eCommerce.
    def _search_products_by_category_for_customer(self, Product, message, limit=8):
        terms = self._extract_customer_category_terms(message)
        if not terms:
            return Product.browse()

        try:
            Category = request.env["product.category"].sudo()
            PublicCategory = request.env["product.public.category"].sudo()
        except Exception:
            return Product.browse()

        internal_categories = Category.browse()
        public_categories = PublicCategory.browse()
        for term in terms:
            term = (term or "").strip()
            if not term:
                continue
            try:
                exact_internal = Category.search(["|", ("complete_name", "=ilike", term), ("name", "=ilike", term)], limit=5)
            except Exception:
                exact_internal = Category.search([("name", "=ilike", term)], limit=5)
            if exact_internal:
                internal_categories |= exact_internal
            else:
                try:
                    internal_categories |= Category.search(["|", ("complete_name", "ilike", term), ("name", "ilike", term)], limit=5)
                except Exception:
                    internal_categories |= Category.search([("name", "ilike", term)], limit=5)

            try:
                if "complete_name" in PublicCategory._fields:
                    exact_public = PublicCategory.search(["|", ("complete_name", "=ilike", term), ("name", "=ilike", term)], limit=5)
                else:
                    exact_public = PublicCategory.search([("name", "=ilike", term)], limit=5)
            except Exception:
                exact_public = PublicCategory.search([("name", "=ilike", term)], limit=5)
            if exact_public:
                public_categories |= exact_public
            else:
                try:
                    if "complete_name" in PublicCategory._fields:
                        public_categories |= PublicCategory.search(["|", ("complete_name", "ilike", term), ("name", "ilike", term)], limit=5)
                    else:
                        public_categories |= PublicCategory.search([("name", "ilike", term)], limit=5)
                except Exception:
                    pass

        domains = []
        if internal_categories:
            domains.append([("categ_id", "child_of", internal_categories.ids)])
        if public_categories:
            domains.append([("product_tmpl_id.public_categ_ids", "in", public_categories.ids)])
        if not domains:
            return Product.browse()

        try:
            domain = expression.OR(domains) if len(domains) > 1 else domains[0]
            if "active" in Product._fields:
                domain = expression.AND([[('active', '=', True)], domain])
            return Product.search(domain, limit=limit, order="default_code asc, name asc")
        except Exception:
            _logger.exception("No se pudieron buscar productos por categoría desde el chat")
            return Product.browse()

    # Extrae la cantidad solicitada para carrito.
    def _parse_requested_quantity(self, message, product_codes=None):
        text = message or ""
        cleaned = text
        for code in product_codes or []:
            if code:
                cleaned = re.sub(r"(?<!\w)%s(?!\w)" % re.escape(str(code)), " ", cleaned, flags=re.IGNORECASE)

        patterns = [
            r"(?:cantidad|cant\.?|qty)\s*[:=]?\s*(\d+(?:[\.,]\d+)?)",
            r"(\d+(?:[\.,]\d+)?)\s*(?:uds?\.?|unidades?|metros?|m)\b",
            r"(?:añade|anade|agrega|mete|pon|comprar|compra|quiero|necesito|pedir)\s+(\d+(?:[\.,]\d+)?)\b",
            r"\bx\s*(\d+(?:[\.,]\d+)?)\b",
        ]
        for pattern in patterns:
            match = re.search(pattern, cleaned, flags=re.IGNORECASE)
            if match:
                return self._parse_quantity_value(match.group(1))

        numbers = re.findall(r"(?<!\w)(\d+(?:[\.,]\d+)?)(?!\w)", cleaned)
        if len(numbers) == 1:
            return self._parse_quantity_value(numbers[0])

        return None

    # Normaliza cantidades numéricas del carrito.
    def _parse_quantity_value(self, raw_value):
        if raw_value is None:
            return None
        text = str(raw_value).strip().replace(",", ".")
        match = re.search(r"\d+(?:\.\d+)?", text)
        if not match:
            return None
        try:
            quantity = float(match.group(0))
        except Exception:
            return None
        if quantity <= 0:
            return None
        return quantity

    # Recupera el producto desde el payload del carrito.
    def _get_product_from_cart_payload(self, data):
        Product = request.env["product.product"].sudo()
        product_id = data.get("productId") or data.get("product_id")
        if product_id:
            try:
                product = Product.browse(int(product_id)).exists()
                if product:
                    return product[0]
            except Exception:
                pass

        code = data.get("productCode") or data.get("default_code") or data.get("sku")
        if code:
            products, _not_found = self._search_products_by_codes(Product, [str(code)], limit=2)
            if len(products) == 1:
                return products[0]
        return False

    # Construye el estado pendiente del carrito para el frontend.
    def _pending_cart_payload(self, product):
        return {
            "productId": product.id,
            "productCode": product.default_code or "",
            "name": product.display_name or product.name or "",
        }

    # Genera una etiqueta corta de producto.
    def _short_product_label(self, product):
        code = product.default_code or "sin referencia"
        return f"{product.display_name or product.name} (Ref: {code})"

    # Calcula disponibilidad de stock para venta en carrito.
    def _get_cart_availability(self, product):
        fields_map = product._fields
        uom = product.uom_id.name if getattr(product, "uom_id", False) else "uds"
        qty_available = float(getattr(product, "qty_available", 0.0) or 0.0)
        free_qty = float(getattr(product, "free_qty", qty_available) or 0.0) if "free_qty" in fields_map else qty_available
        stock_nacional, stock_internacional = self._get_product_stock_breakdown(product)
        return {
            "uom": uom,
            "stock_real": qty_available,
            "available_qty": free_qty,
            "stock_nacional": float(stock_nacional or 0.0),
            "stock_internacional": float(stock_internacional or 0.0),
        }

    # Comprueba si un producto puede venderse.
    def _is_product_sellable(self, product):
        template = product.product_tmpl_id if getattr(product, "product_tmpl_id", False) else False
        if template:
            return bool(template.sale_ok)
        return bool(getattr(product, "sale_ok", False))

    # Lee la cantidad actual de un producto en el pedido.
    def _get_cart_line_quantity(self, order, product):
        try:
            lines = order.order_line.filtered(lambda line: line.product_id.id == product.id)
            return float(sum(lines.mapped("product_uom_qty")) or 0.0)
        except Exception:
            return 0.0

    # Calcula el total de unidades del carrito.
    def _get_cart_total_quantity(self, order):
        try:
            return float(sum(order.order_line.mapped("product_uom_qty")) or 0.0)
        except Exception:
            return 0.0

    # Añade el producto al carrito y devuelve la respuesta final.
    def _add_product_to_cart_response(self, product, quantity):
        quantity = float(quantity or 0.0)
        availability = self._get_cart_availability(product)
        label = self._short_product_label(product)

        if quantity <= 0:
            return {
                "success": False,
                "reply": "Indícame una cantidad válida mayor que cero.",
                "pendingCart": self._set_session_pending_cart(product),
                "actionButton": self._product_open_button_for_current_user(product),
            }

        if not self._is_product_sellable(product):
            self._clear_session_pending_cart()
            return {
                "success": False,
                "reply": f"{label} no está marcado como vendible, así que no puedo añadirlo al carrito.",
                "clearPendingCart": True,
            }

        if availability["available_qty"] < quantity:
            return {
                "success": False,
                "reply": (
                    f"No hay disponibilidad suficiente para {label}.\n"
                    f"Cantidad solicitada: {self._format_quantity(quantity)} {availability['uom']}.\n"
                    f"Disponible ahora: {self._format_quantity(availability['available_qty'])} {availability['uom']}.\n"
                    f"Stock real: {self._format_quantity(availability['stock_real'])} {availability['uom']}.\n"
                    f"Stock nacional 48h: {self._format_quantity(availability['stock_nacional'])} {availability['uom']}.\n"
                    f"Stock internacional 7d: {self._format_quantity(availability['stock_internacional'])} {availability['uom']}.") ,
                "pendingCart": self._set_session_pending_cart(product),
                "actionButton": self._product_open_button_for_current_user(product),
            }

        try:
            website = request.website
            order = website.sale_get_order(force_create=True)
            if not order:
                raise Exception("No se pudo crear o recuperar el pedido web de la sesión.")

            # Garantizamos que el pedido queda asociado a la sesión HTTP del visitante.
            request.session["sale_order_id"] = order.id

            product_id = int(product.id)
            before_qty = self._get_cart_line_quantity(order.sudo(), product)
            update_result = {}
            update_warning = ""

            try:
                update_result = order.sudo()._cart_update(product_id=product_id, add_qty=quantity) or {}
                if isinstance(update_result, dict):
                    update_warning = update_result.get("warning") or update_result.get("error") or ""
            except Exception as cart_error:
                _logger.exception("_cart_update falló; se intentará fallback controlado")
                update_warning = str(cart_error)

            # Releemos el pedido para no depender de cachés del recordset anterior.
            order = request.env["sale.order"].sudo().browse(order.id).exists()
            after_qty = self._get_cart_line_quantity(order, product) if order else 0.0

            # Fallback: si _cart_update no ha creado/incrementado ninguna línea, creamos línea manualmente.
            # Esto evita decir al cliente que se añadió algo si Odoo no modificó realmente el carrito.
            if after_qty <= before_qty:
                line_values = {
                    "order_id": order.id,
                    "product_id": product_id,
                    "product_uom_qty": quantity,
                }
                try:
                    if getattr(product, "uom_id", False):
                        line_values["product_uom"] = product.uom_id.id
                    if hasattr(product, "get_product_multiline_description_sale"):
                        line_values["name"] = product.get_product_multiline_description_sale()
                    else:
                        line_values["name"] = product.display_name or product.name
                    if "price_unit" in request.env["sale.order.line"]._fields:
                        line_values["price_unit"] = float(getattr(product, "lst_price", 0.0) or 0.0)
                    request.env["sale.order.line"].sudo().create(line_values)
                    order = request.env["sale.order"].sudo().browse(order.id).exists()
                    after_qty = self._get_cart_line_quantity(order, product) if order else 0.0
                except Exception as fallback_error:
                    _logger.exception("Fallback manual de carrito falló")
                    detail = update_warning or fallback_error
                    return {
                        "success": False,
                        "reply": f"No he podido añadir {label} al carrito. Detalle técnico: {detail}",
                        "pendingCart": self._set_session_pending_cart(product),
                    }

            effective_added = max(0.0, after_qty - before_qty)
            if effective_added <= 0:
                detail = update_warning or "Odoo no creó ninguna línea de carrito."
                return {
                    "success": False,
                    "reply": f"No he podido añadir {label} al carrito. Detalle técnico: {detail}",
                    "pendingCart": self._set_session_pending_cart(product),
                }

            cart_quantity = self._get_cart_total_quantity(order)
            request.session["sale_order_id"] = order.id
            request.session["website_sale_cart_quantity"] = cart_quantity
            self._clear_session_pending_cart()

            cart_url = "/shop/cart"
            return {
                "success": True,
                "added": True,
                "clearPendingCart": True,
                "orderId": order.id,
                "productId": product_id,
                "lineQuantity": after_qty,
                "cartQuantity": cart_quantity,
                "cartUrl": cart_url,
                "reply": (
                    f"He añadido {self._format_quantity(effective_added)} {availability['uom']} de {label} al carrito.\n"
                    f"Cantidad de este producto en el carrito: {self._format_quantity(after_qty)} {availability['uom']}.\n"
                    f"Disponibilidad restante aproximada: {self._format_quantity(availability['available_qty'] - effective_added)} {availability['uom']}.\n"
                    f"Puedes revisar el carrito aquí: {cart_url}"
                ),
            }
        except Exception as error:
            _logger.exception("No se pudo añadir producto al carrito")
            return {
                "success": False,
                "reply": f"No he podido añadir {label} al carrito. Detalle técnico: {error}",
                "pendingCart": self._set_session_pending_cart(product),
                "actionButton": self._product_open_button_for_current_user(product),
            }

    # Construye el prompt final enviado a n8n con contexto mínimo necesario.
    def _build_prompt(self, user_message, page_url, page_title, product_context):
        current_user_context = self._format_current_user_context_for_prompt()
        include_inventory = self._should_include_product_context_for_ai(user_message)
        admin_note = (
            "Permisos admin IA: sí. La cuenta actual es admin y el addon local puede ejecutar acciones administrativas permitidas. El borrado o archivado de productos está bloqueado para todos; si lo piden, responde que contacte con la empresa. No digas que has creado/modificado/borrado algo si Odoo no lo confirma."
            if self._is_admin_ai_operator()
            else "Permisos admin IA: no. Prohibido crear, modificar o borrar productos, clientes, cuentas o usuarios. El usuario solo puede consultar productos/stock/disponibilidad y añadir productos al carrito."
        )

        inventory_block = ""
        if include_inventory:
            inventory_block = "\n\nInventario Odoo relevante:\n%s" % (product_context or "No disponible")

        return f"""
Pregunta del visitante: {user_message}
Página: {page_title or "No disponible"} - {page_url or "No disponible"}
Usuario Odoo: {current_user_context}
{inventory_block}

Instrucciones:
- Responde siempre en español, breve y en texto plano.
- {admin_note}
- No inventes productos, precios, stock, teléfonos, direcciones ni condiciones comerciales.
- El borrado o archivado de productos está prohibido desde la IA para todos los usuarios; responde que contacte con la empresa.
- Si Permisos admin IA es no, rechaza cualquier solicitud de creación, modificación o borrado de productos, clientes, cuentas o usuarios.
- Si hay inventario en este mensaje y preguntas por productos, úsalo exclusivamente.
- No muestres nombres técnicos de campos como qty_available, x_transit_stock_custom o x_almacen1_custom.
- Si faltan datos, dilo claramente o pide el dato mínimo necesario.
- Devuelve texto plano o JSON con una clave reply/output/text/answer/message.
""".strip()
