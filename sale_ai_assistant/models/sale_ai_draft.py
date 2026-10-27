from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SaleAIDraft(models.Model):
    _name = "sale.ai.draft"
    _description = "Propuesta de presupuesto IA (no es sale.order)"
    _order = "id desc"
    _check_company_auto = True

    session_id = fields.Many2one(
        "sale.ai.session", required=True, ondelete="cascade", index=True,
        string="Conversación"
    )
    company_id = fields.Many2one(
        related="session_id.company_id", store=True, readonly=True, index=True,
        string="Compañía"
    )
    user_id = fields.Many2one(
        related="session_id.user_id", store=True, readonly=True, index=True,
        string="Propietario"
    )
    session_state = fields.Selection(related="session_id.state", string="Estado de la conversación")
    partner_id = fields.Many2one(
        "res.partner", string="Cliente propuesto", check_company=True
    )
    pricelist_id = fields.Many2one(
        "product.pricelist", string="Tarifa propuesta", check_company=True
    )
    currency_id = fields.Many2one("res.currency", required=True, string="Moneda")
    description = fields.Text(string="Comentarios", help="Se trasladan a x_comentarios del presupuesto de Ventas al crearlo.")
    assumptions = fields.Text(
        string="Hipótesis y dudas pendientes",
        help="Incluye incertidumbres sobre cantidades, materiales y condiciones técnicas."
    )
    estimate_details = fields.Text(
        string="Cálculo interno orientativo",
        help="Información de apoyo no trasladada automáticamente a las líneas comerciales."
    )
    change_ids = fields.One2many("sale.ai.draft.change", "draft_id", string="Historial de cambios IA", copy=False)
    undo_snapshot = fields.Text(string="Instantánea del último cambio IA", copy=False,
                               groups="sales_team.group_sale_manager")
    undo_after_fingerprint = fields.Char(string="Huella del último cambio IA", copy=False,
                                        groups="sales_team.group_sale_manager")
    review_required = fields.Boolean(
        string="Revisión humana obligatoria", default=True, readonly=True
    )
    line_ids = fields.One2many(
        "sale.ai.draft.line", "draft_id", string="Líneas propuestas"
    )
    amount_untaxed_estimate = fields.Monetary(
        compute="_compute_amount_estimate", currency_field="currency_id",
        string="Base provisional sin impuestos"
    )

    _sql_constraints = [
        ("unique_session_draft", "unique(session_id)",
         "Cada conversación solo puede contener un borrador provisional."),
    ]

    @api.depends("line_ids.amount_estimate")
    def _compute_amount_estimate(self):
        for draft in self:
            draft.amount_untaxed_estimate = sum(draft.line_ids.mapped("amount_estimate"))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            session = self.env["sale.ai.session"].browse(vals["session_id"])
            session._ensure_can_edit_draft()
            if self.search_count([("session_id", "=", session.id)]):
                raise ValidationError(_("La conversación ya tiene un borrador."))
            vals["review_required"] = True
            vals.setdefault("currency_id", session.company_id.currency_id.id)
        return super().create(vals_list)

    def write(self, vals):
        if "session_id" in vals:
            raise UserError(_("No se puede mover un borrador a otra conversación."))
        if vals.get("review_required") is False:
            raise UserError(_("La revisión humana es obligatoria."))
        self.mapped("session_id")._ensure_can_edit_draft()
        return super().write(vals)

    def unlink(self):
        raise UserError(_("Los borradores se conservan como parte del historial."))
