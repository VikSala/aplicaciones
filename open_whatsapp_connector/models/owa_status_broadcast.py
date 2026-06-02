"""Phase 25C: WhatsApp Status / Stories — text/image/video posted to all
contacts for 24h via the sidecar's STATUS_BROADCAST_JID route."""
import base64
import logging
from datetime import timedelta

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class OwaStatusBroadcast(models.Model):
    _name = 'owa.status.broadcast'
    _description = 'WhatsApp Status Broadcast'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
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
    body_text = fields.Text(string="Caption / text body")
    attachment_id = fields.Many2one('ir.attachment', string="Image/Video")
    media_type = fields.Selection([
        ('text',  'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
    ], default='text', required=True, tracking=True)
    state = fields.Selection([
        ('draft',     'Draft'),
        ('queued',    'Queued'),
        ('posted',    'Posted'),
        ('expired',   'Expired'),
        ('error',     'Error'),
    ], default='draft', tracking=True, index=True)
    posted_at = fields.Datetime(readonly=True)
    expires_at = fields.Datetime(readonly=True)
    error_message = fields.Char(readonly=True)

    @api.depends('body_text', 'media_type', 'create_date')
    def _compute_name(self):
        for rec in self:
            preview = (rec.body_text or '')[:40]
            rec.name = f"[{rec.media_type}] {preview or _('(no text)')}"

    def action_post(self):
        from odoo.addons.open_whatsapp_connector.tools.baileys_api import BaileysApi
        for rec in self:
            try:
                api = BaileysApi(rec.wa_account_id)
                # statusJidList must be non-empty for the broadcast to be
                # visible to anyone other than the sender — gather the JIDs of
                # every DM channel we have on this account so the status shows
                # up for the user's existing WhatsApp contacts.
                channels = self.env['discuss.channel'].sudo().search([
                    ('owa_account_id', '=', rec.wa_account_id.id),
                    ('whatsapp_number', '!=', False),
                ])
                recipients = sorted({
                    (ch.whatsapp_number or '').lstrip('+').strip()
                    for ch in channels if ch.whatsapp_number
                })
                payload = {
                    'account_id': api._account_key(),
                    'type': rec.media_type,
                    'text': rec.body_text or '',
                    'recipients': recipients,
                }
                if rec.attachment_id:
                    payload['attachment_b64'] = (rec.attachment_id.datas or b'').decode('ascii')
                    payload['mimetype'] = rec.attachment_id.mimetype or 'application/octet-stream'
                api._request('POST', '/status/broadcast', json=payload)
                rec.write({
                    'state': 'posted',
                    'posted_at': fields.Datetime.now(),
                    'expires_at': fields.Datetime.now() + timedelta(hours=24),
                    'error_message': False,
                })
            except Exception as e:
                _logger.exception("status broadcast post failed")
                rec.write({'state': 'error', 'error_message': str(e)[:200]})

    @api.model
    def _cron_expire(self):
        now = fields.Datetime.now()
        self.search([
            ('state', '=', 'posted'),
            ('expires_at', '<', now),
        ]).write({'state': 'expired'})
