import unittest

import requests

from ..services.ontime_client import OnTimeAPIError, OnTimeClient


class _FakeResponse:
    def __init__(self, status=200, content=b"{}", headers=None, payload=None):
        self.status_code = status
        self.content = content
        self.headers = headers or {"Content-Type": "application/json"}
        self._payload = payload if payload is not None else {}
        self.ok = 200 <= status < 400
        self.text = content.decode("utf-8", "ignore")

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, actions):
        self.actions = list(actions)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        action = self.actions.pop(0)
        if isinstance(action, Exception):
            raise action
        return action


class TestOnTimeClientSafety(unittest.TestCase):
    def test_safe_get_is_retried(self):
        session = _FakeSession(
            [requests.Timeout("temporary"), _FakeResponse(payload={"ok": True})]
        )
        client = OnTimeClient(
            "https://api.example.test/root",
            "SECRET",
            session=session,
            read_retries=1,
            retry_backoff=0,
        )
        self.assertEqual(client.request("GET", "/v1/test"), {"ok": True})
        self.assertEqual(len(session.calls), 2)

    def test_post_is_never_retried(self):
        session = _FakeSession(
            [requests.Timeout("temporary"), _FakeResponse(payload={"ok": True})]
        )
        client = OnTimeClient(
            "https://api.example.test/root",
            "SECRET",
            session=session,
            read_retries=5,
            retry_backoff=0,
        )
        with self.assertRaises(OnTimeAPIError) as caught:
            client.request("POST", "/v1/envios", json={})
        self.assertEqual(caught.exception.error_code, "TIMEOUT")
        self.assertEqual(len(session.calls), 1)

    def test_bearer_token_is_not_forwarded_to_external_download_url(self):
        session = _FakeSession(
            [
                _FakeResponse(
                    content=b"%PDF-test",
                    headers={"Content-Type": "application/pdf"},
                )
            ]
        )
        client = OnTimeClient(
            "https://api.example.test/root",
            "SECRET",
            session=session,
            read_retries=0,
        )
        client.request_binary("GET", "https://cdn.example.net/signed?token=secret")
        self.assertNotIn("Authorization", session.calls[0][2]["headers"])

    def test_redirect_to_external_host_drops_api_key(self):
        session = _FakeSession(
            [
                _FakeResponse(
                    status=302,
                    content=b"",
                    headers={"Location": "https://cdn.example.net/label?token=secret"},
                ),
                _FakeResponse(
                    content=b"%PDF-test",
                    headers={"Content-Type": "application/pdf"},
                ),
            ]
        )
        client = OnTimeClient(
            "https://api.example.test/root",
            "SECRET",
            session=session,
            read_retries=0,
        )
        client.request_binary("GET", "/v1/label")
        self.assertEqual(session.calls[0][2]["headers"]["Authorization"], "Bearer SECRET")
        self.assertNotIn("Authorization", session.calls[1][2]["headers"])

    def test_document_size_limit(self):
        session = _FakeSession(
            [
                _FakeResponse(
                    content=b"x" * 11,
                    headers={"Content-Type": "application/pdf", "Content-Length": "11"},
                )
            ]
        )
        client = OnTimeClient(
            "https://api.example.test/root",
            "SECRET",
            session=session,
            read_retries=0,
            max_document_bytes=10,
        )
        with self.assertRaises(OnTimeAPIError) as caught:
            client.request_binary("GET", "/v1/document")
        self.assertEqual(caught.exception.error_code, "DOCUMENT_TOO_LARGE")
    def test_mensaglobal_success_false_uses_msg(self):
        session = _FakeSession(
            [
                _FakeResponse(
                    payload={
                        "success": False,
                        "msg": ["Servicio no disponible", "Revise el código"],
                        "data": {},
                    }
                )
            ]
        )
        client = OnTimeClient(
            "https://preproduccion.mensaglobal.com/api",
            "SECRET",
            session=session,
            read_retries=0,
        )
        with self.assertRaises(OnTimeAPIError) as caught:
            client.request("POST", "/v1/envios", json={})
        self.assertIn("Servicio no disponible", caught.exception.message)
        self.assertEqual(caught.exception.status_code, 200)

    def test_bearer_header_on_same_origin(self):
        session = _FakeSession([_FakeResponse(payload={"success": True, "msg": [], "data": {}})])
        client = OnTimeClient(
            "https://preproduccion.mensaglobal.com/api",
            "SECRET",
            session=session,
            read_retries=0,
        )
        client.request("GET", "/v1/envios/localizar/TEST")
        self.assertEqual(session.calls[0][2]["headers"]["Authorization"], "Bearer SECRET")

