"""Official WhatsApp Cloud API (Meta Graph API) webhook.

One shared callback URL for every cloud account. GET handles Meta's
verification handshake (``hub.challenge``); POST verifies the
``X-Hub-Signature-256`` HMAC per account, routes by WABA id +
phone-number-id, and feeds inbound messages into the transport-neutral
``owa.account._handle_inbound`` and status receipts into
``owa.account._apply_cloud_status``.
"""

import hashlib
import hmac
import json
import logging
from http import HTTPStatus

from odoo import http
from odoo.http import request
from odoo.tools import consteq

_logger = logging.getLogger(__name__)


class CloudWebhook(http.Controller):

    @http.route('/open_whatsapp_connector/cloud/webhook',
                methods=['GET'], type='http', auth='public', csrf=False)
    def cloud_verify(self, **kw):
        """Meta webhook verification handshake. Echo ``hub.challenge`` when a
        cloud account with the matching ``cloud_verify_token`` exists."""
        token = kw.get('hub.verify_token')
        mode = kw.get('hub.mode')
        challenge = kw.get('hub.challenge')
        if mode == 'subscribe' and token:
            acc = request.env['owa.account'].sudo().search([
                ('connection_type', '=', 'cloud'),
                ('cloud_verify_token', '=', token),
            ], limit=1)
            if acc:
                resp = request.make_response(challenge or '')
                resp.status_code = HTTPStatus.OK
                return resp
        return request.make_response('', status=HTTPStatus.FORBIDDEN)

    @http.route('/open_whatsapp_connector/cloud/webhook',
                methods=['POST'], type='http', auth='public', csrf=False)
    def cloud_inbound(self, **kw):
        """Receive Meta change notifications. Verifies the per-account HMAC
        signature, then dispatches messages + statuses + template events.

        ``**kw`` swallows the ``?db=`` query arg (and any extras Meta appends)
        so the router doesn't log "called ignoring args {'db'}"; the db is
        already resolved by the ir_http patch before dispatch.
        """
        raw = request.httprequest.get_data()
        try:
            data = json.loads(raw or b'{}')
        except ValueError:
            return request.make_response('', status=HTTPStatus.BAD_REQUEST)
        for entry in data.get('entry', []):
            waba_id = entry.get('id')
            account = request.env['owa.account'].sudo().search([
                ('connection_type', '=', 'cloud'),
                ('cloud_waba_id', '=', waba_id),
            ], limit=1)
            if not account:
                _logger.warning("Cloud webhook: no account for WABA %s", waba_id)
                continue
            if not self._verify_signature(account, raw):
                return request.make_response('', status=HTTPStatus.FORBIDDEN)
            for change in entry.get('changes', []):
                self._process_change(
                    account, change.get('value', {}), change.get('field'))
        return request.make_response('', status=HTTPStatus.OK)

    def _verify_signature(self, account, raw):
        sig = request.httprequest.headers.get('X-Hub-Signature-256', '')
        if not sig.startswith('sha256=') or not account.cloud_app_secret:
            return False
        expected = hmac.new(
            account.cloud_app_secret.encode(), raw, hashlib.sha256).hexdigest()
        return consteq(sig[7:], expected)

    def _process_change(self, account, value, field):
        from odoo.addons.open_whatsapp_connector.tools.meta_inbound import (
            normalize_meta_message)
        meta = value.get('metadata', {})
        # Disambiguate multiple numbers under one WABA: only handle changes for
        # this account's own phone-number-id.
        if (meta.get('phone_number_id')
                and meta['phone_number_id'] != account.cloud_phone_number_id):
            return
        if field == 'messages':
            for status in value.get('statuses', []):
                account._apply_cloud_status(status)
            for message in value.get('messages', []):
                account._handle_inbound(normalize_meta_message(value, message))
        elif field == 'calls':
            # Inbound WhatsApp Business calls -> shared owa.call.log pipeline
            # (call log, ringing toast, missed-call auto-reply). Subscribe the
            # Meta app to the 'calls' webhook field for these to arrive.
            for call in value.get('calls', []):
                account._handle_cloud_call(call)
        elif field in ('message_template_status_update',
                       'message_template_quality_update',
                       'template_category_update'):
            # Cloud template management lands in Phase 3.
            if 'owa.cloud.template' in request.env:
                request.env['owa.cloud.template'].sudo()._apply_meta_event(
                    field, value)
