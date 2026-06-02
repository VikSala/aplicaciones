import re

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class OwaQuickReply(models.Model):
    _name = 'owa.quick.reply'
    _description = 'WhatsApp Quick Reply'
    _order = 'name'

    name = fields.Char(string="Name", required=True)
    template_type = fields.Selection([
        ('text', 'Text'),
        ('button', 'Button Message'),
        ('list', 'List Message'),
    ], string="Template Type", default='text', required=True)
    body = fields.Text(
        string="Message Body", required=True,
        help="Use {{variable_name}} for placeholders, e.g. 'Hello {{partner_name}}'")
    header_type = fields.Selection([
        ('none', 'None'),
        ('text', 'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
        ('document', 'Document'),
    ], string="Header Type", default='none')
    header_text = fields.Char(string="Header Text")
    header_attachment_id = fields.Many2one(
        'ir.attachment', string="Header Media",
        help="Image, video, or document to show as the message header")
    footer = fields.Char(string="Footer Text")
    button_ids = fields.One2many(
        'owa.quick.reply.button', 'quick_reply_id', string="Buttons")
    list_button_text = fields.Char(
        string="List Button Text", default="Menu",
        help="Text shown on the button that opens the list")
    list_section_ids = fields.One2many(
        'owa.quick.reply.list.section', 'quick_reply_id', string="List Sections")
    wa_account_id = fields.Many2one(
        'owa.account', string="Account",
        help="Leave empty to make available for all accounts")
    model_id = fields.Many2one(
        'ir.model', string="Applies To",
        help="Model this quick reply applies to (e.g. Sale Order)")
    phone_field = fields.Char(
        string="Phone Field", default='phone',
        help="Field path on the model to get the phone number")
    active = fields.Boolean(default=True)
    variable_ids = fields.One2many(
        'owa.quick.reply.variable', 'quick_reply_id',
        string="Variables", compute='_compute_variable_ids', store=True, readonly=False)

    @api.constrains('template_type', 'button_ids')
    def _check_button_limit(self):
        for rec in self:
            if rec.template_type == 'button' and len(rec.button_ids) > 3:
                raise ValidationError(_("Button messages can have a maximum of 3 buttons."))

    @api.constrains('template_type', 'list_section_ids')
    def _check_list_limit(self):
        for rec in self:
            if rec.template_type == 'list':
                total_rows = sum(len(s.row_ids) for s in rec.list_section_ids)
                if total_rows > 10:
                    raise ValidationError(_("List messages can have a maximum of 10 rows total."))

    @api.depends('body')
    def _compute_variable_ids(self):
        for reply in self:
            # Extract {{variable}} placeholders from body
            if not reply.body:
                reply.variable_ids = [(5, 0, 0)]
                continue
            placeholders = set(re.findall(r'\{\{(\w+)\}\}', reply.body))
            existing = {v.name for v in reply.variable_ids}
            # Add new placeholders
            new_vars = []
            for ph in placeholders:
                if ph not in existing:
                    new_vars.append((0, 0, {'name': ph}))
            # Remove obsolete
            to_remove = []
            for var in reply.variable_ids:
                if var.name not in placeholders:
                    to_remove.append((2, var.id))
            if new_vars or to_remove:
                reply.variable_ids = to_remove + new_vars

    def render_body(self, record=None, free_text_values=None):
        """Render the body with variable substitution.

        :param record: Odoo record to get field values from
        :param free_text_values: dict of {variable_name: value} for free text variables
        :return: rendered body string
        """
        self.ensure_one()
        body = self.body or ''
        values = dict(free_text_values or {})

        for var in self.variable_ids:
            if var.name in values:
                continue
            resolved = False
            if record:
                paths = []
                if var.field_path:
                    paths.append(var.field_path)
                else:
                    # Fallback: try the var name directly, then well-known
                    # mappings so out-of-the-box templates with `{{partner_name}}`,
                    # `{{record_name}}` etc. render without per-template setup.
                    paths.append(var.name)
                    if var.name in ('partner_name', 'contact_name', 'customer_name'):
                        # On a document (sale.order / account.move /
                        # stock.picking) the customer name lives on partner_id;
                        # the record's own `name` is the document reference
                        # (e.g. "S00001"), so resolve the partner FIRST and
                        # only fall back to `name` for res.partner records
                        # (which have no partner_id). (#compose)
                        paths.append('partner_id.name')
                        paths.append('name')
                    elif var.name == 'record_name':
                        paths.append('display_name')
                        paths.append('name')
                    elif var.name in ('amount', 'amount_total'):
                        paths.append('amount_total')
                    elif var.name == 'currency':
                        paths.append('currency_id.name')
                    elif var.name == 'date':
                        paths.append('date_due')
                        paths.append('date')
                    elif var.name == 'record_url':
                        paths.append('get_base_url')
                for path in paths:
                    try:
                        obj = record
                        for part in path.split('.'):
                            obj = getattr(obj, part)
                        if callable(obj):
                            obj = obj()
                        if obj:
                            values[var.name] = str(obj)
                            resolved = True
                            break
                    except (AttributeError, TypeError):
                        continue
            if not resolved and var.default_value:
                values[var.name] = var.default_value

        for name, value in values.items():
            body = body.replace('{{' + name + '}}', str(value))
        return body

    def render_template_data(self, record=None, free_text_values=None):
        """Render a full template data dict for interactive messages.

        :return: dict with keys: template_type, body, header, footer, buttons, sections
        """
        self.ensure_one()
        body = self.render_body(record=record, free_text_values=free_text_values)
        data = {
            'template_type': self.template_type,
            'body': body,
        }

        # Header
        if self.header_type and self.header_type != 'none':
            header = {'type': self.header_type}
            if self.header_type == 'text':
                header['text'] = self.header_text or ''
            elif self.header_attachment_id:
                header['media_base64'] = self.header_attachment_id.datas.decode() if self.header_attachment_id.datas else ''
                header['mimetype'] = self.header_attachment_id.mimetype or 'application/octet-stream'
                header['filename'] = self.header_attachment_id.name or 'file'
            data['header'] = header

        # Footer
        if self.footer:
            data['footer'] = self.footer

        # Buttons
        if self.template_type == 'button':
            data['buttons'] = [{
                'id': btn.button_id or f'btn_{btn.id}',
                'text': btn.text,
            } for btn in self.button_ids.sorted('sequence')]

        # List sections
        if self.template_type == 'list':
            data['button_text'] = self.list_button_text or 'Menu'
            data['sections'] = [{
                'title': section.title,
                'rows': [{
                    'id': row.row_id or f'row_{row.id}',
                    'title': row.title,
                    'description': row.description or '',
                } for row in section.row_ids.sorted('sequence')]
            } for section in self.list_section_ids.sorted('sequence')]

        return data


class OwaQuickReplyVariable(models.Model):
    _name = 'owa.quick.reply.variable'
    _description = 'WhatsApp Quick Reply Variable'
    _order = 'sequence, id'

    quick_reply_id = fields.Many2one(
        'owa.quick.reply', string="Quick Reply",
        required=True, ondelete='cascade')
    name = fields.Char(string="Variable Name", required=True)
    sequence = fields.Integer(default=10)
    field_path = fields.Char(
        string="Field Path",
        help="Dot-separated field path on the model, e.g. 'partner_id.name'")
    default_value = fields.Char(
        string="Default Value",
        help="Default value if field is empty or no record provided")
