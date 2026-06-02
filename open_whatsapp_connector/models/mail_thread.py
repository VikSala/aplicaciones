import logging

from odoo import api, models
from odoo.addons.mail.tools.discuss import Store

_logger = logging.getLogger(__name__)


class MailThread(models.AbstractModel):
    _inherit = 'mail.thread'

    # v18-compat: v18 base signature is
    #   _thread_to_store(self, store, /, *, fields=None, request_list=None)
    # (keyword-only `fields` with default None). v19 had it as required
    # positional. Accept both calling styles.
    def _thread_to_store(self, store: Store, /, *, fields=None, request_list=None):
        super()._thread_to_store(store, fields=fields, request_list=request_list)
        if request_list:
            can_send = bool(self.env['owa.account'].search([
                ('session_state', '=', 'connected'),
            ], limit=1))
            store.add(self, {"canSendWhatsapp": can_send}, as_thread=True)

    def write(self, vals):
        """Override write to check notification rules when tracked fields change."""
        skip = self.env.context.get('owa_skip_notification')
        before = {}
        if not skip and vals and self:
            # Capture each record's value for every field being written, so we
            # can fire only when the value actually transitions to the trigger
            # value (rather than for every record in a batch write whose new
            # value happens to equal the trigger).
            tracked_fields = [f for f in vals if f in self._fields]
            if tracked_fields:
                before = {
                    rec.id: {f: rec[f] for f in tracked_fields}
                    for rec in self
                }
        result = super().write(vals)
        if skip:
            return result
        try:
            self._owa_check_notification_rules(vals, before)
        except Exception:
            _logger.exception("Error checking WhatsApp notification rules")
        return result

    def _owa_check_notification_rules(self, vals, before=None):
        """Check if any notification rules should fire based on field changes."""
        if not vals or not self:
            return
        before = before or {}
        model_name = self._name
        rules = self.env['owa.notification.rule'].sudo().search([
            ('model_name', '=', model_name),
            ('active', '=', True),
            ('trigger_field_name', 'in', list(vals.keys())),
        ])
        if not rules:
            return
        for record in self:
            for rule in rules:
                if not rule._vals_matches_trigger(vals):
                    continue
                # Only fire when the field's value actually changed. Compare
                # the snapshot we took before super().write to the current
                # value.
                field = rule.trigger_field_name
                old = (before.get(record.id, {}) or {}).get(field)
                new = record[field] if field in record._fields else None
                # Many2one before/after are recordsets; compare by id tuple.
                if hasattr(old, 'ids') and hasattr(new, 'ids'):
                    if tuple(old.ids) == tuple(new.ids):
                        continue
                elif old == new:
                    continue
                rule.with_context(owa_skip_notification=True)._send_notification(record)
