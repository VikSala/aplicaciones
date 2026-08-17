import json
import logging
import os
import threading
import time
import uuid
from urllib.parse import urlparse

import requests
from werkzeug.wrappers import Response

from odoo import http
from odoo.http import request


_logger = logging.getLogger(__name__)

_AI_CHAT_JOBS = {}
_AI_CHAT_JOBS_LOCK = threading.Lock()
_AI_CHAT_JOB_TTL_SECONDS = 30 * 60

REPLY_KEYS = (
    "reply",
    "output",
    "response",
    "answer",
    "text",
    "message",
    "content",
    "generated_text",
    "completion",
    "result",
)

NESTED_KEYS = (
    "body",
    "data",
    "json",
    "result",
    "results",
    "item",
    "items",
    "candidate",
    "candidates",
    "choice",
    "choices",
    "message",
    "content",
    "parts",
    "generations",
)


def _json_response(payload, status=200):
    return Response(
        json.dumps(payload, ensure_ascii=False),
        status=status,
        content_type="application/json; charset=utf-8",
    )


def _cleanup_old_jobs_unlocked():
    now = time.time()
    for job_id, job in list(_AI_CHAT_JOBS.items()):
        if now - (job.get("created_at") or now) > _AI_CHAT_JOB_TTL_SECONDS:
            _AI_CHAT_JOBS.pop(job_id, None)


def _set_job(job_id, **values):
    with _AI_CHAT_JOBS_LOCK:
        job = _AI_CHAT_JOBS.setdefault(job_id, {})
        job.update(values)
        job["updated_at"] = time.time()


def _extract_reply_value(payload):
    """Extrae texto de respuestas habituales de n8n y proveedores de IA."""
    if payload is None:
        return None
    if isinstance(payload, str):
        return payload
    if isinstance(payload, list):
        for item in payload:
            value = _extract_reply_value(item)
            if value:
                return value
        return None
    if isinstance(payload, dict):
        for key in REPLY_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value
            if isinstance(value, (dict, list)):
                nested = _extract_reply_value(value)
                if nested:
                    return nested
        for key in NESTED_KEYS:
            if key in payload:
                nested = _extract_reply_value(payload.get(key))
                if nested:
                    return nested
    return None


def _parse_webhook_response(response):
    raw_text = (response.text or "").strip()
    try:
        payload = response.json() if raw_text else {}
    except ValueError:
        payload = raw_text

    reply = _extract_reply_value(payload)
    if reply is None and isinstance(payload, str):
        reply = payload

    return str(reply or "").strip(), payload


def _call_webhook_in_background(job_id, webhook_url, payload):
    """Ejecuta el webhook fuera de la petición del navegador."""
    _set_job(job_id, status="running")
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Accept": "application/json"},
            timeout=(10, 900),
        )
        response.raise_for_status()
        reply, response_payload = _parse_webhook_response(response)
        _set_job(
            job_id,
            status="done",
            reply=reply or "El flujo respondió sin contenido visible.",
            response_payload=response_payload,
            error=False,
        )
    except Exception:
        _logger.exception("Error conectando AI Chat Base con el webhook")
        _set_job(
            job_id,
            status="error",
            reply="No se ha podido contactar con el asistente en este momento.",
            error="webhook_error",
        )


