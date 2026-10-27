"""Persistent undo journal for provisional quotations only.

Each journal entry stores the full state *before* one successful operation,
and the fingerprint of the state immediately afterwards. The stack is scoped
to a single editable conversation and cannot touch real sale.order records.
"""
from odoo import fields, models, _
from odoo.exceptions import UserError


class SaleAIDraftChange(models.Model):
    _name = "sale.ai.draft.change"
    _description = "Historial reversible de cambios del borrador IA"
    _order = "id desc"
    _check_company_auto = True

    draft_id = fields.Many2one("sale.ai.draft", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="draft_id.company_id", store=True, readonly=True, index=True)
    user_id = fields.Many2one(related="draft_id.user_id", store=True, readonly=True, index=True)
    before_snapshot = fields.Text(required=True, copy=False)
    after_fingerprint = fields.Char(required=True, copy=False)

    def _assert_editable(self):
        self.mapped("draft_id.session_id")._ensure_can_edit_draft()

    def write(self, vals):
        if set(vals) - {"after_fingerprint"}:
            raise UserError(_("No se puede modificar el historial del borrador."))
        self._assert_editable()
        return super().write(vals)

    def unlink(self):
        self._assert_editable()
        return super().unlink()
