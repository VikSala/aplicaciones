import base64
import logging

from datetime import timedelta
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.addons.mail.tools.discuss import Store
from odoo.addons.open_whatsapp_connector.tools.baileys_api import BaileysApi
from odoo.addons.open_whatsapp_connector.tools.baileys_exception import BaileysError
from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format
from odoo.tools import groupby, html2plaintext

_logger = logging.getLogger(__name__)


class OwaMessage(models.Model):
    _name = 'owa.message'
    _description = 'Open WhatsApp Connector Message'
    _order = 'id desc'
    _rec_name = 'mobile_number'

    # Phase 25E: per-message reactions JSON — agent-applied reactions
    # are stored as `{ 'partner_jid': '👍' }` so we can show counts and
    # support clearing.
    wa_reactions_json = fields.Text(
        string="Reactions (JSON)", default='{}',
        help="JSON map of partner JID → emoji.")

    _SUPPORTED_ATTACHMENT_TYPE = {
        'audio': ('audio/aac', 'audio/mp4', 'audio/mpeg', 'audio/amr', 'audio/ogg',
                  'audio/ogg; codecs=opus', 'audio/webm'),
        'document': (
            'text/plain', 'application/pdf',
            'application/vnd.ms-powerpoint', 'application/msword',
            'application/vnd.ms-excel',
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        ),
        'image': ('image/jpeg', 'image/png', 'image/webp', 'image/gif'),
        'video': ('video/mp4', 'video/3gpp'),
    }
    _ACTIVE_THRESHOLD_DAYS = 15

    mobile_number = fields.Char(string="Sent To")
    mobile_number_formatted = fields.Char(
        string="Mobile Number Formatted",
        compute='_compute_mobile_number_formatted', readonly=False, store=True)
    message_type = fields.Selection([
        ('outbound', 'Outbound'),
        ('inbound', 'Inbound'),
    ], string="Message Type", default='outbound')
    state = fields.Selection([
        ('outgoing', 'In Queue'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('read', 'Read'),
        ('replied', 'Replied'),
        ('received', 'Received'),
        ('error', 'Failed'),
        ('bounced', 'Bounced'),
        ('cancel', 'Cancelled'),
    ], string="State", default='outgoing')
    failure_type = fields.Selection([
        ('account', 'Account Error'),
        ('blacklisted', 'Blacklisted Phone Number'),
        ('network', 'Network Error'),
        ('phone_invalid', 'Wrong Number Format'),
        ('unknown', 'Unknown Error'),
        ('recoverable', 'Identified Error'),
        ('unrecoverable', 'Other Technical Error'),
    ])
    failure_reason = fields.Char(string="Failure Reason")
    msg_uid = fields.Char(string="WhatsApp Message ID", index=True)
    # Cloud API correlation id (Meta `wamid...`). Mirrors msg_uid for cloud
    # sends; used by owa.account._apply_cloud_status to match status receipts.
    wa_message_uid = fields.Char(
        string="Cloud Message UID", index=True, copy=False,
        help="Provider message id (Meta wamid) for the Official Cloud API "
             "transport; used to correlate delivery/read/failed receipts.")
    error_message = fields.Char(
        string="Error Message", copy=False,
        help="Last transport error reported for this message (e.g. a Meta "
             "Cloud API failure title).")
    sender_jid = fields.Char(
        string="Sender JID", index='btree_not_null',
        help="For inbound GROUP messages, the participant JID of the original "
             "sender (e.g. 91xxxx@s.whatsapp.net). Required to react to a "
             "message sent by another group member.")
    wa_account_id = fields.Many2one(
        comodel_name='owa.account', string="WhatsApp Account",
        index=True, ondelete='set null')
    mail_message_id = fields.Many2one(
        comodel_name='mail.message', string="Mail Message", index=True)
    body = fields.Html(related='mail_message_id.body', string="Body")
    whatsapp_partner_id = fields.Many2one(
        'res.partner', string="WhatsApp Partner",
        index='btree_not_null', ondelete='set null',
        help="Resolved partner for this message. Mirrors discuss.channel.whatsapp_partner_id "
             "for fast partner-scoped queries (Customer-360 timeline, dashboard groupings).")
    parent_id = fields.Many2one(
        'owa.message', string="Response To",
        index='btree_not_null', ondelete='set null')
    quick_reply_id = fields.Many2one(
        'owa.quick.reply', string="Quick Reply")
    campaign_id = fields.Many2one(
        'owa.campaign', string="Campaign",
        index='btree_not_null', ondelete='set null')
    scheduled_date = fields.Datetime(string="Scheduled Date",
        help="If set, message will be sent at this date/time. Leave empty for immediate sending.")
    # Phase 11: per-message reply-quoting override copied from the rule that
    # produced the message. When set it wins over wa_account_id.reply_to_mode.
    reply_to_mode_override = fields.Selection([
        ('off', 'Off (never quote)'),
        ('first', 'Quote first chunk only'),
        ('all', 'Quote every chunk'),
    ], string="Reply quoting (override)")

    @api.depends('mobile_number')
    def _compute_mobile_number_formatted(self):
        for msg in self:
            if msg.mobile_number:
                # Group/community/newsletter JIDs (e.g. `+120363...@g.us`,
                # `@newsletter`, `@broadcast`) must NOT pass through phone
                # validation — phonenumbers happily reinterprets the leading
                # digits as a US number and drops the `@g.us` suffix, which
                # would route the outbound to a non-existent personal number
                # and surface as separate 1-on-1 messages on WhatsApp.
                if '@' in msg.mobile_number:
                    msg.mobile_number_formatted = msg.mobile_number.lstrip('+')
                else:
                    msg.mobile_number_formatted = wa_phone_format(
                        self.env, msg.mobile_number
                    ) or msg.mobile_number
            else:
                msg.mobile_number_formatted = False

    # ------------------------------------------------------------------
    # SEND
    # ------------------------------------------------------------------

    def _send_message(self):
        """Send message(s) via the WhatsApp sidecar."""
        for message in self:
            message._send_single_message()

    def _send_single_message(self):
        """Send a single message via the WhatsApp sidecar."""
        self.ensure_one()
        if not self.wa_account_id or self.wa_account_id.session_state != 'connected':
            self._handle_error('account', _("WhatsApp account is not connected"))
            return

        # Check blacklist
        number = self.mobile_number_formatted or self.mobile_number
        if self.env['owa.blacklist'].sudo().is_blacklisted(number):
            self._handle_error('blacklisted', _("Phone number is blacklisted"))
            return

        api_client = BaileysApi(self.wa_account_id)
        if not number:
            self._handle_error('phone_invalid', _("No phone number specified"))
            return

        # Strip + prefix for sidecar
        number = number.lstrip('+')
        account = self.wa_account_id

        try:
            body_text = html2plaintext(self.body) if self.body else ''
            attachments = (
                self.mail_message_id.attachment_ids
                if self.mail_message_id
                else self.env['ir.attachment']
            )
            msg_uid = ''

            # ── Official Cloud API transport ──────────────────────────────
            # Text (P1) + media (P2) + 24h customer-service window (P2).
            # Approved-template sends (P3) come in via owa.cloud.template
            # which flags the message with context skip_cloud_window so this
            # branch's window guard is bypassed (templates are the escape
            # hatch for messaging outside the 24h window).
            if account.connection_type == 'cloud':
                msg_uid = self._send_cloud_message(
                    account, number, body_text, attachments)
                return

            # Check if this message uses an interactive template
            template = self.quick_reply_id
            if template and template.template_type in ('button', 'list'):
                msg_uid = self._send_interactive_template(api_client, number, template)
            elif attachments:
                msg_uid = self._send_attachments(
                    api_client, number, attachments, body_text, account,
                )
            elif body_text:
                msg_uid = self._send_chunked_text(api_client, number, body_text, account)
            else:
                self._handle_error('unknown', _("Empty message"))
                return

            self.write({
                'state': 'sent',
                'msg_uid': msg_uid,
                'failure_type': False,
                'failure_reason': False,
            })
            # Notify frontend of status change
            self._notify_status_update()
            # Phase 3: clear our ack (👀) on the message we just replied to.
            self._maybe_clear_ack_reaction(api_client, number, account)

        except BaileysError as e:
            self._handle_error(e.failure_type, e.error_message)
            self._maybe_apply_throttle_backoff(e)

    # ── Official Cloud API send path (text + media + 24h window) ─────────
    @staticmethod
    def _cloud_media_type(mimetype):
        """Map an attachment mimetype to the Meta media object key
        (image / video / audio / document)."""
        mt = (mimetype or '').lower()
        if mt.startswith('image/'):
            return 'image'
        if mt.startswith('video/'):
            return 'video'
        if mt.startswith('audio/'):
            return 'audio'
        return 'document'

    def _send_cloud_message(self, account, number, body_text, attachments):
        """Send a queued message over the Official Cloud API transport.

        Enforces Meta's 24h customer-service window for free-form (non-
        template) sends, uploads each attachment and dispatches it as a media
        message, and otherwise sends the body as text. Returns the last
        provider ``wamid`` and writes state/uid/error onto self.
        """
        self.ensure_one()
        from odoo.addons.open_whatsapp_connector.tools.cloud_api import (
            CloudApiError)

        # 24h window guard. Template sends bypass it via the context flag set
        # by owa.cloud.template.action_send (Task 18).
        is_template = bool(self.env.context.get('skip_cloud_window'))
        if not is_template and not account._cloud_within_window(number):
            reason = _(
                "Outside the 24h customer window — send an approved template.")
            self.write({
                'state': 'error',
                'failure_type': 'recoverable',
                'failure_reason': reason,
                'error_message': reason,
            })
            _logger.info(
                "Cloud send blocked (outside 24h window) for %s on account %s",
                number, account.id)
            self._notify_campaign_update()
            return ''

        if not body_text and not attachments:
            self._handle_error('unknown', _("Empty message"))
            return ''

        msg_uid = ''
        try:
            if attachments:
                api = account._get_cloud_api()
                for idx, att in enumerate(attachments):
                    raw = base64.b64decode(att.datas) if att.datas else b''
                    media_type = self._cloud_media_type(att.mimetype)
                    media_id = api.upload_media(
                        raw, att.mimetype or 'application/octet-stream',
                        att.name or 'file')
                    # Caption rides on the first attachment only (Meta only
                    # honours captions on image/video/document).
                    caption = body_text if idx == 0 else None
                    msg_uid = account._dispatch_send(
                        'media', to=number, media_type=media_type,
                        media_id=media_id, caption=caption,
                        filename=att.name or None)
            else:
                msg_uid = account._dispatch_send(
                    'text', to=number, body=body_text)
        except Exception as e:
            reason = getattr(e, 'message', None) or str(e)
            self._handle_error('recoverable', reason)
            self.write({'error_message': reason})
            if isinstance(e, CloudApiError) and e.is_reengagement_window:
                self.write({'failure_reason': _(
                    "Outside the 24h customer window — send an approved "
                    "template instead. (%s)") % reason})
            return ''

        self.write({
            'state': 'sent',
            'msg_uid': msg_uid,
            'wa_message_uid': msg_uid,
            'failure_type': False,
            'failure_reason': False,
            'error_message': False,
        })
        self._notify_status_update()
        return msg_uid

    def _maybe_apply_throttle_backoff(self, error):
        """If a send failed because WhatsApp rate-limited us, set a backoff
        window on the account so _send_cron defers further dispatch. This is
        the "automatic backoff on throttle responses" behaviour — previously
        throttle_backoff_until was read by the cron but never written by
        anything. (#throttle)"""
        msg = (getattr(error, 'error_message', '') or '').lower()
        ftype = getattr(error, 'failure_type', '') or ''
        is_throttle = ftype == 'rate_limited' or any(
            tok in msg for tok in (
                'rate-limit', 'rate limit', 'ratelimit', '429',
                'too many', 'overlimit', 'throttl', 'try again later',
            )
        )
        if not is_throttle or not self.wa_account_id:
            return
        until = fields.Datetime.now() + timedelta(minutes=15)
        acct = self.wa_account_id.sudo()
        # Extend, never shorten, an existing backoff window.
        if not acct.throttle_backoff_until or acct.throttle_backoff_until < until:
            acct.throttle_backoff_until = until
            _logger.warning(
                "owa: throttle backoff engaged on account %s until %s",
                acct.id, until)

    # ── Phase 1: outbound payload helpers ────────────────────────────────

    def _send_chunked_text(self, api_client, number, body_text, account):
        """Send text in chunks if longer than account.text_chunk_limit.
        Reply-quoting policy is governed by account.reply_to_mode:
        'off' / 'first' / 'all'. Returns the last msg_uid sent."""
        self.ensure_one()
        # Phase 4: self-chat prefix
        if account.self_chat_mode and self.message_type == 'outbound':
            prefix = f"[{account.name or 'bot'}] "
            if not body_text.startswith(prefix):
                body_text = prefix + body_text
        chunks = self._chunk_text(
            body_text,
            account.text_chunk_limit or 4000,
            account.chunk_mode or 'newline',
        )
        reply_to = self.parent_id.msg_uid if self.parent_id else None
        mode = self.reply_to_mode_override or account.reply_to_mode or 'first'
        # @all / @everyone: a GROUP message whose text contains the @all (or
        # @everyone) token fires a group-wide mention via the sidecar, which
        # expands it to every participant JID. Fired only on the first chunk so
        # members are pinged once. (#album)
        import re
        mention_all = bool(
            number and '@g.us' in number
            and re.search(r'(?:^|\s)@(?:all|everyone)\b', body_text or '', re.I)
        )
        last_uid = ''
        for idx, chunk in enumerate(chunks):
            include_reply_to = bool(reply_to) and (
                mode == 'all'
                or (mode == 'first' and idx == 0)
            )
            last_uid = api_client.send_text(
                number, chunk,
                reply_to=reply_to if include_reply_to else None,
                mention_all=mention_all and idx == 0,
            )
        return last_uid

    @staticmethod
    def _chunk_text(text, limit, mode):
        """Split text into chunks no longer than `limit` chars.

        ``mode='newline'`` prefers paragraph (blank-line) boundaries, then
        single newlines, then falls back to length splitting. ``mode='length'``
        is a hard split at every `limit` characters.
        """
        if not text or len(text) <= limit:
            return [text] if text else ['']
        if mode == 'length':
            return [text[i:i + limit] for i in range(0, len(text), limit)]
        # newline mode
        chunks, buf = [], ''
        # First pass: paragraphs (split on blank lines)
        for para in text.split('\n\n'):
            if not para:
                continue
            piece = (buf + '\n\n' + para) if buf else para
            if len(piece) <= limit:
                buf = piece
                continue
            if buf:
                chunks.append(buf)
                buf = ''
            # Paragraph alone might still exceed limit — fall back to lines
            if len(para) <= limit:
                buf = para
                continue
            for line in para.split('\n'):
                piece2 = (buf + '\n' + line) if buf else line
                if len(piece2) <= limit:
                    buf = piece2
                    continue
                if buf:
                    chunks.append(buf)
                    buf = ''
                if len(line) <= limit:
                    buf = line
                    continue
                # Hard split very long single line
                for i in range(0, len(line), limit):
                    chunks.append(line[i:i + limit])
                buf = ''
        if buf:
            chunks.append(buf)
        return [c for c in chunks if c]

    def _send_attachments(self, api_client, number, attachments, body_text, account):
        """Dispatch a set of attachments. When 2+ items are images/videos we
        bundle them as one WhatsApp album (single carousel card on the
        recipient's side) instead of N separate media messages. Audio and
        document attachments always go individually. Returns the last msg_uid
        sent so the caller can store it on owa.message."""
        self.ensure_one()
        IMAGE_VIDEO = ('image/', 'video/')
        media_items = attachments.filtered(
            lambda a: (a.mimetype or '').startswith(IMAGE_VIDEO)
            and not (a.mimetype == 'image/gif' or (a.name or '').lower().endswith('.gif'))
        )
        rest = attachments - media_items

        msg_uid = ''
        used_album = False
        if len(media_items) >= 2:
            try:
                items_payload = []
                for idx, attachment in enumerate(media_items):
                    raw = base64.b64decode(attachment.datas) if attachment.datas else b''
                    size_mb = len(raw) / (1024 * 1024) if raw else 0
                    max_mb = account.media_max_mb or 50
                    mimetype = attachment.mimetype or 'application/octet-stream'
                    if (size_mb > max_mb
                            and mimetype.startswith('image/')):
                        try:
                            raw = self._optimize_image(raw, max_mb)
                            size_mb = len(raw) / (1024 * 1024)
                        except Exception:
                            _logger.exception(
                                "Image resize failed for album attachment %s",
                                attachment.id,
                            )
                    if size_mb > max_mb:
                        # Oversized item disqualifies the album path; fall
                        # back to per-attachment send which can substitute a
                        # text placeholder for the offending item.
                        raise ValueError("oversize_album_item")
                    items_payload.append({
                        'media_data': raw,
                        'mimetype': mimetype,
                        'caption': body_text if idx == 0 else None,
                    })
                result = api_client.send_album(number, items_payload)
                child_ids = result.get('child_message_ids') or []
                msg_uid = child_ids[-1] if child_ids else (
                    result.get('parent_message_id') or ''
                )
                used_album = True
            except Exception as exc:
                _logger.warning(
                    "Album send failed (%s); falling back to per-attachment send",
                    exc,
                )

        if not used_album:
            for idx, attachment in enumerate(attachments):
                caption = body_text if idx == 0 else None
                msg_uid = self._send_one_attachment(
                    api_client, number, attachment, caption, account,
                )
            return msg_uid

        for attachment in rest:
            msg_uid = self._send_one_attachment(
                api_client, number, attachment, None, account,
            )
        return msg_uid

    def _send_one_attachment(self, api_client, number, attachment, caption, account):
        """Send a single attachment with size-cap, image-resize, PTT, GIF flags.
        On a per-attachment failure, falls back to sending a text placeholder
        so the rest of the message doesn't silently drop."""
        self.ensure_one()
        mimetype = attachment.mimetype or 'application/octet-stream'
        try:
            raw = base64.b64decode(attachment.datas) if attachment.datas else b''
        except Exception:
            raw = b''
        size_mb = len(raw) / (1024 * 1024) if raw else 0
        max_mb = account.media_max_mb or 50
        ptt = mimetype.startswith('audio/')
        gif_playback = (
            mimetype == 'image/gif'
            or (attachment.name or '').lower().endswith('.gif')
        )

        if size_mb > max_mb and mimetype.startswith('image/') and not gif_playback:
            try:
                raw = self._optimize_image(raw, max_mb)
                size_mb = len(raw) / (1024 * 1024)
            except Exception:
                _logger.exception("Image resize failed for attachment %s", attachment.id)

        if size_mb > max_mb:
            placeholder = _("[media too large to send: %(name)s — %(size).1f MB > %(max)d MB cap]",
                            name=attachment.name or 'attachment',
                            size=size_mb, max=max_mb)
            return api_client.send_text(number, placeholder)

        try:
            return api_client.send_media(
                number, raw, mimetype,
                filename=attachment.name,
                caption=caption,
                ptt=ptt,
                gif_playback=gif_playback,
            )
        except BaileysError as e:
            placeholder = _("[media failed: %(name)s — %(reason)s]",
                            name=attachment.name or 'attachment',
                            reason=e.error_message or 'unknown')
            return api_client.send_text(number, placeholder)

    def _maybe_clear_ack_reaction(self, api_client, number, account):
        """Phase 3: when we successfully replied to an inbound message we
        had ack'd with 👀, clear the reaction so the recipient sees the
        reply, not a stale reaction."""
        self.ensure_one()
        if not account or not account.remove_ack_after_reply:
            return
        if not account.reaction_level or account.reaction_level == 'off':
            return
        parent_inbound = self.parent_id
        if not parent_inbound or parent_inbound.message_type != 'inbound':
            return
        if not parent_inbound.msg_uid:
            return
        try:
            chat_jid = f"{number}@s.whatsapp.net"
            # Use send_reaction_v2 (the /messages/react route): the older
            # /send/reaction route rejects an empty emoji with HTTP 400
            # (JS `!emoji` is true for ''), so the ack was never cleared.
            # (#reactions)
            api_client.send_reaction_v2(
                chat_jid, parent_inbound.msg_uid, '', target_from_me=False)
        except Exception:
            _logger.exception("Failed to clear ack reaction for parent %s", parent_inbound.id)

    @staticmethod
    def _optimize_image(raw_bytes, max_mb):
        """Resize+recompress an image until it fits under max_mb. Returns bytes."""
        try:
            from PIL import Image
        except ImportError:
            return raw_bytes
        import io
        img = Image.open(io.BytesIO(raw_bytes))
        img = img.convert('RGB') if img.mode in ('RGBA', 'P') else img
        target = max_mb * 1024 * 1024
        for quality in (85, 75, 60, 50, 40):
            for scale in (1.0, 0.75, 0.5, 0.35):
                w, h = img.size
                resized = img.resize((max(1, int(w * scale)), max(1, int(h * scale))))
                buf = io.BytesIO()
                resized.save(buf, format='JPEG', quality=quality, optimize=True)
                data = buf.getvalue()
                if len(data) <= target:
                    return data
        return raw_bytes

    def _send_interactive_template(self, api_client, number, template):
        """Send a button or list template message via the sidecar.

        :param api_client: BaileysApi instance
        :param number: phone number (without + prefix)
        :param template: owa.quick.reply record
        :return: message_id string
        """
        # Get the related record for variable rendering
        record = None
        if self.mail_message_id and self.mail_message_id.model and self.mail_message_id.res_id:
            try:
                record = self.env[self.mail_message_id.model].browse(self.mail_message_id.res_id)
                if not record.exists():
                    record = None
            except Exception:
                record = None

        # Build common free-text values from the recipient context
        free_text = {}
        phone = number.lstrip('+') if number else ''
        partner = self.env['res.partner'].sudo().search([
            '|', ('phone', 'like', phone), ('phone', 'like', f'+{phone}')
        ], limit=1)
        if partner:
            free_text['customer_name'] = partner.name or ''
            free_text['partner_name'] = partner.name or ''
            free_text['name'] = partner.name or ''

        # Add financial/record variables if record is available
        if record:
            free_text['record_name'] = record.display_name or ''
            if hasattr(record, 'amount_total'):
                free_text['amount_total'] = str(record.amount_total or 0)
            if hasattr(record, 'currency_id') and record.currency_id:
                free_text['currency'] = record.currency_id.symbol or record.currency_id.name or ''
            for date_field in ('date_order', 'invoice_date', 'date', 'scheduled_date'):
                if hasattr(record, date_field) and getattr(record, date_field):
                    free_text['date'] = str(getattr(record, date_field))
                    break

        data = template.render_template_data(record=record, free_text_values=free_text)
        body = data.get('body', '')

        if template.template_type == 'button':
            header = data.get('header')
            return api_client.send_buttons(
                number, body,
                buttons=data.get('buttons', []),
                header=header,
                footer=data.get('footer'),
            )
        elif template.template_type == 'list':
            return api_client.send_list(
                number, body,
                button_text=data.get('button_text', 'Menu'),
                sections=data.get('sections', []),
                footer=data.get('footer'),
            )
        return ''

    def _handle_error(self, failure_type, reason):
        """Handle a send error with proper classification."""
        self.ensure_one()
        self.write({
            'state': 'error',
            'failure_type': failure_type,
            'failure_reason': str(reason),
        })
        _logger.warning("WhatsApp message %s failed: [%s] %s", self.id, failure_type, reason)
        self._notify_campaign_update()

    def _notify_status_update(self):
        """Broadcast status update to Discuss frontend via bus."""
        for message in self:
            if message.mail_message_id:
                channel = self.env['discuss.channel'].search([
                    ('channel_type', '=', 'whatsapp'),
                    ('whatsapp_number', '=', message.mobile_number_formatted or message.mobile_number),
                    ('owa_account_id', '=', message.wa_account_id.id),
                ], limit=1)
                if channel:
                    # v18-compat
                    channel._bus_send_store(
                        message.mail_message_id,
                        {"whatsappStatus": message.state},
                    )
        self._notify_campaign_update()

    def _notify_campaign_update(self):
        """Push a bus notification to refresh open owa.campaign forms."""
        campaigns = self.mapped('campaign_id')
        if not campaigns:
            return
        Bus = self.env['bus.bus'].sudo()
        for campaign in campaigns:
            partner = campaign.create_uid.partner_id
            if partner:
                Bus._sendone(partner, "owa.campaign/refresh", {"id": campaign.id})

    # ------------------------------------------------------------------
    # CRON
    # ------------------------------------------------------------------

    def _send_cron(self):
        """Cron: Send queued outbound messages in batches.

        Each message runs inside a savepoint so a DB-level error on one
        doesn't poison the whole batch and so we never rollback an already-
        committed-via-API transmit (which would re-queue and double-send).

        Phase 26A: respects per-account throttle caps and backoff windows.
        """
        from datetime import timedelta
        now = fields.Datetime.now()
        messages = self.search([
            ('state', '=', 'outgoing'),
            ('message_type', '=', 'outbound'),
            '|',
            ('scheduled_date', '=', False),
            ('scheduled_date', '<=', now),
        ], limit=500, order='id asc')
        # Group by account so we can apply per-account throttle in one pass
        sent_per_account = {}
        for msg in messages:
            account = msg.wa_account_id
            # Phase 26A backoff window
            if account.throttle_backoff_until and account.throttle_backoff_until > now:
                continue
            # Phase 26A rate-limit check (per-minute / hour / day)
            if account.messages_per_minute or account.messages_per_hour or account.messages_per_day:
                window_start_min = now - timedelta(minutes=1)
                window_start_hour = now - timedelta(hours=1)
                window_start_day = now - timedelta(days=1)
                Outbound = self.sudo()
                base = [('wa_account_id', '=', account.id),
                        ('message_type', '=', 'outbound'),
                        ('state', 'in', ['sent', 'delivered', 'read'])]
                if account.messages_per_minute:
                    if Outbound.search_count(base + [('write_date', '>=', window_start_min)]) >= account.messages_per_minute:
                        continue
                if account.messages_per_hour:
                    if Outbound.search_count(base + [('write_date', '>=', window_start_hour)]) >= account.messages_per_hour:
                        continue
                if account.messages_per_day:
                    if Outbound.search_count(base + [('write_date', '>=', window_start_day)]) >= account.messages_per_day:
                        continue
            try:
                with self.env.cr.savepoint():
                    msg._send_single_message()
            except Exception:
                _logger.exception("Error sending message %s", msg.id)
        # Odoo's cron runner commits after this method returns; per-message
        # savepoints already isolate failures, so a bare commit here would
        # only flush unrelated cache state.

    def _gc_owa_messages(self):
        """Cron: Garbage collect old messages.

        Campaign-linked messages are EXCLUDED: owa.campaign stat fields are
        computed from message_ids, so deleting them would permanently zero a
        campaign's sent/delivered/read/failed counts and make the historical
        "real-time stats" misleading. (#campaign)
        """
        threshold = fields.Datetime.now() - timedelta(days=self._ACTIVE_THRESHOLD_DAYS)
        old_messages = self.search([
            ('create_date', '<', threshold),
            ('state', 'in', ('sent', 'delivered', 'read', 'received', 'error', 'bounced', 'cancel')),
            ('campaign_id', '=', False),
        ])
        if old_messages:
            _logger.info("Garbage collecting %d old WhatsApp messages", len(old_messages))
            old_messages.unlink()

    # ------------------------------------------------------------------
    # ACTIONS
    # ------------------------------------------------------------------

    def button_resend(self):
        """Resend failed message(s)."""
        for msg in self:
            if msg.state in ('error', 'bounced', 'cancel'):
                msg.write({'state': 'outgoing', 'failure_type': False, 'failure_reason': False})

    def button_cancel(self):
        """Cancel queued message(s)."""
        for msg in self:
            if msg.state == 'outgoing':
                msg.write({'state': 'cancel'})

    def action_open_forward_wizard(self):
        """Open the forward wizard pre-filled with this message."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("Forward WhatsApp Message"),
            'res_model': 'owa.message.forward.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_owa_message_id': self.id},
        }

    def action_open_react_wizard(self):
        """Open the react wizard pre-filled with this message."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _("React to WhatsApp Message"),
            'res_model': 'owa.message.react.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_owa_message_id': self.id},
        }

    # ------------------------------------------------------------------
    # STATUS UPDATES
    # ------------------------------------------------------------------

    # Outbound progression. Late receipts can arrive out of order (e.g. a
    # `delivered` after a `read`); never let the state regress to an earlier
    # rank. `error` is terminal and replaces any prior state.
    _OUTBOUND_RANK = {'outgoing': 0, 'sent': 1, 'delivered': 2, 'read': 3, 'replied': 4}

    def _process_status_update(self, msg_uid, status):
        """Update message state from sidecar status webhook."""
        message = self.search([('msg_uid', '=', msg_uid)], limit=1)
        if not message:
            return
        state_map = {
            'sent': 'sent',
            'delivered': 'delivered',
            'read': 'read',
            'failed': 'error',
        }
        new_state = state_map.get(status)
        if not new_state or new_state == message.state:
            return
        if new_state != 'error':
            new_rank = self._OUTBOUND_RANK.get(new_state)
            cur_rank = self._OUTBOUND_RANK.get(message.state)
            if new_rank is not None and cur_rank is not None and new_rank < cur_rank:
                return
        message.write({'state': new_state})
        message._notify_status_update()

    def _apply_inbound_reaction(self, msg_uid, sender_jid, emoji):
        """Persist an inbound reaction onto the matching owa.message.

        WhatsApp sends a `reaction` payload referencing the message-id of
        the original message; we look that up by ``msg_uid`` and update
        ``wa_reactions_json`` ({sender_jid: emoji}). Empty emoji means the
        sender cleared their reaction.
        """
        import json
        if not msg_uid or not sender_jid:
            return False
        message = self.search([('msg_uid', '=', msg_uid)], limit=1)
        if not message:
            _logger.info(
                "owa.message: ignoring reaction for unknown msg_uid=%s", msg_uid,
            )
            return False
        try:
            data = json.loads(message.wa_reactions_json or '{}')
            if not isinstance(data, dict):
                data = {}
        except Exception:
            data = {}
        if emoji:
            data[sender_jid] = emoji
        else:
            data.pop(sender_jid, None)
        message.write({'wa_reactions_json': json.dumps(data)})
        # Post a small chatter line on the linked Discuss channel so the
        # reaction is visible in the conversation thread.
        channel = self.env['discuss.channel'].sudo().search([
            ('channel_type', '=', 'whatsapp'),
            ('owa_account_id', '=', message.wa_account_id.id),
            '|',
                ('whatsapp_partner_id', '=', message.whatsapp_partner_id.id),
                ('whatsapp_number', '=', message.mobile_number_formatted or message.mobile_number),
        ], limit=1)
        if channel:
            from markupsafe import Markup
            sender_phone = sender_jid.split('@', 1)[0].split(':', 1)[0]
            try:
                if emoji:
                    body = Markup('<p><strong>+{phone}</strong> reacted {emoji} to a message</p>').format(
                        phone=sender_phone, emoji=emoji,
                    )
                else:
                    body = Markup('<p><strong>+{phone}</strong> removed their reaction</p>').format(
                        phone=sender_phone,
                    )
                channel.message_post(
                    body=body,
                    message_type='notification',
                    subtype_xmlid='mail.mt_note',
                    author_id=self.env.ref('base.partner_root').id,
                )
            except Exception:  # pragma: no cover -- chatter post is best-effort
                _logger.exception("Reaction chatter post failed for msg_uid=%s", msg_uid)
        return True

    def _update_message_fetched_seen(self):
        """Update channel member seen/delivered status for WhatsApp messages."""
        for message in self.filtered(lambda m: m.mail_message_id):
            wa_number = message.mobile_number_formatted or message.mobile_number
            if not wa_number:
                _logger.warning(
                    "Skipping seen/delivered update for owa.message %s: no number",
                    message.id,
                )
                continue
            channel = self.env['discuss.channel'].search([
                ('channel_type', '=', 'whatsapp'),
                ('whatsapp_number', '=', wa_number),
                ('owa_account_id', '=', message.wa_account_id.id),
            ], limit=1)
            if channel and channel.whatsapp_partner_id:
                member = channel.channel_member_ids.filtered(
                    lambda m: m.partner_id == channel.whatsapp_partner_id
                )
                if member and message.state in ('delivered', 'read'):
                    if message.state == 'read':
                        member.seen_message_id = message.mail_message_id
                    elif message.state == 'delivered':
                        member.fetched_message_id = message.mail_message_id
