"""Per-call metering by concrete model. Stage results are internal and follow session owner/company access rules."""
from odoo import fields, models


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
    reported_cost_usd = fields.Float(string='Coste proveedor (USD)', digits=(12, 6))
    estimated_cost_usd = fields.Float(string='Coste estimado (USD)', digits=(12, 6))

    turn_ref = fields.Char(string='Referencia del diagnóstico', index=True, readonly=True)
    event_kind = fields.Selection([('call', 'Llamada'), ('turn_failure', 'Fallo del turno')],
                                  default='call', string='Tipo de registro', readonly=True)
    diagnostic_operation = fields.Char(string='Operación', readonly=True)
    error_message = fields.Text(string='Mensaje del error', readonly=True)
    error_type = fields.Char(string='Tipo de excepción', readonly=True)
    turn_elapsed_ms = fields.Integer(string='Tiempo hasta el fallo del turno (ms)', readonly=True,
        help='Tiempo transcurrido desde el inicio del agente; no sumar a las latencias de las llamadas.')
