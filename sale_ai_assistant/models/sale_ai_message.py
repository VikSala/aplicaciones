from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError


class SaleAIMessage(models.Model):
    _name = "sale.ai.message"
    _description = "Mensaje de conversación IA"
    _order = "id asc"

    session_id = fields.Many2one(
        "sale.ai.session", required=True, ondelete="cascade", index=True,
        string="Conversación"
    )
    user_id = fields.Many2one(
        related="session_id.user_id", store=True, index=True, string="Propietario"
    )
    company_id = fields.Many2one(
        related="session_id.company_id", store=True, index=True, string="Compañía"
    )
    role = fields.Selection(
        [("user", "Usuario"), ("assistant", "Asistente"), ("tool", "Herramienta")],
        default="user", required=True, string="Rol"
    )
    content = fields.Text(string="Contenido", required=True)
    model_id = fields.Many2one("sale.ai.model", string="Modelo utilizado", readonly=True)
    models_used_summary = fields.Char(string="Modelos reales usados", readonly=True)
    input_tokens = fields.Integer(string="Tokens entrada", readonly=True)
    output_tokens = fields.Integer(string="Tokens salida", readonly=True)
    estimated_cost_usd = fields.Float(string="Coste calculado por tarifas manuales (USD)",
                                      digits=(12, 6), readonly=True)
    latency_ms = fields.Integer(string="Latencia (ms)", readonly=True)
    reported_cost_usd = fields.Float(string="Coste comunicado por proveedor (USD)", digits=(12, 6), readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("role", "user") != "user" and not self.env.su:
                raise AccessError(_("Solo el backend de IA puede registrar respuestas de asistente/herramienta."))
            session = self.env["sale.ai.session"].browse(vals["session_id"])
            session._ensure_can_chat()
        return super().create(vals_list)

    def write(self, vals):
        # Mensajes históricos inmutables incluso cuando se reabre para consulta.
        raise UserError(_("Los mensajes del historial no se pueden modificar."))

    def unlink(self):
        raise UserError(_("Los mensajes del historial no se pueden eliminar."))
