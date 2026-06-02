import base64
import logging

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format

_logger = logging.getLogger(__name__)


class OwaNotificationRule(models.Model):
    _name = 'owa.notification.rule'
    _description = 'WhatsApp Notification Rule'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'sequence, id'

    name = fields.Char(string="Name", required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    sequence = fields.Integer(default=10)

    # Target model + trigger
    model_id = fields.Many2one('ir.model', string="Model", required=True, ondelete='cascade',
        domain=[('is_mail_thread', '=', True)],
        help="Model to watch for changes (e.g. Sale Order, Invoice)")
    model_name = fields.Char(related='model_id.model', store=True, readonly=True)
    trigger_field_id = fields.Many2one('ir.model.fields', string="Trigger Field",
        required=True, ondelete='cascade',
        domain="[('model_id', '=', model_id), ('ttype', 'in', ('selection', 'char', 'boolean', 'many2one'))]",
        help="Field to watch for changes (e.g. 'state', 'invoice_status')")
    trigger_field_name = fields.Char(related='trigger_field_id.name', store=True, readonly=True)
    trigger_value = fields.Char(string="Trigger Value", required=True,
        help="Value that triggers the notification (e.g. 'sale', 'posted', 'done')")

    # Message config
    # Phase 11: optional per-rule overrides for account-level defaults.
    reply_to_mode_override = fields.Selection([
        ('off', 'Off (never quote)'),
        ('first', 'Quote first chunk only'),
        ('all', 'Quote every chunk'),
    ], string="Reply quoting (override)",
       help="If set, overrides the account's reply_to_mode for messages "
            "produced by this rule.")
    wa_account_id = fields.Many2one('owa.account', string="WhatsApp Account",
        domain=[('session_state', '=', 'connected')],
        help="Select the WhatsApp account to send notifications from. Required to activate the rule.")
    quick_reply_id = fields.Many2one('owa.quick.reply', string="Message Template",
        help="Quick reply template to use. If empty, a default message is sent.")
    custom_body = fields.Text(string="Custom Message",
        help="Used if no quick reply is selected. Supports {{record_name}}, {{partner_name}}")
    phone_field = fields.Char(string="Phone Field", default='partner_id.phone',
        required=True,
        help="Dot-separated field path to recipient phone (e.g. 'partner_id.phone', 'phone')")

    # PDF attachment
    attach_pdf = fields.Boolean(string="Attach PDF Report")
    report_id = fields.Many2one('ir.actions.report', string="Report",
        domain="[('model', '=', model_name)]",
        help="PDF report to attach (e.g. Sale Order report, Invoice report)")

    # Limits
    notify_once = fields.Boolean(string="Notify Once Per Record", default=True,
        help="Only send one notification per record for this rule")
    log_ids = fields.One2many('owa.notification.log', 'rule_id', string="Notification Log")

    @api.constrains('phone_field')
    def _check_phone_field(self):
        for rule in self:
            if not rule.phone_field:
                raise ValidationError(_("Phone field is required"))

    def _get_phone_from_record(self, record):
        """Extract phone number from a record using the configured field path."""
        try:
            obj = record
            for part in self.phone_field.split('.'):
                obj = getattr(obj, part, False)
                if not obj:
                    return False
            phone = str(obj)
            return wa_phone_format(self.env, phone) or phone
        except (AttributeError, TypeError):
            return False

    def _get_message_body(self, record):
        """Build message body from quick reply or custom body."""
        free_text = self._get_record_variables(record)
        if self.quick_reply_id:
            return self.quick_reply_id.render_body(record=record, free_text_values=free_text)
        body = self.custom_body or ''
        for key, value in free_text.items():
            body = body.replace('{{' + key + '}}', str(value))
        return body

    def _get_record_variables(self, record):
        """Extract common variables from a record for template rendering."""
        values = {
            'record_name': record.display_name or '',
        }
        # Partner name — when the record itself is a res.partner, fall back to
        # its own .name. Other models commonly expose partner_id (sale.order,
        # account.move, stock.picking, account.payment, ...).
        if record._name == 'res.partner':
            values['partner_name'] = record.name or ''
        elif hasattr(record, 'partner_id') and record.partner_id:
            values['partner_name'] = record.partner_id.name or ''
        else:
            values['partner_name'] = ''
        # Amount total
        if hasattr(record, 'amount_total'):
            values['amount_total'] = str(record.amount_total or 0)
        # Currency
        if hasattr(record, 'currency_id') and record.currency_id:
            values['currency'] = record.currency_id.symbol or record.currency_id.name or ''
        # Date (try common date fields)
        for date_field in ('date_order', 'invoice_date', 'date', 'scheduled_date'):
            if hasattr(record, date_field) and getattr(record, date_field):
                date_val = getattr(record, date_field)
                values['date'] = str(date_val)
                break
        return values

    def _vals_matches_trigger(self, vals):
        """Return True iff a write's vals dict triggers this rule.

        Handles boolean (True/False) and many2one (id or display name)
        trigger fields in addition to plain selection/char.
        """
        self.ensure_one()
        field_name = self.trigger_field_name
        if not field_name or field_name not in vals:
            return False
        new_val = vals.get(field_name)
        if new_val is None:
            return False
        target = (self.trigger_value or '').strip()
        ttype = self.trigger_field_id.ttype
        if ttype == 'many2one':
            # vals[field] is the integer id of the related record. Accept
            # either an id-as-string in trigger_value or a display name.
            try:
                target_id = int(target)
                return int(new_val) == target_id
            except (TypeError, ValueError):
                related_model = self.trigger_field_id.relation
                related = self.env[related_model].sudo().search(
                    [('display_name', '=', target)], limit=1,
                )
                return bool(related) and int(new_val) == related.id
        if ttype == 'boolean':
            return str(bool(new_val)).lower() == target.lower()
        return str(new_val) == target

    def _check_already_notified(self, record):
        """Check if this rule already fired for this record."""
        if not self.notify_once:
            return False
        return self.env['owa.notification.log'].search_count([
            ('rule_id', '=', self.id),
            ('res_model', '=', record._name),
            ('res_id', '=', record.id),
        ]) > 0

    def _send_notification(self, record):
        """Send a WhatsApp notification for a record."""
        self.ensure_one()
        if not self.active:
            return
        if self._check_already_notified(record):
            return
        if not self.wa_account_id or self.wa_account_id.session_state != 'connected':
            _logger.warning("Notification rule %s: account not connected", self.name)
            return

        phone = self._get_phone_from_record(record)
        if not phone:
            _logger.warning("Notification rule %s: no phone for record %s/%s",
                          self.name, record._name, record.id)
            return

        body = self._get_message_body(record)
        if not body:
            _logger.warning("Notification rule %s: empty message body", self.name)
            return

        # Build attachment list
        attachment_ids = []
        if self.attach_pdf and self.report_id:
            try:
                pdf_content, _ = self.report_id._render_qweb_pdf(
                    self.report_id.report_name, record.ids)
                attachment = self.env['ir.attachment'].create({
                    'name': f'{record.display_name}.pdf',
                    'datas': base64.b64encode(pdf_content),
                    'mimetype': 'application/pdf',
                    'res_model': record._name,
                    'res_id': record.id,
                })
                attachment_ids.append(attachment.id)
            except Exception:
                _logger.exception("Failed to generate PDF for rule %s", self.name)

        # Create mail.message
        mail_message = self.env['mail.message'].create({
            'model': record._name,
            'res_id': record.id,
            'body': body,
            'message_type': 'whatsapp_message',
            'attachment_ids': [(6, 0, attachment_ids)],
        })

        # Create owa.message
        msg_vals = {
            'mobile_number': phone,
            'message_type': 'outbound',
            'state': 'outgoing',
            'wa_account_id': self.wa_account_id.id,
            'mail_message_id': mail_message.id,
        }
        if self.quick_reply_id:
            msg_vals['quick_reply_id'] = self.quick_reply_id.id
        if self.reply_to_mode_override:
            msg_vals['reply_to_mode_override'] = self.reply_to_mode_override
        self.env['owa.message'].create(msg_vals)

        # Log notification
        self.env['owa.notification.log'].create({
            'rule_id': self.id,
            'res_model': record._name,
            'res_id': record.id,
        })

        # Kick the send cron so the user sees delivery within seconds rather
        # than waiting up to a minute for the next scheduled tick.
        cron = self.env.ref(
            'open_whatsapp_connector.ir_cron_send_owa_queue',
            raise_if_not_found=False,
        )
        if cron:
            cron.sudo()._trigger()

        _logger.info("Notification rule '%s' triggered for %s/%s -> %s",
                     self.name, record._name, record.id, phone)


class OwaNotificationLog(models.Model):
    _name = 'owa.notification.log'
    _description = 'WhatsApp Notification Log'
    _order = 'id desc'

    rule_id = fields.Many2one('owa.notification.rule', string="Rule", required=True, ondelete='cascade')
    res_model = fields.Char(string="Model", required=True)
    res_id = fields.Many2oneReference(string="Record", model_field='res_model')
    create_date = fields.Datetime(string="Sent At", readonly=True)
