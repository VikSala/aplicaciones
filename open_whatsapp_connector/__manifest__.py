{
    'name': 'Open WhatsApp Connector',
    'author': 'Roshan',
    'category': 'Productivity/WhatsApp',
    'summary': 'WhatsApp for Odoo - Discuss inbox, dashboard, campaigns, chatbots, slash commands, group support, incoming-call awareness, Customer-360, inbound rules, broadcast groups, standing orders, helpdesk + CSAT bridge. No Meta API. QR-code setup.',
    'price': 30.00,
    'currency': 'USD',
    'license': 'OPL-1',
    'version': '18.0.32.0.0',
    'images': [
        'static/description/banner.png',
        'static/description/screenshots/dashboard_full.png',
        'static/description/screenshots/qr_pairing_screen.png',
        'static/description/screenshots/dashboard_with_incoming_call.png',
        'static/description/screenshots/accounts_kanban_multi.png',
        'static/description/screenshots/sale_order_notification_fired.png',
        'static/description/screenshots/customer_360_timeline.png',
        'static/description/screenshots/contact_smart_buttons_360.png',
        'static/description/screenshots/calls_log.png',
        'static/description/screenshots/messages_list.png',
    ],
    'description': """
WhatsApp integration via WhatsApp Web protocol using a Node.js sidecar
service. No Meta Business API approval needed - scan a QR code to connect.

Messaging
- Text, media, audio (voice notes via PTT), animated GIF, polls, location, vCard
- Long-text chunking (paragraph-aware), per-account size cap with image auto-resize
- Reply quoting policy (off / first / all), self-chat protections
- Acknowledgement reactions on inbound, cleared after reply

Inbox
- Full Discuss integration with WhatsApp channels in the side bar
- Reply-context envelopes, unified <media:*> placeholders, fenced location/vCard

Routing & access control
- DM policy (open / allowlist / pairing / disabled) + Pending Approvals queue
- Group policy (open / allowlist / disabled), per-group @-mention gating
- Blacklist with auto-STOP keyword
- Chat-side slash commands (/help /menu /start /stop /agent), pluggable registry

Automation
- Notification rules triggered by Odoo record state changes
- Campaigns with rendered templates, polls, sync send for small lists, bus-driven
  form refresh
- Auto-reply rules (welcome / away / keyword / all) with per-account timezone
- Chatbots with menu trees, CRM lead creation, single-active-per-account guard

Operations
- Real-time Operations Dashboard with KPI tiles, charts, drill-through
- Per-account Run Diagnostics button, heartbeat cron, computed health badge
- Multi-account, multi-database, per-account credential backups
- Multi-company isolation via wa_account.allowed_company_ids

Incoming calls
- Voice + video call detection via the WhatsApp event stream
- WhatsApp Calls log per contact, missed-call auto-reply (per-account toggle)
- Click-to-call on every partner (Voice / Video, opens WhatsApp app)
- Missed-calls KPI tile + drill-through on the Operations Dashboard

CRM triage
- Conversation assignment with SLA cron + breach activities
- Customer-360 timeline view: WhatsApp + calls + sale orders + invoices +
  helpdesk tickets + CRM leads + activities chronologically interleaved
- Inbound auto-create rules: regex / keyword / sender pattern / unknown sender
  triggers create CRM leads, helpdesk tickets, sale-order drafts, project
  tasks or hr applicants

Enterprise bridges
- Helpdesk ticket linkage on WhatsApp Discuss channels
- CSAT survey auto-sent on conversation resolve, scores aggregated on dashboard
- Mass-mailing + marketing-automation hooks for unified email+WhatsApp campaigns

Domain bridges
- POS digital-receipt push, subscription dunning templates
- Recruitment auto-reply on hr.applicant stage changes
- Project task auto-create from inbound rules

Broadcast & scheduling
- Broadcast Groups: saved recipient lists with per-recipient session isolation
- Standing Orders: recurring sends (daily / weekly / monthly + time of day)
- Status Broadcasts: WhatsApp Stories (text/image/video, 24h expiry)
- Conversation labels with multi-tag M2M
- Granular Health Issues panel with severity + resolve flow

Compliance & polish
- Outbound throttling: per-minute/hour/day caps with anti-ban backoff
- Opt-in tracking on res.partner (date + source) for compliant outbound
- 12 ready-to-use sales templates (Quote/Order/Invoice/Refund flow)
- Auto-tag rules on inbound (regex/keyword -> res.partner.category)
- Mass actions on the Calls log (create lead, block number)
- Conversation merge wizard for orphaned-channel cleanup
- Daily partner-avatar refresh from WhatsApp profile pictures
- Configurable per-user/per-team marketing visibility (Settings -> WhatsApp)
    """,
    'depends': ['mail', 'phone_validation', 'sales_team'],
    'data': [
        'security/res_groups.xml',
        'security/ir_rules.xml',
        'security/ir.model.access.csv',
        'security/ir_model_access_marketing.xml',
        'data/ir_cron_data.xml',
        'data/owa_server_action_data.xml',
        'data/owa_quick_reply_data.xml',
        'data/owa_slash_command_data.xml',
        'data/owa_sale_templates.xml',
        'data/owa_dunning_templates.xml',
        'data/owa_recruitment_templates.xml',
        # Starter automations library - quick-reply templates referenced by the
        # post_init_hook's extra notification rules, plus ready-to-activate
        # auto-replies and a Main Menu chatbot (all ship inactive).
        'data/owa_starter_templates.xml',
        'data/owa_starter_automations.xml',
        # Root menu must load BEFORE any view file that uses
        # parent="open_whatsapp_connector.menu_owa_root" on a <menuitem>.
        'views/owa_menu_root.xml',
        'wizard/owa_composer_views.xml',
        'wizard/owa_channel_merge_wizard_views.xml',
        'wizard/owa_group_participant_wizard_views.xml',
        'wizard/owa_group_create_wizard_views.xml',
        'wizard/owa_group_join_wizard_views.xml',
        'wizard/owa_message_action_wizard_views.xml',
        'wizard/owa_community_create_wizard_views.xml',
        'wizard/owa_newsletter_wizards_views.xml',
        'wizard/owa_send_wizards_views.xml',
        'wizard/owa_status_send_wizard_views.xml',
        'views/owa_message_views.xml',
        'views/owa_account_views.xml',
        'views/owa_quick_reply_views.xml',
        'views/discuss_channel_views.xml',
        'views/res_config_settings_views.xml',
        'views/owa_call_log_views.xml',
        'views/owa_inbound_rule_views.xml',
        'views/owa_phase22_phase26_views.xml',
        'views/owa_baileys_views.xml',
        'views/res_partner_views.xml',
        'views/owa_customer360_views.xml',
        'views/owa_notification_rule_views.xml',
        'views/owa_auto_reply_views.xml',
        'views/owa_blacklist_views.xml',
        'views/owa_allowlist_views.xml',
        'views/owa_pending_pair_views.xml',
        'views/owa_campaign_views.xml',
        'views/owa_chatbot_views.xml',
        'views/owa_slash_command_views.xml',
        'views/owa_dashboard_views.xml',
        'views/owa_group_session_views.xml',
        'views/owa_community_views.xml',
        'views/owa_newsletter_views.xml',
        'views/owa_menus.xml',
        'views/owa_cloud_template_views.xml',
        # NB: the website "WhatsApp Chat Button" settings block lives directly in
        # views/res_config_settings_views.xml. The floating button itself is
        # rendered by the sibling glue addon open_whatsapp_connector_website
        # (auto-installs with the `website` module). The old redundant
        # owa_website_widget_views.xml was removed in 27.3.0.
    ],
    'assets': {
        'web.assets_backend': [
            'open_whatsapp_connector/static/src/**/*',
        ],
        'web.assets_tests': [
            'open_whatsapp_connector/static/tests/**/*.js',
        ],
    },
    'demo': [
        'demo/demo_data.xml',
    ],
    'external_dependencies': {
        'python': ['phonenumbers'],
    },
    'post_init_hook': '_create_default_notification_rules',
    'application': True,
    'installable': True,
    'website': 'https://github.com/roshank8s/',
}
