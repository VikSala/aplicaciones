import logging

from odoo import api, fields, models
from odoo.addons.open_whatsapp_connector.tools.phone_validation import wa_phone_format

_logger = logging.getLogger(__name__)


class ResPartner(models.Model):
    _inherit = 'res.partner'

    owa_channel_count = fields.Integer(
        string="WhatsApp Channels", compute='_compute_owa_channel_count')

    # Phase 21: incoming call awareness
    owa_call_count = fields.Integer(
        string="WhatsApp Calls", compute='_compute_owa_call_count')
    owa_call_log_ids = fields.One2many(
        'owa.call.log', 'partner_id', string="WhatsApp Calls")
    owa_wa_link = fields.Char(
        string="WhatsApp link", compute='_compute_owa_wa_link',
        help="https://wa.me/<intl> link to start a chat with this contact "
             "in WhatsApp.")
    owa_wa_call_link = fields.Char(
        string="WhatsApp voice-call link", compute='_compute_owa_wa_link')
    owa_wa_video_link = fields.Char(
        string="WhatsApp video-call link", compute='_compute_owa_wa_link')

    def _compute_owa_channel_count(self):
        for partner in self:
            partner.owa_channel_count = self.env['discuss.channel'].search_count([
                ('channel_type', '=', 'whatsapp'),
                ('whatsapp_partner_id', '=', partner.id),
            ])

    def _compute_owa_call_count(self):
        for partner in self:
            partner.owa_call_count = self.env['owa.call.log'].search_count([
                ('partner_id', '=', partner.id),
            ])

    @api.depends('phone', 'mobile')
    def _compute_owa_wa_link(self):
        """Compute click-to-WhatsApp URLs. wa.me only accepts a digits-only
        phone number with no +/spaces. ?call= is a non-standard param the
        WhatsApp app interprets as 'open the call screen' on Android/desktop;
        falls back to opening a chat on iOS. Falls back to `mobile` when
        `phone` is empty so mobile-only contacts still get call buttons.
        (#calls)"""
        for partner in self:
            digits = ''.join(
                c for c in (partner.phone or partner.mobile or '') if c.isdigit())
            if digits:
                base = f"https://wa.me/{digits}"
                partner.owa_wa_link = base
                partner.owa_wa_call_link = f"{base}?call=1"
                partner.owa_wa_video_link = f"{base}?call=video"
            else:
                partner.owa_wa_link = False
                partner.owa_wa_call_link = False
                partner.owa_wa_video_link = False

    def action_open_wa_voice_call(self):
        """Phase 21: open the device's WhatsApp app on a voice-call URL.
        Returns an act_url action that opens in a new browser tab; the OS
        handles the wa.me deep link."""
        self.ensure_one()
        if not self.owa_wa_call_link:
            return False
        return {'type': 'ir.actions.act_url', 'url': self.owa_wa_call_link, 'target': 'new'}

    def action_open_wa_video_call(self):
        """Phase 21: open the device's WhatsApp app on a video-call URL."""
        self.ensure_one()
        if not self.owa_wa_video_link:
            return False
        return {'type': 'ir.actions.act_url', 'url': self.owa_wa_video_link, 'target': 'new'}

    # ── Phase C2: block / unblock this contact on WhatsApp ────────────
    def _default_owa_account(self):
        return self.env['owa.account'].search(
            [('session_state', '=', 'connected')], limit=1)

    def action_block_on_whatsapp(self):
        """Block this partner's WhatsApp number on the active account.
        Mirrors into ``owa.blacklist`` so we don't send to them again either."""
        from odoo.exceptions import UserError
        from odoo import _
        self.ensure_one()
        if not self.phone:
            raise UserError(_("This partner has no phone number set."))
        account = self._default_owa_account()
        if not account:
            raise UserError(_("No connected WhatsApp account found."))
        wa_jid = (wa_phone_format(self.phone) or '').lstrip('+') + '@s.whatsapp.net'
        api = account._get_baileys_api()
        api.block_contact(wa_jid)
        Blacklist = self.env['owa.blacklist'].sudo()
        phone = (wa_phone_format(self.phone) or '').lstrip('+')
        if phone and not Blacklist.search_count([('phone_number', '=', phone)]):
            Blacklist.create({
                'wa_account_id': account.id,
                'phone_number': phone,
                'reason': _("Blocked from partner form"),
            })
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _("Blocked on WhatsApp"),
                'message': _("%s won't be able to message you on WhatsApp.") % self.display_name,
                'sticky': False,
            },
        }

    def action_unblock_on_whatsapp(self):
        """Reverse of action_block_on_whatsapp."""
        from odoo.exceptions import UserError
        from odoo import _
        self.ensure_one()
        if not self.phone:
            raise UserError(_("This partner has no phone number set."))
        account = self._default_owa_account()
        if not account:
            raise UserError(_("No connected WhatsApp account found."))
        wa_jid = (wa_phone_format(self.phone) or '').lstrip('+') + '@s.whatsapp.net'
        api = account._get_baileys_api()
        api.unblock_contact(wa_jid)
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _("Unblocked on WhatsApp"),
                'message': _("%s can message you on WhatsApp again.") % self.display_name,
                'sticky': False,
            },
        }

    # ── Phase C6: WhatsApp call-link generator ────────────────────────
    def action_create_wa_call_link(self, kind='audio'):
        """Generate a shareable WhatsApp call link (audio or video) and
        return it as an act_url so the agent can paste it into a chat or
        email. Compensates for the fact that we can't carry call audio."""
        from odoo.exceptions import UserError
        from odoo import _
        from odoo.addons.open_whatsapp_connector.tools.baileys_exception import (
            BaileysError,
        )
        self.ensure_one()
        account = self._default_owa_account()
        if not account:
            raise UserError(_("No connected WhatsApp account found."))
        api = account._get_baileys_api()
        # createCallLink is flaky on the gateway rc10 — WhatsApp doesn't always
        # answer the IQ. Convert the sidecar timeout/error into a friendly
        # notification instead of letting it surface as an RPC_ERROR.
        try:
            result = api.create_call_link(kind=kind) or {}
        except BaileysError as e:
            raise UserError(_(
                "Couldn't generate the WhatsApp %(kind)s call link: %(err)s",
                kind=kind, err=e.error_message or str(e),
            ))
        url = result.get('url') or ''
        if not url:
            raise UserError(_("WhatsApp did not return a call link. Try again later."))
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _("WhatsApp call link"),
                'message': url,
                'sticky': True,
            },
        }

    def action_create_wa_audio_call_link(self):
        return self.action_create_wa_call_link(kind='audio')

    def action_create_wa_video_call_link(self):
        return self.action_create_wa_call_link(kind='video')

    @api.model
    def _find_or_create_from_wa_number(self, number, name=None):
        """Find an existing partner by WhatsApp number or create a new one.

        :param number: WhatsApp number (digits only, no +)
        :param name: optional name for the partner
        :return: res.partner record
        """
        if not number:
            return self.env['res.partner']

        # Format for search
        formatted = wa_phone_format(self.env, '+' + number)

        # Search by phone — try exact matches first to avoid LIKE-substring
        # false positives (e.g. last-10-digits substring of a longer number).
        candidates = []
        if formatted:
            candidates.append(formatted)
        candidates.append('+' + number)
        candidates.append(number)
        seen = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            partner = self.search([('phone', '=', candidate)], limit=1)
            if partner:
                # Phase G polish — when partner.name is still the raw +digits
                # placeholder (auto-created before pushName was available),
                # upgrade it from the inbound pushName so chatter shows a real
                # human name. Don't touch partner.name when the user has
                # already curated it.
                if name and partner.name and partner.name.lstrip('+').replace(' ', '') == (
                        partner.phone or '').lstrip('+').replace(' ', ''):
                    partner.name = name
                return partner

        # Auto-create if configured
        auto_create = self.env['ir.config_parameter'].sudo().get_param(
            'open_whatsapp_connector.auto_create_contacts', 'True'
        )
        if auto_create.lower() in ('true', '1', 'yes'):
            partner = self.create({
                'name': name or f'+{number}',
                'phone': f'+{number}',
            })
            _logger.info("Auto-created partner %s for WhatsApp number %s", partner.id, number)
            return partner

        return self.env['res.partner']
