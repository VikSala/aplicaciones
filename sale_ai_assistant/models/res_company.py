from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    sale_ai_model_id = fields.Many2one(
        "sale.ai.model", string="Modelo de IA para Ventas",
        help="Modelo predeterminado para las conversaciones nuevas de esta compañía."
    )
    sale_ai_context_budget = fields.Integer(
        string="Presupuesto máximo de contexto (tokens)", default=100000,
        help="Se utiliza únicamente en modo acotado. La aproximación no equivale a un tokenizer del proveedor."
    )
    sale_ai_chat_history_limit = fields.Integer(
        string="Conversaciones visibles en el historial", default=10,
        help="Máximo de conversaciones cerradas que se muestran en el panel por usuario y compañía. "
             "El historial anterior se conserva; 0 muestra todas (paginación futura)."
    )
    sale_ai_history_limit = fields.Integer(
        string="Máximo de presupuestos históricos de ejemplo", default=3,
        help="Número máximo de ejemplos relevantes a incorporar al contexto."
    )
    # IMPORTANT FOR UPGRADES FROM FASE 1:
    # Never add stored columns to res.company merely to introduce new AI
    # options. Odoo's module upgrade may access res.company BEFORE updating
    # the schema (e.g. via ir.module.module.button_install), which causes
    # UndefinedColumn when a stored field was just introduced in the registry.
    # Both settings are therefore computed, non-stored fields with an inverse;
    # their persisted values live in per-company ir.config_parameter keys.
    sale_ai_max_output_tokens = fields.Integer(
        string="Tokens máximos de salida",
        compute="_compute_sale_ai_gateway_limits",
        inverse="_inverse_sale_ai_max_output_tokens",
        store=False,
        help="Límite por respuesta del modelo. No garantiza un precio determinado.",
    )
    sale_ai_request_timeout = fields.Integer(
        string="Espera máxima del proveedor (segundos)",
        compute="_compute_sale_ai_gateway_limits",
        inverse="_inverse_sale_ai_request_timeout",
        store=False,
    )

    # Estos controles no agregan columnas a res.company. Son parámetros por compañía
    # para mantener actualizaciones compatibles con instalaciones anteriores.
    _AGENT_DEFAULTS = {
        "context_mode": "full",
        "max_tool_rounds": 10,
        "max_tool_calls": 30,
        "tool_result_chars": 64000,
        "max_turn_seconds": 110,
    }

    @api.model
    def _sale_ai_get_agent_parameter(self, company_id, name):
        if name not in self._AGENT_DEFAULTS:
            raise ValueError("Opción de agente desconocida")
        default = self._AGENT_DEFAULTS[name]
        raw = self.env["ir.config_parameter"].sudo().get_param(
            "sale_ai_assistant.agent.%s.%s" % (name, company_id))
        if raw is None or raw == "":
            return default
        if name == "context_mode":
            return raw if raw in ("full", "bounded") else default
        try:
            return int(raw)
        except (ValueError, TypeError):
            return default

    @api.model
    def _sale_ai_get_int_parameter(self, company_id, name, default):
        if not company_id:
            return default
        key = "sale_ai_assistant.%s.%s" % (name, company_id)
        raw = self.env["ir.config_parameter"].sudo().get_param(key, str(default))
        try:
            return int(raw)
        except (ValueError, TypeError):
            return default

    def _compute_sale_ai_gateway_limits(self):
        for company in self:
            company.sale_ai_max_output_tokens = self._sale_ai_get_int_parameter(
                company.id, "max_output_tokens", 8192
            )
            company.sale_ai_request_timeout = self._sale_ai_get_int_parameter(
                company.id, "request_timeout", 90
            )

    def _inverse_sale_ai_max_output_tokens(self):
        params = self.env["ir.config_parameter"].sudo()
        for company in self:
            if company.id:
                params.set_param(
                    "sale_ai_assistant.max_output_tokens.%s" % company.id,
                    str(company.sale_ai_max_output_tokens),
                )

    def _inverse_sale_ai_request_timeout(self):
        params = self.env["ir.config_parameter"].sudo()
        for company in self:
            if company.id:
                params.set_param(
                    "sale_ai_assistant.request_timeout.%s" % company.id,
                    str(company.sale_ai_request_timeout),
                )

    sale_ai_allow_online_research = fields.Boolean(
        string="Permitir búsquedas de precios externos", default=False,
        help="Preferencia para la futura herramienta de búsqueda, aún no implementada."
    )

    @api.constrains("sale_ai_context_budget", "sale_ai_history_limit", "sale_ai_chat_history_limit",
                    "sale_ai_max_output_tokens", "sale_ai_request_timeout")
    def _check_ai_context_config(self):
        for company in self:
            if not 128 <= company.sale_ai_max_output_tokens <= 65536:
                raise ValidationError(_("Los tokens de salida deben estar entre 128 y 65536."))
            if not 5 <= company.sale_ai_request_timeout <= 300:
                raise ValidationError(_("La espera del proveedor debe estar entre 5 y 300 segundos."))
            if not 1000 <= company.sale_ai_context_budget <= 1000000:
                raise ValidationError(_("El presupuesto aproximado de contexto debe estar entre 1.000 y 1.000.000 tokens."))
            if not 0 <= company.sale_ai_chat_history_limit <= 100:
                raise ValidationError(_("El límite del historial del chat debe estar entre 0 y 100."))
            if not 0 <= company.sale_ai_history_limit <= 20:
                raise ValidationError(_("El número de ejemplos históricos debe estar entre 0 y 20."))
