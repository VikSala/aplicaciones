"""WhatsApp Business Cloud API (Meta Graph API) client.

A thin per-account wrapper used as the "cloud" transport alongside the QR /
Baileys transport. Its public method names mirror BaileysApi so the send
dispatch in owa.account._dispatch_send can swap transports cleanly.
"""

import logging
import requests

_logger = logging.getLogger(__name__)

# Meta error codes meaning "you are outside the 24h customer window — only an
# approved template may be sent now".
# https://developers.facebook.com/docs/whatsapp/cloud-api/support/error-codes
REENGAGEMENT_CODES = {131047, 131026, 131051}
DEFAULT_TIMEOUT = 20
_MEDIA_TYPES = ('image', 'video', 'audio', 'document', 'sticker')


class CloudApiError(Exception):
    def __init__(self, code, message, fbtrace_id=None, http_status=None):
        self.code = code
        self.message = message
        self.fbtrace_id = fbtrace_id
        self.http_status = http_status
        super().__init__(f"[{code}] {message} (fbtrace={fbtrace_id})")

    @property
    def is_reengagement_window(self):
        return self.code in REENGAGEMENT_CODES


class CloudApi:
    """Cloud (Graph) API client bound to one owa.account."""

    def __init__(self, account):
        self.account = account
        self.version = account.cloud_api_version or 'v23.0'
        self.phone_number_id = account.cloud_phone_number_id
        self.waba_id = account.cloud_waba_id
        self.app_id = account.cloud_app_id
        self.token = account.cloud_access_token
        self.base = f"https://graph.facebook.com/{self.version}"

    # ------------------------------------------------------------------
    # low level
    # ------------------------------------------------------------------
    def _headers(self, oauth=False):
        scheme = 'OAuth' if oauth else 'Bearer'
        return {'Authorization': f'{scheme} {self.token}'}

    def _post(self, path, json=None, **kw):
        return self._handle(requests.post(
            self.base + path, headers=self._headers(), json=json,
            timeout=DEFAULT_TIMEOUT, **kw))

    def _get(self, path, params=None):
        return self._handle(requests.get(
            self.base + path, headers=self._headers(), params=params,
            timeout=DEFAULT_TIMEOUT))

    def _handle(self, resp):
        try:
            data = resp.json()
        except ValueError:
            data = {}
        if resp.status_code >= 400 or 'error' in data:
            err = data.get('error', {})
            raise CloudApiError(
                err.get('code', resp.status_code),
                err.get('message', (resp.text or '')[:200]),
                err.get('fbtrace_id'), resp.status_code)
        return data

    def _messages(self, payload):
        payload = dict(payload, messaging_product='whatsapp')
        data = self._post(f"/{self.phone_number_id}/messages", json=payload)
        msgs = data.get('messages') or [{}]
        return msgs[0].get('id', '')

    # ------------------------------------------------------------------
    # messaging
    # ------------------------------------------------------------------
    def health(self):
        self._get(f"/{self.phone_number_id}")
        return True

    def send_text(self, to, body, preview_url=False):
        return self._messages({
            'to': to, 'type': 'text',
            'text': {'body': body or '', 'preview_url': bool(preview_url)},
        })

    def send_media(self, to, media_type, link=None, media_id=None,
                   caption=None, filename=None):
        obj = {}
        if media_id:
            obj['id'] = media_id
        elif link:
            obj['link'] = link
        if caption and media_type in ('image', 'video', 'document'):
            obj['caption'] = caption
        if filename and media_type == 'document':
            obj['filename'] = filename
        return self._messages({'to': to, 'type': media_type, media_type: obj})

    def send_reaction(self, to, message_id, emoji):
        return self._messages({
            'to': to, 'type': 'reaction',
            'reaction': {'message_id': message_id, 'emoji': emoji or ''}})

    def send_template(self, to, name, lang, components=None):
        tmpl = {'name': name, 'language': {'code': lang or 'en'}}
        if components:
            tmpl['components'] = components
        return self._messages({'to': to, 'type': 'template', 'template': tmpl})

    def mark_read(self, message_id):
        return self._post(f"/{self.phone_number_id}/messages", json={
            'messaging_product': 'whatsapp', 'status': 'read',
            'message_id': message_id})

    # ------------------------------------------------------------------
    # media transfer
    # ------------------------------------------------------------------
    def upload_media(self, data_bytes, mime_type, filename='file'):
        """Resumable upload; returns the Meta media handle (h)."""
        sess = self._post(
            f"/{self.app_id}/uploads",
            params={'file_length': len(data_bytes), 'file_type': mime_type,
                    'file_name': filename})
        upload_id = sess.get('id')
        resp = requests.post(
            f"{self.base}/{upload_id}",
            headers={**self._headers(oauth=True), 'file_offset': '0'},
            data=data_bytes, timeout=DEFAULT_TIMEOUT)
        return self._handle(resp).get('h')

    def download_media(self, media_id):
        """Return (bytes, mime_type) for an inbound media id."""
        meta = self._get(f"/{media_id}")
        url = meta.get('url')
        resp = requests.get(url, headers=self._headers(),
                            timeout=DEFAULT_TIMEOUT)
        resp.raise_for_status()
        return resp.content, meta.get('mime_type')

    # ------------------------------------------------------------------
    # templates (management)
    # ------------------------------------------------------------------
    def submit_template(self, payload):
        return self._post(f"/{self.waba_id}/message_templates", json=payload)

    def sync_templates(self):
        data = self._get(
            f"/{self.waba_id}/message_templates",
            params={'fields': 'name,language,status,category,id,'
                    'quality_score,components', 'limit': 200})
        return data.get('data', [])

    def get_template(self, wa_template_uid):
        return self._get(
            f"/{wa_template_uid}",
            params={'fields': 'name,components,language,status,category,id,'
                    'quality_score'})

    # ------------------------------------------------------------------
    # calling (signaling only — we never carry media)
    # ------------------------------------------------------------------
    def reject_call(self, call_id):
        """Reject a still-ringing inbound call via the WhatsApp Calling API.

        POST /{phone_number_id}/calls with action ``reject`` so the caller's
        phone stops ringing. Voice-only product; we never accept (no WebRTC
        media stack) — log, reject, and auto-reply only.
        """
        return self._post(
            f"/{self.phone_number_id}/calls",
            json={
                'messaging_product': 'whatsapp',
                'call_id': call_id,
                'action': 'reject',
            })
