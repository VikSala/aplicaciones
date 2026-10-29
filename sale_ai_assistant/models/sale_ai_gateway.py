"""Fixed-endpoint Vercel AI Gateway transport (no external Python dependencies).

Never send provider credentials to the web client, logs or Odoo chatter.
The provider's catalogue/prices/capabilities are not presumed to be stable.
"""
import json
import logging
import os
import re
import socket
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from urllib.parse import urlencode

from odoo import _

_logger = logging.getLogger(__name__)

GATEWAY_ENDPOINT = "https://ai-gateway.vercel.sh/v1/chat/completions"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
GENERATION_ENDPOINT = 'https://ai-gateway.vercel.sh/v1/generation'
GENERATION_ID_PATTERN = re.compile(r'[a-zA-Z0-9_-]{1,140}\Z')


class GatewayError(Exception):
    """A safe, human-facing diagnostic without credentials or provider payloads."""


def get_gateway_key(env, company_id):
    """Per-company write-only key; environment fallback for self-hosted installs."""
    parameter = "sale_ai_assistant.vercel_key.%d" % company_id
    return (
        env["ir.config_parameter"].sudo().get_param(parameter, "")
        or os.environ.get("AI_GATEWAY_API_KEY", "")
    ).strip()


def call_gateway(api_key, model_id, messages, timeout, max_tokens, tools=None, tool_choice="auto", routing=None):
    """Synchronous non-streaming request; phase-2 frontend provides loading feedback."""
    if not api_key:
        raise GatewayError(_("Falta configurar la clave de Vercel AI Gateway."))
    payload = {
        "model": model_id,
        "messages": messages,
        "stream": False,
    }
    if routing:
        if not isinstance(routing, dict) or set(routing) - {'sort', 'only', 'order'}:
            raise GatewayError(_('La configuración de enrutamiento Vercel no es válida.'))
        if 'sort' in routing and routing['sort'] not in ('cost', 'ttft', 'tps'):
            raise GatewayError(_('El criterio de enrutamiento Vercel no es válido.'))
        provider_pattern = r'[a-zA-Z0-9][a-zA-Z0-9._-]{0,79}'
        for field in ('only', 'order'):
            if field in routing:
                values = routing[field]
                if (not isinstance(values, list) or not values
                        or any(not isinstance(p, str) or not re.fullmatch(provider_pattern, p) for p in values)
                        or len({p.lower() for p in values}) != len(values)):
                    raise GatewayError(_('Los proveedores Vercel configurados no son válidos.'))
        if 'order' in routing:
            # Without an 'only' allowlist Vercel may silently try other
            # providers after those in 'order'. The configuration is strict.
            if ('only' not in routing or 'sort' in routing
                    or set(routing['order']) != set(routing['only'])):
                raise GatewayError(_('El orden de respaldo debe coincidir con la lista de proveedores permitidos.'))
        payload['providerOptions'] = {'gateway': routing}
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
        cost = gateway_meta.get('cost') if isinstance(gateway_meta, dict) else None
        cost_known = isinstance(cost, (int, float)) and not isinstance(cost, bool) and 0 <= cost < 1e9
        routing_meta = gateway_meta.get('routing') if isinstance(gateway_meta, dict) else None
        provider = (routing_meta.get('finalProvider') if isinstance(routing_meta, dict) else None)
        generation_id = gateway_meta.get('generationId') if isinstance(gateway_meta, dict) else None
        generation_id = generation_id or decoded.get('id')
        if not isinstance(generation_id, str) or not GENERATION_ID_PATTERN.fullmatch(generation_id):
            generation_id = False
        if not isinstance(provider, str) or len(provider) > 100:
            provider = False
        return {
            'generation_id': generation_id or False,
            'provider_name': provider or False,
            'cost_status': 'obtained' if cost_known else ('pending' if generation_id else 'unavailable'),
            "content": content.strip(),
            "finish_reason": finish_reason,
            "tool_calls": parsed_calls,
            "input_tokens": max(0, int(usage.get("prompt_tokens") or 0)),
            "output_tokens": max(0, int(usage.get("completion_tokens") or 0)),
            "reported_cost_usd": float(cost) if cost_known else 0.0,
            "latency_ms": elapsed,
        }
    except (ValueError, KeyError, IndexError, TypeError, OverflowError):
        _logger.warning("sale_ai_assistant: Provider response format could not be parsed (no payload logged)")
        raise GatewayError(_("El modelo ha devuelto una respuesta incompatible o vacía. Prueba otro modelo.")) from None


