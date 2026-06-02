import base64
import logging
from datetime import timedelta

from odoo import fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class OwaWebhook(http.Controller):

    @http.route('/open_whatsapp_connector/webhook/incoming', methods=['POST'],
                type='json', auth='public', csrf=False)
    def webhook_incoming(self, **kwargs):
        """Receive incoming WhatsApp messages from the WhatsApp sidecar."""
        # For type='json' controllers, Odoo unpacks jsonrpc params into kwargs
        account_id = kwargs.get('account_id')
        secret = kwargs.get('secret')
        messages = kwargs.get('messages', [])

        if not account_id or not secret:
            _logger.warning("Webhook missing account_id or secret")
            return {'status': 'error', 'message': 'Missing account_id or secret'}

        # Sidecar namespaces its session keys as `{dbname}_{id}` so two
        # databases sharing a sidecar can't collide. Extract the trailing
        # integer here.
        try:
            numeric_id = int(str(account_id).rsplit('_', 1)[-1])
        except (TypeError, ValueError):
            _logger.warning("Webhook account_id not parseable as int: %r", account_id)
            return {'status': 'error', 'message': 'Invalid account_id'}

        # Validate webhook secret AND that it belongs to the account the
        # caller claims to be — multi-account installs must not let one
        # account's secret be used to impersonate another's id.
        account = request.env['owa.account'].sudo().search([
            ('id', '=', numeric_id),
            ('webhook_secret', '=', secret),
        ], limit=1)
        if not account:
            _logger.warning("Invalid webhook secret for account %s", account_id)
            return {'status': 'error', 'message': 'Invalid secret'}

        errors = []
        for msg_data in messages:
            try:
                self._process_inbound_message(account, msg_data)
            except Exception as e:
                _logger.exception("Error processing inbound message")
                errors.append(str(e))

        if errors:
            return {'status': 'partial_error', 'errors': errors}
        return {'status': 'ok'}

    def _process_inbound_message(self, account, msg_data):
        """Process a single inbound message from the sidecar (QR transport).

        This builds the transport-neutral ``normalized`` dict — including the
        decoded inbound media attachments and the finished message body — and
        hands it to ``account._handle_inbound`` (shared with the Cloud API
        transport). Transport-specific pre-processing (inbound reactions, DM /
        group access policy, dedupe claim) stays here so the QR behaviour is
        byte-identical to before the refactor.
        """
        chat_type = msg_data.get('chat_type', 'direct')
        chat_jid = msg_data.get('chat_jid') or ''
        # Routing:
        #   - groups: use the group JID (`...@g.us`) so members' replies
        #     land in the SAME group discuss channel
        #   - DMs: use `from` (just the sender's digits) — chat_jid for DMs
        #     equals the sender's full JID (`...@s.whatsapp.net`) and
        #     passing it to the channel resolver would create a new channel
        #     with the literal JID as the name
        if chat_type == 'group' and chat_jid:
            from_number = chat_jid
        else:
            from_number = msg_data.get('from', '')
        sender_name = msg_data.get('sender_name', '')
        msg_type = msg_data.get('type', 'text')
        msg_id = msg_data.get('id', '')
        context_data = msg_data.get('context') or {}

        if not from_number:
            return

        # Inbound reaction: a contact reacted to one of our (or their) prior
        # messages. Update wa_reactions_json on the matching owa.message and
        # post a chatter notification on the linked Discuss channel. The
        # sidecar populates `from` with the participant JID for groups
        # (resolved from LID) and the chat JID for DMs.
        if msg_type == 'reaction':
            r = msg_data.get('reaction') or {}
            target_msg_uid = r.get('message_id')
            emoji = r.get('emoji') or ''
            if not target_msg_uid:
                return
            sender_jid = msg_data.get('from') or ''
            if sender_jid and '@' not in sender_jid:
                sender_jid = f"{sender_jid.lstrip('+')}@s.whatsapp.net"
            request.env['owa.message'].sudo()._apply_inbound_reaction(
                target_msg_uid, sender_jid, emoji,
            )
            return

        # Phase 2: explicit dedupe via owa.inbound.dedupe (covers worker races
        # the sidecar's in-memory dedupe can't catch). Claimed here (before
        # access-control) to preserve the legacy ordering; _handle_inbound is
        # therefore called with claim_dedupe=False.
        if msg_id and not request.env['owa.inbound.dedupe'].sudo().claim(msg_id, account.id):
            _logger.info("Skipping duplicate inbound msg_uid=%s (account=%s)", msg_id, account.id)
            return

        # Phase 5/6/7: access control (DM via dm_policy, group via group_policy).
        # We need a quick body preview for the pending-pair UI in case the DM
        # gets shunted to pairing approval; pull it from the typed payload.
        _preview = ''
        if msg_type == 'text' and msg_data.get('text'):
            _preview = (msg_data['text'].get('body') or '')[:200]
        if chat_type == 'direct' and not self._dm_allowed(
            account, from_number, sender_name=sender_name, msg_uid=msg_id, body=_preview,
        ):
            _logger.info(
                "Dropping inbound from %s (account=%s, dm_policy=%s)",
                from_number, account.id, account.dm_policy,
            )
            return
        if chat_type == 'group' and not self._group_allowed(account, from_number):
            _logger.info(
                "Dropping inbound group msg from %s (account=%s, group_policy=%s)",
                from_number, account.id, account.group_policy,
            )
            return

        # Build message body + attachments — Phase 2: unified placeholders,
        # fenced metadata, inbound media cap. The reply-context envelope and
        # author attribution happen in account._handle_inbound (shared).
        body = ''
        attachment_ids = []
        max_inbound_mb = account.media_max_mb or 50
        max_inbound_bytes = max_inbound_mb * 1024 * 1024

        def _media_placeholder(kind):
            # Friendly label rendered only when the attachment is unavailable
            # (oversize, missing base64, etc.). When the attachment IS present,
            # leave body empty — the chatter renders the file as a thumbnail
            # on its own and the placeholder is just noise. The previous
            # `<media:image>` form rendered as literal text in Discuss because
            # the angle brackets aren't a valid HTML tag.
            labels = {
                'image': '📷 Image',
                'video': '🎥 Video',
                'audio': '🎵 Audio',
                'document': '📄 Document',
                'sticker': '🏷️ Sticker',
            }
            return labels.get(kind, f'[{kind}]')

        def _save_media(kind, media_obj):
            """Decode base64 media, enforce size cap, save as attachment.
            Returns attachment id (or False if rejected)."""
            if not media_obj or not media_obj.get('base64'):
                return False
            b64 = media_obj['base64']
            # Estimate decoded size from base64 length (3/4 ratio)
            est_size = (len(b64) * 3) // 4
            if est_size > max_inbound_bytes:
                _logger.warning(
                    "Inbound %s media %.1f MB > cap %d MB (account=%s); dropping",
                    kind, est_size / 1024 / 1024, max_inbound_mb, account.id,
                )
                return False
            mimetype = media_obj.get('mimetype', 'application/octet-stream')
            filename = media_obj.get('filename', f'{kind}_{msg_id}')
            # Use the 'pending' res_model that message_post recognises in
            # `_process_attachments_for_post` — otherwise the webhook (which
            # runs as a public user, then .sudo()s into the channel) trips
            # the filter that strips any attachment_ids whose res_model isn't
            # one of the magic pending values, and the message ends up empty
            # which Discuss renders as "This message has been removed".
            return request.env['ir.attachment'].sudo().create({
                'name': filename,
                'datas': b64,
                'mimetype': mimetype,
                'res_model': 'mail.compose.message',
                'res_id': 0,
            }).id

        if msg_type == 'text' and msg_data.get('text'):
            body = msg_data['text'].get('body', '')

        elif msg_type == 'button_response':
            btn = msg_data.get('button_response', {})
            body = f"[Button] {btn.get('button_text', '')}".strip()
            if not body or body == '[Button]':
                body = msg_data.get('text', {}).get('body', '[Button response]')

        elif msg_type == 'list_response':
            lst = msg_data.get('list_response', {})
            body = f"[List] {lst.get('row_title', '')}".strip()
            if lst.get('row_description'):
                body += f" — {lst['row_description']}"
            if not body or body == '[List]':
                body = msg_data.get('text', {}).get('body', '[List response]')

        elif msg_type == 'location' and msg_data.get('location'):
            loc = msg_data['location']
            # Fenced metadata — keeps recipient body distinct from prompt-style text.
            lat = loc.get('latitude', 0)
            lng = loc.get('longitude', 0)
            details = (
                f"<details><summary>📍 Location shared</summary>"
                f"<div>Lat: {lat}, Lng: {lng}</div>"
            )
            if loc.get('name'):
                details += f"<div>Name: {loc['name']}</div>"
            if loc.get('address'):
                details += f"<div>Address: {loc['address']}</div>"
            details += "</details>"
            body = details

        elif msg_type == 'sticker' and msg_data.get('sticker'):
            att_id = _save_media('sticker', msg_data['sticker'])
            if att_id:
                attachment_ids.append(att_id)
                # Sticker is its own thumbnail — no body needed.
            else:
                body = f"{_media_placeholder('sticker')} <em>(content unavailable)</em>"

        elif msg_type == 'contacts' and msg_data.get('contacts'):
            contacts = msg_data['contacts']
            rows = ''
            for contact in contacts:
                display_name = contact.get('displayName', 'Unknown')
                vcard = contact.get('vcard', '')
                phone = ''
                for line in vcard.split('\n'):
                    if line.startswith('TEL'):
                        phone = line.split(':')[-1].strip()
                        break
                rows += f"<li>{display_name}{(' — ' + phone) if phone else ''}</li>"
            body = (
                f"<details><summary>📇 Contact card</summary>"
                f"<ul>{rows}</ul></details>"
            )

        # Handle media types (image, video, audio, document) — unified placeholder
        media_body = ''
        media_data = None
        media_kind = None
        if msg_type == 'image' and msg_data.get('image'):
            media_data = msg_data['image']
            media_body = media_data.get('caption', '')
            media_kind = 'image'
        elif msg_type == 'video' and msg_data.get('video'):
            media_data = msg_data['video']
            media_body = media_data.get('caption', '')
            media_kind = 'video'
        elif msg_type == 'audio' and msg_data.get('audio'):
            media_data = msg_data['audio']
            media_kind = 'audio'
        elif msg_type == 'document' and msg_data.get('document'):
            media_data = msg_data['document']
            media_kind = 'document'

        if media_kind:
            att_id = _save_media(media_kind, media_data)
            if att_id:
                attachment_ids.append(att_id)
                # When the media is saved successfully, only carry the caption
                # (if any). Don't fall back to a placeholder — the chatter
                # renders the attachment thumbnail by itself, and a text
                # placeholder underneath/instead of it is just noise.
                body = media_body or body or ''
            else:
                # Rejected (oversize) or empty — mark with placeholder so
                # the discuss thread shows that media arrived but couldn't
                # be stored.
                body = f"{_media_placeholder(media_kind)} <em>(content unavailable)</em>"

        if not body and not attachment_ids:
            # Sidecar declared a media type but didn't include the payload —
            # most commonly because the sidecar couldn't reach the WhatsApp
            # media CDN (mmg.whatsapp.net) within its 10s connect window.
            # Surface a clear note instead of the cryptic "[image message]".
            if msg_type in ('image', 'video', 'audio', 'document', 'sticker'):
                body = (f"{_media_placeholder(msg_type)} "
                        f"<em>(couldn't be downloaded — check sidecar network access "
                        f"to mmg.whatsapp.net)</em>")
            else:
                body = f'[{msg_type} message]'

        # Hand off to the transport-neutral pipeline (dedupe already claimed).
        normalized = {
            'from_number': from_number,
            'sender_name': sender_name,
            'msg_uid': msg_id,
            'type': msg_type,
            'body': body,
            'media': None,
            'attachment_ids': attachment_ids,
            'reply_to_wamid': context_data.get('message_id'),
            'timestamp': msg_data.get('timestamp'),
            'phone_number_id': None,
            'chat_type': chat_type,
            'participant': msg_data.get('participant') or '',
            'raw': msg_data,
        }
        account._handle_inbound(normalized, claim_dedupe=False)

    def _group_allowed(self, account, from_number):
        """Phase 6: group access policy. ``open`` allows all groups,
        ``disabled`` drops all, ``allowlist`` matches against
        account.group_allow_jids (one JID per line)."""
        policy = account.group_policy or 'open'
        if policy == 'open':
            return True
        if policy == 'disabled':
            return False
        # allowlist
        raw = account.group_allow_jids or ''
        allowed = {line.strip() for line in raw.splitlines() if line.strip()}
        # ``from_number`` for groups is the group JID-or-number
        return from_number in allowed or f"{from_number}@g.us" in allowed

    def _dm_allowed(self, account, from_number, sender_name=None, msg_uid=None, body=None):
        """Phase 5/7: return True if this DM should be processed under the
        account's dm_policy.

        - ``open``: always pass.
        - ``disabled``: always drop.
        - ``allowlist``: only allowlisted numbers pass.
        - ``pairing``: allowlisted numbers pass; unknown ones get a pending
          pair created (Phase 7) and are dropped this round.
        """
        policy = account.dm_policy or 'open'
        if policy == 'open':
            return True
        if policy == 'disabled':
            return False
        if request.env['owa.allowlist.entry'].sudo().is_allowed(account.id, from_number):
            return True
        if policy == 'pairing':
            request.env['owa.pending.pair'].sudo().request_pair(
                account, from_number,
                sender_name=sender_name, msg_uid=msg_uid, body=body,
            )
        return False

    @http.route('/open_whatsapp_connector/webhook/call', methods=['POST'],
                type='json', auth='public', csrf=False)
    def webhook_call(self, **kwargs):
        """Phase 21: receive incoming WhatsApp call events from the
        WhatsApp sidecar (`sock.ev.on('call')`).

        Payload shape:
            { "secret": "<webhook_secret>",
              "calls": [
                  {"id": "<call_id>", "from": "<jid>",
                   "status": "offer"|"ringing"|"timeout"|"reject"|"accept",
                   "isVideo": <bool>, "isGroup": <bool>, "date": <epoch_ms>}
              ] }

        The sidecar fires this once per status transition. We persist
        each as a row in owa.call.log; the model is idempotent on
        (account, call_id) so retries are safe."""
        secret = kwargs.get('secret')
        calls = kwargs.get('calls', [])

        if not secret:
            return {'status': 'error', 'message': 'Missing secret'}

        account = request.env['owa.account'].sudo().search([
            ('webhook_secret', '=', secret),
        ], limit=1)
        if not account:
            _logger.warning("webhook_call: invalid secret")
            return {'status': 'error', 'message': 'Invalid secret'}

        CallLog = request.env['owa.call.log'].sudo()
        errors = []
        for call_payload in calls:
            try:
                CallLog._record_call_event(account, call_payload)
            except Exception as e:  # pragma: no cover -- per-event safety
                _logger.exception("webhook_call: error processing call event")
                errors.append(str(e))

        if errors:
            return {'status': 'partial_error', 'errors': errors}
        return {'status': 'ok'}

    # ── Phase B1: WhatsApp group metadata changes ────────────────────────
    @http.route('/open_whatsapp_connector/webhook/group_meta', methods=['POST'],
                type='json', auth='public', csrf=False)
    def webhook_group_meta(self, **kwargs):
        """Receive groups.upsert / groups.update events from the sidecar so
        Discuss WhatsApp group channels show live names/descriptions."""
        secret = kwargs.get('secret')
        if not secret:
            return {'status': 'error', 'message': 'Missing secret'}
        account = request.env['owa.account'].sudo().search(
            [('webhook_secret', '=', secret)], limit=1)
        if not account:
            return {'status': 'error', 'message': 'Invalid secret'}
        kind = kwargs.get('kind') or 'update'
        group = kwargs.get('group') or {}
        jid = group.get('id')
        if not jid:
            return {'status': 'error', 'message': 'Missing group id'}
        try:
            request.env['owa.group.session'].sudo()._record_group_meta(
                account, kind, group)
        except Exception:  # pragma: no cover -- robust intake
            _logger.exception("webhook_group_meta: failed for jid=%s", jid)
            return {'status': 'error'}
        return {'status': 'ok'}

    # ── Phase B2: WhatsApp group participants change ─────────────────────
    @http.route('/open_whatsapp_connector/webhook/group_participants', methods=['POST'],
                type='json', auth='public', csrf=False)
    def webhook_group_participants(self, **kwargs):
        """Receive group-participants.update events. Posts a chatter line on
        the group's discuss.channel and persists an audit row."""
        secret = kwargs.get('secret')
        if not secret:
            return {'status': 'error', 'message': 'Missing secret'}
        account = request.env['owa.account'].sudo().search(
            [('webhook_secret', '=', secret)], limit=1)
        if not account:
            return {'status': 'error', 'message': 'Invalid secret'}
        try:
            request.env['owa.group.participant.event'].sudo()._record_event(
                account,
                group_jid=kwargs.get('group_jid'),
                action=kwargs.get('action'),
                participants=kwargs.get('participants') or [],
                author=kwargs.get('author'),
            )
        except Exception:  # pragma: no cover
            _logger.exception("webhook_group_participants: failed")
            return {'status': 'error'}
        return {'status': 'ok'}

    # ── Phase B3: WhatsApp presence (online / typing) ─────────────────────
    @http.route('/open_whatsapp_connector/webhook/presence', methods=['POST'],
                type='json', auth='public', csrf=False)
    def webhook_presence(self, **kwargs):
        """Receive presence.update events. Surfaces 'is typing' / 'online' on
        the linked Discuss WhatsApp channel via the bus, but only when the
        channel is actively open in a user's browser (rate-limited)."""
        secret = kwargs.get('secret')
        if not secret:
            return {'status': 'error', 'message': 'Missing secret'}
        account = request.env['owa.account'].sudo().search(
            [('webhook_secret', '=', secret)], limit=1)
        if not account:
            return {'status': 'error', 'message': 'Invalid secret'}
        try:
            request.env['owa.account'].sudo()._handle_presence_update(
                account,
                chat_jid=kwargs.get('chat_jid'),
                presences=kwargs.get('presences') or [],
            )
        except Exception:  # pragma: no cover
            _logger.exception("webhook_presence: failed")
            return {'status': 'error'}
        return {'status': 'ok'}

    @http.route('/open_whatsapp_connector/webhook/status', methods=['POST'],
                type='json', auth='public', csrf=False)
    def webhook_status(self, **kwargs):
        """Receive delivery status updates from the WhatsApp sidecar."""
        secret = kwargs.get('secret')
        statuses = kwargs.get('statuses', [])

        if not secret:
            return {'status': 'error', 'message': 'Missing secret'}

        account = request.env['owa.account'].sudo().search([
            ('webhook_secret', '=', secret),
        ], limit=1)
        if not account:
            return {'status': 'error', 'message': 'Invalid secret'}

        WaMessage = request.env['owa.message'].sudo()
        for status_data in statuses:
            msg_uid = status_data.get('id')
            status = status_data.get('status')
            if msg_uid and status:
                WaMessage._process_status_update(msg_uid, status)

        return {'status': 'ok'}

    @http.route('/open_whatsapp_connector/webhook/connection', methods=['POST'],
                type='json', auth='public', csrf=False)
    def webhook_connection(self, **kwargs):
        """Push-based connection-state updates from the sidecar.

        Fired by sock.ev.on('connection.update') after every transition so
        the Odoo UI no longer has to wait up to 5 min for _cron_heartbeat
        to poll. Mirrors the auth/lookup pattern of webhook_status.
        """
        secret = kwargs.get('secret')
        state = kwargs.get('state')
        if not secret or not state:
            return {'status': 'error', 'message': 'Missing secret or state'}
        account = request.env['owa.account'].sudo().search(
            [('webhook_secret', '=', secret)], limit=1)
        if not account:
            _logger.warning("webhook_connection: invalid secret")
            return {'status': 'error', 'message': 'Invalid secret'}
        valid = {'disconnected', 'qr_pending', 'connecting',
                 'connected', 'logged_out'}
        if state not in valid:
            _logger.warning("webhook_connection: unknown state %r", state)
            return {'status': 'error', 'message': 'Invalid state'}
        vals = {
            'session_state': state,
            'last_seen_dt': fields.Datetime.now(),
            'is_listening': state == 'connected',
        }
        if 'qr_base64' in kwargs:
            vals['qr_code_base64'] = kwargs.get('qr_base64') or False
        elif state in ('connected', 'logged_out', 'disconnected'):
            vals['qr_code_base64'] = False
        phone = kwargs.get('phone_number')
        if phone and state == 'connected':
            vals['phone_number'] = phone
        try:
            account.write(vals)
        except Exception:
            _logger.exception("webhook_connection: write failed for %s",
                              account.id)
            return {'status': 'error', 'message': 'Write failed'}
        try:
            Bus = request.env['bus.bus'].sudo()
            payload = {
                'account_id': account.id,
                'session_state': state,
                'qr_code_base64': vals.get('qr_code_base64') or False,
                'phone_number': account.phone_number or '',
                'last_error': kwargs.get('last_error') or '',
            }
            for user in account.notify_user_ids:
                partner = user.partner_id
                if partner:
                    Bus._sendone(
                        partner,
                        'open_whatsapp_connector/account_updated',
                        payload,
                    )
        except Exception:
            _logger.exception(
                "webhook_connection: bus push failed for account %s",
                account.id,
            )
        return {'status': 'ok'}
