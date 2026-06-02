"""Phase F: WhatsApp group join wizard.

Two-step UX: paste an invite code or full ``chat.whatsapp.com`` URL,
click Preview to see the group's subject / owner / size, then confirm
to actually join.
"""
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.open_whatsapp_connector.tools.baileys_api import BaileysApi

_logger = logging.getLogger(__name__)


class OwaGroupJoinWizard(models.TransientModel):
    _name = 'owa.group.join.wizard'
    _description = 'WhatsApp Group Join Wizard'

    wa_account_id = fields.Many2one(
        'owa.account', required=True, string='WhatsApp Account')
    invite_input = fields.Char(
        string='Invite Code or Link', required=True,
        help='Paste either a full https://chat.whatsapp.com/<code> URL or '
             'just the bare code.')
    preview_loaded = fields.Boolean(default=False)
    preview_subject = fields.Char(string='Group Name', readonly=True)
    preview_description = fields.Text(string='Description', readonly=True)
    preview_owner = fields.Char(string='Owner JID', readonly=True)
    preview_size = fields.Integer(string='Members', readonly=True)
    preview_creation_ts = fields.Integer(readonly=True)

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

    def _code(self):
        return BaileysApi.normalize_invite_code(self.invite_input or '')

    def _ensure_connected(self):
        if self.wa_account_id.session_state != 'connected':
            raise UserError(_(
                "WhatsApp account '%s' is not connected. "
                "Open WhatsApp → Configuration → Accounts and click "
                "Connect or Refresh Status, then retry."
            ) % self.wa_account_id.name)

    def action_preview(self):
        self.ensure_one()
        self._ensure_connected()
        code = self._code()
        if not code:
            raise UserError(_("Please paste an invite link or code."))
        api = self.wa_account_id._get_baileys_api()
        try:
            info = api.get_invite_info(code)
        except Exception as exc:
            _logger.exception("Invite preview failed")
            raise UserError(_("Couldn't fetch invite info: %s") % exc)
        self.write({
            'preview_loaded': True,
            'preview_subject': info.get('subject') or '',
            'preview_description': info.get('desc') or info.get('description') or '',
            'preview_owner': info.get('subjectOwner') or info.get('owner') or '',
            'preview_size': info.get('size') or len(info.get('participants') or []),
            'preview_creation_ts': info.get('creation') or 0,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_join(self):
        self.ensure_one()
        self._ensure_connected()
        if not self.preview_loaded:
            return self.action_preview()
        code = self._code()
        api = self.wa_account_id._get_baileys_api()
        try:
            jid = api.accept_invite(code)
        except Exception as exc:
            _logger.exception("Invite accept failed")
            raise UserError(_("Couldn't accept the invite: %s") % exc)
        if not jid:
            raise UserError(_("WhatsApp didn't return a group JID — the invite "
                              "may have been revoked or expired."))
        # Pull metadata for the freshly-joined group and upsert into our model.
        all_groups = api.fetch_all_groups()
        target = next(
            (g for g in all_groups or [] if (g.get('id') or g.get('jid')) == jid),
            None,
        )
        Session = self.env['owa.group.session'].sudo()
        if target:
            row = Session._upsert_from_metadata(self.wa_account_id, target)
        else:
            row = Session._upsert_from_metadata(self.wa_account_id, {
                'id': jid,
                'subject': self.preview_subject,
                'desc': self.preview_description,
                'subjectOwner': self.preview_owner,
                'size': self.preview_size,
                'creation': self.preview_creation_ts,
            })
        if not row:
            raise UserError(_("Joined the group but couldn't store it locally — "
                              "click Refresh on the Groups list to pick it up."))
        return {
            'type': 'ir.actions.act_window',
            'name': _("WhatsApp Group"),
            'res_model': 'owa.group.session',
            'res_id': row.id,
            'view_mode': 'form',
            'target': 'current',
        }
