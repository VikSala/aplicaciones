"""Fixed-endpoint Vercel AI Gateway transport (no external Python dependencies).

Never send provider credentials to the web client, logs or Odoo chatter.
The provider's catalogue/prices/capabilities are not presumed to be stable.
"""
import json
import logging
import os
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from odoo import _

_logger = logging.getLogger(__name__)

GATEWAY_ENDPOINT = "https://ai-gateway.vercel.sh/v1/chat/completions"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class GatewayError(Exception):
    """A safe, human-facing diagnostic without credentials or provider payloads."""


def get_gateway_key(env, company_id):
    """Per-company write-only key; environment fallback for self-hosted installs."""
    parameter = "sale_ai_assistant.vercel_key.%d" % company_id
    return (
        env["ir.config_parameter"].sudo().get_param(parameter, "")
        or os.environ.get("AI_GATEWAY_API_KEY", "")
    ).strip()


def call_gateway(api_key, model_id, messages, timeout, max_tokens, tools=None, tool_choice="auto"):
    """Synchronous non-streaming request; phase-2 frontend provides loading feedback."""
    if not api_key:
        raise GatewayError(_("Falta configurar la clave de Vercel AI Gateway."))
    payload = {
        "model": model_id,
        "messages": messages,
        "stream": False,
    }
    # GPT-5/o-series require max_completion_tokens in Chat Completions.
    # Most other OpenAI-compatible providers still use max_tokens.
    limit_field = "max_completion_tokens" if model_id.startswith(("openai/gpt-5", "openai/o")) else "max_tokens"
    payload[limit_field] = max_tokens
    if tools:
        # OpenAI-compatible tool calling. Absent for models without capability.
        payload["tools"] = tools
        if tool_choice not in ("auto", "required", "none"):
            raise GatewayError(_("Configuración de herramientas no válida."))
        payload["tool_choice"] = tool_choice
    request = Request(
        GATEWAY_ENDPOINT,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": "Bearer %s" % api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Odoo-sale-ai-assistant/18.0",
        },
        method="POST",
    )
    start = time.monotonic()
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        # HTTPError body may contain secrets or arbitrary untrusted text: do not log it.
        if exc.code in (401, 403):
            raise GatewayError(_("Vercel ha rechazado la API key o el acceso al modelo (HTTP %s).") % exc.code) from None
        if exc.code == 402:
            raise GatewayError(_("Vercel indica saldo insuficiente o un problema de facturación (HTTP 402).")) from None
        if exc.code == 429:
            raise GatewayError(_("Límite de solicitudes de Vercel alcanzado (HTTP 429). Prueba más tarde.")) from None
        if exc.code == 503:
            raise GatewayError(_(
                "El servicio de IA está temporalmente no disponible (HTTP 503). "
                "Es un problema del servicio Vercel/proveedor, no una prueba de que "
                "el modelo carezca de búsqueda web. Puedes pulsar Reintentar o "
                "seleccionar otro modelo."
            )) from None
        if exc.code in (502, 504):
            raise GatewayError(_(
                "Vercel o el proveedor del modelo no ha completado la solicitud "
                "(HTTP %s). Prueba a reintentar o cambia de modelo."
            ) % exc.code) from None
        if exc.code in (400, 404, 422):
            raise GatewayError(_("Modelo o parámetros rechazados por Vercel (HTTP %s). Revisa el identificador y la compatibilidad.") % exc.code) from None
        raise GatewayError(_("Vercel no ha podido completar la solicitud (HTTP %s).") % exc.code) from None
    except (URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
        raise GatewayError(_("No se ha podido conectar con Vercel AI Gateway. Comprueba la red o vuelve a intentarlo.")) from None
    elapsed = int((time.monotonic() - start) * 1000)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise GatewayError(_("La respuesta del modelo supera el tamaño permitido."))
    try:
        decoded = json.loads(raw.decode("utf-8"))
        choice = decoded["choices"][0]
        message = choice["message"]
        # Expose the provider completion reason so callers that create persistent
        # documents never silently save a response cut by the token limit.
        finish_reason = choice.get("finish_reason")
        if not isinstance(finish_reason, str):
            finish_reason = ""
        content = message.get("content") or ""
        # Some models return multiple text parts rather than a single string.
        if isinstance(content, list):
            content = "\n".join(part.get("text", "") for part in content if isinstance(part, dict) and part.get("type") == "text")
        if not isinstance(content, str):
            raise ValueError("Invalid response content")
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list) or len(raw_calls) > 100:
            raise ValueError("Invalid tool calls")
        parsed_calls = []
        for call in raw_calls:
            fn = call.get("function") if isinstance(call, dict) else None
            if not (isinstance(fn, dict) and isinstance(call.get("id"), str)
                    and isinstance(fn.get("name"), str) and isinstance(fn.get("arguments"), str)):
                raise ValueError("Malformed tool call")
            if len(call["id"]) > 200 or len(fn["name"]) > 70 or len(fn["arguments"]) > 600000:
                raise ValueError("Oversized tool call")
            parsed_calls.append({"id": call["id"], "type": "function", "function": {
                "name": fn["name"], "arguments": fn["arguments"]}})
        if not content.strip() and not parsed_calls:
            raise ValueError("Empty response")
        usage = decoded.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        metadata = decoded.get("providerMetadata") or decoded.get("provider_metadata") or {}
        gateway_meta = metadata.get("gateway", {}) if isinstance(metadata, dict) else {}
        cost = gateway_meta.get("cost") if isinstance(gateway_meta, dict) else None
        # The REST chat response does not guarantee that gateway cost is present.
        return {
            "content": content.strip(),
            "finish_reason": finish_reason,
            "tool_calls": parsed_calls,
            "input_tokens": max(0, int(usage.get("prompt_tokens") or 0)),
            "output_tokens": max(0, int(usage.get("completion_tokens") or 0)),
            "reported_cost_usd": float(cost) if isinstance(cost, (int, float)) and cost >= 0 else 0.0,
            "latency_ms": elapsed,
        }
    except (ValueError, KeyError, IndexError, TypeError, OverflowError):
        _logger.warning("sale_ai_assistant: Provider response format could not be parsed (no payload logged)")
        raise GatewayError(_("El modelo ha devuelto una respuesta incompatible o vacía. Prueba otro modelo.")) from None
