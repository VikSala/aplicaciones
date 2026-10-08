import logging
import re
import time
from urllib.parse import urljoin, urlsplit

import requests

_logger = logging.getLogger(__name__)


class OnTimeAPIError(Exception):
    """Technical error returned while communicating with the OnTime API."""

    def __init__(
        self,
        message,
        *,
        status_code=None,
        error_code=None,
        correlation_id=None,
        payload=None,
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code
        self.correlation_id = correlation_id
        self.payload = payload


class OnTimeClient:
    """Small reusable HTTP client for OnTime APIs.

    The client deliberately retries only read-only HTTP methods. Shipment
    creation/cancellation are never retried automatically because a timeout can
    occur after the remote side effect has already happened.

    Absolute document download URLs are also handled defensively: the Bearer
    token is only forwarded when the URL belongs to the same origin as the
    configured Mensaglobal API. This prevents leaking credentials to a
    third-party POD/document URL.
    """

    SAFE_RETRY_METHODS = {"GET", "HEAD", "OPTIONS"}
    RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}

    def __init__(
        self,
        base_url,
        api_key,
        timeout=20,
        session=None,
        read_retries=1,
        retry_backoff=0.25,
        max_document_bytes=20 * 1024 * 1024,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.session = session or requests.Session()
        self.read_retries = max(int(read_retries or 0), 0)
        self.retry_backoff = max(float(retry_backoff or 0.0), 0.0)
        self.max_document_bytes = max(int(max_document_bytes or 0), 0)

    @staticmethod
    def _safe_message(value, limit=1000):
        value = " ".join(str(value or "").split())
        return value[:limit] if limit and len(value) > limit else value

    @staticmethod
    def _safe_log_path(path):
        """Return a log-safe endpoint without query string, credentials or fragment."""
        value = str(path or "")
        parsed = urlsplit(value)
        if parsed.scheme and parsed.netloc:
            host = parsed.hostname or ""
            port = ":%s" % parsed.port if parsed.port else ""
            return "%s://%s%s%s" % (
                parsed.scheme,
                host,
                port,
                parsed.path or "/",
            )
        return value.split("?", 1)[0].split("#", 1)[0]

    def _same_origin_as_base(self, url):
        target = urlsplit(url)
        base = urlsplit(self.base_url)
        if not target.scheme or not target.netloc:
            return True
        target_port = target.port or (443 if target.scheme == "https" else 80)
        base_port = base.port or (443 if base.scheme == "https" else 80)
        return (
            target.scheme.lower() == base.scheme.lower()
            and (target.hostname or "").lower() == (base.hostname or "").lower()
            and target_port == base_port
        )

    def _headers(self, extra_headers=None, *, include_api_key=True):
        headers = {
            "Accept": "application/json",
            "User-Agent": "Odoo-Optima-Delivery-OnTime/18.0",
        }
        if include_api_key:
            headers["Authorization"] = "Bearer %s" % self.api_key
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _url(self, path):
        path = path or ""
        if path.startswith(("https://", "http://")):
            return path
        if not self.base_url:
            raise OnTimeAPIError("OnTime base URL is not configured.")
        return "%s/%s" % (self.base_url, path.lstrip("/"))

    def _check_credentials(self):
        if not self.api_key:
            raise OnTimeAPIError(
                "Mensaglobal API token is not configured.",
                error_code="MISSING_API_KEY",
            )

    @staticmethod
    def _extract_correlation_id(payload, response):
        if isinstance(payload, dict):
            for key in ("correlationId", "correlation_id", "requestId", "request_id"):
                value = payload.get(key)
                if value:
                    return value
            data = payload.get("data")
            if isinstance(data, dict):
                for key in ("correlationId", "correlation_id", "requestId", "request_id"):
                    value = data.get(key)
                    if value:
                        return value
        return (
            response.headers.get("X-Correlation-Id")
            or response.headers.get("X-Request-Id")
            or response.headers.get("Correlation-Id")
        )

    @staticmethod
    def _payload_from_response(response):
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            text = (response.text or "").strip()
            return {"message": text[:1000]} if text else None

    @staticmethod
    def _json_payload_if_applicable(response):
        content_type = (response.headers.get("Content-Type") or "").lower()
        body = (response.content or b"").lstrip()
        if "json" not in content_type and not body.startswith((b"{", b"[")):
            return None
        try:
            return response.json()
        except ValueError:
            return None

    @staticmethod
    def _filename_from_response(response):
        disposition = response.headers.get("Content-Disposition") or ""
        match = re.search(r'filename\s*=\s*"?([^";]+)"?', disposition, re.I)
        return match.group(1).strip() if match else None

    def _retry_delay(self, response, attempt):
        if response is not None:
            retry_after = (response.headers.get("Retry-After") or "").strip()
            try:
                return min(max(float(retry_after), 0.0), 2.0)
            except (TypeError, ValueError):
                pass
        return min(self.retry_backoff * (2 ** attempt), 2.0)

    def _perform(self, method, path, *, params=None, json=None, headers=None):
        self._check_credentials()
        url = self._url(path)
        method = (method or "GET").upper()
        retries = self.read_retries if method in self.SAFE_RETRY_METHODS else 0
        safe_path = self._safe_log_path(path)

        for attempt in range(retries + 1):
            request_url = url
            redirects = 0
            while True:
                include_api_key = self._same_origin_as_base(request_url)
                try:
                    response = self.session.request(
                        method,
                        request_url,
                        params=params,
                        json=json,
                        headers=self._headers(headers, include_api_key=include_api_key),
                        timeout=self.timeout,
                        allow_redirects=False,
                    )
                except requests.Timeout as exc:
                    if attempt < retries:
                        _logger.warning(
                            "Transient OnTime timeout; retrying safe request: method=%s path=%s attempt=%s/%s",
                            method,
                            safe_path,
                            attempt + 1,
                            retries + 1,
                        )
                        time.sleep(self._retry_delay(None, attempt))
                        break
                    raise OnTimeAPIError(
                        "Timeout while connecting to OnTime after %s seconds." % self.timeout,
                        error_code="TIMEOUT",
                    ) from exc
                except requests.ConnectionError as exc:
                    if attempt < retries:
                        _logger.warning(
                            "Transient OnTime connection error; retrying safe request: method=%s path=%s attempt=%s/%s",
                            method,
                            safe_path,
                            attempt + 1,
                            retries + 1,
                        )
                        time.sleep(self._retry_delay(None, attempt))
                        break
                    raise OnTimeAPIError(
                        "Could not connect to the OnTime API.",
                        error_code="CONNECTION_ERROR",
                    ) from exc
                except requests.RequestException as exc:
                    # Do not echo the raw exception because requests may include
                    # a signed download URL (with secret query parameters).
                    raise OnTimeAPIError(
                        "Unexpected HTTP error while connecting to OnTime.",
                        error_code="HTTP_ERROR",
                    ) from exc

                if (
                    method in self.SAFE_RETRY_METHODS
                    and response.status_code in {301, 302, 303, 307, 308}
                    and response.headers.get("Location")
                ):
                    if redirects >= 3:
                        raise OnTimeAPIError(
                            "Too many redirects while downloading data from OnTime.",
                            status_code=response.status_code,
                            error_code="TOO_MANY_REDIRECTS",
                        )
                    target = urljoin(request_url, response.headers["Location"])
                    parsed = urlsplit(target)
                    if parsed.scheme not in {"http", "https"}:
                        raise OnTimeAPIError(
                            "OnTime returned an unsupported redirect URL.",
                            status_code=response.status_code,
                            error_code="UNSAFE_REDIRECT",
                        )
                    # Do not allow HTTPS API calls to be downgraded to HTTP.
                    if urlsplit(request_url).scheme == "https" and parsed.scheme != "https":
                        raise OnTimeAPIError(
                            "OnTime returned an insecure HTTP redirect.",
                            status_code=response.status_code,
                            error_code="UNSAFE_REDIRECT",
                        )
                    redirects += 1
                    request_url = target
                    continue

                if (
                    attempt < retries
                    and response.status_code in self.RETRYABLE_STATUS_CODES
                ):
                    _logger.warning(
                        "Transient OnTime HTTP response; retrying safe request: method=%s path=%s status=%s attempt=%s/%s",
                        method,
                        safe_path,
                        response.status_code,
                        attempt + 1,
                        retries + 1,
                    )
                    time.sleep(self._retry_delay(response, attempt))
                    break
                return response

        # Defensive guard; the loop always returns or raises.
        raise OnTimeAPIError("Unexpected OnTime HTTP client state.", error_code="HTTP_ERROR")

    def _raise_if_error(self, response, *, method, path, payload=None):
        if payload is None:
            payload = self._json_payload_if_applicable(response)
            if payload is None and not response.ok:
                payload = self._payload_from_response(response)
        correlation_id = self._extract_correlation_id(payload, response)
        error_code = payload.get("errorCode") if isinstance(payload, dict) else None
        message = payload.get("message") if isinstance(payload, dict) else None
        if isinstance(payload, dict) and not message:
            messages = payload.get("msg")
            if isinstance(messages, (list, tuple)):
                message = "; ".join(str(item) for item in messages if item)
            elif messages:
                message = str(messages)
        message = self._safe_message(message)
        safe_path = self._safe_log_path(path)

        if 300 <= response.status_code < 400:
            _logger.warning(
                "Unexpected OnTime redirect: method=%s path=%s status=%s correlation_id=%s",
                method,
                safe_path,
                response.status_code,
                correlation_id,
            )
            raise OnTimeAPIError(
                "OnTime returned an unexpected HTTP redirect.",
                status_code=response.status_code,
                error_code="UNEXPECTED_REDIRECT",
                correlation_id=correlation_id,
                payload=payload,
            )

        if not response.ok:
            _logger.warning(
                "OnTime API HTTP error: method=%s path=%s status=%s error_code=%s correlation_id=%s",
                method,
                safe_path,
                response.status_code,
                error_code,
                correlation_id,
            )
            raise OnTimeAPIError(
                message or "OnTime returned HTTP %s." % response.status_code,
                status_code=response.status_code,
                error_code=error_code,
                correlation_id=correlation_id,
                payload=payload,
            )

        if isinstance(payload, dict) and payload.get("success") is False:
            _logger.warning(
                "OnTime API business error: method=%s path=%s error_code=%s correlation_id=%s",
                method,
                safe_path,
                error_code,
                correlation_id,
            )
            raise OnTimeAPIError(
                message or "OnTime rejected the request.",
                status_code=response.status_code,
                error_code=error_code,
                correlation_id=correlation_id,
                payload=payload,
            )
        return correlation_id

    def request(self, method, path, *, params=None, json=None, headers=None):
        method = (method or "GET").upper()
        response = self._perform(method, path, params=params, json=json, headers=headers)
        payload = self._payload_from_response(response)
        correlation_id = self._raise_if_error(
            response,
            method=method,
            path=path,
            payload=payload,
        )
        _logger.info(
            "OnTime API request successful: method=%s path=%s status=%s correlation_id=%s",
            method,
            self._safe_log_path(path),
            response.status_code,
            correlation_id,
        )
        return payload

    def request_binary(self, method, path, *, params=None, headers=None):
        """Return a document response while preserving raw bytes safely."""
        method = (method or "GET").upper()
        response = self._perform(method, path, params=params, headers=headers)

        if self.max_document_bytes:
            content_length = response.headers.get("Content-Length")
            try:
                declared_size = int(content_length) if content_length else 0
            except (TypeError, ValueError):
                declared_size = 0
            if declared_size > self.max_document_bytes:
                raise OnTimeAPIError(
                    "OnTime document exceeds the configured maximum size.",
                    status_code=response.status_code,
                    error_code="DOCUMENT_TOO_LARGE",
                )
            if len(response.content or b"") > self.max_document_bytes:
                raise OnTimeAPIError(
                    "OnTime document exceeds the configured maximum size.",
                    status_code=response.status_code,
                    error_code="DOCUMENT_TOO_LARGE",
                )

        payload = self._json_payload_if_applicable(response)
        correlation_id = self._raise_if_error(
            response,
            method=method,
            path=path,
            payload=payload,
        )
        content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip()
        _logger.info(
            "OnTime API document request successful: method=%s path=%s status=%s content_type=%s correlation_id=%s",
            method,
            self._safe_log_path(path),
            response.status_code,
            content_type,
            correlation_id,
        )
        return {
            "content": response.content or b"",
            "content_type": content_type or "application/octet-stream",
            "filename": self._filename_from_response(response),
            "json": payload,
            "correlation_id": correlation_id,
        }
