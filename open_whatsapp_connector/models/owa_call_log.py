import logging

from markupsafe import Markup

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)

_RAW_TO_STATE = {
    'offer':   'ringing',
    'ringing': 'ringing',
    'timeout': 'missed',
    'reject':  'rejected',
    'accept':  'accepted',
}
_TERMINAL = ('missed', 'rejected', 'accepted', 'timeout')


class OwaCallLog(models.Model):
    """Phase 21: incoming WhatsApp voice/video call events.

    The gateway exposes a ``call`` event with status transitions
    (offer -> ringing -> timeout/reject/accept). We persist each terminal
    transition as one row so the user has a full audit log of who called
    when, voice vs video, and whether the call was missed.

    The sidecar cannot answer calls or carry audio -- this model records
    the signaling envelope only."""

    _name = 'owa.call.log'
    _description = 'WhatsApp Incoming Call Log'
    _inherit = ['mail.thread']
    _order = 'started_at desc, id desc'
    _rec_name = 'display_name'

    wa_account_id = fields.Many2one(
        'owa.account', string='Account',
        required=True, ondelete='cascade', index=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company,
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner', string='Contact', index=True,
        help="Resolved from the caller phone via res.partner.phone match.",
    )
    channel_id = fields.Many2one(
        'discuss.channel', string='Discuss thread', index=True,
        help="Existing WhatsApp Discuss channel for this contact, if any.",
    )

    from_jid = fields.Char(
        string='From JID', required=True, index=True,
        help="WhatsApp JID of the caller, e.g. 919999999999@s.whatsapp.net",
    )
    chat_jid = fields.Char(
        string='Chat JID',
        help="Chat where the call happened. For group calls this is the group "
             "JID (`...@g.us`); for 1-on-1 it equals the caller's JID. Used so "
             "Reject can target the correct WhatsApp endpoint and the chatter "
             "line lands in the right Discuss thread.",
    )
    from_phone = fields.Char(
        string='From phone',
        compute='_compute_from_phone', store=True, index=True,
        help="Phone number portion of the caller JID, with leading +.",
    )

    call_id = fields.Char(
        string='Call ID', required=True, index=True,
        help="WhatsApp's internal call identifier; unique per account.",
    )
    is_video = fields.Boolean(
        string='Video call', default=False, tracking=True,
    )
    is_group = fields.Boolean(
        string='Group call', default=False,
        help="True if the call originated inside a WhatsApp group.",
    )

    state = fields.Selection([
        ('ringing',  'Ringing'),
        ('missed',   'Missed'),
        ('rejected', 'Rejected'),
        ('accepted', 'Accepted'),
        ('timeout',  'Timeout'),
    ], string='Status', required=True, default='ringing',
       index=True, tracking=True)

    started_at = fields.Datetime(
        string='Started at', required=True, default=fields.Datetime.now,
        index=True,
    )
    ended_at = fields.Datetime(string='Ended at')
    duration_seconds = fields.Integer(
        string='Duration (s)', compute='_compute_duration', store=True,
    )
    auto_replied = fields.Boolean(
        string='Auto-reply sent', default=False, readonly=True,
        help="True if the missed-call auto-reply has been queued for this call.",
    )

    display_name = fields.Char(compute='_compute_display_name', store=True)
    notes = fields.Html(string='Notes')

    _sql_constraints = [
        ('uniq_account_call_id',
         'unique(wa_account_id, call_id)',
         'Duplicate call event for this account.'),
    ]

    @api.depends('from_jid')
    def _compute_from_phone(self):
        for rec in self:
            jid = rec.from_jid or ''
            phone = jid.split('@', 1)[0] if '@' in jid else jid
            # Drop multi-device suffix (e.g. "919999999999:47" -> "919999999999")
            if ':' in phone:
                phone = phone.split(':', 1)[0]
            rec.from_phone = ('+' + phone) if (phone and not phone.startswith('+')) else phone

    @api.depends('partner_id', 'partner_id.display_name', 'from_phone',
                 'is_video', 'state')
    def _compute_display_name(self):
        for rec in self:
            who = rec.partner_id.display_name if rec.partner_id else (rec.from_phone or '?')
            kind = _('Video') if rec.is_video else _('Voice')
            rec.display_name = f"{kind} · {who} · {rec.state}"

    @api.depends('started_at', 'ended_at')
    def _compute_duration(self):
        for rec in self:
            if rec.started_at and rec.ended_at and rec.ended_at > rec.started_at:
                rec.duration_seconds = int((rec.ended_at - rec.started_at).total_seconds())
            else:
                rec.duration_seconds = 0

    @api.model
    def _resolve_partner_from_phone(self, phone):
        """Look up a res.partner by mobile or phone using digit-only matching.
        Falls back to last-10-digits suffix match when the country code differs.
        Returns the first hit or an empty recordset."""
        if not phone:
            return self.env['res.partner']
        digits = ''.join(c for c in phone if c.isdigit())
        if not digits:
            return self.env['res.partner']
        Partner = self.env['res.partner'].sudo()
        for needle in (digits, digits[-10:]):
            if not needle:
                continue
            # Match on phone OR mobile — the docstring always promised both,
            # but the search only used phone, so callers stored under mobile
            # were never resolved (and missed-call auto-reply was skipped).
            # (#calls)
            partner = Partner.search([
                '|', ('phone', 'ilike', needle), ('mobile', 'ilike', needle),
            ], limit=1)
            if partner:
                return partner
        return self.env['res.partner']

    @api.model
    def _record_call_event(self, account, payload):
        """Idempotent intake of a single sidecar call event.

        Creates or updates the matching owa.call.log row, posts a chatter
        line to the partner's Discuss thread, and -- when the call is
        terminal and missed/rejected/timeout -- queues the auto-reply
        if the account has it enabled.

        :param account: ``owa.account`` recordset (single)
        :param payload: dict with at least ``id``, ``from``, ``status``;
                       optional ``isVideo`` (bool), ``isGroup`` (bool),
                       ``date`` (epoch ms or iso string)
        :returns: ``owa.call.log`` recordset (the persisted row), or False
                  on bad payload.
        """
        call_id = (payload or {}).get('id')
        raw_from = (payload or {}).get('from') or ''
        chat_id = (payload or {}).get('chat_id') or ''
        # Caller JID may be a LID (anonymized multi-device handle, ends in
        # `@lid`) — that has no usable phone in it. Prefer chat_id when
        # available, otherwise fall through with whatever the gateway gave us.
        if (raw_from.endswith('@lid') or not raw_from) and chat_id:
            from_jid = chat_id
        else:
            from_jid = raw_from
        raw_status = (payload or {}).get('status') or 'ringing'
        if not call_id or not from_jid:
            _logger.warning(
                "owa.call.log: ignoring malformed call payload: %s", payload,
            )
            return False

        new_state = _RAW_TO_STATE.get(raw_status, 'ringing')
        is_video = bool((payload or {}).get('isVideo'))
        is_group = bool((payload or {}).get('isGroup'))
        phone_part = from_jid.split('@', 1)[0]
        if ':' in phone_part:
            phone_part = phone_part.split(':', 1)[0]

        existing = self.search([
            ('wa_account_id', '=', account.id),
            ('call_id', '=', call_id),
        ], limit=1)
        now = fields.Datetime.now()

        if existing:
            # Once a call has reached a terminal state (missed/rejected/
            # accepted/timeout), don't regress to 'ringing' on stray late
            # events. Allow corrections among terminal states only.
            if existing.state in _TERMINAL and new_state not in _TERMINAL:
                return existing
            vals = {'state': new_state}
            if new_state in _TERMINAL and not existing.ended_at:
                vals['ended_at'] = now
            existing.write(vals)
            log = existing
        else:
            partner = self._resolve_partner_from_phone(phone_part)
            channel = self.env['discuss.channel']
            # Only route to the GROUP discuss channel when the gateway actually
            # gave us a real group JID (`...@g.us`). For "isGroup=true"
            # events where chat_id is a LID or empty, the gateway is reporting
            # call-from-group-context but the call is still peer-to-peer at
            # the protocol layer — fall back to the caller's personal
            # channel so the user actually sees the incoming call somewhere.
            if is_group and chat_id and chat_id.endswith('@g.us'):
                channel = self.env['discuss.channel'].sudo().search([
                    ('channel_type', '=', 'whatsapp'),
                    ('owa_account_id', '=', account.id),
                    ('whatsapp_number', '=', chat_id.lstrip('+')),
                ], limit=1)
            if not channel and partner:
                channel = self.env['discuss.channel'].sudo().search([
                    ('channel_type', '=', 'whatsapp'),
                    ('owa_account_id', '=', account.id),
                    ('whatsapp_partner_id', '=', partner.id),
                ], limit=1)
            log = self.create({
                'wa_account_id': account.id,
                'partner_id': partner.id if partner else False,
                'channel_id': channel.id if channel else False,
                'from_jid': from_jid,
                'chat_jid': chat_id or False,
                'call_id': call_id,
                'is_video': is_video,
                'is_group': is_group,
                'state': new_state,
                'started_at': now,
                'ended_at': now if new_state in _TERMINAL else False,
            })

        if new_state in _TERMINAL and log.channel_id:
            self._post_chatter(log)
        # Group calls: post an "Incoming call from X" chatter line on ringing
        # too, so members see the call in the group thread immediately rather
        # than waiting for the terminal event.
        elif new_state == 'ringing' and log.is_group and log.channel_id and not existing:
            self._post_chatter(log)

        if (new_state in ('missed', 'rejected', 'timeout')
                and not log.auto_replied
                and account.auto_reply_on_missed_call
                and account.missed_call_reply_template
                and log.partner_id):
            self._queue_missed_call_reply(log, account)

        # Bus-notify subscribed users so the toast can show / dismiss in real time.
        if new_state == 'ringing':
            self._notify_ringing(log, account)
        elif new_state in _TERMINAL:
            self._notify_ended(log, account)

        return log

    def _notify_ringing(self, log, account):
        """Push a transient toast event to every user subscribed via
        ``account.notify_user_ids``. The OWL listener
        (``static/src/calls/owa_call_ringing_notifier.js``) renders the
        actual toast with Open / Reject / Dismiss buttons."""
        Bus = self.env['bus.bus'].sudo()
        payload = {
            'call_log_id': log.id,
            'call_id': log.call_id,
            'account_id': account.id,
            'account_name': account.name or '',
            'from_phone': log.from_phone or '?',
            'partner_id': log.partner_id.id if log.partner_id else False,
            'partner_name': log.partner_id.display_name if log.partner_id else '',
            'is_video': bool(log.is_video),
        }
        for user in account.notify_user_ids:
            partner = user.partner_id
            if partner:
                Bus._sendone(partner, 'owa.call/ringing', payload)

    def _notify_ended(self, log, account):
        """Tell the OWL listener to dismiss any toast for this call."""
        Bus = self.env['bus.bus'].sudo()
        payload = {'call_log_id': log.id, 'state': log.state}
        for user in account.notify_user_ids:
            partner = user.partner_id
            if partner:
                Bus._sendone(partner, 'owa.call/ended', payload)

    def _post_chatter(self, log):
        """Post a system message to the existing Discuss WhatsApp channel for the
        contact summarising the call status."""
        for rec in log:
            if not rec.channel_id:
                continue
            kind_emoji = '\U0001F4F9' if rec.is_video else '\U0001F4DE'
            kind_label = _('Video call') if rec.is_video else _('Voice call')
            human_state = dict(self._fields['state'].selection).get(rec.state, rec.state)
            body = Markup('<p>{emoji} <strong>{kind}</strong> · {state}</p>').format(
                emoji=kind_emoji, kind=kind_label, state=human_state,
            )
            # Attribute the call entry to the CALLER (incoming call), not
            # OdooBot. partner_root was being used unconditionally, so every
            # "Voice/Video call · Rejected" line — and the messaging-menu
            # preview — showed "OdooBot". Fall back to OdooBot only when the
            # caller couldn't be resolved to a partner. (#calls)
            author = rec.partner_id or rec.channel_id.whatsapp_partner_id
            author_id = author.id if author else self.env.ref('base.partner_root').id
            try:
                rec.channel_id.sudo().message_post(
                    body=body,
                    message_type='notification',
                    subtype_xmlid='mail.mt_note',
                    author_id=author_id,
                )
            except Exception:  # pragma: no cover -- chatter post is best-effort
                _logger.exception(
                    "owa.call.log: failed to post chatter for call_id=%s",
                    rec.call_id,
                )

    def _queue_missed_call_reply(self, log, account):
        """Queue the missed-call auto-reply through the standard owa.message
        send pipeline so the existing send cron picks it up."""
        body = (account.missed_call_reply_template or '').replace(
            '{{partner_name}}', log.partner_id.name or '',
        )
        if not body.strip():
            return
        try:
            # owa.message.body is a related field on mail_message_id; writing
            # 'body' directly is silently dropped, queuing an empty message
            # that then fails with "Empty message". Build the mail.message
            # first so the auto-reply text actually goes out.
            mail_message = self.env['mail.message'].sudo().create({
                'body': body,
                'message_type': 'whatsapp_message',
            })
            self.env['owa.message'].sudo().create({
                'wa_account_id': account.id,
                'mobile_number': log.from_phone,
                'mail_message_id': mail_message.id,
                'message_type': 'outbound',
                'state': 'outgoing',
                'whatsapp_partner_id': log.partner_id.id,
            })
            log.auto_replied = True
        except Exception:
            _logger.exception(
                "owa.call.log: failed to queue auto-reply for call_id=%s",
                log.call_id,
            )

    def action_reject_call(self):
        """Reject a still-ringing WhatsApp call so the caller's phone stops
        ringing, then flip this row to ``rejected``. No-op for calls already
        in a terminal state. Routes to the matching transport: QR/Baileys
        sends the gateway reject IQ via the sidecar; cloud accounts POST a
        reject action to the Meta Calling API."""
        self.ensure_one()
        if self.state != 'ringing':
            return False
        if self.wa_account_id.connection_type == 'cloud':
            return self._reject_cloud_call(self.wa_account_id.sudo())
        from odoo.addons.open_whatsapp_connector.tools.baileys_exception import BaileysError
        # sudo: the reject toast is shown to regular agents (notify_user_ids)
        # who have read-only ACL on owa.call.log and cannot read the
        # admin-only sidecar_api_key. Without sudo this raises AccessError the
        # moment a non-admin clicks Reject. (#ringing)
        api = self.wa_account_id.sudo()._get_baileys_api()
        # For group calls the gateway's reject IQ must target the GROUP JID (not
        # the caller's personal JID) — sending to the personal JID is a no-op
        # because that's not where the call session is anchored.
        target_jid = self.chat_jid if (self.is_group and self.chat_jid) else self.from_jid
        try:
            api.reject_call(self.call_id, target_jid)
        except BaileysError as e:
            _logger.warning(
                "owa.call.log %s: rejectCall failed: %s",
                self.id, e.error_message,
            )
            return False
        except Exception as e:
            _logger.exception(
                "owa.call.log %s: rejectCall unexpected failure: %s",
                self.id, e,
            )
            return False
        now = fields.Datetime.now()
        self.sudo().write({'state': 'rejected', 'ended_at': now})
        # Trigger the same bus push the sidecar would on a reject event
        # so any open toasts dismiss immediately.
        self.sudo()._notify_ended(self.sudo(), self.wa_account_id.sudo())
        return True

    def _reject_cloud_call(self, account):
        """Reject a still-ringing call on a cloud (Meta Cloud API) account via
        the Calling API, then flip this row to ``rejected``. Mirrors the
        Baileys reject path's state/bus behaviour."""
        self.ensure_one()
        from odoo.addons.open_whatsapp_connector.tools.cloud_api import (
            CloudApiError)
        api = account._get_cloud_api()
        try:
            api.reject_call(self.call_id)
        except CloudApiError as e:
            _logger.warning(
                "owa.call.log %s: cloud rejectCall failed: %s",
                self.id, e.message)
            return False
        except Exception as e:
            _logger.exception(
                "owa.call.log %s: cloud rejectCall unexpected failure: %s",
                self.id, e)
            return False
        now = fields.Datetime.now()
        self.sudo().write({'state': 'rejected', 'ended_at': now})
        self.sudo()._notify_ended(self.sudo(), account)
        return True

    def action_open_partner(self):
        """Form-action: jump to the linked partner."""
        self.ensure_one()
        if not self.partner_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'res_id': self.partner_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_open_channel(self):
        """Form-action: jump to the linked WhatsApp Discuss channel."""
        self.ensure_one()
        if not self.channel_id:
            return False
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'discuss.channel',
            'res_id': self.channel_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

    # ── Phase 26H: mass actions ──────────────────────────────────────────

    def action_mass_create_lead(self):
        """Create one crm.lead per selected call (when crm is installed)."""
        if 'crm.lead' not in self.env:
            return False
        Lead = self.env['crm.lead'].sudo()
        for rec in self:
            Lead.create({
                'name': _("WhatsApp call from %s") % (rec.partner_id.name or rec.from_phone or '?'),
                'partner_id': rec.partner_id.id if rec.partner_id else False,
                'description': _("Generated from WhatsApp call %(kind)s · %(state)s · %(when)s") % {
                    'kind': 'video' if rec.is_video else 'voice',
                    'state': rec.state,
                    'when': rec.started_at,
                },
                'phone': rec.from_phone or '',
            })
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Leads created"),
                'message': _("%d CRM leads created.") % len(self),
                'sticky': False,
            },
        }

    def action_mass_block_number(self):
        """Add the caller's phone to owa.blacklist for each selected call."""
        Blacklist = self.env['owa.blacklist'].sudo()
        added = 0
        for rec in self:
            phone = rec.from_phone
            if not phone:
                continue
            existing = Blacklist.search([('phone_number', '=', phone)], limit=1)
            if existing:
                continue
            Blacklist.create({
                'wa_account_id': rec.wa_account_id.id,
                'phone_number': phone,
                'reason': _("Auto-blocked from call log"),
            })
            added += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Numbers blocked"),
                'message': _("%d phone numbers added to blacklist.") % added,
                'sticky': False,
            },
        }
