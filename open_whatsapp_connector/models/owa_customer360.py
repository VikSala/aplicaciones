"""Phase 22B: aggregated customer-360 timeline service.

Returns one chronological array of events per partner, drawing from every
Odoo app installed in the database (WhatsApp messages, calls, emails, sale
orders, invoices, helpdesk tickets, CRM leads, activities). The OWL
client mounts the result as a vertical timeline."""
import logging
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class OwaCustomer360(models.AbstractModel):
    _name = 'owa.customer360'
    _description = 'WhatsApp Customer-360 Timeline'

    @api.model
    def get_timeline_data(self, partner_id, date_from=None, date_to=None, limit=300):
        """Return one sorted timeline of events for a partner.

        Each event is a dict::
            {type, datetime, summary, model, res_id, icon, color}

        :param partner_id: int — required
        :param date_from, date_to: ISO date strings or None
        :param limit: max events returned (default 300, capped at 1000)
        """
        if not partner_id:
            return {'partner': None, 'events': []}
        partner = self.env['res.partner'].browse(partner_id).exists()
        if not partner:
            return {'partner': None, 'events': []}
        limit = min(int(limit or 300), 1000)
        now = fields.Datetime.now()
        dt_to = (fields.Datetime.from_string(date_to + ' 23:59:59')
                 if (date_to and len(date_to) == 10) else now)
        dt_from = (fields.Datetime.from_string(date_from + ' 00:00:00')
                   if (date_from and len(date_from) == 10)
                   else dt_to - timedelta(days=180))

        events = []
        # model -> list of record ids gathered below, so the activity query
        # can also surface activities scheduled on the contact's linked
        # records (tickets / leads / orders / invoices). (#c360)
        linked_refs = {}

        # WhatsApp messages
        WaMessage = self.env['owa.message'].sudo()
        messages = WaMessage.search([
            ('whatsapp_partner_id', '=', partner.id),
            ('create_date', '>=', dt_from), ('create_date', '<=', dt_to),
        ], order='create_date desc', limit=limit)
        for m in messages:
            events.append({
                'type': 'wa_message',
                'datetime': fields.Datetime.to_string(m.create_date),
                'summary': self._summarize_message(m),
                'model': 'owa.message', 'res_id': m.id,
                'icon': 'fa-whatsapp',
                'color': 'success' if m.message_type == 'inbound' else 'info',
            })

        # Phase 21 calls
        if 'owa.call.log' in self.env:
            calls = self.env['owa.call.log'].sudo().search([
                ('partner_id', '=', partner.id),
                ('started_at', '>=', dt_from), ('started_at', '<=', dt_to),
            ], order='started_at desc', limit=limit)
            for c in calls:
                events.append({
                    'type': 'wa_call',
                    'datetime': fields.Datetime.to_string(c.started_at),
                    'summary': c.display_name,
                    'model': 'owa.call.log', 'res_id': c.id,
                    'icon': 'fa-video-camera' if c.is_video else 'fa-phone',
                    'color': 'danger' if c.state in ('missed', 'rejected', 'timeout') else 'success',
                })

        # Mail messages (excluding notifications already covered by chatter)
        mail_messages = self.env['mail.message'].sudo().search([
            ('partner_ids', 'in', partner.id),
            ('message_type', 'in', ['email', 'comment']),
            ('date', '>=', dt_from), ('date', '<=', dt_to),
        ], order='date desc', limit=limit)
        for mm in mail_messages:
            events.append({
                'type': 'mail',
                'datetime': fields.Datetime.to_string(mm.date),
                'summary': (mm.subject or _("(no subject)"))[:120],
                'model': mm.model, 'res_id': mm.res_id,
                'icon': 'fa-envelope',
                'color': 'secondary',
            })

        # Sale orders
        if 'sale.order' in self.env:
            sos = self.env['sale.order'].sudo().search([
                ('partner_id', '=', partner.id),
                ('create_date', '>=', dt_from), ('create_date', '<=', dt_to),
            ], order='create_date desc', limit=limit)
            linked_refs['sale.order'] = sos.ids
            for so in sos:
                events.append({
                    'type': 'sale_order',
                    'datetime': fields.Datetime.to_string(so.create_date),
                    'summary': f"{so.name} · {so.state} · {so.amount_total} {so.currency_id.name}",
                    'model': 'sale.order', 'res_id': so.id,
                    'icon': 'fa-shopping-cart',
                    'color': 'success' if so.state == 'sale' else 'info',
                })

        # Account moves (invoices/payments)
        if 'account.move' in self.env:
            moves = self.env['account.move'].sudo().search([
                ('partner_id', '=', partner.id),
                ('move_type', 'in', ['out_invoice', 'out_refund']),
                ('create_date', '>=', dt_from), ('create_date', '<=', dt_to),
            ], order='create_date desc', limit=limit)
            linked_refs['account.move'] = moves.ids
            for inv in moves:
                events.append({
                    'type': 'invoice',
                    'datetime': fields.Datetime.to_string(inv.create_date),
                    'summary': f"{inv.name} · {inv.payment_state or inv.state}",
                    'model': 'account.move', 'res_id': inv.id,
                    'icon': 'fa-file-text-o',
                    'color': 'success' if inv.payment_state == 'paid' else 'warning',
                })

        # Helpdesk tickets
        if 'helpdesk.ticket' in self.env:
            tickets = self.env['helpdesk.ticket'].sudo().search([
                ('partner_id', '=', partner.id),
                ('create_date', '>=', dt_from), ('create_date', '<=', dt_to),
            ], order='create_date desc', limit=limit)
            linked_refs['helpdesk.ticket'] = tickets.ids
            for t in tickets:
                events.append({
                    'type': 'ticket',
                    'datetime': fields.Datetime.to_string(t.create_date),
                    'summary': f"#{t.id} {t.name}",
                    'model': 'helpdesk.ticket', 'res_id': t.id,
                    'icon': 'fa-life-ring',
                    'color': 'danger',
                })

        # CRM leads
        if 'crm.lead' in self.env:
            leads = self.env['crm.lead'].sudo().search([
                ('partner_id', '=', partner.id),
                ('create_date', '>=', dt_from), ('create_date', '<=', dt_to),
            ], order='create_date desc', limit=limit)
            linked_refs['crm.lead'] = leads.ids
            for l in leads:
                events.append({
                    'type': 'lead',
                    'datetime': fields.Datetime.to_string(l.create_date),
                    'summary': f"{l.name} · {l.stage_id.name or '?'}",
                    'model': 'crm.lead', 'res_id': l.id,
                    'icon': 'fa-bullseye',
                    'color': 'info',
                })

        # Activities (open ones), spanning the contact AND its linked records
        # (tickets / leads / orders / invoices) — not just res.partner. Both
        # date bounds applied like every other query. (#c360)
        ref_clauses = [
            ['&', ('res_model', '=', 'res.partner'), ('res_id', '=', partner.id)]
        ]
        for model_name, ids in linked_refs.items():
            if ids:
                ref_clauses.append(
                    ['&', ('res_model', '=', model_name), ('res_id', 'in', ids)])
        # OR the ref clauses together (n-1 '|' prefixes), then AND the dates.
        ref_domain = ['|'] * (len(ref_clauses) - 1)
        for clause in ref_clauses:
            ref_domain += clause
        activities = self.env['mail.activity'].sudo().search(
            [('date_deadline', '>=', dt_from.date()),
             ('date_deadline', '<=', dt_to.date())] + ref_domain,
            order='date_deadline desc', limit=limit)
        for a in activities:
            events.append({
                'type': 'activity',
                'datetime': fields.Datetime.to_string(
                    fields.Datetime.from_string(str(a.date_deadline) + ' 12:00:00')
                ) if a.date_deadline else fields.Datetime.to_string(a.create_date),
                'summary': f"{a.activity_type_id.name} · {a.summary or ''}",
                # Open the activity's underlying record on click (res.partner
                # here) — mail.activity itself has no form view, so the old
                # 'mail.activity' target raised "No form view found". (#c360)
                'model': a.res_model or 'res.partner', 'res_id': a.res_id or partner.id,
                'icon': 'fa-clock-o',
                'color': 'warning',
            })

        events.sort(key=lambda e: e['datetime'], reverse=True)
        events = events[:limit]
        return {
            'partner': {
                'id': partner.id,
                'name': partner.name,
                'image_1024': bool(partner.image_1024),
                'phone': partner.phone or '',
                'mobile': partner.mobile or '',
                'email': partner.email or '',
            },
            'events': events,
            'total': len(events),
        }

    def _summarize_message(self, msg):
        body = html2plaintext(msg.body or '').strip()
        if not body:
            has_media = bool(msg.mail_message_id and msg.mail_message_id.attachment_ids)
            body = '<media>' if has_media else _('(empty)')
        return body[:140] + ('…' if len(body) > 140 else '')
