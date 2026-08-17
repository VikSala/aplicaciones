import json
import logging
import os
import re
import threading
import time
import uuid
from urllib.parse import urlparse

import requests
from werkzeug.wrappers import Response

from odoo import api, fields, http, SUPERUSER_ID
from odoo.modules.registry import Registry
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

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
SHORT_HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{3}$")


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


def _update_persistent_ai_job(db_name, job_token, values):
    """Actualiza un job desde el hilo usando un cursor propio de Odoo."""
    try:
        with Registry(db_name).cursor() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            job = env["odoo.ai.appointment.ai.job"].sudo().search(
                [("token", "=", job_token)],
                limit=1,
            )
            if job:
                job.write(values)
                cr.commit()
    except Exception:
        _logger.exception("No se ha podido actualizar el job persistente de fallback IA %s", job_token)


def _call_webhook_in_background(db_name, job_token, webhook_url, payload, python_fallback_reply=""):
    """Ejecuta n8n fuera de la petición y persiste el resultado en PostgreSQL.

    A diferencia de las fases anteriores, el estado del job no vive en memoria
    del worker HTTP. El polling puede caer en otro worker/proceso y seguirá
    encontrando la respuesta.
    """
    _update_persistent_ai_job(db_name, job_token, {"status": "running"})
    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Accept": "application/json"},
            timeout=(10, 120),
        )
        response.raise_for_status()
        reply, _response_payload = _parse_webhook_response(response)
        if not reply:
            _update_persistent_ai_job(db_name, job_token, {
                "status": "done",
                "reply": python_fallback_reply or "No he podido interpretar el mensaje. ¿Puedes reformularlo?",
                "ai_fallback_used": False,
                "ai_error": "empty_ai_reply",
            })
            return
        _update_persistent_ai_job(db_name, job_token, {
            "status": "done",
            "reply": reply,
            "ai_fallback_used": True,
            "ai_error": False,
        })
    except Exception:
        _logger.exception("Error conectando AI Chat Citas con el webhook de fallback")
        _update_persistent_ai_job(db_name, job_token, {
            "status": "done",
            "reply": python_fallback_reply or "No he podido interpretar el mensaje. ¿Puedes reformularlo?",
            "ai_fallback_used": False,
            "ai_error": "webhook_error",
        })


