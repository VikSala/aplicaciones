from . import controllers
from . import models
from . import tools
from . import wizard


def _create_default_notification_rules(env):
    """Create default notification rules for common business flows.

    Called as a post_init_hook. Rules are created inactive since they
    need a WhatsApp account to be selected before they can work.
    Only creates rules for models that are actually installed.
    """
    Rule = env['owa.notification.rule']
    QuickReply = env['owa.quick.reply']
    IrModel = env['ir.model']
    IrModelFields = env['ir.model.fields']

    rules_config = [
        {
            'name': 'Sale Order Confirmed',
            'model': 'sale.order',
            'field': 'state',
            'value': 'sale',
            'template_xmlid': 'open_whatsapp_connector.quick_reply_sale_order_confirmed',
            'phone_field': 'partner_id.phone',
            # Attach the Quotation / Order PDF so the customer gets a copy of
            # their confirmed order on WhatsApp. (At SO-confirm time there is
            # no invoice yet — that PDF rides on the "Invoice Posted" rule.)
            'report_xmlid': 'sale.action_report_saleorder',
        },
        {
            'name': 'Invoice Posted',
            'model': 'account.move',
            'field': 'state',
            'value': 'posted',
            'template_xmlid': 'open_whatsapp_connector.quick_reply_invoice_posted',
            'phone_field': 'partner_id.phone',
            # Attach the Invoice PDF the moment the invoice is validated.
            'report_xmlid': 'account.account_invoices',
        },
        {
            'name': 'Delivery Completed',
            'model': 'stock.picking',
            'field': 'state',
            'value': 'done',
            'template_xmlid': 'open_whatsapp_connector.quick_reply_delivery_done',
            'phone_field': 'partner_id.phone',
        },
        {
            'name': 'Payment Received',
            'model': 'account.payment',
            'field': 'state',
            # Odoo 18 account.payment.state = draft/in_process/paid/canceled/
            # rejected — there is NO 'posted' state (that's account.move).
            # action_post() moves the payment to 'in_process' (bank/card/SEPA)
            # — that's the moment to notify "payment received". 'paid' only
            # happens later on reconciliation / for cash journals. (#notif)
            'value': 'in_process',
            'template_xmlid': 'open_whatsapp_connector.quick_reply_payment_received',
            'phone_field': 'partner_id.phone',
        },
        # --- Additional ready-to-use rules (state-based: fire reliably) ---
        {
            'name': 'Quotation Sent',
            'model': 'sale.order',
            'field': 'state',
            'value': 'sent',
            'template_xmlid': 'open_whatsapp_connector.quick_reply_quotation_sent',
            'phone_field': 'partner_id.phone',
            'report_xmlid': 'sale.action_report_saleorder',
        },
        {
            'name': 'Purchase Order Confirmed',
            'model': 'purchase.order',
            'field': 'state',
            'value': 'purchase',
            'template_xmlid': 'open_whatsapp_connector.quick_reply_po_confirmed',
            'phone_field': 'partner_id.phone',
            'report_xmlid': 'purchase.report_purchase_order',
        },
        {
            'name': 'Repair Completed',
            'model': 'repair.order',
            'field': 'state',
            'value': 'done',
            'template_xmlid': 'open_whatsapp_connector.quick_reply_repair_done',
            'phone_field': 'partner_id.phone',
        },
        # --- Stage-based rules: trigger on stage_id, whose NAME varies per DB.
        # Shipped with the caveat baked into the rule name so a non-technical
        # admin checks the trigger stage before activating. The bulk "Enable
        # recommended automations" button deliberately SKIPS these (it only
        # touches state-based rules that always fire). ---
        {
            'name': 'CRM — Opportunity Won (check your Won stage)',
            'model': 'crm.lead',
            'field': 'stage_id',
            'value': 'Won',
            'template_xmlid': 'open_whatsapp_connector.quick_reply_crm_won',
            'phone_field': 'phone',
        },
        {
            'name': 'Project — Task Done (check your Done stage)',
            'model': 'project.task',
            'field': 'stage_id',
            'value': 'Done',
            'template_xmlid': 'open_whatsapp_connector.quick_reply_task_done',
            'phone_field': 'partner_id.phone',
        },
        {
            'name': 'Helpdesk — Ticket Solved (check your Solved stage)',
            'model': 'helpdesk.ticket',
            'field': 'stage_id',
            'value': 'Solved',
            'template_xmlid': 'open_whatsapp_connector.quick_reply_ticket_solved',
            'phone_field': 'partner_id.phone',
        },
    ]

    for cfg in rules_config:
        # Skip if model not installed
        model = IrModel.search([('model', '=', cfg['model'])], limit=1)
        if not model:
            continue

        field = IrModelFields.search([
            ('model_id', '=', model.id),
            ('name', '=', cfg['field']),
        ], limit=1)
        if not field:
            continue

        # Skip if rule already exists. Dedupe on model_id (the real FK, always
        # set) rather than model_name — model_name is a stored-related field
        # that is NULL on rules created by very old installs, which would let
        # this helper create duplicates on re-run. (#dedupe)
        existing = Rule.with_context(active_test=False).search([
            ('name', '=', cfg['name']),
            ('model_id', '=', model.id),
        ], limit=1)
        if existing:
            continue

        template = env.ref(cfg['template_xmlid'], raise_if_not_found=False)

        # Resolve the optional PDF report; only enable attachment if the
        # report's XML id actually exists in this DB (it ships with the
        # sale / account modules, which we already confirmed are installed).
        report = False
        if cfg.get('report_xmlid'):
            report = env.ref(cfg['report_xmlid'], raise_if_not_found=False)

        Rule.create({
            'name': cfg['name'],
            'active': False,
            'model_id': model.id,
            'trigger_field_id': field.id,
            'trigger_value': cfg['value'],
            'quick_reply_id': template.id if template else False,
            'phone_field': cfg['phone_field'],
            'wa_account_id': False,
            'attach_pdf': bool(report),
            'report_id': report.id if report else False,
        })

    # Create "Send WhatsApp" server actions for common models. Each opens the
    # composer pre-selecting the model's customer-facing report, so its PDF is
    # attached on send. report xmlids resolve at wizard-open time (guarded with
    # raise_if_not_found=False), so a missing report is harmless.
    ServerAction = env['ir.actions.server']
    action_models = [
        ('sale.order', 'Send WhatsApp', 'sale.action_report_saleorder'),
        ('account.move', 'Send WhatsApp', 'account.account_invoices'),
        ('stock.picking', 'Send WhatsApp', 'stock.action_report_delivery'),
        ('purchase.order', 'Send WhatsApp', 'purchase.report_purchase_quotation'),
    ]
    for model_name, action_name, report_xmlid in action_models:
        model = IrModel.search([('model', '=', model_name)], limit=1)
        if not model:
            continue
        code = ("action = env['owa.composer']._action_open_composer("
                "records, report_xmlid='%s')" % report_xmlid)
        existing = ServerAction.search([
            ('name', '=', action_name),
            ('model_id', '=', model.id),
            ('state', '=', 'code'),
        ], limit=1)
        if existing:
            # Older installs created the action WITHOUT report_xmlid — refresh
            # the code so the PDF-attach behaviour also reaches upgraded DBs
            # (the migration re-runs this helper).
            if 'report_xmlid' not in (existing.code or ''):
                existing.write({'code': code})
            continue
        ServerAction.create({
            'name': action_name,
            'model_id': model.id,
            'binding_model_id': model.id,
            'binding_view_types': 'list,form',
            'state': 'code',
            'code': code,
        })
