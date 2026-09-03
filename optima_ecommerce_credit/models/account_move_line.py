from odoo import models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    def _optima_get_draft_ecommerce_sync_map(self):
        result = {}
        for line in self.filtered(
            lambda line: line.move_id.state == "draft"
            and line.move_id.move_type in ("out_invoice", "out_refund")
            and line.move_id._optima_is_ecommerce_risk_move()
        ):
            result.setdefault(line.company_id, self.env["res.partner"])
            result[line.company_id] |= line.move_id.commercial_partner_id
        return result

    def write(self, vals):
        before = self._optima_get_draft_ecommerce_sync_map()
        result = super().write(vals)
        after = self._optima_get_draft_ecommerce_sync_map()
        for company in set(before) | set(after):
            partners = (
                before.get(company, self.env["res.partner"])
                | after.get(company, self.env["res.partner"])
            ).exists()
            if partners:
                partners._optima_queue_ecommerce_risk_sync(company=company)
        return result

    def unlink(self):
        before = self._optima_get_draft_ecommerce_sync_map()
        result = super().unlink()
        for company, partners in before.items():
            partners.exists()._optima_queue_ecommerce_risk_sync(company=company)
        return result