class OdooAIChatAppointmentsController(http.Controller):
    """Controlador web del chatbot de citas Python-first.

    Python procesa siempre primero. n8n solo se invoca cuando la máquina de
    estados devuelve ``fallback=True`` y existe una URL HTTP(S) configurada.
    La respuesta de n8n es exclusivamente texto conversacional.
    """

    # ------------------------------------------------------------------
    # Configuración y habilitación por página
    # ------------------------------------------------------------------

    def _config(self):
        return request.env["ir.config_parameter"].sudo()

    def _get_webhook_url(self):
        return (
            os.environ.get("ODOO_AI_CHAT_APPOINTMENTS_WEBHOOK_URL")
            or os.environ.get("ODOO_AI_CHAT_WEBHOOK_URL")
            or self._config().get_param("odoo_ai_chat_appointments.webhook_url")
            or ""
        ).strip()

    def _ai_fallback_service(self):
        return request.env["odoo.ai.appointment.ai.fallback"].sudo()

    def _is_ai_fallback_enabled(self):
        return self._ai_fallback_service().is_enabled()

    def _get_selected_page_ids(self):
        raw = self._config().get_param("odoo_ai_chat_appointments.page_ids", default="") or ""
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

    def _safe_hex_color(self, value, default):
        value = (value or "").strip()
        if SHORT_HEX_COLOR_RE.fullmatch(value):
            value = "#" + "".join(char * 2 for char in value[1:])
        if HEX_COLOR_RE.fullmatch(value):
            return value.lower()
        return default

    def _public_config(self, page_url=None, web_session_id=None):
        config = self._config()
        payload = {
            "enabled": self._is_enabled_for_page(page_url=page_url),
            "title": config.get_param("odoo_ai_chat_appointments.title") or "Asistente de citas",
            "welcomeMessage": config.get_param("odoo_ai_chat_appointments.welcome_message") or "Hola, ¿en qué puedo ayudarte?",
            "primaryColor": self._safe_hex_color(
                config.get_param("odoo_ai_chat_appointments.primary_color"),
                "#0e273b",
            ),
            "secondaryColor": self._safe_hex_color(
                config.get_param("odoo_ai_chat_appointments.secondary_color"),
                "#4caf50",
            ),
            "textColor": self._safe_hex_color(
                config.get_param("odoo_ai_chat_appointments.text_color"),
                "#ffffff",
            ),
        }

        # Fase 4: al recargar una página, el widget puede recuperar el punto
        # exacto de la conversación sin crear una sesión solo por abrir el chat.
        session = self._find_active_web_session(web_session_id)
        if session:
            conversation = request.env["odoo.ai.appointment.conversation"].sudo()
            payload.update({
                "resumeMessage": conversation.get_resume_message(session),
                "appointmentState": session.state,
                "appointmentSessionRef": session.name,
            })
        return payload

    # ------------------------------------------------------------------
    # Puntos internos preparados para las siguientes fases
    # ------------------------------------------------------------------

    def _normalize_web_session_id(self, value):
        """Valida el identificador opaco conservado por el navegador.

        El valor funciona como clave de continuidad de una conversación web;
        nunca se interpreta como un ID de base de datos.
        """
        value = str(value or "").strip()
        if not value or len(value) > 160:
            return ""
        if not re.fullmatch(r"[A-Za-z0-9._:-]+", value):
            return ""
        return value

    def _find_active_web_session(self, web_session_id):
        web_session_id = self._normalize_web_session_id(web_session_id)
        if not web_session_id:
            return request.env["odoo.ai.appointment.session"].sudo().browse()
        return request.env["odoo.ai.appointment.session"].sudo().find_active_web_session(web_session_id)

    def _current_partner_for_web_session(self):
        user = request.env.user
        try:
            if user and not user._is_public():
                return user.partner_id
        except Exception:
            pass
        return request.env["res.partner"].browse()

    def _get_or_create_web_session(self, web_session_id):
        web_session_id = self._normalize_web_session_id(web_session_id)
        if not web_session_id:
            return request.env["odoo.ai.appointment.session"].sudo().browse()
        return request.env["odoo.ai.appointment.session"].sudo().get_or_create_web_session(
            web_session_id,
            partner=self._current_partner_for_web_session(),
        )

    def _try_handle_local_message(self, data):
        """Entrada Web -> máquina de estados Python de la Fase 3.1.

        Python conserva siempre la autoridad sobre estado y acciones. Si el
        resultado contiene `fallback=True`, la ruta HTTP podrá delegar solo la
        respuesta conversacional a n8n/IA.
        """
        web_session_id = self._normalize_web_session_id(data.get("sessionId"))
        if not web_session_id:
            return {
                "reply": "No se ha podido identificar la sesión del navegador. Recarga la página y vuelve a intentarlo.",
                "error": "invalid_session_id",
            }

        session = self._get_or_create_web_session(web_session_id)
        if not session:
            return {
                "reply": "No se ha podido iniciar la sesión de reserva.",
                "error": "session_create_error",
            }

        conversation = request.env["odoo.ai.appointment.conversation"].sudo()
        result = conversation.process_message(session, data.get("message") or "")
        result_session_id = result.get("session_id")
        result_session = request.env["odoo.ai.appointment.session"].sudo().browse(result_session_id).exists() if result_session_id else session
        # No exponemos el ID interno de base de datos que utiliza la API
        # interna del parser; el navegador solo conoce su token opaco y una
        # referencia funcional de la sesión.
        result.pop("session_id", None)
        # `slot` es un detalle técnico del motor y contiene datetimes Python
        # (`start` / `end`). El widget no lo necesita: la respuesta visible ya
        # incluye `reply` y el estado queda persistido en la sesión. No exponer
        # este diccionario evita además intentar serializar datetimes crudos a
        # JSON en una ruta HTTP pública.
        result.pop("slot", None)
        result.update({
            "status": "done",
            "local": True,
            "appointmentSessionRef": (result_session or session).name,
        })
        return result

    def _build_variant_context(self, data):
        """Contexto estructurado preparado para el fallback IA de Fase 7."""
        session = self._find_active_web_session(data.get("sessionId"))
        if not session:
            return {}
        return {
            "appointmentSession": {
                "reference": session.name,
                "state": session.state,
                "service": session.service_id.display_name if session.service_id else False,
                "bookingMode": session.booking_mode or False,
                "employee": session.employee_id.display_name if session.employee_id else False,
                "preferenceText": session.preference_text or False,
                "proposedEmployee": session.proposed_employee_id.display_name if session.proposed_employee_id else False,
                "proposedStart": session.proposed_start.isoformat() if session.proposed_start else False,
                "proposedEnd": session.proposed_end.isoformat() if session.proposed_end else False,
            }
        }

    def _build_ai_message(self, data):
        """Hook legado. El payload real de Fase 7.4 construye un prompt controlado."""
        session = self._find_active_web_session(data.get("sessionId"))
        return self._ai_fallback_service()._build_controlled_prompt(
            session=session,
            user_message=data.get("message") or "",
            python_result=data.get("_python_result") or {},
            history=[],
        )

    def _build_n8n_payload(self, data):
        session = self._find_active_web_session(data.get("sessionId"))
        return self._ai_fallback_service().build_payload(
            session=session,
            user_message=data.get("message") or "",
            python_result=data.get("_python_result") or {},
            source="web",
            session_key=data.get("sessionId") or "odoo-public",
            page_url=data.get("pageUrl") or "",
            page_title=data.get("pageTitle") or "",
        )

    def _response_payload_from_job(self, job):
        """Construye la respuesta final del job asíncrono."""
        return {
            "status": job.get("status") or "pending",
            "reply": job.get("reply") or "",
            "error": job.get("error") or False,
            "aiFallbackUsed": bool(job.get("ai_fallback_used")),
            "aiFallbackError": job.get("ai_error") or False,
        }

    # ------------------------------------------------------------------
    # Rutas públicas del widget
    # ------------------------------------------------------------------

    @http.route("/ai/chat/appointments/config", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_chat_appointments_config(self, **kwargs):
        try:
            data = self._read_json_body()
            return _json_response(self._public_config(
                page_url=data.get("pageUrl") or "",
                web_session_id=data.get("sessionId") or "",
            ))
        except Exception:
            _logger.exception("Error leyendo la configuración pública del chatbot")
            return _json_response({"enabled": False}, status=500)

    @http.route("/ai/chat/appointments/start", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_chat_appointments_start(self, **kwargs):
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
            if isinstance(local_response, str):
                local_response = {"reply": local_response, "handled": True, "fallback": False}

            # Todo lo comprendido por Python vuelve directamente al usuario.
            if local_response and not local_response.get("fallback"):
                return _json_response(local_response)

            # Solo un fallback explícito puede llegar a la IA. Si está
            # desactivada, mal configurada o sin URL, conservamos la respuesta
            # determinista de Python en lugar de romper el chatbot.
            python_fallback_reply = (local_response or {}).get("reply") or (
                "No he podido interpretar el mensaje. ¿Puedes reformularlo?"
            )
            ai_service = self._ai_fallback_service()
            if not local_response:
                return _json_response({
                    "reply": python_fallback_reply,
                    "handled": False,
                    "fallback": True,
                    "status": "done",
                    "local": True,
                })

            webhook_url = ai_service.get_webhook_url()
            if not webhook_url:
                _logger.warning("Fallback IA solicitado pero no hay URL de webhook configurada")
                local_response["aiFallbackError"] = "missing_webhook_url"
                return _json_response(local_response)
            if not webhook_url.startswith(("http://", "https://")):
                _logger.warning("Fallback IA solicitado pero la URL no es HTTP(S): %s", webhook_url)
                local_response["aiFallbackError"] = "invalid_webhook_url"
                return _json_response(local_response)

            # El parser ya ha aplicado exclusivamente las transiciones
            # deterministas que correspondan. n8n recibe una instantánea de ese
            # estado, pero su respuesta nunca se interpreta como una acción.
            data["_python_result"] = local_response

            job = request.env["odoo.ai.appointment.ai.job"].sudo().create_job(
                fallback_reply=python_fallback_reply,
            )
            db_name = request.env.cr.dbname
            thread = threading.Thread(
                target=_call_webhook_in_background,
                args=(db_name, job.token, webhook_url, self._build_n8n_payload(data), python_fallback_reply),
                daemon=True,
            )
            thread.start()
            return _json_response({"jobId": job.token, "status": "pending"})

        except Exception:
            _logger.exception("Error iniciando AI Chat Citas")
            return _json_response(
                {"reply": "Ha ocurrido un error al procesar el mensaje.", "error": "internal_error"},
                status=500,
            )

    @http.route("/ai/chat/appointments/result", type="http", auth="public", methods=["POST"], csrf=False, website=True)
    def ai_chat_appointments_result(self, **kwargs):
        try:
            data = self._read_json_body()
            job_id = (data.get("jobId") or "").strip()
            if not job_id:
                return _json_response({"status": "error", "reply": "Falta jobId.", "error": "missing_job_id"}, status=400)

            job = request.env["odoo.ai.appointment.ai.job"].sudo().search(
                [("token", "=", job_id)],
                limit=1,
            )
            if not job:
                return _json_response(
                    {
                        "status": "error",
                        "reply": "La consulta ha caducado o no existe. Vuelve a enviar el mensaje.",
                        "error": "job_not_found",
                    },
                    status=404,
                )

            # Si el proceso que ejecutaba n8n desapareció, no dejamos al
            # navegador bloqueado indefinidamente: tras 150 s recuperamos la
            # aclaración Python guardada en el propio job.
            created = fields.Datetime.to_datetime(job.create_date)
            current = fields.Datetime.to_datetime(fields.Datetime.now())
            if job.status in ("pending", "running") and created and (current - created).total_seconds() > 150:
                job.write({
                    "status": "done",
                    "reply": job.fallback_reply or "No he podido interpretar el mensaje. ¿Puedes reformularlo?",
                    "ai_fallback_used": False,
                    "ai_error": "worker_timeout",
                })

            return _json_response({
                "status": job.status or "pending",
                "reply": job.reply or "",
                "error": False,
                "aiFallbackUsed": bool(job.ai_fallback_used),
                "aiFallbackError": job.ai_error or False,
            })

        except Exception:
            _logger.exception("Error leyendo resultado de AI Chat Citas")
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
