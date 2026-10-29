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

    gateway_usage_ids = fields.One2many('sale.ai.model.usage', 'message_id', string='Llamadas Vercel')
    gateway_cost_usd = fields.Float(compute='_compute_gateway_receipt', digits=(16, 9), string='Coste confirmado Vercel (USD)')
    gateway_cost_status = fields.Selection([
        ('none','Sin llamadas facturables'), ('pending','Pendiente'), ('obtained','Confirmado'), ('unavailable','No disponible'),
    ], compute='_compute_gateway_receipt', string='Estado del coste')
    gateway_providers = fields.Char(compute='_compute_gateway_receipt', string='Proveedores utilizados')

    @api.depends('gateway_usage_ids.cost_status', 'gateway_usage_ids.reported_cost_usd',
                 'gateway_usage_ids.provider_name')
    def _compute_gateway_receipt(self):
        for rec in self:
            calls = rec.gateway_usage_ids.filtered(lambda row: row.status == 'ok')
            rec.gateway_cost_usd = sum(calls.filtered(lambda row: row.cost_status == 'obtained').mapped('reported_cost_usd'))
            rec.gateway_cost_status = ('none' if not calls else
                                       'pending' if any(row.cost_status == 'pending' for row in calls) else
                                       'unavailable' if any(row.cost_status != 'obtained' for row in calls) else
                                       'obtained')
            rec.gateway_providers = ', '.join(sorted(set(calls.mapped('provider_name')) - {False, ''}))

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
