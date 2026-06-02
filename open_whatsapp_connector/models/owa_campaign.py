import logging
import re

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format

_PLACEHOLDER_RE = re.compile(r'\{\{\s*\w+\s*\}\}')
SYNC_SEND_LIMIT = 25

_logger = logging.getLogger(__name__)


class OwaCampaign(models.Model):
    _name = 'owa.campaign'
    _description = 'WhatsApp Campaign'
    _inherit = ['mail.thread']
    _order = 'id desc'

    name = fields.Char(string="Campaign Name", required=True, tracking=True)
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sending', 'Sending'),
        ('sent', 'Sent'),
        ('cancelled', 'Cancelled'),
    ], string="Status", default='draft', required=True, tracking=True)

    # Phase 11: optional per-campaign override for account-level reply quoting.
    reply_to_mode_override = fields.Selection([
        ('off', 'Off (never quote)'),
        ('first', 'Quote first chunk only'),
        ('all', 'Quote every chunk'),
    ], string="Reply quoting (override)",
       help="If set, overrides the account's reply_to_mode for messages "
            "produced by this campaign.")
    wa_account_id = fields.Many2one('owa.account', string="WhatsApp Account",
        required=True, domain=[('session_state', '=', 'connected')])
    quick_reply_id = fields.Many2one('owa.quick.reply', string="Message Template")
    body = fields.Text(string="Message Body",
        help="Used if no quick reply is selected")
    attachment_ids = fields.Many2many('ir.attachment', string="Attachments")

    contact_list_id = fields.Many2one('owa.contact.list', string="Contact List", required=True)
    scheduled_date = fields.Datetime(string="Scheduled Date",
        help="Leave empty to send immediately on launch")

    # Per-user / per-team ownership (visibility controlled by the
    # "Campaign & Contact Visibility" setting — see res.config.settings).
    # Always present; only the toggle-able ir.rules act on them.
    user_id = fields.Many2one(
        'res.users', string="Responsible", index=True,
        default=lambda self: self.env.user, tracking=True)
    team_id = fields.Many2one(
        'crm.team', string="Sales Team", index=True,
        default=lambda self: self.env['crm.team']._get_default_team_id(
            user_id=self.env.uid))

    # Stats
    message_ids = fields.One2many('owa.message', 'campaign_id', string="Messages")
    total_count = fields.Integer(string="Total", compute='_compute_stats', store=True)
    sent_count = fields.Integer(string="Sent", compute='_compute_stats', store=True)
    delivered_count = fields.Integer(string="Delivered", compute='_compute_stats', store=True)
    read_count = fields.Integer(string="Read", compute='_compute_stats', store=True)
    failed_count = fields.Integer(string="Failed", compute='_compute_stats', store=True)

    @api.depends('message_ids.state')
    def _compute_stats(self):
        for campaign in self:
            messages = campaign.message_ids
            campaign.total_count = len(messages)
            campaign.sent_count = len(messages.filtered(lambda m: m.state in ('sent', 'delivered', 'read')))
            campaign.delivered_count = len(messages.filtered(lambda m: m.state in ('delivered', 'read')))
            campaign.read_count = len(messages.filtered(lambda m: m.state == 'read'))
            campaign.failed_count = len(messages.filtered(lambda m: m.state in ('error', 'bounced')))

    def action_launch(self):
        """Launch the campaign — create messages for all contacts."""
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_("Campaign can only be launched from draft state."))

        if not self.wa_account_id or self.wa_account_id.session_state != 'connected':
            raise UserError(_("WhatsApp account is not connected."))

        contacts = self.contact_list_id.member_ids.filtered('active')
        if not contacts:
            raise UserError(_("Contact list is empty."))

        Blacklist = self.env['owa.blacklist'].sudo()
        owa_message_vals = []

        for member in contacts:
            phone = member.phone_formatted or member.phone
            if not phone:
                continue
            if Blacklist.is_blacklisted(phone):
                continue

            partner_record = member.partner_id or None
            if self.quick_reply_id:
                free_text = self._campaign_free_text_values(member, partner_record)
                body = self.quick_reply_id.render_body(
                    record=partner_record, free_text_values=free_text,
                )
                body = _PLACEHOLDER_RE.sub('', body)
            else:
                body = self.body or ''

            mail_message = self.env['mail.message'].create({
                'body': body,
                'message_type': 'whatsapp_message',
                'attachment_ids': [(6, 0, self.attachment_ids.ids)],
            })

            msg_vals = {
                'mobile_number': phone,
                'message_type': 'outbound',
                'state': 'outgoing',
                'wa_account_id': self.wa_account_id.id,
                'mail_message_id': mail_message.id,
                'campaign_id': self.id,
                'scheduled_date': self.scheduled_date,
            }
            if self.quick_reply_id:
                msg_vals['quick_reply_id'] = self.quick_reply_id.id
            if self.reply_to_mode_override:
                msg_vals['reply_to_mode_override'] = self.reply_to_mode_override
            owa_message_vals.append(msg_vals)

        self.state = 'sending'
        if owa_message_vals:
            queued = self.env['owa.message'].create(owa_message_vals)
            if not self.scheduled_date:
                if len(queued) <= SYNC_SEND_LIMIT:
                    queued._send_message()
                    if not self.message_ids.filtered(lambda m: m.state == 'outgoing'):
                        self.state = 'sent'
                else:
                    cron = self.env.ref(
                        'open_whatsapp_connector.ir_cron_send_owa_queue',
                        raise_if_not_found=False,
                    )
                    if cron:
                        cron.sudo()._trigger()

        _logger.info("Campaign '%s' launched: %d messages queued", self.name, len(owa_message_vals))
        self.message_post(body=_("Campaign launched: %d messages queued for sending.", len(owa_message_vals)))

    def _campaign_free_text_values(self, member, partner):
        """Build placeholder values from the contact list member + linked partner.

        Campaigns address partner contacts; SO/invoice-style placeholders like
        amount_total/currency have no source, so we leave those keys absent and
        let the post-render regex strip the unresolved tokens.
        """
        partner_name = (partner.name if partner else None) or member.name or ''
        return {
            'partner_name': partner_name,
            'record_name': partner_name,
            'phone': member.phone_formatted or member.phone or '',
        }

    def action_cancel(self):
        """Cancel the campaign and queued messages."""
        self.ensure_one()
        if self.state not in ('draft', 'sending'):
            raise UserError(_("Cannot cancel a completed campaign."))
        # Cancel queued messages
        self.message_ids.filtered(lambda m: m.state == 'outgoing').write({'state': 'cancel'})
        self.state = 'cancelled'

    def action_reset_to_draft(self):
        """Reset a cancelled campaign to draft."""
        self.ensure_one()
        if self.state != 'cancelled':
            raise UserError(_("Only cancelled campaigns can be reset."))
        self.state = 'draft'

    def _cron_update_campaign_state(self):
        """Cron: Update campaign state when all messages are processed."""
        campaigns = self.search([('state', '=', 'sending')])
        Bus = self.env['bus.bus'].sudo()
        for campaign in campaigns:
            pending = campaign.message_ids.filtered(lambda m: m.state == 'outgoing')
            if not pending:
                campaign.state = 'sent'
                partner = campaign.create_uid.partner_id
                if partner:
                    Bus._sendone(partner, "owa.campaign/refresh", {"id": campaign.id})