def lookup_generation(api_key, generation_id, timeout=8):
    """Return settled generation receipt or None (not yet indexed / unavailable).

    The documented REST endpoint uses snake_case fields in data. This request
    must NEVER interrupt an AI conversation or expose credentials in logs.
    """
    if not api_key or not isinstance(generation_id, str) or not GENERATION_ID_PATTERN.fullmatch(generation_id):
        return None
    url = GENERATION_ENDPOINT + '?' + urlencode({'id': generation_id})
    request = Request(url, headers={
        'Authorization': 'Bearer %s' % api_key,
        'Accept': 'application/json',
        'User-Agent': 'Odoo-sale-ai-assistant/18.0',
    }, method='GET')
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            return None
        obj = json.loads(raw.decode('utf-8'))
        data = obj.get('data', obj) if isinstance(obj, dict) else None
        if not isinstance(data, dict):
            return None
        amount = data.get('total_cost', data.get('totalCost'))
        if not isinstance(amount, (float, int)) or isinstance(amount, bool) or not 0 <= amount < 1e9:
            return None
        provider = data.get('provider_name', data.get('providerName'))
        if not isinstance(provider, str) or len(provider) > 100:
            provider = False
        return {'reported_cost_usd': float(amount), 'provider_name': provider or False,
                'input_tokens': data.get('prompt_tokens', data.get('promptTokens')),
                'output_tokens': data.get('completion_tokens', data.get('completionTokens'))}
    except (HTTPError, URLError, socket.timeout, TimeoutError, ConnectionError, OSError,
            ValueError, TypeError, UnicodeError):
        return None


# AI Gateway's native AI SDK transcription protocol (different from the /v1/chat URL).
# https://github.com/vercel/ai/blob/main/packages/gateway/src/gateway-transcription-model.ts
TRANSCRIPTION_ENDPOINT = "https://ai-gateway.vercel.sh/v4/ai/transcription-model"
DEFAULT_TRANSCRIPTION_MODEL = "microsoft/mai-transcribe-1.5"
TRANSCRIPTION_MODEL_PATTERN = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9._-]*/[a-zA-Z0-9][a-zA-Z0-9._-]*\Z")


def get_transcription_model(env, company_id):
    """Read a per-company transcription model; legacy 11.15 remains the default."""
    key = "sale_ai_assistant.transcription_model.%d" % company_id
    return (env["ir.config_parameter"].sudo().get_param(key, "") or DEFAULT_TRANSCRIPTION_MODEL).strip()


def validate_transcription_model(model_id):
    """Reject malformed IDs before sending any audio to the gateway."""
    if not isinstance(model_id, str) or len(model_id) > 128 or not TRANSCRIPTION_MODEL_PATTERN.fullmatch(model_id):
        raise GatewayError(_("Identificador de transcripción no válido. Usa proveedor/modelo (por ejemplo microsoft/mai-transcribe-2)."))



def _safe_transcription_error_detail(exc, api_key):
    """Return a bounded, redacted upstream diagnostic, never the raw HTTP body.

    Vercel can return useful 400 error descriptions (missing headers, invalid
    audio data, unsupported inputs). The 11.18 code discarded those messages,
    making every distinct cause appear as an identical generic HTTP 400.
    Only the structured error message/code is examined, not arbitrary payloads.
    """
    try:
        raw = exc.read(8192)
        data = json.loads(raw.decode('utf-8'))
        if not isinstance(data, dict):
            return ''
        error = data.get('error')
        if isinstance(error, dict):
            message = error.get('message')
            code = error.get('code') or error.get('type')
        else:
            message = error if isinstance(error, str) else data.get('message')
            code = data.get('code')
        elements = []
        if isinstance(code, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,80}', code):
            elements.append('código: %s' % code)
        if isinstance(message, str):
            # Upstream text is untrusted: prevent raw bytes, HTML, line breaks,
            # long identifiers and credential strings from reaching the UI.
            message = re.sub(r'[\x00-\x1f\x7f]+', ' ', message)
            message = re.sub(r'<[^>]*>', '', message)
            if api_key:
                message = message.replace(api_key, '[oculto]')
            message = re.sub(r'(?i)bearer\s+\S+', 'Bearer [oculto]', message)
            message = re.sub(r'(?i)\b(?:sk|vck|vcst|ai_gateway)[-_][A-Za-z0-9_-]{8,}', '[oculto]', message)
            message = re.sub(r'(?i)data:audio/[^,\s]+,[^\s]+', '[audio oculto]', message)
            message = re.sub(r'[A-Za-z0-9+/=_-]{65,}', '[datos ocultos]', message)
            message = ' '.join(message.split()).strip()
            if message:
                elements.append('detalle: %s' % message[:300])
        return ' (%s)' % '; '.join(elements) if elements else ''
    except (AttributeError, ValueError, TypeError, UnicodeError, OSError):
        return ''



