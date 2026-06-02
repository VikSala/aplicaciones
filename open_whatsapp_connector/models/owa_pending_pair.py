import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format

_logger = logging.getLogger(__name__)


class OwaPendingPair(models.Model):
    """Phase 7 — Pairing approval workflow.

    When ``owa.account.dm_policy='pairing'``, an inbound DM from an unknown
    number creates a pending-pair record and the message itself is dropped
    until an admin approves. Approve → adds entry to owa.allowlist.entry +
    posts a system note in discuss. Reject → unlink (and optionally
    blacklist).

    Replaces the openclaw `openclaw pairing approve` CLI; same flow,
    Odoo-native UI.
    """
    _name = 'owa.pending.pair'
    _description = 'Pending WhatsApp Pairing Request'
    _inherit = ['mail.thread']
    _order = 'create_date desc'
    _rec_name = 'phone'

    _PER_ACCOUNT_CAP = 20  # max simultaneous pending requests per account
    _EXPIRY_HOURS = 1

    account_id = fields.Many2one(
        'owa.account', required=True, ondelete='cascade', index=True)
    phone = fields.Char(string="Phone", required=True, index=True)
    sender_name = fields.Char(string="Sender name")
    msg_uid = fields.Char(string="Inbound message UID")
    body_preview = fields.Char(string="Message preview", size=200)
    state = fields.Selection([
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('expired', 'Expired'),
    ], default='pending', required=True, index=True, tracking=True)
    expires_at = fields.Datetime(
        string="Expires at",
        default=lambda self: fields.Datetime.now() + timedelta(hours=self._EXPIRY_HOURS),
    )
    blacklist_on_reject = fields.Boolean(
        string="Add to blacklist on reject", default=False)

    @api.model
    def request_pair(self, account, phone, sender_name=None, msg_uid=None, body=None):
        """Create or refresh a pending pair. Cap at _PER_ACCOUNT_CAP per account."""
        formatted = wa_phone_format(self.env, phone) or phone
        existing = self.sudo().search([
            ('account_id', '=', account.id),
            ('phone', '=', formatted),
            ('state', '=', 'pending'),
        ], limit=1)
        if existing:
            # Refresh expiry + body preview, don't re-create
            vals = {
                'expires_at': fields.Datetime.now() + timedelta(hours=self._EXPIRY_HOURS),
            }
            if body:
                vals['body_preview'] = (body or '')[:200]
            existing.write(vals)
            return existing
        # Enforce cap
        pending_count = self.sudo().search_count([
            ('account_id', '=', account.id), ('state', '=', 'pending'),
        ])
        if pending_count >= self._PER_ACCOUNT_CAP:
            _logger.warning(
                "Pending-pair cap reached for account %s; dropping request from %s",
                account.id, formatted,
            )
            return False
        return self.sudo().create({
            'account_id': account.id,
            'phone': formatted,
            'sender_name': sender_name,
            'msg_uid': msg_uid,
            'body_preview': (body or '')[:200],
        })

    def action_approve(self):
        """Approve: add to allowlist, mark approved."""
        for rec in self:
            if rec.state != 'pending':
                raise UserError(_("Only pending requests can be approved."))
            self.env['owa.allowlist.entry'].sudo().create({
                'account_id': rec.account_id.id,
                'phone': rec.phone,
                'note': _("Approved via pending-pair %s") % rec.id,
            })
            rec.write({'state': 'approved'})
        return True

    def action_reject(self):
        """Reject: optionally blacklist the number, then unlink."""
        for rec in self:
            if rec.blacklist_on_reject:
                self.env['owa.blacklist'].sudo().add_to_blacklist(
                    rec.phone, reason=_("Rejected via pending-pair"))
            rec.write({'state': 'rejected'})
        return True

    @api.model
    def _cron_expire(self):
        """Expire pending pairs older than _EXPIRY_HOURS."""
        cutoff = fields.Datetime.now()
        stale = self.sudo().search([
            ('state', '=', 'pending'),
            ('expires_at', '<=', cutoff),
        ])
        if stale:
            stale.write({'state': 'expired'})
            _logger.info("Expired %d pending pair(s)", len(stale))
