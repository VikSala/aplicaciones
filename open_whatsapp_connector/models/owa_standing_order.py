"""Phase 25B: standing orders — recurring rules ("every Monday 9am send
template X to contact list Y"). Marries existing campaigns + cron infra."""
import logging
from datetime import datetime, timedelta, time

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class OwaStandingOrder(models.Model):
    _name = 'owa.standing.order'
    _description = 'WhatsApp Standing Order (Recurring Send)'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    wa_account_id = fields.Many2one(
        'owa.account', required=True, ondelete='cascade', tracking=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, index=True)
    # Per-user / per-team ownership (visibility gated by toggle-able ir.rules).
    user_id = fields.Many2one(
        'res.users', string="Responsible", index=True,
        default=lambda self: self.env.user, tracking=True)
    team_id = fields.Many2one(
        'crm.team', string="Sales Team", index=True,
        default=lambda self: self.env['crm.team']._get_default_team_id(
            user_id=self.env.uid))
    quick_reply_id = fields.Many2one(
        'owa.quick.reply', required=True, string="Template")

    schedule_kind = fields.Selection([
        ('daily',   'Daily'),
        ('weekly',  'Weekly'),
        ('monthly', 'Monthly (day-of-month)'),
    ], default='daily', required=True, tracking=True)
    schedule_time = fields.Float(string="Time (HH.MM)", default=9.0,
        help="Float hour, e.g. 9.5 = 09:30")
    schedule_dow = fields.Selection([
        ('0', 'Mon'), ('1', 'Tue'), ('2', 'Wed'), ('3', 'Thu'),
        ('4', 'Fri'), ('5', 'Sat'), ('6', 'Sun'),
    ], string="Day of week", default='0')
    schedule_dom = fields.Integer(string="Day of month", default=1)

    recipient_kind = fields.Selection([
        ('partner',         'Single contact'),
        ('contact_list',    'Contact list'),
        ('broadcast_group', 'Broadcast group'),
    ], default='broadcast_group', required=True)
    partner_id = fields.Many2one('res.partner')
    contact_list_id = fields.Many2one('owa.contact.list')
    broadcast_group_id = fields.Many2one('owa.broadcast.group')

    next_run_at = fields.Datetime(readonly=True, index=True)
    last_run_at = fields.Datetime(readonly=True)
    runs_count = fields.Integer(readonly=True)

    def _compute_next_run(self, after=None):
        """Compute the next firing datetime after `after` (default now)."""
        self.ensure_one()
        ref = after or fields.Datetime.now()
        h = int(self.schedule_time)
        m = int(round((self.schedule_time - h) * 60))
        target_time = time(h % 24, m % 60)
        if self.schedule_kind == 'daily':
            cand = datetime.combine(ref.date(), target_time)
            if cand <= ref:
                cand += timedelta(days=1)
            return cand
        if self.schedule_kind == 'weekly':
            target_dow = int(self.schedule_dow or '0')
            days_ahead = (target_dow - ref.weekday()) % 7
            cand = datetime.combine(ref.date(), target_time) + timedelta(days=days_ahead)
            if cand <= ref:
                cand += timedelta(days=7)
            return cand
        if self.schedule_kind == 'monthly':
            dom = max(1, min(28, self.schedule_dom or 1))
            cand = ref.replace(day=dom, hour=h, minute=m, second=0, microsecond=0)
            if cand <= ref:
                # next month
                year = cand.year + (1 if cand.month == 12 else 0)
                month = 1 if cand.month == 12 else cand.month + 1
                cand = cand.replace(year=year, month=month)
            return cand
        return False

    @api.model_create_multi
    def create(self, vals_list):
        recs = super().create(vals_list)
        for rec in recs:
            rec.next_run_at = rec._compute_next_run()
        return recs

    def write(self, vals):
        result = super().write(vals)
        if any(k in vals for k in ('schedule_kind', 'schedule_time',
                                    'schedule_dow', 'schedule_dom')):
            for rec in self:
                rec.next_run_at = rec._compute_next_run()
        return result

    def action_run_now(self):
        for rec in self:
            rec._fire()
        return True

    def _fire(self):
        self.ensure_one()
        body = self.quick_reply_id.body or ''
        # Strip HTML tags for plain WhatsApp text
        try:
            from html import unescape
            import re
            body = unescape(re.sub(r'<[^>]+>', '', body or '')).strip()
        except Exception:
            pass
        if not body:
            _logger.warning("standing-order %s: empty template body", self.name)
            self.last_run_at = fields.Datetime.now()
            self.runs_count += 1
            return 0
        if self.recipient_kind == 'broadcast_group' and self.broadcast_group_id:
            sent = self.broadcast_group_id.fanout(body)
        elif self.recipient_kind == 'contact_list' and self.contact_list_id:
            sent = 0
            Message = self.env['owa.message'].sudo()
            MailMessage = self.env['mail.message'].sudo()
            for member in self.contact_list_id.member_ids:
                # `phone` is required on the member; `partner_id` is optional.
                # Reading partner_id.phone skipped partner-less members.
                mobile = member.phone or (
                    member.partner_id.phone if member.partner_id else False)
                if not mobile:
                    continue
                try:
                    # owa.message.body is a related field on mail_message_id;
                    # writing 'body' directly is silently dropped. Build the
                    # mail.message first so the queued text isn't empty.
                    mail_message = MailMessage.create({
                        'body': body,
                        'message_type': 'whatsapp_message',
                    })
                    Message.create({
                        'wa_account_id': self.wa_account_id.id,
                        'mobile_number': mobile,
                        'mail_message_id': mail_message.id,
                        'message_type': 'outbound',
                        'state': 'outgoing',
                        'whatsapp_partner_id': member.partner_id.id,
                    })
                    sent += 1
                except Exception:
                    _logger.exception("standing-order: contact-list skip")
        elif self.recipient_kind == 'partner' and self.partner_id:
            mobile = self.partner_id.phone
            sent = 0
            if mobile:
                try:
                    mail_message = self.env['mail.message'].sudo().create({
                        'body': body,
                        'message_type': 'whatsapp_message',
                    })
                    self.env['owa.message'].sudo().create({
                        'wa_account_id': self.wa_account_id.id,
                        'mobile_number': mobile,
                        'mail_message_id': mail_message.id,
                        'message_type': 'outbound',
                        'state': 'outgoing',
                        'whatsapp_partner_id': self.partner_id.id,
                    })
                    sent = 1
                except Exception:
                    _logger.exception("standing-order: single-partner skip")
        else:
            sent = 0
        self.write({
            'last_run_at': fields.Datetime.now(),
            'runs_count': self.runs_count + 1,
            'next_run_at': self._compute_next_run(),
        })
        return sent

    @api.model
    def _cron_dispatch(self):
        """Fire every standing order whose next_run_at is past."""
        now = fields.Datetime.now()
        due = self.search([
            ('active', '=', True),
            ('next_run_at', '<=', now),
        ])
        for order in due:
            try:
                order._fire()
            except Exception:
                _logger.exception("standing-order %s: fire failed", order.name)