def transcribe_audio_gateway(api_key, audio, model_id=DEFAULT_TRANSCRIPTION_MODEL, timeout=90,
                             max_response_bytes=1024 * 1024, max_transcript_chars=50000):
    """Transcribe MP3 remotely using the existing company Vercel API key.

    No audio analysis or decoding is done in Odoo. The native Gateway endpoint
    expects base64-encoded audio in JSON, not OpenAI multipart form data.
    """
    import base64

    if not api_key:
        raise GatewayError(_("Falta configurar la clave de Vercel AI Gateway."))
    validate_transcription_model(model_id)
    if not isinstance(audio, bytes) or not audio:
        raise GatewayError(_("No se ha recibido un archivo de audio válido."))
    payload = {
        "audio": base64.b64encode(audio).decode("ascii"),
        "mediaType": "audio/mpeg",
    }
    request = Request(
        TRANSCRIPTION_ENDPOINT,
        data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
        headers={
            "Authorization": "Bearer %s" % api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "Odoo-sale-ai-assistant/18.0",
            "ai-transcription-model-specification-version": "4",
            "ai-model-id": model_id,
            # These native-protocol headers are sent by the official Vercel
            # AI SDK Gateway provider (not used for /v1/chat/completions).
            "ai-gateway-protocol-version": "0.0.1",
            "ai-gateway-auth-method": "api-key",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw_response = response.read(max_response_bytes + 1) if max_response_bytes else response.read()
    except HTTPError as exc:
        # Expose only a short, sanitized diagnostic from Vercel. Never log the
        # raw HTTP response or the audio, and redact the Gateway credential.
        provider_code = _safe_transcription_error_detail(exc, api_key)
        if exc.code in (401, 403):
            raise GatewayError(_("Vercel ha rechazado la API key o el acceso al modelo (HTTP %s).") % exc.code) from None
        if exc.code == 402:
            raise GatewayError(_("Vercel indica saldo insuficiente o un problema de facturación (HTTP 402).")) from None
        if exc.code == 413:
            raise GatewayError(_("Vercel o el proveedor rechaza el tamaño del archivo (HTTP 413)%s. Aunque el módulo lo admita, prueba otro tamaño o modelo.") % provider_code) from None
        if exc.code == 429:
            raise GatewayError(_("Límite de solicitudes de Vercel alcanzado (HTTP 429).")) from None
        if exc.code in (502, 503, 504):
            raise GatewayError(_("El servicio de transcripción no está disponible temporalmente (HTTP %s).") % exc.code) from None
        if exc.code in (400, 404, 415, 422):
            raise GatewayError(_("Vercel o el proveedor ha rechazado la transcripción con el modelo %s (HTTP %s)%s.") % (model_id, exc.code, provider_code)) from None
        raise GatewayError(_("Vercel no ha podido transcribir el archivo (HTTP %s).") % exc.code) from None
    except (URLError, socket.timeout, TimeoutError, ConnectionError, OSError):
        raise GatewayError(_("No se ha podido conectar con Vercel para transcribir el audio.")) from None
    if max_response_bytes and len(raw_response) > max_response_bytes:
        raise GatewayError(_("La respuesta de transcripción supera el límite de respuesta configurado en Conexión Vercel IA."))
    try:
        result = json.loads(raw_response.decode("utf-8"))
        transcript = result["text"]
        if not isinstance(transcript, str):
            raise ValueError("Invalid transcript")
        transcript = transcript.strip()
        if not transcript:
            raise GatewayError(_("No se ha detectado voz transcribible en el MP3."))
        if max_transcript_chars and len(transcript) > max_transcript_chars:
            raise GatewayError(_("La transcripción supera el límite configurado de %s caracteres.") % max_transcript_chars)
        return transcript
    except (ValueError, KeyError, TypeError, UnicodeError):
        _logger.warning("sale_ai_assistant: Unrecognized Gateway transcription response (no payload logged)")
        raise GatewayError(_("Vercel ha devuelto una respuesta de transcripción incompatible.")) from None
