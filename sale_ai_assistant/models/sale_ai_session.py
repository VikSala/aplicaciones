from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SaleAISession(models.Model):
    """One conversation per quotation; never reuse previous session messages by default."""

    _name = "sale.ai.session"
    _description = "Conversación del asistente IA de Ventas"
    _order = "write_date desc, id desc"
    _check_company_auto = True

    name = fields.Char(string="Asunto", required=True, default="Nuevo presupuesto IA")
    user_id = fields.Many2one(
        "res.users", string="Creador", required=True, index=True,
        default=lambda self: self.env.user, readonly=True
    )
    company_id = fields.Many2one(
        "res.company", string="Compañía", required=True, index=True,
        default=lambda self: self.env.company, readonly=True
    )
    model_id = fields.Many2one(
        "sale.ai.model", string="Modelo asignado",
        default=lambda self: self.env.company.sale_ai_model_id,
        help="Modelo asignado a esta conversación; podrá cambiarse explícitamente."
    )
    state = fields.Selection(
        [
            ("active", "En curso"),
            ("archived", "Archivada sin presupuesto"),
            ("completed", "Presupuesto creado / cerrada"),
            ("consultation", "Consulta posterior (sin editar presupuesto)"),
        ],
        default="active", required=True, index=True, string="Estado"
    )
    message_ids = fields.One2many(
        "sale.ai.message", "session_id", string="Mensajes"
    )
    draft_ids = fields.One2many(
        "sale.ai.draft", "session_id", string="Borrador de esta conversación"
    )
    draft_id = fields.Many2one(
        "sale.ai.draft", compute="_compute_draft_id", string="Borrador"
    )
    edit_order_id = fields.Many2one(
        "sale.order", string="Presupuesto en edición", readonly=True, copy=False,
        check_company=True, index=True,
    )
    edit_baseline_json = fields.Text(
        string="Instantánea original del presupuesto", readonly=True, copy=False,
        groups="sales_team.group_sale_manager",
    )
    sale_order_id = fields.Many2one(
        "sale.order", string="Presupuesto resultante", check_company=True,
        readonly=True, copy=False
    )
    ended_at = fields.Datetime(string="Fecha de cierre", readonly=True, copy=False)
    reopened_at = fields.Datetime(string="Última reapertura", readonly=True, copy=False)
    summary = fields.Text(
        string="Resumen de contexto", copy=False,
        help="Resumen específico de esta conversación. No se comparte con sesiones nuevas."
    )

    @api.depends("draft_ids")
    def _compute_draft_id(self):
        for record in self:
            record.draft_id = record.draft_ids[:1]

    @api.model_create_multi
    def create(self, vals_list):
        sanitized = []
        for incoming in vals_list:
            vals = dict(incoming)
            if any(key in vals for key in ("draft_ids", "message_ids", "sale_order_id", "ended_at", "reopened_at", "edit_order_id", "edit_baseline_json")):
                raise UserError(_("La conversación debe comenzar sin mensajes ni presupuesto asociado."))
            # El creador no se puede suplantar mediante RPC.
            vals["user_id"] = self.env.uid
            company_id = vals.get("company_id") or self.env.company.id
            if company_id not in self.env.companies.ids:
                raise ValidationError(_("No puedes crear conversaciones para otra compañía."))
            vals["company_id"] = company_id
            vals.setdefault("state", "active")
            if vals["state"] != "active":
                raise UserError(_("Una conversación nueva siempre empieza en curso."))
            if not vals.get("model_id"):
                vals["model_id"] = self.env["res.company"].browse(company_id).sale_ai_model_id.id or False
            sanitized.append(vals)
        records = super().create(sanitized)
        self.env["sale.ai.draft"].create([
            {
                "session_id": rec.id,
                "currency_id": rec.company_id.currency_id.id,
            }
            for rec in records
        ])
        return records

    def write(self, vals):
        if not self.env.context.get("sale_ai_internal_edit") and any(
            key in vals for key in ("edit_order_id", "edit_baseline_json")
        ):
            raise UserError(_("La asociación a presupuestos solo puede establecerla el asistente."))
        if "user_id" in vals or "company_id" in vals:
            raise UserError(_("No se puede reasignar una conversación a otro usuario o compañía."))
        transitions = {
            "active": {"archived", "completed"},
            "archived": {"active"},
            "completed": {"consultation"},
            "consultation": {"completed"},
        }
        for session in self:
            if session.state in ("completed", "consultation") and any(
                key not in {"state", "reopened_at", "ended_at"} for key in vals
            ):
                raise UserError(_("La conversación finalizada es un historial de solo lectura."))
            if "sale_order_id" in vals:
                if session.edit_order_id:
                    raise UserError(_("Una sesión de edición no puede crear un presupuesto nuevo."))
                if session.sale_order_id or session.state != "active":
                    raise UserError(_("No se puede sustituir ni volver a crear el presupuesto asociado."))
                order = self.env["sale.order"].browse(vals["sale_order_id"])
                if not order.exists() or order.state != "draft" or order.company_id != session.company_id:
                    raise ValidationError(_("Debe asociarse un presupuesto en borrador de la misma compañía."))
                if vals.get("state") != "completed":
                    raise UserError(_("La creación del presupuesto debe cerrar la conversación."))
            if "state" in vals and vals["state"] != session.state:
                if vals["state"] not in transitions.get(session.state, set()):
                    raise UserError(_("Transición de estado de conversación no permitida."))
                if vals["state"] == "completed" and not (session.sale_order_id or vals.get("sale_order_id")):
                    raise UserError(_("No se puede marcar completada sin presupuesto creado."))
            if "model_id" in vals and session.state not in ("active", "consultation"):
                raise UserError(_("Abre explícitamente la conversación antes de cambiar el modelo."))
        return super().write(vals)

    def action_close(self):
        for session in self:
            if session.state == "active":
                session.write({"state": "archived", "ended_at": fields.Datetime.now()})
            elif session.state == "consultation":
                session.write({"state": "completed", "ended_at": fields.Datetime.now()})
        return True

    def action_reopen(self):
        for session in self:
            if session.state == "archived":
                session.write({"state": "active", "reopened_at": fields.Datetime.now()})
            elif session.state == "completed" and session.sale_order_id:
                # Reapertura consultiva: nunca vuelve a habilitar edición de su borrador.
                session.write({"state": "consultation", "reopened_at": fields.Datetime.now()})
            else:
                raise UserError(_("Esta conversación no admite reapertura en su estado actual."))
        return True

    def _ensure_can_chat(self):
        for session in self:
            if session.state != "active":
                raise UserError(_("Esta conversación está cerrada: el historial es de solo lectura."))

    def _ensure_can_edit_draft(self):
        for session in self:
            if session.state != "active" or session.sale_order_id:
                raise UserError(_("El borrador está cerrado o ya existe un presupuesto asociado."))

    def _complete_with_order(self, order):
        """Private internal hook for phase 6: invoked only after explicit confirmation."""
        self.ensure_one()
        self._ensure_can_edit_draft()
        if order.state != "draft" or order.company_id != self.company_id:
            raise ValidationError(_("Solo puede asociarse un presupuesto borrador de esta compañía."))
        self.write({
            "sale_order_id": order.id,
            "state": "completed",
            "ended_at": fields.Datetime.now(),
        })
