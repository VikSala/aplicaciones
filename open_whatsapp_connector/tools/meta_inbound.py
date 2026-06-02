"""Pure conversion of a Meta Cloud webhook message into the connector's
transport-neutral inbound dict consumed by owa.account._handle_inbound.

No Odoo / ORM imports — fully unit-testable on its own.
"""

_MEDIA_TYPES = ('image', 'video', 'audio', 'document', 'sticker')


def normalize_meta_message(value, message):
    """Convert one Meta ``changes.value`` + one ``messages[]`` entry into the
    normalized inbound dict shape shared by every transport.

    Returns a dict with keys:
      from_number, sender_name, msg_uid, type, body, media,
      reply_to_wamid, timestamp, phone_number_id, raw
    """
    contacts = value.get('contacts') or [{}]
    profile = contacts[0].get('profile') or {}
    mtype = message.get('type')
    body = ''
    media = None
    if mtype == 'text':
        body = (message.get('text') or {}).get('body', '')
    elif mtype in _MEDIA_TYPES:
        m = message.get(mtype) or {}
        media = {'id': m.get('id'), 'mime': m.get('mime_type'),
                 'filename': m.get('filename'), 'caption': m.get('caption')}
        body = m.get('caption') or ''
    elif mtype == 'interactive':
        inter = message.get('interactive') or {}
        sub = inter.get(inter.get('type'), {})
        body = sub.get('title') or sub.get('id') or ''
    elif mtype == 'button':                       # template quick-reply echo
        body = (message.get('button') or {}).get('text', '')
    elif mtype == 'reaction':
        body = (message.get('reaction') or {}).get('emoji', '')
    elif mtype == 'location':
        loc = message.get('location') or {}
        body = loc.get('name') or f"{loc.get('latitude')},{loc.get('longitude')}"
    ctx = message.get('context') or {}
    return {
        'from_number': message.get('from'),
        'sender_name': profile.get('name'),
        'msg_uid': message.get('id'),
        'type': mtype,
        'body': body,
        'media': media,
        'reply_to_wamid': ctx.get('id'),
        'timestamp': message.get('timestamp'),
        'phone_number_id': (value.get('metadata') or {}).get('phone_number_id'),
        'raw': message,
    }


# Meta Calling-API ``event`` -> the raw status vocabulary owa.call.log's
# _RAW_TO_STATE understands (offer/ringing/timeout/reject/accept). The Cloud
# API only emits ``connect`` (call being set up = ringing) and ``terminate``
# (call ended). Since we never answer (voice-only, no WebRTC media), a
# terminate is treated as 'timeout' -> the model maps that to 'missed' so the
# missed-call auto-reply fires. Both 'ringing' and 'timeout' are themselves
# keys in _RAW_TO_STATE, so the value passes through cleanly.
_META_CALL_EVENT_TO_STATUS = {
    'connect': 'ringing',
    'terminate': 'timeout',
}


def normalize_meta_call(call):
    """Convert one Meta ``calls[]`` entry into the transport-neutral payload
    dict that ``owa.call.log._record_call_event`` consumes (the same shape the
    Baileys/QR sidecar produces): ``id``, ``from``, ``chat_id``, ``status``,
    ``isVideo``, ``isGroup`` — plus ``event`` / ``direction`` for callers that
    branch on them.

    Meta gives a bare wa_id (digits) for ``from``; ``_record_call_event``
    needs a non-empty JID-like ``from`` and derives the phone from it, so we
    synthesise ``<digits>@s.whatsapp.net``. The Calling API is voice-only with
    no group-call concept, so ``isVideo``/``isGroup`` are always False.

    Returns None when the call dict lacks the mandatory id or from.
    """
    if not isinstance(call, dict):
        return None
    call_id = call.get('id') or call.get('call_id')
    digits = ''.join(c for c in (call.get('from') or '') if c.isdigit())
    if not call_id or not digits:
        return None
    event = (call.get('event') or '').lower()
    return {
        'id': call_id,
        'from': '%s@s.whatsapp.net' % digits,
        'chat_id': '',
        'status': _META_CALL_EVENT_TO_STATUS.get(event, 'ringing'),
        'isVideo': False,
        'isGroup': False,
        'event': event,
        'direction': (call.get('direction') or '').upper(),
    }
