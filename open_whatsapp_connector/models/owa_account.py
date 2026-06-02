import logging
import secrets
import string
from datetime import timedelta
from urllib.parse import quote

from markupsafe import Markup

import base64

from odoo import api, fields, models, SUPERUSER_ID, _
from odoo.exceptions import UserError, ValidationError
from odoo.addons.open_whatsapp_connector.tools.baileys_api import BaileysApi
from odoo.addons.open_whatsapp_connector.tools.baileys_exception import BaileysError

_logger = logging.getLogger(__name__)


class OwaAccount(models.Model):
    _name = 'owa.account'
    _inherit = ['mail.thread']
    _description = 'Open WhatsApp Connector Account'
    _rec_name = 'display_name'
    _order = 'display_name, id'

    name = fields.Char(string="Name", required=True, tracking=1)
    display_name = fields.Char(
        string="Display Name", compute='_compute_display_name', store=True,
        help="Human-friendly name shown in lists and menus. Falls back to "
             "the technical 'name' if unset.")
    label = fields.Char(
        string="Label", help="Optional human-friendly label; if set, this "
                              "overrides the internal name in lists.")
    active = fields.Boolean(default=True, tracking=6)
    enabled = fields.Boolean(
        string="Enabled", default=True,
        help="If unchecked, the sidecar listener is not started for this "
             "account on Connect — useful for keeping a configured account "
             "around without it consuming a sidecar slot.")
    auth_dir = fields.Char(
        string="Auth directory override",
        groups='open_whatsapp_connector.group_owa_admin',
        help="Optional absolute path; sidecar reads the gateway's multi-file auth "
             "state from here instead of the default per-account dir. Only "
             "set this if you need to share auth state with another tool.")

    @api.depends('label', 'name')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.label or rec.name or ''

    @api.onchange('throttle_preset')
    def _onchange_throttle_preset(self):
        # The preset is a convenience that fills the per-hour cap; the numeric
        # caps remain editable for fine-tuning. Without this the preset field
        # was inert (selecting it changed nothing).
        presets = {
            'unlimited': (0, 0, 0),
            'safe_low_volume': (0, 60, 0),
            'medium': (0, 300, 0),
            'high': (0, 1000, 0),
        }
        for rec in self:
            if rec.throttle_preset in presets:
                m, h, d = presets[rec.throttle_preset]
                rec.messages_per_minute = m
                rec.messages_per_hour = h
                rec.messages_per_day = d

    # Sidecar connection
    sidecar_url = fields.Char(
        string="Sidecar URL", default="http://localhost:3100", required=True,
        help="URL of the Node.js sidecar service")
    sidecar_api_key = fields.Char(
        string="API Key", groups='open_whatsapp_connector.group_owa_admin',
        help="Shared API key for authenticating with the sidecar service")
    webhook_secret = fields.Char(
        string="Webhook Secret", compute='_compute_webhook_secret', store=True,
        copy=False,
        groups='open_whatsapp_connector.group_owa_admin')

    # Session state (synced from sidecar)
    session_state = fields.Selection([
        ('disconnected', 'Disconnected'),
        ('qr_pending', 'Awaiting QR Scan'),
        ('connecting', 'Connecting'),
        ('connected', 'Connected'),
        ('logged_out', 'Logged Out'),
    ], string="Status", default='disconnected', readonly=True, tracking=5)
    qr_code_base64 = fields.Text(string="QR Code Data", readonly=True)
    phone_number = fields.Char(string="Phone Number", readonly=True, copy=False)

    # Access control
    allowed_company_ids = fields.Many2many(
        comodel_name='res.company', string="Allowed Companies",
        default=lambda self: self.env.company)
    notify_user_ids = fields.Many2many(
        comodel_name='res.users', string="Users to Notify",
        default=lambda self: self.env.user,
        domain=[('share', '=', False)], required=True, tracking=3,
        help="Users notified when a new message is received")

    # Config
    debug_logging = fields.Boolean(
        string="Debug Logging",
        help="Log sidecar API requests for debugging")
    callback_url = fields.Char(
        string="Callback URL", compute='_compute_callback_url', readonly=True)

    # Sidecar process status
    sidecar_running = fields.Boolean(
        string="Sidecar Running", compute='_compute_sidecar_running')

    # Phase C3: business profile picture (uploaded to WhatsApp via the sidecar)
    image_1920 = fields.Image(string="Profile Picture", max_width=1920, max_height=1920)

    # Phase D: pairing method — explicit choice between QR scan and pairing code
    pairing_method = fields.Selection([
        ('qr', 'Scan QR Code'),
        ('code', 'Link with Code'),
    ], string="Pairing Method", default='qr', required=True, tracking=4,
       help="Choose how this account pairs to WhatsApp the first time. "
            "Scan QR is the default and works on every phone. "
            "Link with Code is a fallback if camera scanning isn't available.")
    pairing_phone = fields.Char(
        string="WhatsApp Pairing Phone",
        help="Phone number of the WhatsApp account to pair (digits only, country code included). "
             "Used by the 'Request pairing code' action as an alternative to scanning the QR.")
    pairing_code = fields.Char(
        string="WhatsApp Pairing Code", readonly=True,
        help="Most recent 8-character pairing code returned by WhatsApp. Type this on the phone "
             "in Settings → Linked Devices → Link with phone number.")

    # ─── Transport selection: QR/device-link vs Official Cloud API ──────
    connection_type = fields.Selection([
        ('qr', 'QR / Device Link'),
        ('cloud', 'Official Cloud API'),
    ], string="Connection Type", default='qr', required=True, tracking=True,
       help="How this account talks to WhatsApp. 'QR / Device Link' uses the "
            "Node.js gateway (scan a QR / pairing code). 'Official Cloud API' "
            "talks directly to the Meta Graph API for a WhatsApp Business "
            "number — no gateway, supports multiple business numbers.")

    # ─── Official Cloud API (Meta Graph API) credentials ────────────────
    cloud_phone_number_id = fields.Char(
        string="Phone Number ID", copy=False,
        help="Meta Phone Number ID of the sending WhatsApp Business number.")
    cloud_waba_id = fields.Char(
        string="WhatsApp Business Account ID", copy=False,
        help="Meta WhatsApp Business Account (WABA) ID — matches the inbound "
             "webhook entry.id used to route messages to this account.")
    cloud_app_id = fields.Char(
        string="Meta App ID", copy=False,
        help="Meta App ID — used for resumable media upload sessions.")
    cloud_app_secret = fields.Char(
        string="App Secret", copy=False,
        groups='open_whatsapp_connector.group_owa_admin',
        help="Meta App Secret — used to verify the X-Hub-Signature-256 on "
             "inbound webhooks. Never logged.")
    cloud_access_token = fields.Char(
        string="Access Token", copy=False,
        groups='open_whatsapp_connector.group_owa_admin',
        help="Bearer token for the Graph API. Sandbox tokens are short-lived; "
             "use a system-user permanent token in production.")
    cloud_verify_token = fields.Char(
        string="Webhook Verify Token", copy=False, readonly=True,
        groups='open_whatsapp_connector.group_owa_admin',
        help="Random token auto-generated per cloud account. Enter this in the "
             "Meta console webhook setup so the GET verification handshake "
             "succeeds.")
    cloud_api_version = fields.Char(
        string="Graph API Version", default='v23.0',
        help="Meta Graph API version, e.g. v23.0.")
    cloud_callback_url = fields.Char(
        string="Callback URL", compute='_compute_cloud_callback_url',
        help="Webhook URL to register in the Meta console for this account.")

    @api.depends('connection_type')
    def _compute_cloud_callback_url(self):
        # Carry ?db=<dbname> so Meta's webhook resolves the right database on a
        # multi-database host — the controllers/ir_http.py patch reads this query
        # arg (and the X-Odoo-Database header) before dispatch. Mirrors the QR
        # callback_url pattern so both transports behave identically on multi-DB
        # deployments. web.base.url already carries the https scheme Meta requires.
        db_name = quote(self.env.cr.dbname or '')
        base = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        for acc in self:
            acc.cloud_callback_url = (
                (base or '')
                + f'/open_whatsapp_connector/cloud/webhook?db={db_name}')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if (vals.get('connection_type') == 'cloud'
                    and not vals.get('cloud_verify_token')):
                vals['cloud_verify_token'] = ''.join(
                    secrets.choice(string.ascii_letters + string.digits)
                    for _ in range(20))
        return super().create(vals_list)

    # ─── Phase 1: outbound payload shaping ──────────────────────────────
    media_max_mb = fields.Integer(
        string="Media size cap (MB)", default=50,
        help="Outbound + inbound media files larger than this are rejected "
             "(images are auto-resized first).")
    text_chunk_limit = fields.Integer(
        string="Text chunk limit", default=4000,
        help="Outbound text messages longer than this are split into chunks "
             "and sent sequentially. WhatsApp's hard limit is ~65000 chars; "
             "4000 keeps each chunk readable on a phone screen.")
    chunk_mode = fields.Selection([
        ('length', 'Length (split at character limit)'),
        ('newline', 'Newline (prefer paragraph boundaries)'),
    ], string="Chunk mode", default='newline')

    # ─── Phase 3: reactions ─────────────────────────────────────────────
    reaction_level = fields.Selection([
        ('off', 'Off (no reactions)'),
        ('ack', 'Ack only (👀 on receipt)'),
        ('manual', 'Ack + manual agent reactions'),
    ], string="Reaction level", default='ack')
    ack_reaction_emoji = fields.Char(
        string="Ack emoji", default='👀',
        help="Emoji sent immediately when an inbound message is received, "
             "before any agent or bot replies. Empty disables ack reactions.")
    ack_reaction_dm = fields.Boolean(
        string="Ack on DMs", default=True,
        help="Send ack reaction on direct messages.")
    ack_reaction_group = fields.Selection([
        ('always', 'Always'),
        ('mentions', 'Only when mentioned'),
        ('never', 'Never'),
    ], string="Ack on groups", default='mentions')
    remove_ack_after_reply = fields.Boolean(
        string="Clear ack after reply", default=True,
        help="When the bot or an agent replies to a message we ack'd, "
             "remove the original ack reaction so the recipient sees only "
             "the reply.")

    # ─── Phase 22A: triage SLA ─────────────────────────────────────────
    sla_minutes = fields.Integer(
        string="Triage SLA (minutes)", default=60,
        help="If a conversation goes unanswered or unassigned for this many "
             "minutes, an SLA-breach activity is scheduled for the assignee. "
             "Set 0 to disable.")

    # ─── Phase 23B: customer-satisfaction survey ───────────────────────
    auto_csat = fields.Boolean(
        string="Auto-send CSAT after resolve", default=False,
        help="When a WhatsApp Discuss channel flips to 'resolved', send the "
             "customer a survey link (requires the survey module).")
    csat_minimum_score = fields.Integer(
        string="CSAT alert threshold", default=3,
        help="Scores at or below this trigger an activity for the manager.")

    # ─── Phase 24D: project-task auto-create default ───────────────────
    # Plain int so it installs without project module.
    default_project_id_int = fields.Integer(
        string="Default project id (for inbound rules)",
        help="Numeric id of a project.project record, when the project "
             "module is installed.")

    # ─── Phase 26A: outbound throttling ────────────────────────────────
    messages_per_minute = fields.Integer(
        string="Max msgs / minute", default=0,
        help="0 = unlimited. Cron defers dispatch when the rolling-window "
             "count for this account exceeds the cap.")
    messages_per_hour = fields.Integer(string="Max msgs / hour", default=0)
    messages_per_day = fields.Integer(string="Max msgs / day", default=0)
    throttle_preset = fields.Selection([
        ('unlimited', 'Unlimited'),
        ('safe_low_volume', 'Safe — low volume (60/h)'),
        ('medium', 'Medium (300/h)'),
        ('high', 'High (1000/h)'),
    ], string="Throttle preset", default='unlimited')
    throttle_backoff_until = fields.Datetime(string="Backoff until", readonly=True)

    # ─── Phase 26J: avatar sync ────────────────────────────────────────
    auto_sync_avatars = fields.Boolean(
        string="Auto-sync partner avatars", default=True,
        help="On first inbound from a partner with no image, fetch their "
             "WhatsApp profile picture and store it on res.partner.")

    # ─── Phase 21: missed-call auto-reply ──────────────────────────────
    auto_reply_on_missed_call = fields.Boolean(
        string="Auto-reply on missed call", default=False,
        help="When an inbound voice or video call is missed, rejected or "
             "times out, automatically queue the template below as a text "
             "reply to the caller. Requires the partner to be resolved by "
             "phone match.")
    missed_call_reply_template = fields.Text(
        string="Missed-call reply template",
        default="Sorry I missed your call! Please send a message and I'll "
                "respond shortly.",
        help="Text sent on missed/rejected/timed-out incoming calls. "
             "Supports {{partner_name}} placeholder.")

    # ─── Phase 4: read receipts / self-chat / reply quoting ────────────
    send_read_receipts = fields.Boolean(
        string="Send read receipts", default=True,
        help="If unchecked, no blue ticks are sent — recipients see only "
             "two grey ticks when their messages are received. The sidecar "
             "honours this flag at message-receive time.")
    stealth_mode = fields.Boolean(
        string="Stealth mode", default=False, tracking=True,
        help="One-click privacy mode. When on, this account never sends blue "
             "read-receipt ticks (overrides 'Send read receipts'). The sidecar "
             "already connects without broadcasting an online/last-seen status "
             "(markOnlineOnConnect=false), so with stealth on the account is "
             "effectively invisible: no online dot, no last-seen, no blue ticks.")
    self_chat_mode = fields.Boolean(
        string="Self-chat mode", default=False,
        help="Treat this account as if WhatsApp messages may come from the "
             "same number as the account itself. Outbound replies get a "
             "[bot-name] prefix so you can tell them apart from your own "
             "manual messages, and read receipts are skipped on self-chat.")
    reply_to_mode = fields.Selection([
        ('off', 'Off (never quote)'),
        ('first', 'Quote first chunk only'),
        ('all', 'Quote every chunk'),
    ], string="Reply quoting", default='first',
       help="Whether outbound replies natively quote the inbound message "
            "they're replying to.")

    # ─── Phase 5: DM access control ────────────────────────────────────
    dm_policy = fields.Selection([
        ('open', 'Open (anyone can DM)'),
        ('allowlist', 'Allowlist (only listed numbers can DM)'),
        ('pairing', 'Pairing (unknown senders need admin approval)'),
        ('disabled', 'Disabled (drop all DMs)'),
    ], string="DM policy", default='open', tracking=True,
       help="Controls who can send direct messages to this WhatsApp account. "
            "Default 'open' keeps existing behavior; tighten to 'allowlist' "
            "or 'pairing' for restricted use.")
    allowlist_entry_ids = fields.One2many(
        'owa.allowlist.entry', 'account_id', string="Allowlist entries")

    # ─── Phase 6: group support ────────────────────────────────────────
    group_policy = fields.Selection([
        ('open', 'Open (any group)'),
        ('allowlist', 'Allowlist (only listed group JIDs)'),
        ('disabled', 'Disabled (drop all group messages)'),
    ], string="Group policy", default='open', tracking=True,
       help="Controls whether group messages are processed. Default 'open' "
            "keeps existing behavior.")
    group_allow_jids = fields.Text(
        string="Allowed group JIDs",
        help="One group JID per line. Format: <number>-<timestamp>@g.us "
             "(e.g. 120363025246125678@g.us). Get the JID from the channel's "
             "WhatsApp Number field. Only used when Group policy = 'allowlist'.")
    group_intro_message = fields.Text(
        string="Group intro message",
        help="Sent automatically the first time the bot is added to (or sees "
             "an inbound from) a new WhatsApp group.")

    # ─── Phase 8: session reliability + diagnostics ────────────────────
    last_seen_dt = fields.Datetime(
        string="Last seen", readonly=True,
        help="Last time the heartbeat cron successfully reached the sidecar "
             "for this account.")
    is_listening = fields.Boolean(
        string="Listening", readonly=True,
        help="True when the sidecar is actively delivering events to Odoo "
             "for this account.")
    health_status = fields.Selection([
        ('healthy', 'Healthy'),
        ('degraded', 'Degraded'),
        ('down', 'Down'),
        ('unknown', 'Unknown'),
    ], string="Health", compute='_compute_health_status', store=True)

    @api.depends('session_state', 'last_seen_dt', 'sidecar_running',
                 'connection_type')
    def _compute_health_status(self):
        from datetime import timedelta as _td
        now = fields.Datetime.now()
        for rec in self:
            # Cloud API accounts have no sidecar/heartbeat — health is simply
            # whether the access token last verified as connected.
            if rec.connection_type == 'cloud':
                rec.health_status = (
                    'healthy' if rec.session_state == 'connected' else 'down')
                continue
            if rec.session_state == 'connected' and rec.sidecar_running:
                if rec.last_seen_dt and (now - rec.last_seen_dt) > _td(minutes=15):
                    rec.health_status = 'degraded'
                else:
                    rec.health_status = 'healthy'
            elif rec.session_state in ('disconnected', 'logged_out') or not rec.sidecar_running:
                rec.health_status = 'down'
            else:
                rec.health_status = 'unknown'

    @api.model
    def _cron_refresh_avatars(self):
        """Phase 26J: refresh stale partner avatars (>30 days) for partners
        active on connected WhatsApp accounts. Best-effort; sidecar-down is silent."""
        from datetime import timedelta
        cutoff = fields.Datetime.now() - timedelta(days=30)
        for account in self.search([
            ('active', '=', True),
            ('session_state', '=', 'connected'),
            ('auto_sync_avatars', '=', True),
        ]):
            try:
                channels = self.env['discuss.channel'].sudo().search([
                    ('channel_type', '=', 'whatsapp'),
                    ('owa_account_id', '=', account.id),
                    ('whatsapp_partner_id', '!=', False),
                ], limit=200)
                api = BaileysApi(account)
                for ch in channels:
                    p = ch.whatsapp_partner_id
                    if not p:
                        continue
                    if p.image_1920 and (p.write_date or fields.Datetime.now()) > cutoff:
                        continue
                    try:
                        digits = ''.join(c for c in (p.phone or '') if c.isdigit())
                        if not digits:
                            continue
                        result = api._request('GET', f'/profile-pic/{digits}@s.whatsapp.net')
                        if result and result.get('image_b64'):
                            p.image_1920 = result['image_b64']
                    except Exception:
                        continue
            except Exception:
                _logger.exception("avatar refresh failed for %s", account.id)

    @api.model
    def _cron_heartbeat(self):
        """Phase 8: ping the sidecar for each connected account; updates
        last_seen_dt + is_listening. Graceful on sidecar-down (just leaves
        last_seen_dt stale and recomputes health_status)."""
        # Sidecar heartbeat is QR-only; Cloud API accounts have no sidecar and
        # their session_state is owned by action_verify_connection + the
        # Meta webhook, so they must be excluded or this cron would keep
        # flipping a connected Cloud account back to 'disconnected'.
        for account in self.search([('active', '=', True),
                                    ('connection_type', '=', 'qr')]):
            try:
                api = account._get_baileys_api()
                status = api.get_session_status()
                state = (status or {}).get('status') or 'unknown'
                vals = {
                    'last_seen_dt': fields.Datetime.now(),
                    'is_listening': state == 'connected',
                }
                if state and state != account.session_state:
                    vals['session_state'] = state
                account.write(vals)
            except Exception:
                # Sidecar unreachable — flip is_listening off but don't bury
                # last_seen_dt so we know how long it's been.
                if account.is_listening:
                    account.is_listening = False

    @api.model
    def _handle_presence_update(self, account, chat_jid, presences):
        """Phase B3: surface inbound presence (online / typing / paused) on
        the matching Discuss WhatsApp channel via a bus notification.

        Cheap to call frequently — it never writes the DB, only pushes a
        transient bus message that any open Discuss tab can ignore.
        """
        if not chat_jid or not presences:
            return False
        Channel = self.env['discuss.channel'].sudo()
        # DM JIDs arrive as '917012345678@s.whatsapp.net' but whatsapp_number
        # stores bare digits for 1:1 channels; group/newsletter JIDs (@g.us,
        # @newsletter, @broadcast) are stored verbatim. Without this strip the
        # equality match always failed for DMs, so the green dot / typing
        # indicator never lit up for any 1:1 conversation. (#presence)
        lookup_jid = (chat_jid.split('@')[0]
                      if '@s.whatsapp.net' in chat_jid else chat_jid)
        channel = Channel.search([
            ('owa_account_id', '=', account.id),
            ('whatsapp_number', '=', lookup_jid),
            ('channel_type', '=', 'whatsapp'),
        ], limit=1)
        if not channel:
            return False
        # Compact the payload: only forward the chat-level "is anyone typing?".
        any_typing = any(
            (p.get('lastKnownPresence') in ('composing', 'recording'))
            for p in presences
        )
        any_online = any(
            (p.get('lastKnownPresence') == 'available')
            for p in presences
        )
        try:
            channel._bus_send('owa_presence', {
                'channel_id': channel.id,
                'typing': any_typing,
                'online': any_online,
            })
        except Exception:  # pragma: no cover -- bus push is best-effort
            _logger.exception(
                "owa.account._handle_presence_update: bus push failed for jid=%s",
                chat_jid,
            )
        return True

    def action_run_diagnostics(self):
        """Phase 8: chatter-posted diagnostic report. Replaces the
        ``openclaw channels doctor`` CLI with a one-click admin button."""
        self.ensure_one()
        from odoo.addons.open_whatsapp_connector.tools.sidecar_manager import is_sidecar_running
        from odoo.addons.open_whatsapp_connector.tools.baileys_api import BaileysApi
        sidecar_url = self.sidecar_url or 'http://localhost:3100'
        sidecar_up = is_sidecar_running(sidecar_url)
        outgoing = self.env['owa.message'].sudo().search_count([
            ('wa_account_id', '=', self.id), ('state', '=', 'outgoing'),
        ])
        last_msg = self.env['owa.message'].sudo().search([
            ('wa_account_id', '=', self.id),
        ], order='create_date desc', limit=1)
        try:
            status = BaileysApi(self).get_session_status()
            sidecar_state = (status or {}).get('status', 'unknown')
        except Exception as e:
            sidecar_state = f'unreachable: {e}'

        rows = [
            ('Sidecar URL', sidecar_url),
            ('Sidecar process up', '✓' if sidecar_up else '✗'),
            ('Sidecar session state', sidecar_state),
            ('Odoo session_state', self.session_state),
            ('health_status', self.health_status),
            ('is_listening', self.is_listening),
            ('Outgoing queue depth', outgoing),
            ('Last message at', fields.Datetime.to_string(last_msg.create_date) if last_msg else '—'),
            ('last_seen_dt', fields.Datetime.to_string(self.last_seen_dt) if self.last_seen_dt else '—'),
        ]
        body = Markup(
            '<table class="table table-sm" style="margin: 0;"><tbody>'
            + ''.join(
                Markup('<tr><td style="font-weight:600; padding-right: 14px;">{}</td>'
                       '<td>{}</td></tr>').format(k, v)
                for k, v in rows
            )
            + '</tbody></table>'
        )
        self.message_post(body=body, subject="WhatsApp Diagnostics")
        return True

    def _effective_send_read_receipts(self):
        """Read-receipts actually sent to the sidecar: suppressed when stealth
        mode is on (stealth overrides the granular toggle). (#diag)"""
        self.ensure_one()
        return bool(self.send_read_receipts) and not self.stealth_mode

    def write(self, vals):
        """Phase 4: when send_read_receipts (or stealth_mode) toggles on a
        connected session, push the change to the sidecar without requiring a
        reconnect."""
        result = super().write(vals)
        if 'send_read_receipts' in vals or 'stealth_mode' in vals:
            for account in self:
                if account.session_state == 'connected':
                    try:
                        api = account._get_baileys_api()
                        api.update_session_config(
                            send_read_receipts=account._effective_send_read_receipts())
                    except Exception:
                        _logger.exception("Failed to push read-receipt config to sidecar for %s", account.id)
        return result

    # Counts
    message_count = fields.Integer(compute='_compute_message_count')

    @api.constrains('notify_user_ids')
    def _check_notify_user_ids(self):
        for account in self:
            if len(account.notify_user_ids) < 1:
                raise ValidationError(_("At least one user to notify is required"))

    @api.constrains('name')
    def _check_name_normalized(self):
        """Phase 11: account name is used as part of the sidecar account_id
        (`<dbname>_<id>` plus `name` is the human reference). Reject leading/
        trailing whitespace and inner double-spaces so account_ids are
        consistent across the codebase."""
        for account in self:
            if not account.name:
                continue
            stripped = account.name.strip()
            if stripped != account.name or '  ' in stripped:
                raise ValidationError(_(
                    "Account name '%s' has leading/trailing whitespace or "
                    "double spaces. Please use the cleaned form '%s'."
                ) % (account.name, ' '.join(stripped.split())))

    @api.depends('name')
    def _compute_webhook_secret(self):
        for rec in self:
            if rec.id and not rec.webhook_secret:
                rec.webhook_secret = ''.join(
                    secrets.choice(string.ascii_letters + string.digits) for _ in range(16)
                )

    def _compute_callback_url(self):
        for account in self:
            db_name = quote(self.env.cr.dbname or '')
            account.callback_url = (
                account.get_base_url()
                + f'/open_whatsapp_connector/webhook/incoming?db={db_name}'
            )

    def _compute_message_count(self):
        for account in self:
            account.message_count = self.env['owa.message'].search_count(
                [('wa_account_id', '=', account.id)]
            )

    @api.depends('sidecar_url', 'connection_type')
    def _compute_sidecar_running(self):
        from odoo.addons.open_whatsapp_connector.tools.sidecar_manager import is_sidecar_running
        cache = {}
        for account in self:
            # The sidecar is a QR-transport concept; Cloud API accounts use
            # Meta's Graph API and have no sidecar. Skip the ping for them so
            # the QR-only buttons stay hidden and we don't waste a request.
            if account.connection_type and account.connection_type != 'qr':
                account.sidecar_running = False
                continue
            url = account.sidecar_url or 'http://localhost:3100'
            if url not in cache:
                cache[url] = is_sidecar_running(url)
            account.sidecar_running = cache[url]

    def _get_baileys_api(self):
        """Get a BaileysApi instance for this account.

        Backstop for the whole family of QR-only actions (connect, logout,
        profile picture, pairing code, blocklist sync, test connection, …):
        a cloud account has no Baileys sidecar session, so calling any of
        them would hit the sidecar and surface a raw 500 traceback. Raise a
        clean, explanatory UserError instead. The views also hide these
        controls for cloud accounts; this guards the code path itself.
        """
        self.ensure_one()
        if self.connection_type and self.connection_type != 'qr':
            raise UserError(_(
                "This action is only available for QR-connected WhatsApp "
                "accounts. '%s' uses the Official Cloud API, which manages "
                "the profile, pairing and connection through the Meta "
                "console instead.") % (self.name or ''))
        return BaileysApi(self)

    # ── Official Cloud API transport seam ─────────────────────────────
    def _get_cloud_api(self):
        """Return a CloudApi client bound to this account."""
        self.ensure_one()
        from odoo.addons.open_whatsapp_connector.tools.cloud_api import CloudApi
        return CloudApi(self)

    def _dispatch_send(self, kind, **payload):
        """Transport-neutral outbound dispatch.

        ``kind`` in {'text', 'media', 'reaction', 'template', 'mark_read'}.
        Routes by ``connection_type`` and returns the provider message id
        (a ``wamid...`` for cloud accounts). Keyword names in ``payload``
        must match the target client's method signature; the send-queue
        builds the right kwargs per transport (see owa.message).
        """
        self.ensure_one()
        method = kind if kind == 'mark_read' else 'send_' + kind
        if self.connection_type == 'cloud':
            api = self._get_cloud_api()
        else:
            # QR / Baileys path — preserve existing behaviour.
            api = self._get_baileys_api()
        return getattr(api, method)(**payload)

    # ── Cloud 24h customer-service window ──────────────────────────────
    def _cloud_within_window(self, mobile):
        """True when an INBOUND owa.message exists for ``mobile`` on this
        account within the last 24 hours.

        Meta's Cloud API only allows free-form (non-template) messages inside
        a 24h customer-service window opened by the customer's last inbound
        message. Outside that window only an approved template may be sent.
        """
        self.ensure_one()
        if not mobile:
            return False
        number = (mobile or '').lstrip('+')
        cutoff = fields.Datetime.now() - timedelta(hours=24)
        # Match either the raw or the formatted form of the number; inbound
        # rows store mobile_number / mobile_number_formatted as bare digits.
        return bool(self.env['owa.message'].sudo().search_count([
            ('wa_account_id', '=', self.id),
            ('message_type', '=', 'inbound'),
            ('create_date', '>=', cutoff),
            '|',
                ('mobile_number', 'in', (number, '+' + number, mobile)),
                ('mobile_number_formatted', 'in', (number, '+' + number, mobile)),
        ]))

    # ── Cloud delivery/read/failed status receipts ────────────────────
    _CLOUD_STATUS_MAP = {
        'sent': 'sent',
        'delivered': 'delivered',
        'read': 'read',
        'failed': 'error',
    }

    def _apply_cloud_status(self, status):
        """Apply a Meta status receipt (sent/delivered/read/failed) to the
        matching outbound owa.message, correlated by ``wa_message_uid``."""
        wamid = status.get('id')
        new_state = self._CLOUD_STATUS_MAP.get(status.get('status'))
        if not wamid or not new_state:
            return
        msg = self.env['owa.message'].sudo().search([
            ('wa_message_uid', '=', wamid),
            ('wa_account_id', '=', self.id),
        ], limit=1)
        if not msg:
            return
        vals = {'state': new_state}
        if new_state == 'error':
            errs = status.get('errors') or [{}]
            vals['error_message'] = (
                errs[0].get('title') or errs[0].get('message') or 'failed')
        msg.write(vals)

    # ── Cloud: inbound call events ─────────────────────────────────────
    def _handle_cloud_call(self, call):
        """Transport-neutral intake for one Meta Cloud API call event.

        Maps the Meta ``calls[]`` payload onto the shared owa.call.log
        pipeline so an inbound WhatsApp Business call shows up as a call
        log / missed-call entry with the same chatter line, ringing toast
        and missed-call auto-reply the QR transport already produces.

        Only inbound (``USER_INITIATED``) calls are handled; outbound
        (``BUSINESS_INITIATED``) call legs we placed are ignored. The
        Calling API is voice-only, so the resulting log is always voice.
        """
        self.ensure_one()
        from odoo.addons.open_whatsapp_connector.tools.meta_inbound import (
            normalize_meta_call)
        payload = normalize_meta_call(call)
        if not payload:
            return False
        if payload.get('direction') and payload['direction'] != 'USER_INITIATED':
            return False
        # A `terminate` maps to 'missed'; don't let it regress a call we
        # already settled locally (e.g. the agent clicked Reject, then Meta
        # sends the matching terminate webhook).
        if payload.get('status') == 'timeout':
            existing = self.env['owa.call.log'].sudo().search([
                ('wa_account_id', '=', self.id),
                ('call_id', '=', payload['id']),
            ], limit=1)
            if existing and existing.state in ('rejected', 'accepted'):
                return existing
        return self.env['owa.call.log'].sudo()._record_call_event(self, payload)

    # ── Cloud connection health check ─────────────────────────────────
    def action_verify_connection(self):
        """Ping the Graph API for each cloud account; flip session_state to
        'connected' on success, 'disconnected' on any failure."""
        from odoo.addons.open_whatsapp_connector.tools.cloud_api import (
            CloudApi, CloudApiError)
        for acc in self.filtered(lambda a: a.connection_type == 'cloud'):
            try:
                CloudApi(acc).health()
                acc.session_state = 'connected'
            except (CloudApiError, Exception) as e:
                acc.session_state = 'disconnected'
                _logger.warning(
                    "Cloud verify failed for %s: %s", acc.name, e)
        return True

    def action_sync_templates(self):
        """Pull message templates + statuses from Meta into owa.cloud.template
        (upsert by wa_template_uid, else by name+language)."""
        Template = self.env['owa.cloud.template'].sudo()
        from odoo.addons.open_whatsapp_connector.tools.cloud_api import (
            CloudApiError)
        for acc in self.filtered(lambda a: a.connection_type == 'cloud'):
            try:
                rows = acc._get_cloud_api().sync_templates()
            except (CloudApiError, Exception) as e:
                _logger.warning("Template sync failed for %s: %s", acc.name, e)
                continue
            for data in rows:
                uid = data.get('id')
                rec = Template.browse()
                if uid:
                    rec = Template.search(
                        [('wa_template_uid', '=', str(uid))], limit=1)
                if not rec:
                    rec = Template.search([
                        ('wa_account_id', '=', acc.id),
                        ('name', '=', data.get('name')),
                        ('lang_code', '=', data.get('language') or 'en'),
                    ], limit=1)
                if not rec:
                    rec = Template.create({
                        'name': data.get('name') or 'template',
                        'lang_code': data.get('language') or 'en',
                        'wa_account_id': acc.id,
                        'wa_template_uid': uid,
                    })
                rec._apply_meta_template_dict(data)
        return True

    def button_connect(self):
        """Connect to WhatsApp via the sidecar (triggers QR code)."""
        self.ensure_one()
        if not self.enabled:
            from odoo.exceptions import UserError as _UserError
            raise _UserError(_(
                "Account is disabled. Tick 'Enabled' before connecting."
            ))
        if self.pairing_method == 'code' and not self.pairing_phone:
            from odoo.exceptions import UserError as _UserError
            raise _UserError(_(
                "Set the WhatsApp phone number in 'Pairing Phone' below before "
                "clicking Connect, or switch Pairing Method to 'Scan QR Code'."
            ))
        self._ensure_sidecar_running()
        api = self._get_baileys_api()
        try:
            result = api.create_session(
                odoo_base_url=self.get_base_url(),
                callback_url=self.callback_url,
                webhook_secret=self.webhook_secret,
                send_read_receipts=self._effective_send_read_receipts(),
            )
            state = result.get('status', 'connecting')
            self.write({
                'session_state': state,
                'qr_code_base64': result.get('qr_base64', False),
            })
            # If already connected (existing creds), poll briefly for phone number
            if state == 'connected':
                import time
                time.sleep(1)
                try:
                    status = api.get_session_status()
                    if status.get('phone_number'):
                        self.write({'phone_number': status['phone_number']})
                except Exception:
                    pass
                # Phase B3 — bulk-subscribe presence for every existing
                # WhatsApp channel so the discuss UI can show online/typing
                # without waiting for the next inbound message.
                try:
                    self._subscribe_presence_for_channels(api=api)
                except Exception:
                    _logger.exception(
                        "subscribe presence for channels failed for account %s", self.id)
        except BaileysError as e:
            raise UserError(_("Failed to connect: %s", e.error_message))

    @api.model
    def cleanup_duplicate_whatsapp_channels(self):
        """Merge duplicate WhatsApp channels having the same
        (owa_account_id, whatsapp_number) into the oldest one. Moves
        every mail.message and member to the keeper, then unlinks the
        duplicates. Idempotent — safe to call repeatedly."""
        self.env.cr.execute("""
            SELECT owa_account_id, whatsapp_number, array_agg(id ORDER BY id) AS ids
            FROM discuss_channel
            WHERE channel_type = 'whatsapp'
              AND owa_account_id IS NOT NULL
              AND whatsapp_number IS NOT NULL
            GROUP BY owa_account_id, whatsapp_number
            HAVING COUNT(*) > 1
        """)
        groups_merged = 0
        channels_deleted = 0
        Channel = self.env['discuss.channel'].sudo()
        for _acc_id, _number, ids in self.env.cr.fetchall():
            keeper_id = ids[0]
            dupe_ids = list(ids[1:])
            if not dupe_ids:
                continue
            self.env.cr.execute("""
                UPDATE mail_message
                SET res_id = %s
                WHERE model = 'discuss.channel'
                  AND res_id = ANY(%s)
            """, (keeper_id, dupe_ids))
            # Move members from dupes to keeper, skipping any whose
            # (channel, partner) pair already exists on the keeper to
            # avoid violating discuss_channel_member's unique index.
            self.env.cr.execute("""
                DELETE FROM discuss_channel_member
                WHERE channel_id = ANY(%s)
                  AND partner_id IN (
                    SELECT partner_id FROM discuss_channel_member
                    WHERE channel_id = %s
                  )
            """, (dupe_ids, keeper_id))
            self.env.cr.execute("""
                UPDATE discuss_channel_member
                SET channel_id = %s
                WHERE channel_id = ANY(%s)
            """, (keeper_id, dupe_ids))
            Channel.browse(dupe_ids).unlink()
            groups_merged += 1
            channels_deleted += len(dupe_ids)
        return {'groups_merged': groups_merged, 'channels_deleted': channels_deleted}

    def _subscribe_presence_for_channels(self, api=None):
        """Push every existing WhatsApp channel JID for this account to
        the sidecar so it subscribes to their presence updates."""
        self.ensure_one()
        Channel = self.env['discuss.channel'].sudo()
        channels = Channel.search([
            ('owa_account_id', '=', self.id),
            ('channel_type', '=', 'whatsapp'),
            ('whatsapp_number', '!=', False),
        ])
        jids = sorted({ch.whatsapp_number for ch in channels if ch.whatsapp_number})
        if not jids:
            return {'subscribed': 0, 'total': 0}
        api = api or self._get_baileys_api()
        return api.subscribe_presence(jids)

    def _ensure_sidecar_running(self):
        """Try to auto-start sidecar if configured and not reachable."""
        from odoo.addons.open_whatsapp_connector.tools.sidecar_manager import (
            is_sidecar_running, start_sidecar,
        )
        if is_sidecar_running(self.sidecar_url):
            return
        ICP = self.env['ir.config_parameter'].sudo()
        auto_start = ICP.get_param('open_whatsapp_connector.sidecar_auto_start', 'False')
        sidecar_path = ICP.get_param('open_whatsapp_connector.sidecar_path', '')
        if auto_start == 'True' and sidecar_path:
            port = 3100
            try:
                from urllib.parse import urlparse
                port = urlparse(self.sidecar_url).port or 3100
            except Exception:
                pass
            api_key = self.sudo().sidecar_api_key or ''
            if start_sidecar(sidecar_path, port=port, api_key=api_key):
                import time
                time.sleep(2)

    def button_refresh_status(self):
        """Refresh session status from the sidecar."""
        self.ensure_one()
        api = self._get_baileys_api()
        try:
            result = api.get_session_status()
            vals = {
                'session_state': result.get('status', 'disconnected'),
                'qr_code_base64': result.get('qr_base64', False),
            }
            if result.get('phone_number'):
                vals['phone_number'] = result['phone_number']
            self.write(vals)
        except BaileysError:
            self.write({'session_state': 'disconnected'})

    def button_disconnect(self):
        """Disconnect the WhatsApp session."""
        self.ensure_one()
        api = self._get_baileys_api()
        try:
            api.disconnect()
        except BaileysError:
            pass
        self.write({
            'session_state': 'disconnected',
            'qr_code_base64': False,
        })

    def button_logout(self):
        """Logout and delete auth state on the sidecar."""
        self.ensure_one()
        api = self._get_baileys_api()
        try:
            api.logout()
        except BaileysError:
            pass
        self.write({
            'session_state': 'logged_out',
            'qr_code_base64': False,
            'phone_number': False,
        })

    # ── Phase C3: WhatsApp profile picture ────────────────────────────
    def action_push_profile_picture(self):
        """Upload this account's avatar to WhatsApp as the business
        profile picture. Pulls from ``image_1920`` if set."""
        self.ensure_one()
        if not self.image_1920:
            raise UserError(_(
                "Set an image on this WhatsApp account first."))
        api = self._get_baileys_api()
        api.update_profile_picture(base64.b64decode(self.image_1920))
        self.message_post(body=_("WhatsApp profile picture updated."))
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _("WhatsApp profile updated"),
                'message': _("The new picture is now visible to your contacts on WhatsApp."),
                'sticky': False,
            },
        }

    def action_clear_profile_picture(self):
        """Remove the WhatsApp business profile picture for this account."""
        self.ensure_one()
        api = self._get_baileys_api()
        api.remove_profile_picture()
        self.message_post(body=_("WhatsApp profile picture cleared."))
        return True

    # ── Phase C2: WhatsApp blocklist sync ─────────────────────────────
    def action_sync_whatsapp_blocklist(self):
        """Pull the current WhatsApp blocklist and reconcile into ``owa.blacklist``.
        Adds rows that exist on WhatsApp but not in Odoo; does NOT remove
        Odoo-only rows (those usually exist for a reason)."""
        self.ensure_one()
        api = self._get_baileys_api()
        jids = api.fetch_whatsapp_blocklist() or []
        Blacklist = self.env['owa.blacklist'].sudo()
        added = 0
        for jid in jids:
            if not jid or '@' not in jid:
                continue
            phone = jid.split('@', 1)[0].split(':', 1)[0]
            if not phone:
                continue
            # owa.blacklist has no phone_number / wa_account_id fields — the
            # real fields are phone / phone_formatted / reason / active. The
            # previous code raised ValueError(Invalid field) on every click of
            # the "Sync from WhatsApp" button. (#multiacct)
            if Blacklist.search_count([('phone', '=', phone)]):
                continue
            Blacklist.create({
                'phone': phone,
                'reason': _("Synced from WhatsApp blocklist"),
            })
            added += 1
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _("WhatsApp blocklist synced"),
                'message': _("%(added)d new entries added; %(total)d total on WhatsApp.") % {
                    'added': added, 'total': len(jids),
                },
                'sticky': False,
            },
        }

    # ── Phase D: WhatsApp pairing-code login ──────────────────────────
    def action_request_pairing_code(self):
        """Request an 8-character WhatsApp pairing code as an alternative
        to scanning the QR. Phone number for pairing comes from
        ``self.pairing_phone`` (set by the user on the connect wizard)."""
        self.ensure_one()
        phone = (self.pairing_phone or '').strip()
        if not phone:
            raise UserError(_("Enter the WhatsApp account phone number first (digits only, country code included)."))
        # Pairing-code requires a FRESH socket where the gateway hasn't yet
        # registered. Statuses 'qr_pending' / 'connecting' are fine to reuse;
        # 'connected' / 'logged_out' / 'disconnected' / missing all mean the
        # in-memory socket is either already paired or torn down — recreate
        # so requestPairingCode runs against a live, unregistered socket.
        api = self._get_baileys_api()
        try:
            status_resp = api.get_session_status() or {}
        except BaileysError:
            status_resp = {}
        current = status_resp.get('status') or ''
        if current not in ('qr_pending', 'connecting'):
            self._ensure_sidecar_running()
            base_url = self.env['ir.config_parameter'].sudo().get_param(
                'web.base.url', 'http://localhost:8069')
            api.create_session(
                odoo_base_url=base_url,
                webhook_secret=self.webhook_secret,
                callback_url=self.callback_url or None,
                send_read_receipts=self._effective_send_read_receipts(),
            )
        # Now ask for the pairing code.
        result = api.request_pairing_code(phone)
        code = (result or {}).get('code') or ''
        if not code:
            raise UserError(_(
                "Sidecar did not return a pairing code. Make sure the sidecar is running, "
                "the account is freshly disconnected (logout first if it was paired before), "
                "and the phone number is correct."
            ))
        self.write({'pairing_code': code})
        # Log the code to chatter so the user always has a permanent record
        # even if the form reload races the toast — this also covers the case
        # where the toast is dismissed before the user types it on the phone.
        from markupsafe import Markup
        self.message_post(
            body=Markup(_(
                "WhatsApp pairing code requested for %(phone)s: <b>%(code)s</b>"
            )) % {'phone': phone, 'code': code},
        )
        # Return a notification chained to a soft reload so the form picks up
        # the freshly-written pairing_code and shows it instead of the stale
        # value from a previous attempt.
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _("WhatsApp pairing code"),
                'message': _("Enter %(code)s on the phone in Settings → Linked Devices → Link with phone number.") % {
                    'code': code,
                },
                'sticky': True,
                'next': {'type': 'ir.actions.client', 'tag': 'soft_reload'},
            },
        }

    def button_test_connection(self):
        """Test connection to the sidecar service."""
        self.ensure_one()
        api = self._get_baileys_api()
        try:
            result = api.health_check()
            if result.get('status') == 'ok':
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Connection Successful"),
                        'message': _("Sidecar service is running."),
                        'type': 'success',
                        'sticky': False,
                    }
                }
        except BaileysError as e:
            raise UserError(_("Connection failed: %s", e.error_message))

    def button_start_sidecar(self):
        """Start the sidecar process."""
        from odoo.addons.open_whatsapp_connector.tools.sidecar_manager import (
            is_sidecar_running, start_sidecar,
        )
        self.ensure_one()
        if is_sidecar_running(self.sidecar_url):
            return self._notify_and_reload(_("Sidecar is already running."), 'warning')
        ICP = self.env['ir.config_parameter'].sudo()
        sidecar_path = ICP.get_param('open_whatsapp_connector.sidecar_path', '')
        if not sidecar_path:
            raise UserError(_(
                "Sidecar path not configured. Go to Settings > Open WhatsApp Connector."))
        port = 3100
        try:
            from urllib.parse import urlparse
            port = urlparse(self.sidecar_url).port or 3100
        except Exception:
            pass
        api_key = self.sudo().sidecar_api_key or ''
        if start_sidecar(sidecar_path, port=port, api_key=api_key, sidecar_url=self.sidecar_url):
            return self._notify_and_reload(_("Sidecar started successfully."))
        raise UserError(_("Failed to start sidecar. Check the logs for details."))

    def button_stop_sidecar(self):
        """Stop the sidecar process."""
        from odoo.addons.open_whatsapp_connector.tools.sidecar_manager import stop_sidecar
        self.ensure_one()
        if stop_sidecar():
            return self._notify_and_reload(_("Sidecar stopped."))
        return self._notify_and_reload(_("Sidecar was not running."), 'warning')

    def _notify_and_reload(self, message, msg_type='success'):
        """Return a notification + reload action."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("WhatsApp"),
                'message': message,
                'type': msg_type,
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            },
        }

    def _notify_success(self, message):
        """Return a success notification action."""
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("WhatsApp"),
                'message': message,
                'type': 'success',
                'sticky': False,
            },
        }

    def _cron_sync_session_status(self):
        """Cron: Sync session status for all active QR accounts. Cloud API
        accounts have no sidecar session to reconcile (their state is set by
        action_verify_connection + the Meta webhook), so they are excluded."""
        accounts = self.search([
            ('active', '=', True),
            ('connection_type', '=', 'qr'),
            ('session_state', 'in', ('connected', 'connecting', 'qr_pending')),
        ])
        for account in accounts:
            try:
                account.button_refresh_status()
            except Exception:
                _logger.exception("Failed to sync session status for account %s", account.name)

    @classmethod
    def _reset_stale_session_state_after_restart(cls, env):
        """One-shot startup correction.

        After an OS reboot or unexpected sidecar crash, ``session_state`` rows
        keep saying ``connected`` even though the Node sidecar process is no
        longer running. The web UI then shows the wrong badges until either
        the user clicks Refresh or the periodic cron fires (up to 5 min later).

        This method runs once per worker on registry load (see
        :meth:`_register_hook`) and cheaply resets any
        ``connected|connecting|qr_pending`` row to ``disconnected`` when its
        sidecar URL fails the live ``/health`` probe. Sidecars that ARE up
        are left untouched; the row will be corrected by the next cron pass.
        """
        from odoo.addons.open_whatsapp_connector.tools.sidecar_manager import (
            is_sidecar_running,
        )
        try:
            Account = env['owa.account'].sudo()
            # QR-only: a Cloud API account is "connected" without any sidecar,
            # so it must not be reset by the sidecar /health probe below.
            stale = Account.search([
                ('active', '=', True),
                ('connection_type', '=', 'qr'),
                ('session_state', 'in', ('connected', 'connecting', 'qr_pending')),
            ])
            if not stale:
                return
            url_cache = {}
            to_reset = Account.browse()
            for acc in stale:
                url = acc.sidecar_url or 'http://localhost:3100'
                if url not in url_cache:
                    url_cache[url] = is_sidecar_running(url)
                if not url_cache[url]:
                    to_reset |= acc
            if to_reset:
                to_reset.write({
                    'session_state': 'disconnected',
                    'qr_code_base64': False,
                })
                _logger.info(
                    "owa.account: reset %d stale session_state row(s) on startup",
                    len(to_reset),
                )
        except Exception:
            _logger.exception("startup session_state reset failed")

    def _register_hook(self):
        """Hook fired once per worker after the registry is ready. Used to
        run :meth:`_reset_stale_session_state_after_restart` so the UI shows
        accurate state immediately on Odoo (re)start instead of waiting for
        the Sync-Session-Status cron."""
        super()._register_hook()
        try:
            with self.pool.cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                self._reset_stale_session_state_after_restart(env)
        except Exception:
            # Never let a startup hook fail the registry load — the cron
            # will catch up within minutes.
            _logger.exception("owa.account._register_hook startup correction failed")

    def _find_active_channel(self, number, partner=None):
        """Find an existing active discuss.channel for a WhatsApp number."""
        self.ensure_one()
        domain = [
            ('channel_type', '=', 'whatsapp'),
            ('whatsapp_number', '=', number),
            ('owa_account_id', '=', self.id),
        ]
        channel = self.env['discuss.channel'].search(domain, limit=1, order='id desc')
        return channel

    def _get_or_create_channel(self, number, sender_name=None):
        """Get or create a discuss.channel for the given WhatsApp number."""
        self.ensure_one()
        channel = self._find_active_channel(number)
        if channel:
            return channel

        # Find or create partner
        partner = self.env['res.partner']._find_or_create_from_wa_number(number, sender_name)

        recipient_name = (
            partner.name
            if partner and partner.name and partner.name != partner.phone
            else False
        )
        channel_name = f"{recipient_name} ({number})" if recipient_name else number

        # Create channel
        channel = self.env['discuss.channel'].with_context(
            mail_create_nosubscribe=True
        ).create({
            'name': channel_name,
            'channel_type': 'whatsapp',
            'whatsapp_number': number,
            'owa_account_id': self.id,
            'whatsapp_partner_id': partner.id if partner else False,
            'channel_member_ids': [
                (0, 0, {'partner_id': partner.id}) if partner else (0, 0, {}),
            ] + [
                (0, 0, {'partner_id': user.partner_id.id})
                for user in self.notify_user_ids
            ],
        })
        return channel

    # ══════════════════════════════════════════════════════════════════
    # Transport-neutral inbound processing
    # ══════════════════════════════════════════════════════════════════
    def _handle_inbound(self, normalized, claim_dedupe=True):
        """Shared inbound pipeline for every transport (QR + Cloud).

        ``normalized`` keys (see tools.meta_inbound.normalize_meta_message and
        the QR normalizer in controllers/main.py):
          from_number, sender_name, msg_uid, type, body, media,
          reply_to_wamid, timestamp, phone_number_id, raw
        plus optional QR-specific keys:
          chat_type, participant, attachment_ids (pre-decoded), is_group

        ``claim_dedupe`` — when True (Cloud webhook / direct callers) this
        method claims the msg_uid in owa.inbound.dedupe and short-circuits on
        a duplicate. The QR controller already claims before its access-control
        step (to keep the legacy ordering byte-identical), so it passes
        ``claim_dedupe=False``.

        Behaviour is byte-identical to the legacy
        controllers/main.py::_process_inbound_message body for the QR path.
        Side-effects (channel + message_post + rules + chatbot + auto-reply)
        are the same; the method returns nothing.
        """
        self.ensure_one()
        account = self
        from_number = normalized.get('from_number') or ''
        sender_name = normalized.get('sender_name') or ''
        msg_id = normalized.get('msg_uid') or ''
        msg_type = normalized.get('type') or 'text'
        chat_type = normalized.get('chat_type') or 'direct'
        participant_jid = normalized.get('participant') or ''
        reply_to_wamid = normalized.get('reply_to_wamid')

        if not from_number:
            return

        # Phase 2: explicit dedupe via owa.inbound.dedupe (covers worker races
        # the gateway's in-memory dedupe can't catch). The QR controller claims
        # earlier (before access-control) and passes claim_dedupe=False.
        if claim_dedupe and msg_id and not self.env['owa.inbound.dedupe'].sudo().claim(msg_id, account.id):
            _logger.info("Skipping duplicate inbound msg_uid=%s (account=%s)", msg_id, account.id)
            return

        # Use the central WhatsApp channel helper so inbound and outbound
        # messages resolve to the same normalized thread and new channels are broadcast.
        channel = self.env['discuss.channel'].sudo()._get_whatsapp_channel(
            from_number,
            account,
            sender_name=sender_name,
            create_if_not_found=True,
        )
        if not channel:
            return
        # Welcome auto-replies fire only when this is the first contact —
        # i.e. the channel was created by the call above (no inbound history yet).
        is_new_channel = (
            bool(channel.create_date)
            and (fields.Datetime.now() - channel.create_date) < timedelta(seconds=30)
            and not channel.message_ids
        )

        parent_wa_message = self.env['owa.message'].sudo()
        if reply_to_wamid:
            parent_wa_message = self.env['owa.message'].sudo().search([
                ('msg_uid', '=', reply_to_wamid),
                ('message_type', '=', 'outbound'),
                ('wa_account_id', '=', account.id),
            ], limit=1)

        # Body + attachments: the transport already prepared these. The QR
        # normalizer decodes inline base64 media into ir.attachment ids and a
        # finished body; the Cloud normalizer hands us a media dict (download
        # is a Phase-2 item) so we surface a placeholder body for now.
        body = normalized.get('body') or ''
        attachment_ids = list(normalized.get('attachment_ids') or [])
        media = normalized.get('media')
        labels = {
            'image': '📷 Image',
            'video': '🎥 Video',
            'audio': '🎵 Audio',
            'document': '📄 Document',
            'sticker': '🏷️ Sticker',
        }
        # Cloud inbound media (Phase 2): the normalizer hands us a media dict
        # with the Meta media id (no bytes). Download via the Graph API and
        # attach. The QR transport already decodes inline bytes into
        # attachment_ids upstream, so this branch only fires for cloud.
        if (media and media.get('id') and not attachment_ids
                and account.connection_type == 'cloud'):
            try:
                content, mime = account._get_cloud_api().download_media(
                    media['id'])
                if content:
                    fname = (media.get('filename')
                             or f"{msg_type or 'file'}_{media['id']}")
                    attachment = self.env['ir.attachment'].sudo().create({
                        'name': fname,
                        'datas': base64.b64encode(content),
                        'mimetype': mime or media.get('mime')
                        or 'application/octet-stream',
                        'res_model': 'discuss.channel',
                        'res_id': channel.id,
                    })
                    attachment_ids.append(attachment.id)
            except Exception:
                _logger.exception(
                    "Cloud inbound media download failed for media id=%s",
                    media.get('id'))
        if media and not attachment_ids and not body:
            # Media we couldn't fetch (download failed / no id) — placeholder.
            label = labels.get(msg_type, f'[{msg_type}]')
            body = f"{label} <em>(media download pending)</em>"

        # Reply-context envelope (Phase 2): when this is a reply to one of our
        # outbound messages, prepend a quoted snippet so the agent sees what
        # the contact is replying to.
        if parent_wa_message and parent_wa_message.mail_message_id:
            quoted = parent_wa_message.mail_message_id.body or ''
            quoted_plain = (quoted or '').strip()
            if quoted_plain:
                body = (
                    f"<blockquote class=\"owa-reply-quote\" "
                    f"style=\"border-left: 3px solid #25D366; padding-left: 8px; "
                    f"color: #6c757d; margin: 0 0 6px;\">"
                    f"<small>↩️ Replying to:</small><br/>{quoted}</blockquote>"
                    f"{body}"
                )

        # Author attribution: for groups every member's reply must be
        # attributed to the *participant* (actual sender), not to the group's
        # ``whatsapp_partner_id`` — otherwise the chat shows every message
        # under the same anonymous group avatar with no way to tell who said
        # what. For DMs the sender == the channel partner, so reuse it.
        author_partner = channel.whatsapp_partner_id
        if chat_type == 'group':
            participant_digits = participant_jid.split('@')[0].lstrip('+').strip()
            if participant_digits:
                author_partner = self.env['res.partner'].sudo()\
                    ._find_or_create_from_wa_number(
                        participant_digits, name=sender_name or None,
                    )

        # Post message to discuss channel
        mail_message = channel.sudo().with_context(
            mail_create_nosubscribe=True,
            owa_inbound=True,
        ).message_post(
            body=body,
            message_type='whatsapp_message',
            subtype_xmlid='mail.mt_comment',
            author_id=author_partner.id if author_partner else False,
            attachment_ids=attachment_ids,
            parent_id=parent_wa_message.mail_message_id.id if parent_wa_message else False,
            parent_msg_id=parent_wa_message.id if parent_wa_message else False,
            owa_inbound_msg_uid=msg_id,
            # Store the original sender's participant JID for GROUP inbound so
            # agents can react to another member's message. (#reactions)
            owa_sender_jid=(participant_jid if chat_type == 'group' else ''),
        )

        # Safety net: if attachments we passed didn't end up linked to the
        # message (e.g. message_post's pending-attachment filter stripped
        # them), force-link them now. Otherwise the chat renders empty as
        # "This message has been removed" because isEmpty=true.
        if attachment_ids and mail_message and not mail_message.attachment_ids:
            atts = self.env['ir.attachment'].sudo().browse(attachment_ids).exists()
            if atts:
                atts.write({'res_model': 'mail.message', 'res_id': mail_message.id})
                mail_message.sudo().write({
                    'attachment_ids': [(6, 0, atts.ids)],
                })

        # Phase 6: group intro on first contact in a new group.
        try:
            self._maybe_send_group_intro(channel)
        except Exception:
            _logger.exception("Error sending group intro")

        # Phase 6: gate chatbot / auto-reply on @-mention if the group requires it.
        skip_bot = bool(
            channel and channel.is_whatsapp_group and channel.require_mention
            and not self._bot_mentioned(body)
        )

        # Phase 3: send ack reaction (👀 by default) right after the inbound
        # is recorded, before any agent or bot replies. Cheap, visible UX win.
        try:
            self._send_ack_reaction(msg_id, from_number, channel, body=body)
        except Exception:
            _logger.exception("Error sending ack reaction")

        # Check for blacklist keywords
        stop_keywords = {'stop', 'unsubscribe', 'opt-out', 'optout'}
        if body and body.strip().lower() in stop_keywords:
            self.env['owa.blacklist'].sudo().add_to_blacklist(
                from_number, reason='User sent STOP'
            )
            _logger.info("Auto-blacklisted %s (sent STOP keyword)", from_number)

        # Phase 9: chat-side slash commands take priority over chatbot /
        # auto-reply when the user types '/menu', '/stop', '/agent' etc.
        try:
            if self.env['owa.slash.command'].sudo().parse_and_dispatch(
                account, from_number, body, channel,
            ):
                return
        except Exception:
            _logger.exception("Error in slash-command dispatch")

        # Phase 22C / 27B: inbound auto-create rule engine — fires before
        # chatbot so a created record + its auto_reply_template can
        # short-circuit the rest of the customer-facing reply chain
        # (avoids the customer receiving a rule reply AND a chatbot
        # reply AND an auto-reply for the same inbound).
        rule_replied = False
        if not skip_bot:
            try:
                # Reuse the partner already resolved by the channel
                # creation flow above. That path uses
                # _find_or_create_from_wa_number, which is normalised + safer
                # than a substring `phone ilike` (which trips on trailing-
                # digit collisions across accounts).
                partner = (channel and channel.whatsapp_partner_id) or False
                if not partner:
                    # Fallback for the unknown-sender case: don't search by
                    # phone ilike — that's the wrong-partner bug. Leave
                    # partner=False; rules with match_type='unknown_sender'
                    # are designed for exactly this path.
                    partner = self.env['res.partner']
                # Scope the env to the account's allowed companies so the
                # created record lands in the right company.
                env_scoped = self.env(
                    context=dict(
                        self.env.context,
                        allowed_company_ids=(
                            account.allowed_company_ids.ids
                            if account.allowed_company_ids
                            else [account.company_id.id]
                        ),
                    ),
                )
                is_group = bool(channel and channel.is_whatsapp_group)
                rec, rule_replied = env_scoped['owa.inbound.rule'].sudo()._evaluate_and_create(
                    account, partner or False, body, channel,
                    sender_phone=from_number, is_group=is_group,
                )
            except Exception:
                _logger.exception("Error in inbound-rule evaluation")

        # Phase 26E: auto-tag rules — drop res.partner.category tags on the
        # partner based on inbound message content. Runs regardless of
        # skip_bot and independently of the reply chain so tagging happens
        # even when bot replies are suppressed. (#labels)
        try:
            tag_partner = channel and channel.whatsapp_partner_id
            if tag_partner and body:
                self.env['owa.tag.rule'].sudo()._evaluate(tag_partner, body)
        except Exception:
            _logger.exception("Error in auto-tag rule evaluation")

        # If the rule fired AND queued an auto-reply, short-circuit the
        # chatbot + auto-reply pipeline so the customer doesn't get 2-3
        # replies for the same inbound.
        if rule_replied:
            return

        # Check chatbot sessions (skip if group requires mention and none present)
        if not skip_bot:
            try:
                if self._check_chatbot(from_number, body, is_new_channel=is_new_channel):
                    return  # Chatbot handled the message
            except Exception:
                _logger.exception("Error in chatbot processing")

        # Check auto-reply rules (same gate)
        if not skip_bot:
            try:
                self._check_auto_replies(from_number, body, is_new_channel=is_new_channel)
            except Exception:
                _logger.exception("Error checking auto-reply rules")

    # ── Inbound-pipeline helpers (moved from controllers/main.py so both
    #    transports share them; ``self`` is the owa.account) ────────────
    def _bot_mentioned(self, body):
        """True if the inbound body contains a recognisable @-mention of this
        account. Matches phone_number (digits only) or name (substring)."""
        if not body:
            return False
        haystack = body.lower()
        if self.phone_number:
            digits = ''.join(c for c in self.phone_number if c.isdigit())
            if digits and digits in body:
                return True
        if self.name and self.name.lower() in haystack:
            return True
        return False

    def _maybe_send_group_intro(self, channel):
        """Send the group intro message the first time we see a group.
        Only the QR transport can push the intro (uses the gateway)."""
        if not channel or not channel.is_whatsapp_group:
            return
        if channel.group_intro_sent:
            return
        intro = (self.group_intro_message or '').strip()
        if not intro:
            channel.sudo().group_intro_sent = True
            return
        if self.connection_type != 'qr':
            # Cloud group intro is out of P1 scope; mark sent to avoid retries.
            channel.sudo().group_intro_sent = True
            return
        try:
            api = self._get_baileys_api()
            jid = channel.whatsapp_number or ''
            if not jid.endswith('@g.us'):
                jid = f"{jid}@g.us"
            api.send_text(jid, intro)
            channel.sudo().group_intro_sent = True
        except Exception:
            _logger.exception("Group intro send failed for channel %s", channel.id)

    def _send_ack_reaction(self, msg_id, from_number, channel, body=''):
        """Send the 👀 ack reaction to the inbound message. Gated by
        reaction_level + ack_reaction_dm/group + ack_reaction_emoji. Failures
        never block processing. Ack reactions use the QR gateway only."""
        if not msg_id:
            return
        if self.connection_type != 'qr':
            # Cloud reactions are a Phase-2 item.
            return
        if not self.reaction_level or self.reaction_level == 'off':
            return
        emoji = (self.ack_reaction_emoji or '').strip()
        if not emoji:
            return
        is_group = channel and getattr(channel, 'is_group', False)
        # Determine "is_group" without relying on a non-existent field —
        # fall back to inspecting channel name or remote JID.
        if is_group is None or is_group is False:
            is_group = channel and (
                (channel.name or '').endswith('@g.us')
                or '@g.us' in (channel.whatsapp_number or '')
            )
        if is_group:
            scope = self.ack_reaction_group or 'mentions'
            if scope == 'never':
                return
            # 'mentions' scope only fires when the inbound body actually
            # @-mentions the account, so we don't spam every group message.
            if scope == 'mentions' and not self._bot_mentioned(body or ''):
                return
        else:
            if not self.ack_reaction_dm:
                return

        from odoo.addons.open_whatsapp_connector.tools.baileys_exception import BaileysError
        try:
            api = self._get_baileys_api()
            chat_jid = (
                channel.whatsapp_number if channel and '@' in (channel.whatsapp_number or '')
                else f"{from_number.lstrip('+')}@s.whatsapp.net"
            )
            api.send_reaction(chat_jid, msg_id, emoji, from_me=False)
        except BaileysError as e:
            _logger.warning("Ack reaction failed for %s: %s", msg_id, e.error_message)

    def _check_chatbot(self, from_number, message_text, is_new_channel=False):
        """Check if there's an active chatbot session for this number.
        Returns True if the chatbot handled the message (skip auto-replies)."""
        from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format
        account = self
        ChatbotSession = self.env['owa.chatbot.session'].sudo()
        formatted_phone = wa_phone_format(self.env, from_number) or from_number

        # Check for active session — match formatted or raw to cover legacy rows.
        session = ChatbotSession.search([
            ('chatbot_id.wa_account_id', '=', account.id),
            '|', ('phone_number', '=', formatted_phone),
                 ('phone_number', '=', from_number),
            ('state', '=', 'active'),
        ], limit=1)

        if session:
            return session._process_message(message_text)

        # Check if any chatbot should start for new conversations.
        if is_new_channel:
            chatbot = self.env['owa.chatbot'].sudo().search([
                ('wa_account_id', '=', account.id),
                ('active', '=', True),
            ], limit=1, order='sequence, id')
            if chatbot:
                chatbot._start_session(from_number)
                # Bot was just started and already sent its own welcome +
                # first menu. Treat the inbound as handled so the auto-reply
                # pipeline is skipped — otherwise a "welcome" auto-reply rule
                # fires too and the new contact gets two welcome messages.
                # (#chatbot)
                return True

        return False

    def _check_auto_replies(self, from_number, message_text, is_new_channel=False):
        """Check and send auto-replies for an inbound message."""
        account = self
        rules = self.env['owa.auto.reply'].sudo().search([
            ('active', '=', True),
            '|', ('wa_account_id', '=', account.id), ('wa_account_id', '=', False),
        ], order='sequence, id')

        for rule in rules:
            if rule._matches_message(message_text, from_number, is_new_channel=is_new_channel):
                rule._send_auto_reply(account, from_number)
                break  # Only first matching rule fires
