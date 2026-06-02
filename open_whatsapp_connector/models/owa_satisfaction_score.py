"""Phase 23B: customer-satisfaction score persisted from a survey.user_input
generated when a WhatsApp Discuss channel flips to triage_state=resolved."""
import logging
from urllib.parse import urljoin

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class OwaSatisfactionScore(models.Model):
    _name = 'owa.satisfaction.score'
    _description = 'WhatsApp Conversation CSAT'
    _order = 'submitted_at desc, id desc'

    partner_id = fields.Many2one('res.partner', required=True, index=True)
    channel_id = fields.Many2one('discuss.channel', index=True)
    wa_account_id = fields.Many2one(
        'owa.account', related='channel_id.owa_account_id', store=True, index=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, index=True)
    score = fields.Integer(string="Score 1–5", required=True)
    comment = fields.Text()
    submitted_at = fields.Datetime(default=fields.Datetime.now, index=True)
    # Stored as int so the model loads without the survey module.
    survey_user_input_id_int = fields.Integer(
        string="Survey response id",
        help="Numeric id of a survey.user_input record, when survey module "
             "is installed.")

    @api.model
    def _send_csat_invite(self, channel):
        """Send a survey URL via WhatsApp when a channel resolves. Best-effort —
        silently skips if the survey module isn't installed or no template
        is configured."""
        if not channel or not channel.whatsapp_partner_id:
            return False
        if 'survey.survey' not in self.env:
            return False
        try:
            survey = self.env['survey.survey'].sudo().search([], limit=1)
            if not survey:
                return False
            user_input = self.env['survey.user_input'].sudo().create({
                'survey_id': survey.id,
                'partner_id': channel.whatsapp_partner_id.id,
            })
            base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url') or ''
            link = urljoin(base_url + '/', f'survey/start/{survey.access_token}?answer_token={user_input.access_token}')
            mobile = channel.whatsapp_partner_id.phone
            if not mobile:
                return False
            # owa.message.body is a related field on mail_message_id; writing
            # 'body' directly is silently dropped. Build the mail.message first
            # so the CSAT invite text actually goes out.
            mail_message = self.env['mail.message'].sudo().create({
                'body': _("Thanks for chatting with us! Please rate your experience: %s") % link,
                'message_type': 'whatsapp_message',
            })
            self.env['owa.message'].sudo().create({
                'wa_account_id': channel.owa_account_id.id,
                'mobile_number': mobile,
                'mail_message_id': mail_message.id,
                'message_type': 'outbound',
                'state': 'outgoing',
                'whatsapp_partner_id': channel.whatsapp_partner_id.id,
            })
            return True
        except Exception:
            _logger.exception("CSAT invite failed for channel %s", channel.id)
            return False
