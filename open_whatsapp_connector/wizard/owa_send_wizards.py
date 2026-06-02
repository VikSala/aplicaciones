"""Phase G: outbound-send wizards: Event, Location, Sticker.

All three are dispatched from the WhatsApp Discuss channel form via
context-bound ``binding_model_id`` so a user opens the channel, hits the
gear → "Send Event / Location / Sticker", picks the chat in the
wizard, fills the payload, and the wizard pushes it via the sidecar.
"""
import base64
import logging
from datetime import timezone as _tz

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _resolve_target_jid(channel):
    if not channel:
        return ''
    return channel.whatsapp_number or ''


class OwaSendEventWizard(models.TransientModel):
    _name = 'owa.send.event.wizard'
    _description = 'Send a WhatsApp Event'

    channel_id = fields.Many2one(
        'discuss.channel', required=True,
        domain="[('channel_type', '=', 'whatsapp')]")
    wa_account_id = fields.Many2one(
        'owa.account', related='channel_id.owa_account_id', readonly=True)
    name = fields.Char(string='Event Name', required=True, size=100)
    description = fields.Text(size=1024)
    start_at = fields.Datetime(required=True, string='Start')
    location_name = fields.Char(string='Location Name')
    latitude = fields.Float(digits=(10, 6))
    longitude = fields.Float(digits=(10, 6))

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if 'channel_id' in fields_list and not vals.get('channel_id'):
            ctx_id = self.env.context.get('default_channel_id') \
                or self.env.context.get('active_id')
            if ctx_id:
                vals['channel_id'] = ctx_id
        return vals

    def action_send(self):
        self.ensure_one()
        target = _resolve_target_jid(self.channel_id)
        if not target:
            raise UserError(_("Pick a WhatsApp channel first."))
        api = self.wa_account_id._get_baileys_api()
        location = None
        if self.latitude and self.longitude:
            location = {
                'name': self.location_name or '',
                'degreesLatitude': self.latitude,
                'degreesLongitude': self.longitude,
            }
        elif self.location_name:
            location = {'name': self.location_name}
        # Odoo's fields.Datetime is naive UTC; .timestamp() on a naive dt
        # uses the host's local zone, which silently shifts the event by the
        # server's TZ offset. Attach UTC explicitly for a correct epoch.
        start_unix = int(self.start_at.replace(tzinfo=_tz.utc).timestamp())
        api.send_event(
            target,
            self.name,
            self.description or '',
            start_unix,
            location,
        )
        return {'type': 'ir.actions.act_window_close'}


class OwaSendLocationWizard(models.TransientModel):
    # Internal model name kept as ``owa.send.live.location.wizard`` for
    # ext-id continuity across upgrades; the "live" piece is misleading
    # but renaming it dropped existing ACL rows and the upgrade refused
    # to clean up. User-facing label is "Send Location" (Phase G bug-fix).
    _name = 'owa.send.live.location.wizard'
    _description = 'Send WhatsApp Location'

    channel_id = fields.Many2one(
        'discuss.channel', required=True,
        domain="[('channel_type', '=', 'whatsapp')]")
    wa_account_id = fields.Many2one(
        'owa.account', related='channel_id.owa_account_id', readonly=True)
    latitude = fields.Float(required=True, digits=(10, 6))
    longitude = fields.Float(required=True, digits=(10, 6))
    location_name = fields.Char(string='Place Name')
    address = fields.Char()

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if 'channel_id' in fields_list and not vals.get('channel_id'):
            ctx_id = self.env.context.get('default_channel_id') \
                or self.env.context.get('active_id')
            if ctx_id:
                vals['channel_id'] = ctx_id
        return vals

    def action_send(self):
        self.ensure_one()
        target = _resolve_target_jid(self.channel_id)
        if not target:
            raise UserError(_("Pick a WhatsApp channel first."))
        api = self.wa_account_id._get_baileys_api()
        api.send_location(
            target,
            self.latitude, self.longitude,
            name=self.location_name or None,
            address=self.address or None,
        )
        return {'type': 'ir.actions.act_window_close'}


