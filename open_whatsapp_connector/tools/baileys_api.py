import base64
import logging
import requests

from .baileys_exception import BaileysError

_logger = logging.getLogger(__name__)


class BaileysApi:
    """HTTP client for the WhatsApp Node.js sidecar service."""

    def __init__(self, wa_account):
        wa_account.ensure_one()
        self.account = wa_account
        self.base_url = (wa_account.sidecar_url or 'http://localhost:3100').rstrip('/')
        self.api_key = wa_account.sudo().sidecar_api_key or ''

    def _account_key(self):
        """Sidecar-facing account identifier, namespaced by db name so two
        databases sharing the same sidecar don't collide on Odoo's per-db
        auto-incrementing ``owa.account.id``. Persisted on disk by the sidecar
        as ``sessions/<db>_<id>/``."""
        return f"{self.account.env.cr.dbname}_{self.account.id}"

    def _request(self, method, path, **kwargs):
        headers = {
            'X-Api-Key': self.api_key,
            'Content-Type': 'application/json',
        }
        url = f"{self.base_url}{path}"
        if self.account.debug_logging:
            _logger.info("Gateway API %s %s", method, url)
        try:
            resp = requests.request(
                method, url, headers=headers, timeout=(5, 30), **kwargs
            )
            resp.raise_for_status()
            return resp.json()
        except requests.ConnectionError as e:
            raise BaileysError(
                failure_type='network',
                message=f"Cannot connect to sidecar at {self.base_url}: {e}"
            )
        except requests.Timeout as e:
            raise BaileysError(
                failure_type='network',
                message=f"Sidecar request timed out: {e}"
            )
        except requests.HTTPError as e:
            error_msg = ''
            try:
                error_msg = e.response.json().get('error', '')
            except Exception:
                error_msg = e.response.text[:200] if e.response else str(e)
            raise BaileysError(
                failure_type='network',
                message=f"Sidecar error ({e.response.status_code}): {error_msg}"
            )

    def create_session(self, odoo_base_url, webhook_secret, callback_url=None,
                       send_read_receipts=True):
        """Create a new gateway session (triggers QR code generation).

        :param send_read_receipts: when False, sidecar will skip
            ``sock.readMessages(...)`` so the recipient never sees blue ticks.
        """
        return self._request('POST', '/session/create', json={
            'account_id': self._account_key(),
            'odoo_base_url': odoo_base_url,
            'callback_url': callback_url,
            'webhook_secret': webhook_secret,
            'send_read_receipts': send_read_receipts,
        })

    def update_session_config(self, send_read_receipts=None):
        """Update mutable session config without re-creating the session."""
        body = {'account_id': self._account_key()}
        if send_read_receipts is not None:
            body['send_read_receipts'] = send_read_receipts
        return self._request('POST', f'/session/{self._account_key()}/config', json=body)

    def get_session_status(self):
        """Get current session status and QR code if pending."""
        return self._request('GET', f'/session/{self._account_key()}/status')

    def get_qr_code(self):
        """Get the QR code data URL for linking."""
        return self._request('GET', f'/session/{self._account_key()}/qr')

    def disconnect(self):
        """Disconnect the WhatsApp session."""
        return self._request('POST', f'/session/{self._account_key()}/disconnect')

    def logout(self):
        """Logout and delete auth state."""
        return self._request('POST', f'/session/{self._account_key()}/logout')

    def send_text(self, number, body, reply_to=None, mention_all=False, mentions=None):
        """Send a text message. Returns message_id.

        :param mention_all: True → group-only ``@everyone`` mention (silently
            ignored on direct chats by the gateway).
        :param mentions: optional list of JIDs to @-mention individually
            (e.g. ``['919999999999@s.whatsapp.net']``).
        """
        data = {
            'account_id': self._account_key(),
            'to': number,
            'body': body,
        }
        if reply_to:
            data['reply_to'] = reply_to
        if mention_all:
            data['mention_all'] = True
        if mentions:
            data['mentions'] = list(mentions)
        result = self._request('POST', '/send/text', json=data)
        return result.get('message_id', '')

    def send_media(self, number, media_data, mimetype, filename=None, caption=None,
                   ptt=False, gif_playback=False):
        """Send a media message (image, video, audio, document). Returns message_id.

        :param media_data: bytes or base64 string
        :param ptt: True → audio is sent as a push-to-talk voice note
        :param gif_playback: True → video plays as animated GIF in WhatsApp
        """
        if isinstance(media_data, bytes):
            media_base64 = base64.b64encode(media_data).decode()
        else:
            media_base64 = media_data
        data = {
            'account_id': self._account_key(),
            'to': number,
            'media_base64': media_base64,
            'mimetype': mimetype,
        }
        if filename:
            data['filename'] = filename
        if caption:
            data['caption'] = caption
        if ptt:
            data['ptt'] = True
        if gif_playback:
            data['gif_playback'] = True
        result = self._request('POST', '/send/media', json=data)
        return result.get('message_id', '')

    def send_album(self, number, items):
        """Send 2+ images/videos as a single album carousel.

        :param items: list of dicts with keys ``media_data`` (bytes or base64 str),
                      ``mimetype`` (image/* or video/*), and optional ``caption``.
        :returns: dict ``{'parent_message_id': ..., 'child_message_ids': [...]}``.
        """
        payload_items = []
        for item in items:
            data = item.get('media_data')
            if isinstance(data, bytes):
                media_base64 = base64.b64encode(data).decode()
            else:
                media_base64 = data
            entry = {
                'media_base64': media_base64,
                'mimetype': item['mimetype'],
            }
            if item.get('caption'):
                entry['caption'] = item['caption']
            payload_items.append(entry)
        return self._request('POST', '/send/album', json={
            'account_id': self._account_key(),
            'to': number,
            'items': payload_items,
        })

    def send_poll(self, number, name, options, selectable_count=1):
        """Send a poll message. Returns message_id.

        :param name: poll question
        :param options: list of option strings (1–12)
        :param selectable_count: how many options the recipient can pick (1=single-choice)
        """
        result = self._request('POST', '/send/poll', json={
            'account_id': self._account_key(),
            'to': number,
            'name': name,
            'options': options,
            'selectable_count': selectable_count,
        })
        return result.get('message_id', '')

    def send_contact(self, number, contacts):
        """Send a contact card (vCard). Returns message_id.

        :param contacts: list of dicts {'display_name': str, 'vcard': str}
        """
        result = self._request('POST', '/send/contact', json={
            'account_id': self._account_key(),
            'to': number,
            'contacts': contacts,
        })
        return result.get('message_id', '')

    def send_location(self, number, latitude, longitude, name=None, address=None):
        """Send a location message. Returns message_id."""
        data = {
            'account_id': self._account_key(),
            'to': number,
            'latitude': latitude,
            'longitude': longitude,
        }
        if name:
            data['name'] = name
        if address:
            data['address'] = address
        result = self._request('POST', '/send/location', json=data)
        return result.get('message_id', '')

    def send_reaction(self, chat_jid, message_id, emoji, from_me=False):
        """Send a reaction emoji to a message."""
        self._request('POST', '/send/reaction', json={
            'account_id': self._account_key(),
            'chat_jid': chat_jid,
            'message_id': message_id,
            'emoji': emoji,
            'from_me': from_me,
        })

    def send_buttons(self, number, body, buttons, header=None, footer=None):
        """Send a button message. Returns message_id.

        :param buttons: list of dicts with 'id' and 'text' keys (max 3)
        :param header: optional dict with 'type', 'text'/'media_base64'/'mimetype'
        :param footer: optional footer text string
        """
        data = {
            'account_id': self._account_key(),
            'to': number,
            'body': body,
            'buttons': buttons,
        }
        if header:
            data['header'] = header
        if footer:
            data['footer'] = footer
        result = self._request('POST', '/send/buttons', json=data)
        return result.get('message_id', '')

    def send_list(self, number, body, button_text, sections, footer=None):
        """Send a list message. Returns message_id.

        :param button_text: text on the button that opens the list
        :param sections: list of dicts with 'title' and 'rows' keys
        :param footer: optional footer text string
        """
        data = {
            'account_id': self._account_key(),
            'to': number,
            'body': body,
            'button_text': button_text,
            'sections': sections,
        }
        if footer:
            data['footer'] = footer
        result = self._request('POST', '/send/list', json=data)
        return result.get('message_id', '')

    def get_groups(self):
        """Get list of WhatsApp groups."""
        result = self._request('GET', f'/groups/{self._account_key()}')
        return result.get('groups', [])

    def health_check(self):
        """Check sidecar health."""
        return self._request('GET', '/health')

    # ── Phase C1: WhatsApp group participant administration ──────────────
    def group_participants_update(self, group_jid, action, jids):
        """Add / remove / promote / demote participants in a WhatsApp group.

        :param group_jid: full JID, e.g. ``120363xxx@g.us``
        :param action: ``add`` | ``remove`` | ``promote`` | ``demote``
        :param jids: list of phone numbers or full JIDs
        :returns: list of {jid, status} dicts (one per participant)
        """
        result = self._request(
            'POST',
            f'/session/{self._account_key()}/groups/{group_jid}/participants',
            json={'action': action, 'jids': jids},
        )
        return result.get('result', [])

    # ── Phase F — full group management ─────────────────────────────────
    INVITE_URL_PREFIX = 'https://chat.whatsapp.com/'

    @classmethod
    def normalize_invite_code(cls, value):
        """Strip ``https://chat.whatsapp.com/`` prefix from a user-pasted invite
        so the rest of the code can treat it as a bare WhatsApp invite code."""
        text = (value or '').strip()
        prefix_lower = cls.INVITE_URL_PREFIX.lower()
        if text.lower().startswith(prefix_lower):
            text = text[len(prefix_lower):]
        return text.split('/')[0].split('?')[0]

    def fetch_all_groups(self):
        """Return the full list of groups the connected account is in."""
        result = self._request(
            'GET', f'/session/{self._account_key()}/groups')
        return result.get('groups', [])

    def create_group(self, subject, participant_jids):
        """Create a new WhatsApp group. ``participant_jids`` may be raw phone
        strings or full ``<digits>@s.whatsapp.net`` JIDs; the sidecar
        normalises. Returns the freshly-created group's metadata dict."""
        return self._request(
            'POST', f'/session/{self._account_key()}/groups',
            json={'subject': (subject or '')[:100], 'participants': participant_jids},
        )

    def leave_group(self, group_jid):
        return self._request(
            'POST', f'/session/{self._account_key()}/groups/{group_jid}/leave')

    def update_group_subject(self, group_jid, subject):
        return self._request(
            'POST', f'/session/{self._account_key()}/groups/{group_jid}/subject',
            json={'subject': (subject or '')[:100]},
        )

    def update_group_description(self, group_jid, description):
        return self._request(
            'POST', f'/session/{self._account_key()}/groups/{group_jid}/description',
            json={'description': (description or '')[:512]},
        )

    def update_group_setting(self, group_jid, setting):
        """``setting`` ∈ {'announcement','not_announcement','locked','unlocked'}.
        ``announcement`` = admins-only posting; ``locked`` = admins-only edit."""
        return self._request(
            'POST', f'/session/{self._account_key()}/groups/{group_jid}/setting',
            json={'setting': setting},
        )

    def get_invite_code(self, group_jid):
        result = self._request(
            'GET', f'/session/{self._account_key()}/groups/{group_jid}/invite')
        return result.get('code') or ''

    def revoke_invite_code(self, group_jid):
        result = self._request(
            'POST', f'/session/{self._account_key()}/groups/{group_jid}/invite/revoke')
        return result.get('code') or ''

    def get_invite_info(self, code):
        cleaned = self.normalize_invite_code(code)
        return self._request(
            'GET', f'/session/{self._account_key()}/invites/{cleaned}')

    def accept_invite(self, code):
        cleaned = self.normalize_invite_code(code)
        result = self._request(
            'POST', f'/session/{self._account_key()}/invites/{cleaned}/accept')
        return result.get('jid') or ''

    # ── Phase G — group picture, forward, reactions, sticker, live loc,
    #             chat moderation, communities, newsletters, events, V4 ────

    def update_group_picture(self, group_jid, image_data):
        """Set or clear the group profile picture. ``image_data`` is a base64
        string (e.g. Odoo Binary field's RPC value), already-base64 bytes
        (e.g. ``record.image_1920``), or None / empty (clear the picture)."""
        if image_data is None or image_data == '':
            return self._request(
                'DELETE',
                f'/session/{self._account_key()}/groups/{group_jid}/picture',
            )
        # Odoo's fields.Binary / fields.Image return BASE64-ENCODED BYTES when
        # accessed on a record, NOT raw image bytes — re-encoding would
        # double-base64 and Sharp would read "FFD8…" as ASCII text and reject
        # the buffer with "unsupported image format". Decode to str directly.
        if isinstance(image_data, (bytes, bytearray)):
            image_b64 = bytes(image_data).decode('ascii')
        else:
            image_b64 = image_data
        return self._request(
            'POST',
            f'/session/{self._account_key()}/groups/{group_jid}/picture',
            json={'image_base64': image_b64},
        )

    def forward_message(self, from_jid, msg_id, to_jid):
        """Forward a previously-seen WhatsApp message from ``from_jid``/``msg_id``
        to ``to_jid``. The sidecar reconstructs the full message proto from its
        in-memory cache (populated on every send and inbound). Returns ``{message_id}``.
        Raises if the source isn't in cache (sidecar restarted, or message older
        than the cache TTL)."""
        return self._request(
            'POST', f'/session/{self._account_key()}/messages/forward',
            json={'from_jid': from_jid, 'msg_id': msg_id, 'to_jid': to_jid},
        )

    def send_reaction_v2(self, to_jid, target_message_id, emoji,
                         target_from_me=False, target_participant=None):
        """Send a reaction to ``target_message_id``. ``emoji`` empty string =
        unreact. ``target_participant`` is required when reacting to a
        message in a group chat that wasn't sent by the bot itself."""
        body = {
            'to': to_jid,
            'target_message_id': target_message_id,
            'emoji': emoji or '',
            'target_from_me': bool(target_from_me),
        }
        if target_participant:
            body['target_participant'] = target_participant
        return self._request(
            'POST', f'/session/{self._account_key()}/messages/react',
            json=body,
        )

    def send_sticker(self, to_jid, sticker_data, mimetype='image/webp'):
        """Send a WebP / animated WebP sticker to a chat. ``sticker_data`` is
        a base64 string OR already-base64 bytes (e.g. ``record.sticker_data``
        from an Odoo Binary field — those are base64 text, not raw bytes).
        Re-encoding bytes would double-base64 and the recipient would see a
        broken sticker tile."""
        if isinstance(sticker_data, (bytes, bytearray)):
            sticker_b64 = bytes(sticker_data).decode('ascii')
        else:
            sticker_b64 = sticker_data
        return self._request(
            'POST', f'/session/{self._account_key()}/messages/sticker',
            json={'to': to_jid, 'sticker_base64': sticker_b64, 'mimetype': mimetype},
        )

    def send_location(self, to_jid, latitude, longitude, name=None, address=None):
        """Send a static WhatsApp location pin. The previous send_live_location
        wrapper claimed live-location support but the gateway doesn't plumb the
        periodic position updates that real live-location requires; the
        existing /send/location route always sent static."""
        body = {
            'account_id': self._account_key(),
            'to': to_jid,
            'latitude': float(latitude),
            'longitude': float(longitude),
        }
        if name:
            body['name'] = name
        if address:
            body['address'] = address
        return self._request('POST', '/send/location', json=body)

    def send_event(self, to_jid, name, description, start_unix, location=None):
        """Send a WhatsApp Event message (RSVP-able). ``start_unix`` is epoch
        seconds. ``location`` is optional dict {name, degreesLatitude,
        degreesLongitude}."""
        body = {
            'to': to_jid,
            'name': name,
            'description': description or '',
            'start_unix': int(start_unix),
        }
        if location:
            body['location'] = location
        return self._request(
            'POST', f'/session/{self._account_key()}/messages/event',
            json=body,
        )

    # Phase G bug-fix: send_native_flow_single_select removed. The previous
    # wrapper called a sidecar method that silently produced a plain text
    # message instead of a Native Flow dropdown. The existing `list`
    # template type on owa.quick.reply covers the section/rows menu use-case.

    def chat_modify(self, target_jid, action, mute_end_timestamp=None):
        """Modify a chat's WhatsApp-side state. ``action`` ∈
        archive|unarchive|pin|unpin|mute|unmute. ``mute_end_timestamp`` is an
        epoch-millis number; default 8 h when muting."""
        body = {'action': action}
        if mute_end_timestamp:
            body['mute_end_timestamp'] = int(mute_end_timestamp)
        return self._request(
            'POST', f'/session/{self._account_key()}/chats/{target_jid}/modify',
            json=body,
        )

    # Communities ───────────────────────────────────────────────────────
    def fetch_all_communities(self):
        result = self._request(
            'GET', f'/session/{self._account_key()}/communities')
        return result.get('communities', [])

    def create_community(self, subject, body=''):
        return self._request(
            'POST', f'/session/{self._account_key()}/communities',
            json={'subject': (subject or '')[:100], 'body': body or ''},
        )

    def create_community_group(self, parent_community_jid, subject, participant_jids):
        return self._request(
            'POST',
            f'/session/{self._account_key()}/communities/{parent_community_jid}/groups',
            json={'subject': (subject or '')[:100], 'participants': participant_jids},
        )

    def leave_community(self, community_jid):
        return self._request(
            'POST', f'/session/{self._account_key()}/communities/{community_jid}/leave')

    def update_community_subject(self, community_jid, subject):
        return self._request(
            'POST', f'/session/{self._account_key()}/communities/{community_jid}/subject',
            json={'subject': (subject or '')[:100]},
        )

    def get_community_metadata(self, community_jid):
        return self._request(
            'GET', f'/session/{self._account_key()}/communities/{community_jid}')

    def get_community_linked_groups(self, community_jid):
        result = self._request(
            'GET', f'/session/{self._account_key()}/communities/{community_jid}/groups')
        return result.get('groups', [])

    # Newsletters / Channels ────────────────────────────────────────────
    def create_newsletter(self, name, description=''):
        return self._request(
            'POST', f'/session/{self._account_key()}/newsletters',
            json={'name': name, 'description': description or ''},
        )

    def follow_newsletter(self, newsletter_jid):
        return self._request(
            'POST', f'/session/{self._account_key()}/newsletters/{newsletter_jid}/follow')

    def unfollow_newsletter(self, newsletter_jid):
        return self._request(
            'POST', f'/session/{self._account_key()}/newsletters/{newsletter_jid}/unfollow')

    def mute_newsletter(self, newsletter_jid, mute=True):
        return self._request(
            'POST', f'/session/{self._account_key()}/newsletters/{newsletter_jid}/mute',
            json={'mute': bool(mute)},
        )

    def update_newsletter(self, newsletter_jid, name=None, description=None,
                          picture_data=None):
        body = {}
        if name is not None:
            body['name'] = name
        if description is not None:
            body['description'] = description
        if picture_data is not None:
            # Same Odoo-binary convention as update_group_picture: bytes from
            # a record field are already base64 text, NOT raw image bytes.
            if isinstance(picture_data, (bytes, bytearray)):
                body['picture_base64'] = bytes(picture_data).decode('ascii')
            else:
                body['picture_base64'] = picture_data
        return self._request(
            'POST',
            f'/session/{self._account_key()}/newsletters/{newsletter_jid}/update',
            json=body,
        )

    def get_newsletter_metadata(self, newsletter_jid):
        return self._request(
            'GET', f'/session/{self._account_key()}/newsletters/{newsletter_jid}')

    def get_newsletter_by_invite(self, code):
        """Resolve a ``chat.whatsapp.com/channel/<code>`` URL fragment to the
        newsletter's full metadata (including the JID needed for follow)."""
        return self._request(
            'GET', f'/session/{self._account_key()}/newsletter-invites/{code}')

    # V4 invite ─────────────────────────────────────────────────────────
    def accept_invite_v4(self, source_jid, invite_message):
        """Accept a group-invite-card embedded in a chat message."""
        return self._request(
            'POST', f'/session/{self._account_key()}/invites/v4/accept',
            json={'source_jid': source_jid, 'invite_message': invite_message},
        )

    def update_member_label(self, group_jid, label):
        """Set the bot's display label inside a WhatsApp group (≤30 chars).

        Lets each WhatsApp account project a friendly name (e.g. "Acme Support")
        in groups where the raw phone number would be unhelpful. The label is
        WhatsApp-side only — Odoo still uses ``partner.name`` everywhere.
        """
        return self._request(
            'POST',
            f'/session/{self._account_key()}/groups/{group_jid}/member-label',
            json={'label': (label or '')[:30]},
        )

    # ── Phase C2: blocklist management ───────────────────────────────────
    def block_contact(self, jid):
        """Block a WhatsApp contact at the WhatsApp level."""
        return self._request(
            'POST', f'/session/{self._account_key()}/contacts/{jid}/block')

    def unblock_contact(self, jid):
        """Remove a WhatsApp contact from the WhatsApp blocklist."""
        return self._request(
            'POST', f'/session/{self._account_key()}/contacts/{jid}/unblock')

    def fetch_whatsapp_blocklist(self):
        """Fetch the current WhatsApp blocklist for this account."""
        result = self._request('GET', f'/session/{self._account_key()}/blocklist')
        return result.get('jids', [])

    # ── Phase C3: business profile picture ───────────────────────────────
    def update_profile_picture(self, image_bytes):
        """Set the WhatsApp profile picture for this account."""
        b64 = base64.b64encode(image_bytes).decode('ascii') if isinstance(image_bytes, (bytes, bytearray)) else image_bytes
        return self._request(
            'POST',
            f'/session/{self._account_key()}/profile/picture',
            json={'image_base64': b64},
        )

    def remove_profile_picture(self):
        """Clear the WhatsApp profile picture for this account."""
        return self._request(
            'DELETE', f'/session/{self._account_key()}/profile/picture')

    # ── Phase B3: subscribe to contact(s) presence ────────────────────────
    def subscribe_presence(self, jids):
        """Tell the sidecar to start receiving online/typing/lastSeen
        updates for these JIDs. Pass a single JID string or a list.
        Idempotent server-side."""
        if isinstance(jids, str):
            payload = {'jid': jids}
        else:
            payload = {'jids': list(jids)}
        return self._request(
            'POST',
            f'/session/{self._account_key()}/presence/subscribe',
            json=payload,
        )

    # ── Phase C4: typing / presence indicator ────────────────────────────
    def send_presence_update(self, jid, state):
        """Send a presence indicator (``available``, ``unavailable``,
        ``composing``, ``recording``, ``paused``) to a specific chat."""
        return self._request(
            'POST',
            f'/session/{self._account_key()}/presence/{jid}',
            json={'state': state},
        )

    # ── Phase C5: star / unstar a message ────────────────────────────────
    def star_message(self, jid, msg_id, from_me, star=True):
        """Star or unstar a single WhatsApp message."""
        return self._request(
            'POST',
            f'/session/{self._account_key()}/messages/star',
            json={'jid': jid, 'msg_id': msg_id, 'from_me': from_me, 'star': star},
        )

    # ── Phase C6: WhatsApp call link ─────────────────────────────────────
    def create_call_link(self, kind='audio'):
        """Generate a shareable WhatsApp audio/video call link.

        :param kind: ``audio`` | ``video``
        :returns: dict with ``token`` and ``url`` keys
        """
        return self._request(
            'POST',
            f'/session/{self._account_key()}/call-link',
            json={'type': kind},
        )

    # ── Reject an incoming WhatsApp call ─────────────────────────────────
    def reject_call(self, call_id, call_from):
        """Reject an incoming WhatsApp call. Sends the gateway's reject IQ so the
        caller's phone stops ringing. Does not carry audio."""
        return self._request(
            'POST',
            f'/session/{self._account_key()}/calls/{call_id}/reject',
            json={'from': call_from},
        )

    # ── Phase D: pairing-code login (alternative to QR scan) ─────────────
    def request_pairing_code(self, phone):
        """Request an 8-character pairing code for headless login.

        :param phone: WhatsApp account phone number, digits only
        :returns: dict with ``code`` key
        """
        return self._request(
            'POST',
            f'/session/{self._account_key()}/pairing-code',
            json={'phone': phone},
        )