class OdooAIChatBaseController(http.Controller):
    """Infraestructura mínima reutilizable del chatbot.

    Un módulo vertical puede heredar esta clase y sobreescribir los hooks
    `_try_handle_local_message`, `_build_variant_context`, `_build_ai_message`,
    `_build_n8n_payload` o `_response_payload_from_job`.
    """

    # ------------------------------------------------------------------
    # Configuración y habilitación por página
    # ------------------------------------------------------------------

    def _config(self):
        return request.env["ir.config_parameter"].sudo()

    def _get_webhook_url(self):
        return (
            os.environ.get("ODOO_AI_CHAT_WEBHOOK_URL")
            or self._config().get_param("odoo_ai_chat_base.webhook_url")
            or ""
        ).strip()

    def _get_selected_page_ids(self):
        raw = self._config().get_param("odoo_ai_chat_base.page_ids", default="") or ""
        page_ids = []
        for value in raw.split(","):
            value = value.strip()
            if value.isdigit():
                page_ids.append(int(value))
        return page_ids

    def _normalize_path(self, value):
        if not value:
            return "/"
        value = str(value).strip()
        if value.startswith(("http://", "https://")):
            value = urlparse(value).path or "/"
        else:
            value = value.split("?", 1)[0].split("#", 1)[0] or "/"
        if not value.startswith("/"):
            value = "/" + value
        if len(value) > 1:
            value = value.rstrip("/")
        return value or "/"

    def _current_website_id(self):
        try:
            return request.website.id if request.website else False
        except Exception:
            return False

    def _is_enabled_for_page(self, page_url=None):
        page_ids = self._get_selected_page_ids()
        if not page_ids:
            return False

        pages = request.env["website.page"].sudo().browse(page_ids).exists()
        current_path = self._normalize_path(page_url or request.httprequest.path)
        current_website_id = self._current_website_id()

        for page in pages:
            if self._normalize_path(page.url) != current_path:
                continue
            page_website_id = page.website_id.id if page.website_id else False
            if page_website_id and current_website_id and page_website_id != current_website_id:
                continue
            return True
        return False

    def _public_config(self, page_url=None):
        config = self._config()
        return {
            "enabled": self._is_enabled_for_page(page_url=page_url),
            "title": config.get_param("odoo_ai_chat_base.title") or "Asistente",
            "welcomeMessage": config.get_param("odoo_ai_chat_base.welcome_message") or "Hola, ¿en qué puedo ayudarte?",
        }

    # ------------------------------------------------------------------
    # Hooks de extensión para módulos verticales
    # ------------------------------------------------------------------

    def _try_handle_local_message(self, data):
        """Devuelve payload/string si el vertical resuelve el mensaje sin IA."""
        return None

    def _build_variant_context(self, data):
        """Contexto estructurado adicional enviado al webhook."""
        return {}

    def _build_ai_message(self, data):
        """Mensaje enviado como `message`; por defecto es el texto original."""
        return (data.get("message") or "").strip()

    def _build_n8n_payload(self, data):
        user_message = (data.get("message") or "").strip()
        return {
            "message": self._build_ai_message(data),
            "userMessage": user_message,
            "sessionId": data.get("sessionId") or "odoo-public",
            "pageUrl": data.get("pageUrl") or "",
            "pageTitle": data.get("pageTitle") or "",
            "odooContext": self._build_variant_context(data),
            "source": "odoo_ai_chat_base",
            "expectedResponseField": "reply",
        }

    def _response_payload_from_job(self, job):
        """Permite a un vertical enriquecer la respuesta final del job."""
        return {
            "status": job.get("status") or "pending",
            "reply": job.get("reply") or "",
            "error": job.get("error") or False,
        }

    # ------------------------------------------------------------------
    # Rutas públicas del widget
    # ------------------------------------------------------------------

    @http.route("/ai/chat/base/config", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_chat_base_config(self, **kwargs):
        try:
            data = self._read_json_body()
            return _json_response(self._public_config(page_url=data.get("pageUrl") or ""))
        except Exception:
            _logger.exception("Error leyendo la configuración pública del chatbot")
            return _json_response({"enabled": False}, status=500)

    @http.route("/ai/chat/base/start", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_chat_base_start(self, **kwargs):
        try:
            data = self._read_json_body()
            user_message = (data.get("message") or "").strip()
            page_url = data.get("pageUrl") or ""

            if not self._is_enabled_for_page(page_url=page_url):
                return _json_response(
                    {"reply": "El chat no está habilitado en esta página.", "error": "disabled_on_page"},
                    status=403,
                )
            if not user_message:
                return _json_response({"reply": "No he recibido ningún mensaje."}, status=400)

            local_response = self._try_handle_local_message(data)
            if local_response:
                if isinstance(local_response, str):
                    local_response = {"reply": local_response}
                return _json_response(local_response)

            webhook_url = self._get_webhook_url()
            if not webhook_url:
                return _json_response(
                    {"reply": "El chatbot todavía no tiene configurado su webhook.", "error": "missing_webhook_url"},
                    status=503,
                )
            if not webhook_url.startswith(("http://", "https://")):
                _logger.error("URL de webhook inválida para AI Chat Base: %s", webhook_url)
                return _json_response(
                    {"reply": "La configuración del chatbot no es válida.", "error": "invalid_webhook_url"},
                    status=503,
                )

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
                target=_call_webhook_in_background,
                args=(job_id, webhook_url, self._build_n8n_payload(data)),
                daemon=True,
            )
            thread.start()
            return _json_response({"jobId": job_id, "status": "pending"})

        except Exception:
            _logger.exception("Error iniciando AI Chat Base")
            return _json_response(
                {"reply": "Ha ocurrido un error al procesar el mensaje.", "error": "internal_error"},
                status=500,
            )

    @http.route("/ai/chat/base/result", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_chat_base_result(self, **kwargs):
        try:
            data = self._read_json_body()
            job_id = (data.get("jobId") or "").strip()
            if not job_id:
                return _json_response({"status": "error", "reply": "Falta jobId.", "error": "missing_job_id"}, status=400)

            with _AI_CHAT_JOBS_LOCK:
                _cleanup_old_jobs_unlocked()
                job = dict(_AI_CHAT_JOBS.get(job_id) or {})

            if not job:
                return _json_response(
                    {
                        "status": "error",
                        "reply": "La consulta ha caducado o no existe. Vuelve a enviar el mensaje.",
                        "error": "job_not_found",
                    },
                    status=404,
                )

            return _json_response(self._response_payload_from_job(job))

        except Exception:
            _logger.exception("Error leyendo resultado de AI Chat Base")
            return _json_response(
                {"status": "error", "reply": "Ha ocurrido un error al leer la respuesta.", "error": "internal_error"},
                status=500,
            )

    def _read_json_body(self):
        raw_body = request.httprequest.data or b"{}"
        if not raw_body:
            return {}
        data = json.loads(raw_body.decode("utf-8"))
        return data if isinstance(data, dict) else {}