class OwaContactList(models.Model):
    _name = 'owa.contact.list'
    _description = 'WhatsApp Contact List'
    _order = 'name'

    name = fields.Char(string="List Name", required=True)
    active = fields.Boolean(default=True)
    member_ids = fields.One2many('owa.contact.list.member', 'list_id', string="Contacts")
    member_count = fields.Integer(string="Contacts", compute='_compute_member_count')

    # Per-user / per-team ownership. No mail.thread on this model -> no
    # tracking attribute. Visibility gated by the toggle-able ir.rules.
    user_id = fields.Many2one(
        'res.users', string="Responsible", index=True,
        default=lambda self: self.env.user)
    team_id = fields.Many2one(
        'crm.team', string="Sales Team", index=True,
        default=lambda self: self.env['crm.team']._get_default_team_id(
            user_id=self.env.uid))

    @api.depends('member_ids')
    def _compute_member_count(self):
        for rec in self:
            rec.member_count = len(rec.member_ids.filtered('active'))

    def action_import_partners(self):
        """Import contacts from res.partner records with phone numbers."""
        self.ensure_one()
        partners = self.env['res.partner'].search([
            ('phone', '!=', False),
        ])
        existing_phones = set(
            (p for p in self.member_ids.mapped('phone_formatted') if p)
        )
        # Also include raw phones so a member saved before a phone-format
        # round-trip is still recognised.
        existing_phones |= set(
            (p for p in self.member_ids.mapped('phone') if p)
        )
        new_members = []
        for partner in partners:
            phone = partner.phone
            formatted = wa_phone_format(self.env, phone) or phone
            if formatted and formatted not in existing_phones:
                new_members.append({
                    'list_id': self.id,
                    'partner_id': partner.id,
                    'name': partner.name,
                    'phone': formatted,
                })
                existing_phones.add(formatted)
        if new_members:
            self.env['owa.contact.list.member'].create(new_members)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Import Complete"),
                'message': _("%d contacts imported.", len(new_members)),
                'type': 'success',
                'sticky': False,
            }
        }


class OwaContactListMember(models.Model):
    _name = 'owa.contact.list.member'
    _description = 'WhatsApp Contact List Member'
    _order = 'name'

    list_id = fields.Many2one('owa.contact.list', string="Contact List",
        required=True, ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string="Contact")
    name = fields.Char(string="Name")
    phone = fields.Char(string="Phone Number", required=True)
    phone_formatted = fields.Char(string="Formatted Phone",
        compute='_compute_phone_formatted', store=True)
    active = fields.Boolean(default=True)

    @api.depends('phone')
    def _compute_phone_formatted(self):
        for member in self:
            if member.phone:
                member.phone_formatted = wa_phone_format(self.env, member.phone) or member.phone
            else:
                member.phone_formatted = False

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id:
            self.name = self.partner_id.name
            self.phone = self.partner_id.phone or ''
