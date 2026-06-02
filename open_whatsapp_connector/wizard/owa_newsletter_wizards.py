"""Phase G: WhatsApp Newsletter create + subscribe wizards."""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OwaNewsletterCreateWizard(models.TransientModel):
    _name = 'owa.newsletter.create.wizard'
    _description = 'WhatsApp Newsletter Creation Wizard'

    wa_account_id = fields.Many2one(
        'owa.account', required=True)
    name = fields.Char(required=True, size=100)
    description = fields.Text(size=512)

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

    def action_create(self):
        self.ensure_one()
        if self.wa_account_id.session_state != 'connected':
            raise UserError(_(
                "WhatsApp account '%s' is not connected. "
                "Open WhatsApp → Configuration → Accounts and click "
                "Connect or Refresh Status, then retry."
            ) % self.wa_account_id.name)
        api = self.wa_account_id._get_baileys_api()
        try:
            metadata = api.create_newsletter(self.name.strip(), self.description or '')
        except Exception as exc:
            raise UserError(_("Newsletter creation failed: %s") % exc)
        Newsletter = self.env['owa.newsletter'].sudo()
        row = Newsletter._upsert_from_metadata(self.wa_account_id, metadata)
        if not row:
            raise UserError(_("Created but no metadata returned."))
        row.role = 'owner'
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'owa.newsletter',
            'res_id': row.id,
            'view_mode': 'form',
            'target': 'current',
        }


class OwaNewsletterSubscribeWizard(models.TransientModel):
    _name = 'owa.newsletter.subscribe.wizard'
    _description = 'Subscribe to WhatsApp Newsletter'

    wa_account_id = fields.Many2one('owa.account', required=True)
    newsletter_input = fields.Char(
        string='Newsletter JID or Invite Link', required=True,
        help='Either a full ``<digits>@newsletter`` JID, or a '
             'whatsapp.com/channel/<code> link.')

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

    def _ensure_connected(self):
        if self.wa_account_id.session_state != 'connected':
            raise UserError(_(
                "WhatsApp account '%s' is not connected. "
                "Open WhatsApp → Configuration → Accounts and click "
                "Connect or Refresh Status, then retry."
            ) % self.wa_account_id.name)

    def _resolve_jid_and_metadata(self):
        """Return (jid, metadata_dict) for the user-pasted input.

        The input can be either a full ``<digits>@newsletter`` JID or a
        ``https://whatsapp.com/channel/<code>`` URL. For JIDs we go straight
        to ``newsletterMetadata``; for URLs we use the invite-by-code path
        (sidecar route ``newsletterMetadataByInvite``)."""
        text = (self.newsletter_input or '').strip()
        if not text:
            return '', {}
        api = self.wa_account_id._get_baileys_api()
        if '@newsletter' in text:
            try:
                meta = api.get_newsletter_metadata(text)
            except Exception:
                meta = {}
            return text, meta or {}
        # URL form — strip and resolve via invite code.
        code = text
        if text.startswith('http'):
            code = text.rstrip('/').split('/')[-1].split('?')[0]
        try:
            meta = api.get_newsletter_by_invite(code)
        except Exception as exc:
            raise UserError(_(
                "Couldn't fetch the newsletter via invite code: %s") % exc)
        jid = (meta or {}).get('id') or (meta or {}).get('jid') or ''
        return jid, meta or {}

    def _resolve_jid(self):
        jid, _meta = self._resolve_jid_and_metadata()
        return jid

    def action_subscribe(self):
        self.ensure_one()
        self._ensure_connected()
        jid, metadata = self._resolve_jid_and_metadata()
        if not jid:
            raise UserError(_(
                "Couldn't resolve the JID — paste the chat.whatsapp.com/channel link "
                "again, or use the bare <digits>@newsletter JID."
            ))
        api = self.wa_account_id._get_baileys_api()
        api.follow_newsletter(jid)
        # Ensure metadata at least carries the jid so _upsert can write something.
        if not metadata:
            metadata = {'id': jid}
        Newsletter = self.env['owa.newsletter'].sudo()
        row = Newsletter._upsert_from_metadata(self.wa_account_id, metadata)
        if row:
            row.role = 'subscriber'
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'owa.newsletter',
                'res_id': row.id,
                'view_mode': 'form',
                'target': 'current',
            }
        return True
