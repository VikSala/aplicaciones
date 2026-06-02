"""Phase 25A: broadcast groups — saved recipient lists with per-recipient
session isolation. Distinct from campaigns (template-based one-shots) —
broadcast groups are persistent fan-out targets."""
import logging

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class OwaBroadcastGroup(models.Model):
    _name = 'owa.broadcast.group'
    _description = 'WhatsApp Broadcast Group'
    _inherit = ['mail.thread']
    _order = 'name'

    name = fields.Char(required=True, tracking=True)
    description = fields.Text()
    wa_account_id = fields.Many2one(
        'owa.account', required=True, ondelete='cascade', tracking=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, index=True)
    is_active = fields.Boolean(default=True, tracking=True)
    # Per-user / per-team ownership (visibility gated by toggle-able ir.rules).
    user_id = fields.Many2one(
        'res.users', string="Responsible", index=True,
        default=lambda self: self.env.user, tracking=True)
    team_id = fields.Many2one(
        'crm.team', string="Sales Team", index=True,
        default=lambda self: self.env['crm.team']._get_default_team_id(
            user_id=self.env.uid))
    partner_ids = fields.Many2many(
        'res.partner', 'owa_broadcast_group_partner_rel',
        'group_id', 'partner_id', string="Recipients")
    partner_count = fields.Integer(
        string="Recipients", compute='_compute_partner_count')
    last_sent_at = fields.Datetime(readonly=True)
    last_sent_count = fields.Integer(readonly=True)

    @api.depends('partner_ids')
    def _compute_partner_count(self):
        for grp in self:
            grp.partner_count = len(grp.partner_ids)

    def action_send_broadcast(self):
        """Open the composer wizard pre-targeted at this group."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Send to %s') % self.name,
            'res_model': 'owa.composer',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_wa_account_id': self.wa_account_id.id,
                'default_partner_ids': [(6, 0, self.partner_ids.ids)],
                'default_broadcast_group_id': self.id,
            },
        }

    def fanout(self, body_text, attachments=None):
        """Programmatic fan-out: queue one outbound owa.message per
        recipient. Each gets its own 1:1 channel via the existing send
        cron path."""
        self.ensure_one()
        Message = self.env['owa.message'].sudo()
        MailMessage = self.env['mail.message'].sudo()
        attachment_ids = list(attachments or [])
        sent = 0
        for partner in self.partner_ids:
            mobile = partner.phone
            if not mobile:
                continue
            try:
                # owa.message.body is related to mail_message_id.body, so
                # the body has to live on a backing mail.message — without
                # it the send cron sees an empty payload and errors out.
                mail_message = MailMessage.create({
                    'body': body_text or '',
                    'message_type': 'whatsapp_message',
                    'attachment_ids': [(6, 0, attachment_ids)],
                })
                Message.create({
                    'wa_account_id': self.wa_account_id.id,
                    'mobile_number': mobile,
                    'mail_message_id': mail_message.id,
                    'message_type': 'outbound',
                    'state': 'outgoing',
                    'whatsapp_partner_id': partner.id,
                })
                sent += 1
            except Exception:
                _logger.exception("broadcast fanout: skip partner %s", partner.id)
        self.write({
            'last_sent_at': fields.Datetime.now(),
            'last_sent_count': sent,
        })
        return sent
