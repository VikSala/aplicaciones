import base64
import logging

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class OwaComposer(models.TransientModel):
    _name = 'owa.composer'
    _description = 'Send WhatsApp Message'

    # res_model + res_ids are populated when the composer is opened from a
    # specific record (e.g. server-action binding on res.partner). Both are
    # OPTIONAL — when the composer is opened from the top "Compose" menu
    # the user picks a recipient via partner_id or phone_input instead.
    res_model = fields.Char(string="Document Model")
    res_ids = fields.Char(string="Document IDs")
    batch_mode = fields.Boolean(string="Batch Mode")

    # Phase H — standalone-compose support: pick a partner or type a raw phone.
    partner_id = fields.Many2one(
        'res.partner', string="Recipient",
        help="Pick a contact, or use Phone Number for someone not in your contacts.")
    phone_input = fields.Char(
        string="Phone Number (raw)",
        help="E.164 format, e.g. +919999999999. Used when no contact is selected.")

    phone = fields.Char(
        string="Resolved Phone",
        compute='_compute_phone', readonly=False, store=True)
    body = fields.Text(string="Message")
    attachment_ids = fields.Many2many(
        'ir.attachment', string="Attachments",
        help="Attachments to send with the message")
    quick_reply_id = fields.Many2one(
        'owa.quick.reply', string="Quick Reply",
        domain="[('active', '=', True)]")
    report_id = fields.Many2one(
        'ir.actions.report', string="Attach Report PDF",
        domain="[('model', '=', res_model), ('report_type', '=', 'qweb-pdf')]",
        help="Render this report for the source record and attach it as a PDF "
             "(e.g. the invoice or sale-order PDF). Not used in batch mode.")
    wa_account_id = fields.Many2one(
        'owa.account', string="WhatsApp Account", required=True,
        default=lambda self: (self.env['owa.account'].search(
            [('session_state', '=', 'connected')], limit=1)
            or self.env['owa.account'].search([], limit=1)))
    scheduled_date = fields.Datetime(string="Schedule Send",
        help="Schedule message for later delivery. Leave empty to send immediately.")

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        context = self.env.context

        active_model = context.get('active_model')
        active_ids = context.get('active_ids')
        active_id = context.get('active_id')

        if not values.get('res_model') and active_model:
            values['res_model'] = active_model

        if not values.get('res_ids'):
            if active_ids:
                values['res_ids'] = ','.join(str(record_id) for record_id in active_ids)
            elif active_id:
                values['res_ids'] = str(active_id)

        if 'batch_mode' in fields_list and 'batch_mode' not in values:
            ids_for_batch = active_ids or ([active_id] if active_id else [])
            values['batch_mode'] = len(ids_for_batch) > 1

        return values

    @api.depends('res_model', 'res_ids', 'partner_id', 'phone_input')
    def _compute_phone(self):
        for composer in self:
            # Priority order:
            #   1. partner_id.phone (Compose top-menu, picked contact)
            #   2. phone_input (Compose top-menu, raw entry)
            #   3. derived from res_model/res_ids (server-action binding)
            if composer.partner_id and composer.partner_id.phone:
                phone = composer.partner_id.phone
                composer.phone = wa_phone_format(self.env, phone) or phone
                continue
            if composer.phone_input:
                phone = composer.phone_input
                composer.phone = wa_phone_format(self.env, phone) or phone
                continue
            if not composer.res_model or not composer.res_ids:
                composer.phone = False
                continue
            try:
                res_ids = [int(x) for x in composer.res_ids.split(',')]
            except (ValueError, AttributeError):
                composer.phone = False
                continue
            if len(res_ids) != 1:
                composer.phone = False
                continue
            record = self.env[composer.res_model].browse(res_ids[0])
            if not record.exists():
                composer.phone = False
                continue
            # Try common phone fields
            for field_name in ('phone', 'partner_id.phone'):
                try:
                    obj = record
                    for part in field_name.split('.'):
                        obj = getattr(obj, part)
                    if obj:
                        composer.phone = wa_phone_format(self.env, str(obj)) or str(obj)
                        break
                except (AttributeError, TypeError):
                    continue
            else:
                composer.phone = False

    @api.onchange('quick_reply_id', 'partner_id')
    def _onchange_quick_reply_id(self):
        """Fill body from quick reply template, using whichever record we
        can resolve as the rendering context — the explicitly-passed
        res_model/res_ids when the composer was launched from a record
        binding, otherwise the picked partner_id (top-menu Compose path)."""
        if not self.quick_reply_id:
            return
        record = None
        if self.res_model and self.res_ids:
            try:
                res_ids = [int(x) for x in self.res_ids.split(',')]
                if len(res_ids) == 1:
                    record = self.env[self.res_model].browse(res_ids[0])
            except (ValueError, AttributeError):
                pass
        if record is None and self.partner_id:
            record = self.partner_id
        self.body = self.quick_reply_id.render_body(record=record)

    @api.model
    def _action_open_composer(self, records, report_xmlid=None):
        """Open the WhatsApp composer for the given records.
        Used by server actions to open the composer from any model.
        ``report_xmlid`` (optional) pre-selects a report so its rendered PDF
        is attached on send (e.g. the invoice / sale-order PDF)."""
        if not records:
            return False
        ctx = {
            'active_model': records._name,
            'active_ids': records.ids,
            'default_res_model': records._name,
            'default_res_ids': ','.join(str(id) for id in records.ids),
            'default_batch_mode': len(records) > 1,
        }
        if report_xmlid and len(records) == 1:
            report = self.env.ref(report_xmlid, raise_if_not_found=False)
            if report:
                ctx['default_report_id'] = report.id
        return {
            'type': 'ir.actions.act_window',
            'name': _("Send WhatsApp Message"),
            'res_model': 'owa.composer',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': ctx,
        }

    def _render_report_attachment(self, record):
        """Render self.report_id for ``record`` and return an ir.attachment
        (the PDF). Returns None when no report is selected or rendering fails.
        Mirrors owa.notification.rule's PDF-render pattern."""
        self.ensure_one()
        if not self.report_id or not record:
            return None
        try:
            pdf_bytes, _dummy = self.report_id._render_qweb_pdf(
                self.report_id.report_name, [record.id])
            return self.env['ir.attachment'].create({
                'name': '%s.pdf' % (record.display_name or 'document'),
                'res_model': record._name,
                'res_id': record.id,
                'mimetype': 'application/pdf',
                'datas': base64.b64encode(pdf_bytes),
            })
        except Exception:
            _logger.exception(
                "owa.composer: failed to render report %s for %s",
                self.report_id.report_name, record)
            return None

    def _send_standalone(self):
        """Send to the partner or raw phone picked in the top-menu Compose
        wizard. Auto-creates the Discuss channel if none exists, then posts
        the message through the channel so it routes through the existing
        outbound pipeline (owa.message + sidecar)."""
        self.ensure_one()
        if not self.body and not self.attachment_ids:
            raise UserError(_("Type a message or attach something."))

        # Resolve recipient.
        if self.partner_id:
            partner = self.partner_id
            number_raw = partner.phone or self.phone_input or ''
        else:
            number_raw = self.phone_input or ''
            partner = False

        if not number_raw:
            raise UserError(_("Please pick a contact or type a phone number."))
        formatted = wa_phone_format(self.env, number_raw)
        if not formatted:
            raise UserError(_(
                "Couldn't parse '%s' as a valid phone number. Use E.164 "
                "format with country code, e.g. +919999999999."
            ) % number_raw)
        digits = formatted.lstrip('+')

        # Make sure we have a partner so the channel + chatter render with a
        # human name; reuse the auto-create helper that the inbound pipeline
        # already uses for unknown senders.
        if not partner:
            partner = self.env['res.partner']._find_or_create_from_wa_number(
                digits, name=None,
            )

        # Get-or-create the Discuss channel for this account+number pair.
        channel = self.wa_account_id._get_or_create_channel(
            digits, sender_name=(partner.name if partner else None),
        )
        if not channel:
            raise UserError(_("Couldn't create a WhatsApp channel for %s.") % digits)

        # Render body (apply quick-reply if picked).
        body = self.body or ''
        if self.quick_reply_id:
            body = self.quick_reply_id.render_body(record=partner) or body

        # Hand off to discuss.channel.message_post — same code path as
        # in-channel reply, so chunking / parent_id / outbound owa.message
        # creation work unchanged.
        channel.message_post(
            body=body,
            attachment_ids=self.attachment_ids.ids,
            message_type='whatsapp_message',
            # Thread the template id so button/list templates send as
            # interactive content instead of being downgraded to plain
            # text. _send_message() fires synchronously inside message_post,
            # so it must be present at create time. (#compose/#buttons)
            quick_reply_id=self.quick_reply_id.id if self.quick_reply_id else False,
        )

        # Optional defer — if scheduled, mark the just-created owa.message.
        if self.scheduled_date:
            recent = self.env['owa.message'].search(
                [('wa_account_id', '=', self.wa_account_id.id),
                 ('mobile_number', '=', f'+{digits}'),
                 ('message_type', '=', 'outbound'),
                 ('state', '=', 'outgoing')],
                order='id desc', limit=1,
            )
            if recent:
                recent.scheduled_date = self.scheduled_date

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'discuss.channel',
            'res_id': channel.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_send(self):
        """Send WhatsApp message(s)."""
        self.ensure_one()
        if not self.wa_account_id:
            raise UserError(_("Pick a WhatsApp account."))
        if self.wa_account_id.session_state != 'connected':
            raise UserError(_(
                "WhatsApp account '%s' is not connected. Open WhatsApp → "
                "Configuration → Accounts and click Connect or Refresh "
                "Status, then retry."
            ) % self.wa_account_id.name)

        # Phase H — standalone compose path: no res_model/res_ids, just a
        # picked partner or a raw phone. Resolve to a discuss.channel via
        # the existing _get_or_create_channel helper, then post through the
        # standard mail-thread pipeline so all downstream features (chunking,
        # attachments, status tracking) keep working unchanged.
        if not self.res_ids:
            return self._send_standalone()

        try:
            res_ids = [int(x) for x in self.res_ids.split(',')]
        except (ValueError, AttributeError):
            raise UserError(_("Invalid document IDs"))

        records = self.env[self.res_model].browse(res_ids)
        if not records.exists():
            raise UserError(_("No records found"))

        created = self.env['owa.message']
        for record in records:
            phone = self.phone
            if self.batch_mode or len(records) > 1:
                # Re-compute phone for each record in batch mode
                for field_name in ('phone', 'partner_id.phone'):
                    try:
                        obj = record
                        for part in field_name.split('.'):
                            obj = getattr(obj, part)
                        if obj:
                            phone = wa_phone_format(self.env, str(obj)) or str(obj)
                            break
                    except (AttributeError, TypeError):
                        continue
                else:
                    _logger.warning("No phone number found for record %s/%s", self.res_model, record.id)
                    continue

            if not phone:
                if len(records) == 1:
                    raise UserError(_("No phone number specified"))
                continue

            # Render body with quick reply if applicable
            body = self.body or ''
            if self.quick_reply_id:
                body = self.quick_reply_id.render_body(record=record)

            # Attach the rendered report PDF first (skipped in batch mode —
            # one user-picked report per N records is confusing UX).
            att_ids = list(self.attachment_ids.ids)
            if not self.batch_mode and self.report_id:
                rendered = self._render_report_attachment(record)
                if rendered:
                    att_ids = [rendered.id] + att_ids

            # Create mail.message
            mail_message = self.env['mail.message'].create({
                'model': self.res_model,
                'res_id': record.id,
                'body': body,
                'message_type': 'whatsapp_message',
                'attachment_ids': [(6, 0, att_ids)],
            })

            # Create owa.message
            msg_vals = {
                'mobile_number': phone,
                'message_type': 'outbound',
                'state': 'outgoing',
                'wa_account_id': self.wa_account_id.id,
                'mail_message_id': mail_message.id,
                'scheduled_date': self.scheduled_date,
            }
            if self.quick_reply_id:
                msg_vals['quick_reply_id'] = self.quick_reply_id.id
            created |= self.env['owa.message'].create(msg_vals)

        # Non-scheduled single sends fire immediately so the user gets the
        # real result (Sent / error) right away instead of waiting up to a
        # minute for the "Send Queued Messages" cron. Batch sends stay queued
        # so the cron's per-account throttle still governs bulk dispatch.
        send_now = bool(created) and not self.scheduled_date and len(created) == 1
        if send_now:
            created._send_message()

        ntype = 'success'
        if self.scheduled_date:
            title = _("WhatsApp Message Scheduled")
            body_msg = _("%d message(s) scheduled.", len(created))
        elif send_now and created.state in ('sent', 'delivered', 'read'):
            title = _("WhatsApp Message Sent")
            body_msg = _("Message sent.")
        elif send_now:
            # Inline send attempted but the provider rejected it (e.g. outside
            # the Cloud API 24h window) — surface the real reason.
            ntype = 'warning'
            title = _("WhatsApp Send Failed")
            body_msg = (created.failure_reason or created.error_message
                        or _("The message could not be sent."))
        else:
            title = _("WhatsApp Message Queued")
            body_msg = _("%d message(s) queued for sending.", len(created))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': title,
                'message': body_msg,
                'type': ntype,
                'sticky': ntype == 'warning',
            }
        }
