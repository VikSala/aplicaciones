"""WhatsApp Official Cloud API message templates.

In-Odoo authoring + Meta submit/sync for the approved-template messaging
path. Templates are the escape hatch for messaging a contact outside the
24h customer-service window.
"""

import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Meta message_template_status_update event → local status.
_META_EVENT_STATUS = {
    'APPROVED': 'approved',
    'REJECTED': 'rejected',
    'PENDING': 'pending',
    'IN_APPEAL': 'pending',
    'PENDING_DELETION': 'pending',
    'DELETED': 'rejected',
    'DISABLED': 'rejected',
    'PAUSED': 'approved',
    'FLAGGED': 'approved',
}

# Meta quality score → local quality selection.
_META_QUALITY = {
    'GREEN': 'green',
    'YELLOW': 'yellow',
    'RED': 'red',
    'UNKNOWN': 'none',
}


class OwaCloudTemplate(models.Model):
    _name = 'owa.cloud.template'
    _description = 'WhatsApp Cloud API Template'
    _inherit = ['mail.thread']
    _order = 'name, lang_code'

    name = fields.Char(required=True, tracking=True)
    lang_code = fields.Char(
        string="Language", default='en', required=True,
        help="BCP-47 language/locale code, e.g. en, en_US, pt_BR.")
    category = fields.Selection([
        ('utility', 'Utility'),
        ('marketing', 'Marketing'),
        ('authentication', 'Authentication'),
    ], default='utility', required=True, tracking=True)
    wa_account_id = fields.Many2one(
        'owa.account', string="WhatsApp Account", required=True,
        domain=[('connection_type', '=', 'cloud')],
        help="Cloud API account this template is authored / submitted under.")
    header_type = fields.Selection([
        ('none', 'None'),
        ('text', 'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
        ('document', 'Document'),
    ], default='none')
    header_text = fields.Char()
    body_text = fields.Text(
        string="Body",
        help="Body text. Use {{1}}, {{2}}, … placeholders for variables.")
    footer_text = fields.Char()
    wa_template_uid = fields.Char(
        string="Meta Template ID", copy=False, tracking=True)
    status = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], default='draft', copy=False, tracking=True)
    quality = fields.Selection([
        ('none', 'None'),
        ('green', 'High'),
        ('yellow', 'Medium'),
        ('red', 'Low'),
    ], default='none', copy=False)
    error_msg = fields.Char(copy=False)
    variable_ids = fields.One2many(
        'owa.cloud.template.variable', 'template_id', string="Variables")
    button_ids = fields.One2many(
        'owa.cloud.template.button', 'template_id', string="Buttons")

    # ------------------------------------------------------------------
    # Meta payload assembly
    # ------------------------------------------------------------------
    def _build_meta_payload(self):
        """Assemble the Meta ``POST /{waba_id}/message_templates`` payload
        (name + language + category + components) from this record."""
        self.ensure_one()
        components = []

        # Header
        if self.header_type == 'text' and self.header_text:
            header = {'type': 'HEADER', 'format': 'TEXT',
                      'text': self.header_text}
            header_vars = self.variable_ids.filtered(
                lambda v: v.component == 'header').sorted('index')
            if header_vars:
                header['example'] = {
                    'header_text': [v.sample or '' for v in header_vars]}
            components.append(header)
        elif self.header_type in ('image', 'video', 'document'):
            components.append({
                'type': 'HEADER',
                'format': self.header_type.upper(),
            })

        # Body
        if self.body_text:
            body = {'type': 'BODY', 'text': self.body_text}
            body_vars = self.variable_ids.filtered(
                lambda v: v.component == 'body').sorted('index')
            if body_vars:
                body['example'] = {
                    'body_text': [[v.sample or '' for v in body_vars]]}
            components.append(body)

        # Footer
        if self.footer_text:
            components.append({'type': 'FOOTER', 'text': self.footer_text})

        # Buttons
        if self.button_ids:
            buttons = []
            for btn in self.button_ids:
                if btn.button_type == 'quick_reply':
                    buttons.append({'type': 'QUICK_REPLY', 'text': btn.text})
                elif btn.button_type == 'url':
                    buttons.append({'type': 'URL', 'text': btn.text,
                                    'url': btn.url or ''})
                elif btn.button_type == 'phone_number':
                    buttons.append({'type': 'PHONE_NUMBER', 'text': btn.text,
                                    'phone_number': btn.phone_number or ''})
            if buttons:
                components.append({'type': 'BUTTONS', 'buttons': buttons})

        return {
            'name': self.name,
            'language': self.lang_code or 'en',
            'category': (self.category or 'utility').upper(),
            'components': components,
        }

    # ------------------------------------------------------------------
    # Actions — submit / sync
    # ------------------------------------------------------------------
    def action_submit(self):
        """Submit this template to Meta for review."""
        from odoo.addons.open_whatsapp_connector.tools.cloud_api import (
            CloudApiError)
        for tmpl in self:
            if not tmpl.wa_account_id:
                raise UserError(_("Set a Cloud API account first."))
            payload = tmpl._build_meta_payload()
            try:
                resp = tmpl.wa_account_id._get_cloud_api().submit_template(
                    payload)
            except CloudApiError as e:
                tmpl.error_msg = e.message
                _logger.warning(
                    "Template submit failed for %s: %s", tmpl.name, e)
                continue
            meta_status = str(resp.get('status') or '').upper()
            tmpl.write({
                'wa_template_uid': resp.get('id') or tmpl.wa_template_uid,
                'status': _META_EVENT_STATUS.get(meta_status, 'pending'),
                'error_msg': False,
            })
        return True

    def action_sync(self):
        """Refresh this single template's status from Meta."""
        from odoo.addons.open_whatsapp_connector.tools.cloud_api import (
            CloudApiError)
        for tmpl in self.filtered('wa_template_uid'):
            try:
                data = tmpl.wa_account_id._get_cloud_api().get_template(
                    tmpl.wa_template_uid)
            except CloudApiError as e:
                tmpl.error_msg = e.message
                continue
            tmpl._apply_meta_template_dict(data)
        return True

    # ------------------------------------------------------------------
    # Meta event / sync ingestion
    # ------------------------------------------------------------------
    def _apply_meta_template_dict(self, data):
        """Write status / quality / category from a Meta template dict
        (as returned by the message_templates list / single GET)."""
        self.ensure_one()
        vals = {}
        meta_status = str(data.get('status') or '').upper()
        if meta_status in _META_EVENT_STATUS:
            vals['status'] = _META_EVENT_STATUS[meta_status]
        category = str(data.get('category') or '').lower()
        if category in ('utility', 'marketing', 'authentication'):
            vals['category'] = category
        q = data.get('quality_score') or {}
        qscore = str((q.get('score') if isinstance(q, dict) else q)
                     or '').upper()
        if qscore in _META_QUALITY:
            vals['quality'] = _META_QUALITY[qscore]
        if data.get('id'):
            vals['wa_template_uid'] = data['id']
        if vals:
            self.write(vals)

    @api.model
    def _apply_meta_event(self, field, value):
        """Apply a Meta webhook template event (message_template_status_update
        / quality / category) to the matching local template row.

        ``value`` carries ``message_template_id`` (the wa_template_uid),
        ``message_template_name`` / ``message_template_language`` and an
        ``event`` (APPROVED/REJECTED/…) or ``new_quality_score`` /
        ``new_category``.
        """
        uid = (value.get('message_template_id')
               or value.get('message_template_ID'))
        name = value.get('message_template_name')
        lang = value.get('message_template_language')
        tmpl = self.sudo()
        rec = self.browse()
        if uid:
            rec = tmpl.search([('wa_template_uid', '=', str(uid))], limit=1)
        if not rec and name:
            dom = [('name', '=', name)]
            if lang:
                dom.append(('lang_code', '=', lang))
            rec = tmpl.search(dom, limit=1)
        if not rec:
            _logger.info(
                "Cloud template event %s: no local row for id=%s name=%s",
                field, uid, name)
            return False

        vals = {}
        if field == 'message_template_status_update':
            event = str(value.get('event') or '').upper()
            if event in _META_EVENT_STATUS:
                vals['status'] = _META_EVENT_STATUS[event]
            reason = value.get('reason')
            if event == 'REJECTED':
                vals['error_msg'] = reason or 'rejected'
        elif field == 'message_template_quality_update':
            q = str(value.get('new_quality_score') or '').upper()
            if q in _META_QUALITY:
                vals['quality'] = _META_QUALITY[q]
        elif field == 'template_category_update':
            cat = str(value.get('new_category')
                      or value.get('correct_category') or '').lower()
            if cat in ('utility', 'marketing', 'authentication'):
                vals['category'] = cat

        if vals:
            rec.write(vals)
            # Post a chatter note on rejection so the author sees the reason.
            if vals.get('status') == 'rejected':
                try:
                    rec.message_post(body=_(
                        "Template rejected by Meta: %s")
                        % (rec.error_msg or value.get('reason') or 'no reason'))
                except Exception:  # pragma: no cover -- chatter best-effort
                    _logger.exception(
                        "Rejection chatter post failed for template %s", rec.id)
        return True

    # ------------------------------------------------------------------
    # Send-by-template (24h-window escape hatch)
    # ------------------------------------------------------------------
    def _build_send_components(self, values=None):
        """Build the Meta send-time ``components`` array from this template's
        variables + a ``{index: value}`` (or ``[value, …]``) mapping.

        Only text body/header parameters are wired here; media-header
        parameters and button URL/payload params can be layered on later.
        """
        self.ensure_one()
        values = values or {}

        def _val(var):
            if isinstance(values, dict):
                return (values.get(var.index)
                        or values.get(str(var.index))
                        or var.sample or '')
            try:
                return values[var.index - 1]
            except (IndexError, TypeError):
                return var.sample or ''

        components = []
        header_vars = self.variable_ids.filtered(
            lambda v: v.component == 'header').sorted('index')
        if header_vars:
            components.append({
                'type': 'header',
                'parameters': [
                    {'type': 'text', 'text': str(_val(v))}
                    for v in header_vars],
            })
        body_vars = self.variable_ids.filtered(
            lambda v: v.component == 'body').sorted('index')
        if body_vars:
            components.append({
                'type': 'body',
                'parameters': [
                    {'type': 'text', 'text': str(_val(v))}
                    for v in body_vars],
            })
        return components

    def action_send(self, number, values=None):
        """Send this approved template to ``number``.

        Builds the send-time components from ``values`` (a {index: value}
        dict or ordered list), dispatches via the cloud transport, and writes
        an outbound owa.message flagged so the 24h-window guard is skipped
        (templates are the legitimate way to message outside the window).
        Returns the created owa.message.
        """
        self.ensure_one()
        if self.status != 'approved':
            raise UserError(_(
                "Template '%s' is not approved yet (status: %s).")
                % (self.name, self.status))
        account = self.wa_account_id
        if not account or account.connection_type != 'cloud':
            raise UserError(_("Template is not bound to a Cloud API account."))
        to = (number or '').lstrip('+')
        if not to:
            raise UserError(_("No recipient number."))

        components = self._build_send_components(values)
        # Create the outbound owa.message + its mail.message so the send is
        # visible in the conversation + logs, mirroring a normal outbound.
        mail = self.env['mail.message'].create({
            'body': self.body_text or self.name,
            'message_type': 'whatsapp_message',
        })
        msg = self.env['owa.message'].create({
            'mobile_number': to,
            'message_type': 'outbound',
            'state': 'outgoing',
            'wa_account_id': account.id,
            'mail_message_id': mail.id,
        })
        from odoo.addons.open_whatsapp_connector.tools.cloud_api import (
            CloudApiError)
        try:
            wamid = account._dispatch_send(
                'template', to=to, name=self.name,
                lang=self.lang_code or 'en', components=components or None)
        except (CloudApiError, Exception) as e:
            reason = getattr(e, 'message', None) or str(e)
            msg.write({
                'state': 'error',
                'failure_type': 'recoverable',
                'failure_reason': reason,
                'error_message': reason,
            })
            raise UserError(_("Template send failed: %s") % reason)
        msg.write({
            'state': 'sent',
            'msg_uid': wamid,
            'wa_message_uid': wamid,
        })
        return msg


class OwaCloudTemplateVariable(models.Model):
    _name = 'owa.cloud.template.variable'
    _description = 'WhatsApp Cloud Template Variable'
    _order = 'component, index'

    template_id = fields.Many2one(
        'owa.cloud.template', required=True, ondelete='cascade')
    index = fields.Integer(string="Placeholder #", required=True)
    component = fields.Selection([
        ('body', 'Body'),
        ('header', 'Header'),
    ], default='body', required=True)
    sample = fields.Char(string="Sample value")


class OwaCloudTemplateButton(models.Model):
    _name = 'owa.cloud.template.button'
    _description = 'WhatsApp Cloud Template Button'

    template_id = fields.Many2one(
        'owa.cloud.template', required=True, ondelete='cascade')
    button_type = fields.Selection([
        ('quick_reply', 'Quick Reply'),
        ('url', 'URL'),
        ('phone_number', 'Call'),
    ], default='quick_reply', required=True)
    text = fields.Char(required=True)
    url = fields.Char()
    phone_number = fields.Char()
