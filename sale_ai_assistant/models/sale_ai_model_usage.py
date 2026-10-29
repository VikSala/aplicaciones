"""Per-call metering by concrete model. Stage results are internal and follow session owner/company access rules."""
from odoo import api, fields, models
from odoo.exceptions import AccessError

from . import sale_ai_gateway


class SaleAIModelUsage(models.Model):
    _name = 'sale.ai.model.usage'
    _description = 'Consumo de modelos IA por llamada'
    _order = 'id desc'

    session_id = fields.Many2one('sale.ai.session', required=True, index=True,
                                  ondelete='cascade', string='Conversación')
    user_id = fields.Many2one('res.users', related='session_id.user_id', store=True,
                               index=True, string='Usuario')
    company_id = fields.Many2one('res.company', related='session_id.company_id',
                                  store=True, index=True, string='Compañía')
    model_id = fields.Many2one('sale.ai.model', required=True, ondelete='restrict',
                                string='Modelo real')
    stage = fields.Selection([
        ('validation', 'Validación técnica'), ('planning', 'Planificación'), ('description', 'Descripción'),
        ('tools', 'Herramientas'), ('completion', 'Respuesta'),
        ('tool_fallback', 'Fallback herramientas'), ('market', 'Síntesis de búsqueda'),
        ('commercial', 'Propuesta comercial'), ('review', 'Revisión final'),
    ], required=True, string='Etapa')
    status = fields.Selection([('ok','Correcta'), ('failed','Fallida')],
                              required=True, string='Resultado')
    result_text = fields.Text(string='Resultado de etapa', readonly=True)
    fallback_reason = fields.Text(string='Motivo de fallback', readonly=True)
    input_tokens = fields.Integer(string='Tokens entrada')
    output_tokens = fields.Integer(string='Tokens salida')
    latency_ms = fields.Integer(string='Latencia (ms)')
    reported_cost_usd = fields.Float(string='Coste real Vercel (USD)', digits=(16, 9))
    # Kept for older historical records; new calls never calculate manual tariffs.
    estimated_cost_usd = fields.Float(string='Estimación histórica manual (USD)', digits=(12, 6))
    generation_id = fields.Char(string='ID generación Vercel', index=True, readonly=True)
    provider_name = fields.Char(string='Proveedor real', readonly=True)
    cost_status = fields.Selection([
        ('pending', 'Pendiente de Vercel'),
        ('obtained', 'Confirmado por Vercel'),
        ('unavailable', 'No disponible'),
    ], string='Estado del coste', default='unavailable', readonly=True, index=True)
    cost_lookup_attempts = fields.Integer(default=0, readonly=True)
    message_id = fields.Many2one('sale.ai.message', string='Mensaje asociado', ondelete='set null', index=True, readonly=True)

    @api.model
    def _refresh_pending_gateway_costs(self):
        """Fetch real costs only when explicitly requested via the UI button.

        Pending rows remain visibly pending if Vercel has not indexed them yet.
        Network failures never become fake zero-cost transactions.
        """
        rows = self.sudo().search([
            ('cost_status', '=', 'pending'), ('generation_id', '!=', False),
            ('cost_lookup_attempts', '<', 36),
        ], order='id asc', limit=12)
        for row in rows:
            api_key = sale_ai_gateway.get_gateway_key(self.env, row.company_id.id)
            if not api_key:
                continue
            result = sale_ai_gateway.lookup_generation(api_key, row.generation_id, timeout=5)
            vals = {'cost_lookup_attempts': row.cost_lookup_attempts + 1}
            if result:
                vals.update({'reported_cost_usd': result['reported_cost_usd'], 'cost_status': 'obtained'})
                if result.get('provider_name'):
                    vals['provider_name'] = result['provider_name']
            elif vals['cost_lookup_attempts'] >= 36:
                vals['cost_status'] = 'unavailable'
            row.write(vals)
        return True

    def action_refresh_gateway_costs(self):
        if not self.env.user.has_group('sales_team.group_sale_manager'):
            raise AccessError('Solo los administradores de Ventas pueden consultar los costes.')
        self.env['sale.ai.model.usage']._refresh_pending_gateway_costs()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    turn_ref = fields.Char(string='Referencia del diagnóstico', index=True, readonly=True)
    event_kind = fields.Selection([('call', 'Llamada'), ('turn_failure', 'Fallo del turno')],
                                  default='call', string='Tipo de registro', readonly=True)
    diagnostic_operation = fields.Char(string='Operación', readonly=True)
    error_message = fields.Text(string='Mensaje del error', readonly=True)
    error_type = fields.Char(string='Tipo de excepción', readonly=True)
    turn_elapsed_ms = fields.Integer(string='Tiempo hasta el fallo del turno (ms)', readonly=True,
        help='Tiempo transcurrido desde el inicio del agente; no sumar a las latencias de las llamadas.')
