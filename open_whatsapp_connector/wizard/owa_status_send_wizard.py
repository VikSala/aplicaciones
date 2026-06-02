"""Phase H: WhatsApp Status / Stories send wizard.

Top-menu wizard that drafts an ``owa.status.broadcast`` row and immediately
calls its ``action_post()``. Mirrors the Send Event / Send Location pattern
so users can post a Status without navigating into Marketing > Status
Broadcasts and creating a record by hand.
"""
import base64
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OwaStatusSendWizard(models.TransientModel):
    _name = 'owa.status.send.wizard'
    _description = 'Send WhatsApp Status'

    wa_account_id = fields.Many2one(
        'owa.account', required=True, string='WhatsApp Account')
    media_type = fields.Selection([
        ('text', 'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
    ], default='text', required=True)
    body_text = fields.Text(
        string='Caption / Text',
        help='For text statuses this is the body. For image/video this is '
             'an optional caption.')
    media_data = fields.Binary(string='Image / Video')
    media_filename = fields.Char()

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if 'wa_account_id' in fields_list and not vals.get('wa_account_id'):
            Account = self.env['owa.account'].sudo()
            account = (Account.search([('session_state', '=', 'connected')], limit=1)
                       or Account.search([], limit=1))
            if account:
                vals['wa_account_id'] = account.id
        return vals

    def action_post(self):
        self.ensure_one()
        if self.wa_account_id.session_state != 'connected':
            raise UserError(_(
                "WhatsApp account '%s' is not connected. "
                "Open WhatsApp → Configuration → Accounts and click "
                "Connect or Refresh Status, then retry."
            ) % self.wa_account_id.name)
        if self.media_type == 'text' and not (self.body_text or '').strip():
            raise UserError(_("Type some text for the status."))
        if self.media_type in ('image', 'video') and not self.media_data:
            raise UserError(_("Upload an image or video for the status."))

        Broadcast = self.env['owa.status.broadcast'].sudo()
        vals = {
            'wa_account_id': self.wa_account_id.id,
            'media_type': self.media_type,
            'body_text': self.body_text or '',
            'state': 'draft',
        }
        if self.media_data:
            mimetype = 'image/jpeg' if self.media_type == 'image' else 'video/mp4'
            attachment = self.env['ir.attachment'].sudo().create({
                'name': self.media_filename or f'status.{self.media_type}',
                'datas': self.media_data,
                'mimetype': mimetype,
                'res_model': 'owa.status.broadcast',
            })
            vals['attachment_id'] = attachment.id
        record = Broadcast.create(vals)
        record.action_post()
        if record.state == 'error':
            raise UserError(_(
                "Status post failed: %s") % (record.error_message or 'unknown error'))

        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _("WhatsApp Status"),
                'message': _("Posted. Visible to your contacts for 24 hours."),
                'type': 'success',
            },
        }
