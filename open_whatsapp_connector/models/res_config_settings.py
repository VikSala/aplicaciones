from urllib.parse import quote

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    owa_default_sidecar_url = fields.Char(
        string="Default Sidecar URL",
        config_parameter='open_whatsapp_connector.default_sidecar_url',
        default='http://localhost:3100')
    owa_default_api_key = fields.Char(
        string="Default API Key",
        config_parameter='open_whatsapp_connector.default_api_key')
    owa_sidecar_path = fields.Char(
        string="Sidecar Path",
        config_parameter='open_whatsapp_connector.sidecar_path',
        help="Absolute path to the sidecar directory (containing package.json)")
    owa_sidecar_auto_start = fields.Boolean(
        string="Auto-start Sidecar",
        config_parameter='open_whatsapp_connector.sidecar_auto_start',
        default=False,
        help="Automatically start sidecar when connecting an account")

    owa_auto_create_contacts = fields.Boolean(
        string="Auto-create Contacts",
        config_parameter='open_whatsapp_connector.auto_create_contacts',
        default=True,
        help="Automatically create contact records for unknown WhatsApp numbers")

    owa_default_account_id = fields.Many2one(
        'owa.account', string="Default WhatsApp Account",
        config_parameter='open_whatsapp_connector.default_account_id',
        help="Pre-selected account in the composer wizard and notification "
             "rules when no other account has been chosen.")

    # ------------------------------------------------------------------
    # Marketing record visibility (per-user / per-team isolation toggle)
    # ------------------------------------------------------------------
    owa_marketing_visibility = fields.Selection(
        [
            ('shared', 'Shared across company (everyone sees all)'),
            ('own_team', 'Restricted to owner + their Sales Team'),
        ],
        string="Campaign & Contact Visibility",
        default='shared',
        config_parameter='open_whatsapp_connector.marketing_visibility',
        help="Shared: every WhatsApp user in the company sees all campaigns, "
             "contact lists, broadcast groups, standing orders and status "
             "broadcasts (default).\n"
             "Restricted: each user sees only the records they own or that "
             "belong to a Sales Team they are a member of / lead; WhatsApp "
             "users can create and manage their own records. WhatsApp "
             "Administrators always see everything.")

    # Record-rule + ACL XML ids toggled by the visibility setting. Kept in
    # one place so set_values() and any future maintenance stay in sync.
    _OWA_VISIBILITY_RULE_XMLIDS = (
        'open_whatsapp_connector.owa_campaign_user_rule',
        'open_whatsapp_connector.owa_campaign_admin_all_rule',
        'open_whatsapp_connector.owa_contact_list_user_rule',
        'open_whatsapp_connector.owa_contact_list_admin_all_rule',
        'open_whatsapp_connector.owa_contact_list_member_user_rule',
        'open_whatsapp_connector.owa_contact_list_member_admin_all_rule',
        'open_whatsapp_connector.owa_broadcast_group_user_rule',
        'open_whatsapp_connector.owa_broadcast_group_admin_all_rule',
        'open_whatsapp_connector.owa_standing_order_user_rule',
        'open_whatsapp_connector.owa_standing_order_admin_all_rule',
        'open_whatsapp_connector.owa_status_broadcast_user_rule',
        'open_whatsapp_connector.owa_status_broadcast_admin_all_rule',
    )
    _OWA_VISIBILITY_ACL_XMLIDS = (
        'open_whatsapp_connector.access_owa_campaign_user_manage',
        'open_whatsapp_connector.access_owa_contact_list_user_manage',
        'open_whatsapp_connector.access_owa_contact_list_member_user_manage',
        'open_whatsapp_connector.access_owa_broadcast_group_user_manage',
        'open_whatsapp_connector.access_owa_standing_order_user_manage',
        'open_whatsapp_connector.access_owa_status_broadcast_user_manage',
    )

    def set_values(self):
        super().set_values()
        # Reflect the chosen visibility mode by activating/deactivating the
        # shipped-inactive record rules + user-CRUD ACLs.
        restrict = self.owa_marketing_visibility == 'own_team'
        for xmlid in (self._OWA_VISIBILITY_RULE_XMLIDS
                      + self._OWA_VISIBILITY_ACL_XMLIDS):
            rec = self.env.ref(xmlid, raise_if_not_found=False)
            if rec and rec.active != restrict:
                rec.sudo().active = restrict

    def action_owa_enable_recommended(self):
        """One-click activate the ready-to-use, state-based starter rules.

        Bulk-activates every inactive notification rule that triggers on a
        ``state`` field (Sale confirmed, Invoice posted, Payment received,
        Delivery done, Quotation sent, PO confirmed, Repair done) and assigns
        the first connected WhatsApp account so they start sending right away.

        Stage-based rules (CRM Won, Task Done, Ticket Solved) are intentionally
        skipped — their trigger stage name varies per database, so they need a
        quick manual check before activation.
        """
        self.ensure_one()
        account = self.env['owa.account'].search(
            [('session_state', '=', 'connected')], limit=1)
        if not account:
            raise UserError(_(
                "Connect a WhatsApp account first, then click "
                "“Enable recommended automations” again."))
        rules = self.env['owa.notification.rule'].with_context(
            active_test=False).search([
                ('active', '=', False),
                ('trigger_field_name', '=', 'state'),
            ])
        if not rules:
            raise UserError(_(
                "No recommended automation rules left to enable — they may "
                "already be active."))
        rules.write({'wa_account_id': account.id, 'active': True})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("WhatsApp automations enabled"),
                'message': _(
                    "%(count)s rule(s) activated on account “%(name)s”.",
                    count=len(rules), name=account.name),
                'type': 'success',
                'sticky': False,
            },
        }

    # Website WhatsApp Widget
    owa_website_widget_enabled = fields.Boolean(
        string="Website WhatsApp Widget",
        config_parameter='open_whatsapp_connector.website_widget_enabled')
    owa_website_widget_phone = fields.Char(
        string="Widget Phone Number",
        config_parameter='open_whatsapp_connector.website_widget_phone')
    owa_website_widget_message = fields.Char(
        string="Default Message",
        config_parameter='open_whatsapp_connector.website_widget_message',
        default="Hello! I'd like to know more about your products.")
    owa_website_widget_code = fields.Text(
        string="Widget Embed Code",
        compute='_compute_website_widget_code')

    @api.depends('owa_website_widget_enabled', 'owa_website_widget_phone', 'owa_website_widget_message')
    def _compute_website_widget_code(self):
        for rec in self:
            if rec.owa_website_widget_enabled and rec.owa_website_widget_phone:
                phone = (rec.owa_website_widget_phone or '').replace('+', '').replace(' ', '').replace('-', '')
                # URL-encode the prefilled message — spaces/&/? would otherwise
                # break the wa.me link. (matches the glue addon's QWeb button)
                message = quote(rec.owa_website_widget_message or '', safe='')
                rec.owa_website_widget_code = (
                    '<!-- WhatsApp Chat Widget -->\n'
                    '<a href="https://wa.me/%s?text=%s" target="_blank" rel="noopener"\n'
                    '   style="position:fixed;bottom:24px;right:24px;z-index:9999;width:60px;height:60px;\n'
                    '   border-radius:50%%;background:#25D366;display:flex;align-items:center;\n'
                    '   justify-content:center;box-shadow:0 4px 12px rgba(0,0,0,.15);text-decoration:none">\n'
                    '   <svg viewBox="0 0 24 24" width="32" height="32" fill="white">\n'
                    '      <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15'
                    '-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475'
                    '-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52'
                    '.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207'
                    '-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297'
                    '-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487'
                    '.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413'
                    '.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347z"/>\n'
                    '      <path d="M12 0C5.373 0 0 5.373 0 12c0 2.625.846 5.059 2.284 7.034L.789 23.492'
                    'l4.632-1.467A11.95 11.95 0 0012 24c6.627 0 12-5.373 12-12S18.627 0 12 0zm0 21.818'
                    'c-2.168 0-4.18-.587-5.918-1.608l-.424-.252-4.393 1.152 1.172-4.283-.276-.439A9.77 9.77'
                    ' 0 012.182 12c0-5.423 4.395-9.818 9.818-9.818S21.818 6.577 21.818 12 17.423 21.818 12'
                    ' 21.818z"/>\n'
                    '   </svg>\n'
                    '</a>'
                ) % (phone, message)
            else:
                rec.owa_website_widget_code = False