class OwaSendStickerWizard(models.TransientModel):
    _name = 'owa.send.sticker.wizard'
    _description = 'Send a WhatsApp Sticker'

    channel_id = fields.Many2one(
        'discuss.channel', required=True,
        domain="[('channel_type', '=', 'whatsapp')]")
    wa_account_id = fields.Many2one(
        'owa.account', related='channel_id.owa_account_id', readonly=True)
    sticker_data = fields.Binary(
        string='Sticker (.webp)', required=True,
        help='Animated or static WebP sticker. Square 512×512 recommended.')
    sticker_name = fields.Char(string='Filename')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if 'channel_id' in fields_list and not vals.get('channel_id'):
            ctx_id = self.env.context.get('default_channel_id') \
                or self.env.context.get('active_id')
            if ctx_id:
                vals['channel_id'] = ctx_id
        return vals

    def action_send(self):
        self.ensure_one()
        target = _resolve_target_jid(self.channel_id)
        if not target:
            raise UserError(_("Pick a WhatsApp channel first."))
        if not self.sticker_data:
            raise UserError(_("Upload a .webp sticker first."))
        api = self.wa_account_id._get_baileys_api()
        api.send_sticker(target, self.sticker_data, mimetype='image/webp')
        return {'type': 'ir.actions.act_window_close'}


class OwaSendPollWizard(models.TransientModel):
    # The send_poll BaileysApi method + /send/poll sidecar route already
    # existed but had ZERO callers (no wizard/view/action), so the advertised
    # "polls" feature was unreachable. This wizard wires it up. (#reactions)
    _name = 'owa.send.poll.wizard'
    _description = 'Send a WhatsApp Poll'

    channel_id = fields.Many2one(
        'discuss.channel', required=True,
        domain="[('channel_type', '=', 'whatsapp')]")
    wa_account_id = fields.Many2one(
        'owa.account', related='channel_id.owa_account_id', readonly=True)
    question = fields.Char(string='Question', required=True, size=255)
    options_text = fields.Text(
        string='Options', required=True,
        help='One option per line (2–12 options).')
    selectable_count = fields.Integer(
        string='Selectable answers', default=1,
        help='How many options a recipient may pick (1 = single choice).')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if 'channel_id' in fields_list and not vals.get('channel_id'):
            ctx_id = self.env.context.get('default_channel_id') \
                or self.env.context.get('active_id')
            if ctx_id:
                vals['channel_id'] = ctx_id
        return vals

    def action_send(self):
        self.ensure_one()
        target = _resolve_target_jid(self.channel_id)
        if not target:
            raise UserError(_("Pick a WhatsApp channel first."))
        options = [o.strip() for o in (self.options_text or '').splitlines() if o.strip()]
        if not (2 <= len(options) <= 12):
            raise UserError(_("A poll needs between 2 and 12 options (one per line)."))
        count = self.selectable_count or 1
        if count < 1 or count > len(options):
            raise UserError(_(
                "Selectable answers must be between 1 and the number of options."))
        api = self.wa_account_id._get_baileys_api()
        api.send_poll(target, self.question, options, selectable_count=count)
        return {'type': 'ir.actions.act_window_close'}


class OwaSendContactWizard(models.TransientModel):
    # send_contact BaileysApi + /send/contact sidecar route already existed but
    # had ZERO callers, so outbound vCard was unreachable from Odoo. (#reactions)
    _name = 'owa.send.contact.wizard'
    _description = 'Send a WhatsApp Contact Card (vCard)'

    channel_id = fields.Many2one(
        'discuss.channel', required=True,
        domain="[('channel_type', '=', 'whatsapp')]")
    wa_account_id = fields.Many2one(
        'owa.account', related='channel_id.owa_account_id', readonly=True)
    partner_id = fields.Many2one(
        'res.partner', string='Contact to share', required=True,
        help='The contact whose card (name, phone, email) is sent as a vCard.')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if 'channel_id' in fields_list and not vals.get('channel_id'):
            ctx_id = self.env.context.get('default_channel_id') \
                or self.env.context.get('active_id')
            if ctx_id:
                vals['channel_id'] = ctx_id
        return vals

    def action_send(self):
        self.ensure_one()
        target = _resolve_target_jid(self.channel_id)
        if not target:
            raise UserError(_("Pick a WhatsApp channel first."))
        p = self.partner_id
        # Use phone only — Odoo 19 has no res.partner.mobile field. (gotcha #1)
        phone = p.phone or ''
        digits = ''.join(c for c in phone if c.isdigit())
        name = p.name or _('Contact')
        lines = ['BEGIN:VCARD', 'VERSION:3.0', 'FN:%s' % name]
        if phone:
            waid = ';waid=%s' % digits if digits else ''
            lines.append('TEL;type=CELL;type=VOICE%s:%s' % (waid, phone))
        if p.email:
            lines.append('EMAIL:%s' % p.email)
        lines.append('END:VCARD')
        vcard = '\n'.join(lines)
        api = self.wa_account_id._get_baileys_api()
        api.send_contact(target, [{'display_name': name, 'vcard': vcard}])
        return {'type': 'ir.actions.act_window_close'}
