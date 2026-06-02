import logging
import re
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format

_logger = logging.getLogger(__name__)


class OwaAutoReply(models.Model):
    _name = 'owa.auto.reply'
    _description = 'WhatsApp Auto-Reply Rule'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, id'

    name = fields.Char(string="Name", required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    sequence = fields.Integer(default=10)

    # Phase 11: optional per-rule override for account-level reply quoting.
    reply_to_mode_override = fields.Selection([
        ('off', 'Off (never quote)'),
        ('first', 'Quote first chunk only'),
        ('all', 'Quote every chunk'),
    ], string="Reply quoting (override)",
       help="If set, overrides the account's reply_to_mode for messages "
            "produced by this auto-reply.")
    wa_account_id = fields.Many2one('owa.account', string="WhatsApp Account",
        help="Leave empty to apply to all accounts")

    trigger_type = fields.Selection([
        ('keyword', 'Keyword Match'),
        ('welcome', 'Welcome Message'),
        ('away', 'Away / Out of Office'),
        ('all', 'Reply to All Messages'),
    ], string="Trigger Type", required=True, default='keyword')

    # Keyword trigger config
    keyword = fields.Char(string="Keywords",
        help="Comma-separated keywords to match (case-insensitive)")
    match_type = fields.Selection([
        ('contains', 'Message Contains Keyword'),
        ('exact', 'Exact Match'),
        ('regex', 'Regular Expression'),
    ], string="Match Type", default='contains')

    # Response
    response_body = fields.Text(string="Response Message", required=True)

    # Schedule (for 'away' type)
    schedule_start = fields.Float(string="Business Hours Start", default=9.0,
        help="Start of business hours (24h format, e.g. 9.0 = 9:00 AM)")
    schedule_end = fields.Float(string="Business Hours End", default=18.0,
        help="End of business hours (24h format, e.g. 18.0 = 6:00 PM)")
    schedule_days = fields.Char(string="Business Days", default='0,1,2,3,4',
        help="Comma-separated day numbers (0=Monday, 6=Sunday)")
    timezone = fields.Selection(
        lambda self: [(tz, tz) for tz in pytz.all_timezones],
        string="Timezone", default=lambda self: self.env.user.tz or 'UTC',
        help="Timezone for the business-hours schedule above. Defaults to "
             "the editing user's timezone.")

    # Limits
    cooldown_minutes = fields.Integer(string="Cooldown (minutes)", default=60,
        help="Minimum minutes between auto-replies to the same number (0 = no cooldown)")

    def _matches_message(self, message_text, from_number, is_new_channel=False):
        """Check if this rule matches an incoming message."""
        self.ensure_one()
        if not self.active:
            return False

        if self.trigger_type == 'welcome':
            return bool(is_new_channel)

        if self.trigger_type == 'away':
            return self._is_outside_business_hours()

        if self.trigger_type == 'all':
            return True

        if self.trigger_type == 'keyword' and self.keyword:
            return self._matches_keyword(message_text)

        return False

    def _matches_keyword(self, message_text):
        """Check if message matches configured keywords."""
        if not message_text or not self.keyword:
            return False
        text_lower = message_text.lower().strip()
        keywords = [k.strip().lower() for k in self.keyword.split(',') if k.strip()]

        if self.match_type == 'exact':
            return text_lower in keywords
        elif self.match_type == 'contains':
            return any(kw in text_lower for kw in keywords)
        elif self.match_type == 'regex':
            try:
                pattern = self.keyword
                return bool(re.search(pattern, message_text, re.IGNORECASE))
            except re.error:
                _logger.warning("Invalid regex pattern in auto-reply %s: %s", self.name, self.keyword)
                return False
        return False

    def _is_outside_business_hours(self):
        """Check if current time is outside business hours, in the rule's tz."""
        tz_name = self.timezone or 'UTC'
        try:
            tz = pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            tz = pytz.UTC
        now_local = pytz.UTC.localize(datetime.utcnow()).astimezone(tz)
        current_day = now_local.weekday()  # 0=Monday
        days = [int(d.strip()) for d in (self.schedule_days or '').split(',') if d.strip().isdigit()]

        if current_day not in days:
            return True  # Not a business day

        current_hour = now_local.hour + now_local.minute / 60.0
        if current_hour < self.schedule_start or current_hour >= self.schedule_end:
            return True  # Outside business hours

        return False

    def _check_cooldown(self, formatted_phone):
        """Check if cooldown period has passed for this (already-formatted) number."""
        if not self.cooldown_minutes:
            return True
        last_reply = self.env['owa.auto.reply.log'].search([
            ('rule_id', '=', self.id),
            ('phone_number', '=', formatted_phone),
        ], limit=1, order='create_date desc')
        if last_reply:
            threshold = fields.Datetime.now() - timedelta(minutes=self.cooldown_minutes)
            if last_reply.create_date > threshold:
                return False
        return True

    def _send_auto_reply(self, account, from_number):
        """Queue the auto-reply through owa.message so it gets the same audit
        trail, status tracking, and chatter post as any other outbound."""
        self.ensure_one()
        formatted_phone = wa_phone_format(self.env, from_number) or from_number
        if not self._check_cooldown(formatted_phone):
            return

        wa_account = self.wa_account_id or account
        if not wa_account or wa_account.session_state != 'connected':
            return

        if not self.response_body:
            return

        mail_message = self.env['mail.message'].create({
            'body': self.response_body,
            'message_type': 'whatsapp_message',
        })
        msg_vals = {
            'mobile_number': formatted_phone,
            'message_type': 'outbound',
            'state': 'outgoing',
            'wa_account_id': wa_account.id,
            'mail_message_id': mail_message.id,
        }
        if self.reply_to_mode_override:
            msg_vals['reply_to_mode_override'] = self.reply_to_mode_override
        self.env['owa.message'].create(msg_vals)
        self.env['owa.auto.reply.log'].create({
            'rule_id': self.id,
            'phone_number': formatted_phone,
        })

        cron = self.env.ref(
            'open_whatsapp_connector.ir_cron_send_owa_queue',
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo()._trigger()

        _logger.info("Auto-reply '%s' queued for %s", self.name, formatted_phone)


class OwaAutoReplyLog(models.Model):
    _name = 'owa.auto.reply.log'
    _description = 'Auto-Reply Log'
    _order = 'id desc'
    _log_access = True

    rule_id = fields.Many2one('owa.auto.reply', string="Rule", required=True, ondelete='cascade')
    phone_number = fields.Char(string="Phone Number", required=True, index=True)
    create_date = fields.Datetime(string="Sent At", readonly=True)
