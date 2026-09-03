from odoo import api, models


class AccountPartialReconcile(models.Model):
    _inherit = "account.partial.reconcile"

    def _optima_get_ecommerce_partners_by_company(self):
        result = {}
        move_lines = self.mapped("debit_move_id") | self.mapped("credit_move_id")
        moves = move_lines.mapped("move_id")
        for move in moves.filtered(lambda m: m._optima_is_ecommerce_risk_move()):
            result.setdefault(move.company_id, self.env["res.partner"])
            result[move.company_id] |= move.commercial_partner_id
        return result

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for company, partners in records._optima_get_ecommerce_partners_by_company().items():
            partners._optima_queue_ecommerce_risk_sync(company=company)
        return records

    def unlink(self):
        by_company = self._optima_get_ecommerce_partners_by_company()
        result = super().unlink()
        for company, partners in by_company.items():
            partners.exists()._optima_queue_ecommerce_risk_sync(company=company)
        return result
