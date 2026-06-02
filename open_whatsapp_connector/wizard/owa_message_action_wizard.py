"""Phase G: outbound message-action wizards (forward + react).

Two transient models drive the right-click actions on chatter:
- ``owa.message.forward.wizard`` — forward a previously-sent / received
  WhatsApp message to a different chat or contact.
- ``owa.message.react.wizard`` — send an emoji reaction to a specific
  WhatsApp message (group or 1:1) from Odoo, the user-driven counterpart
  of the existing inbound 👀 ack reaction.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _resolve_message_jid(msg):
    """Resolve the source chat's JID for an owa.message. Prefer the linked
    discuss.channel.whatsapp_number (already a JID for groups, +digits for
    direct chats); fall back to mobile_number when the mail.message isn't
    linked to a channel. Shared by the Forward and React wizards."""
    mail_msg = msg.mail_message_id
    if mail_msg and mail_msg.model == 'discuss.channel' and mail_msg.res_id:
        channel = msg.env['discuss.channel'].browse(mail_msg.res_id)
        if channel.whatsapp_number:
            jid = channel.whatsapp_number
            if '@' not in jid:
                jid = f'{jid.lstrip("+")}@s.whatsapp.net'
            return jid
    raw = (msg.mobile_number or '').lstrip('+')
    if not raw:
        return ''
    if '@' in raw:
        return raw
    return f'{raw}@s.whatsapp.net'


class OwaMessageForwardWizard(models.TransientModel):
    _name = 'owa.message.forward.wizard'
    _description = 'Forward a WhatsApp Message'

    owa_message_id = fields.Many2one(
        'owa.message', required=True, ondelete='cascade',
        help='The original message to forward.')
    wa_account_id = fields.Many2one(
        'owa.account', related='owa_message_id.wa_account_id',
        readonly=True)
    target_channel_ids = fields.Many2many(
        'discuss.channel', string='Target WhatsApp Chats',
        domain="[('channel_type', '=', 'whatsapp')]",
        help='Pick existing WhatsApp Discuss channels.')
    target_phones = fields.Text(
        string='Or — Raw Phone Numbers',
        help='One per line, country code first.')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if 'owa_message_id' in fields_list and not vals.get('owa_message_id'):
            ctx_id = self.env.context.get('default_owa_message_id') \
                or self.env.context.get('active_id')
            if ctx_id:
                vals['owa_message_id'] = ctx_id
        return vals

    def _resolve_targets(self):
        targets = []
        for ch in self.target_channel_ids:
            if ch.whatsapp_number:
                jid = ch.whatsapp_number
                if '@' not in jid:
                    jid = f'{jid.lstrip("+")}@s.whatsapp.net'
                targets.append(jid)
        for line in (self.target_phones or '').replace(',', '\n').split('\n'):
            line = line.strip().lstrip('+')
            if line:
                targets.append(f'{line}@s.whatsapp.net')
        return list(dict.fromkeys(targets))

    def _source_jid(self):
        return _resolve_message_jid(self.owa_message_id)

    def action_forward(self):
        self.ensure_one()
        targets = self._resolve_targets()
        if not targets:
            raise UserError(_("Pick at least one target channel or enter a phone number."))
        msg = self.owa_message_id
        if not msg.msg_uid:
            raise UserError(_(
                "This message has no WhatsApp ID — it may have failed to send "
                "or arrived before message tracking was enabled."
            ))
        source_jid = self._source_jid()
        if not source_jid:
            raise UserError(_("Couldn't determine the source chat JID."))
        api = self.wa_account_id._get_baileys_api()
        ok, fail, errors = 0, 0, []
        for to in targets:
            try:
                api.forward_message(source_jid, msg.msg_uid, to)
                ok += 1
            except Exception as exc:
                _logger.warning("Forward to %s failed: %s", to, exc)
                fail += 1
                errors.append("%s: %s" % (to, exc))
        message = _("Forwarded to %(ok)d / %(total)d targets.") % {
            'ok': ok, 'total': ok + fail,
        }
        if errors:
            message += "\n" + "\n".join(errors[:5])
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _("Forward"),
                'message': message,
                'type': 'success' if fail == 0 else 'warning',
                'sticky': fail > 0,
            },
        }


class OwaMessageReactWizard(models.TransientModel):
    _name = 'owa.message.react.wizard'
    _description = 'React to a WhatsApp Message'

    owa_message_id = fields.Many2one(
        'owa.message', required=True, ondelete='cascade')
    wa_account_id = fields.Many2one(
        'owa.account', related='owa_message_id.wa_account_id', readonly=True)
    emoji = fields.Char(
        string='Emoji', required=True, default='👍',
        help='Single emoji glyph. Empty string = remove your previous reaction.')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        if 'owa_message_id' in fields_list and not vals.get('owa_message_id'):
            ctx_id = self.env.context.get('default_owa_message_id') \
                or self.env.context.get('active_id')
            if ctx_id:
                vals['owa_message_id'] = ctx_id
        return vals

    def action_react(self):
        self.ensure_one()
        msg = self.owa_message_id
        if not msg.msg_uid:
            raise UserError(_("This message has no WhatsApp ID — can't react."))
        # ── Official Cloud API transport ──────────────────────────────
        # Meta's reaction message targets the original wamid + the bare
        # recipient number (no @s.whatsapp.net JID). Empty emoji clears a
        # prior reaction, same as the QR path.
        if self.wa_account_id.connection_type == 'cloud':
            to = (msg.mobile_number_formatted or msg.mobile_number or '').lstrip('+')
            if not to:
                raise UserError(_("Couldn't determine the recipient number."))
            self.wa_account_id._dispatch_send(
                'reaction', to=to, message_id=msg.msg_uid,
                emoji=self.emoji or '')
            return {
                'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {
                    'title': _("Reaction sent"),
                    'message': self.emoji or _("(reaction cleared)"),
                    'type': 'success',
                },
            }
        api = self.wa_account_id._get_baileys_api()
        # Reuse the same source-JID resolution as forward — works for both
        # 1:1 and group chats by walking through the linked discuss.channel.
        target_jid = _resolve_message_jid(msg)
        if not target_jid:
            raise UserError(_("Couldn't determine the chat JID for this message."))
        # `participant` (the original sender of an inbound group message) is
        # required to react to another member's message in a group. It's stored
        # on owa.message.sender_jid for group inbound (empty for DMs / our own
        # outbound, where it's correctly omitted). (#reactions)
        api.send_reaction_v2(
            target_jid, msg.msg_uid, self.emoji or '',
            target_from_me=(msg.message_type == 'outbound'),
            target_participant=msg.sender_jid or None,
        )
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {
                'title': _("Reaction sent"),
                'message': self.emoji or _("(reaction cleared)"),
                'type': 'success',
            },
        }
