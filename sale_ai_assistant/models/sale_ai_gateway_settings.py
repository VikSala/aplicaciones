"""Sales-manager configuration wizard; no read endpoint ever returns an API key."""
from odoo import api, fields, models, _
from odoo.exceptions import AccessError, ValidationError

from .sale_ai_gateway import get_gateway_key
from .sale_ai_market import market_setting


class SaleAIGatewaySettings(models.TransientModel):
    _name = "sale.ai.gateway.settings"
    _description = "Configuración de Vercel AI Gateway para Ventas"

    company_id = fields.Many2one("res.company", string="Compañía", readonly=True,
                                 default=lambda self: self.env.company)
    api_key = fields.Char(string="Nueva API key (se guardará en el servidor)", copy=False)
    key_configured = fields.Boolean(string="Clave configurada", compute="_compute_key_configured")
    remove_key = fields.Boolean(string="Eliminar clave existente")
    model_id = fields.Many2one("sale.ai.model", string="Modelo predeterminado",
                              domain="[('provider','=','vercel_gateway'),('active','=',True)]")
    max_output_tokens = fields.Integer(string="Máximo de tokens de respuesta (por llamada)", default=8192, help="Se envía al proveedor exactamente como figura aquí, también para notas y secciones. Los modelos pueden tener límites propios.")
    request_timeout = fields.Integer(string="Tiempo máximo de espera por llamada (segundos)", default=90)
    context_mode = fields.Selection([
        ("full", "Experimental: conversación completa"),
        ("bounded", "Acotado: conversación reciente sin recortar mensajes"),
    ], string="Modo de contexto", default="full", required=True,
        help="Completo: envía todos los mensajes de esta sesión sin truncarlos. Acotado: conserva mensajes completos hasta el presupuesto aproximado configurado.")
    context_budget = fields.Integer(string="Contexto acotado (tokens aproximados)", default=100000,
        help="Solo funciona en modo acotado. Es una estimación por caracteres, NO una medida exacta de tokens del modelo.")
    max_tool_rounds = fields.Integer(string="Rondas de herramientas por respuesta", default=10)
    max_tool_calls = fields.Integer(string="Llamadas a herramientas por respuesta", default=30)
    tool_result_chars = fields.Integer(string="Caracteres de resultados de herramientas por respuesta", default=64000)
    max_turn_seconds = fields.Integer(string="Tiempo total máximo del agente (segundos)", default=110,
        help="La instancia Odoo debe admitir esta duración (limit_time_real del servidor).")
    chat_history_limit = fields.Integer(string="Conversaciones visibles en historial", default=10)
    historical_examples_limit = fields.Integer(
        string="Máximo de presupuestos históricos por búsqueda", default=3,
        help="De 0 a 5. Un valor 0 deshabilita herramientas de consulta histórica.")

    market_search_enabled = fields.Boolean(string="Permitir búsquedas web de materiales", default=False)
    market_key = fields.Char(string="Nueva clave Tavily (opcional)", copy=False)
    market_key_configured = fields.Boolean(string="Clave Tavily configurada", compute="_compute_market_key_configured")
    market_remove_key = fields.Boolean(string="Eliminar clave Tavily guardada")
    market_queries_per_turn = fields.Integer(string="Consultas web por respuesta", default=4, help="De 1 a 12. El total está condicionado además por los límites de conversación y compañía.")
    market_queries_per_session = fields.Integer(string="Consultas web por conversación", default=4, help="Entre 1 y 12. Escribe 0 para recuperar el valor predeterminado (4).")
    market_queries_per_month = fields.Integer(string="Consultas web por compañía/mes", default=60, help="Entre 1 y 1000. Escribe 0 para recuperar el valor predeterminado (60).")
    market_results = fields.Integer(string="Resultados por búsqueda", default=4, help="Entre 2 y 5. Escribe 0 para recuperar el valor predeterminado (4).")
    market_timeout = fields.Integer(string="Espera máxima web (segundos)", default=9, help="Entre 3 y 18 segundos. Escribe 0 para recuperar el valor predeterminado (9).")

    # Permite abrir el wizard aunque existan parámetros vacíos o corruptos de
    # una configuración anterior.  No tocamos los parámetros hasta pulsar
    # "Guardar configuración".  0 se considera sin inicializar, nunca
    # "sin límite" (lo que podría disparar el consumo de Tavily).
    _MARKET_LIMITS = (
        ("market_queries_per_turn", "per_turn", 4, 1, 12),
        ("market_queries_per_session", "per_session", 4, 1, 12),
        ("market_queries_per_month", "per_month", 60, 1, 1000),
        ("market_results", "results", 4, 2, 5),
        ("market_timeout", "timeout", 9, 3, 18),
    )

    @api.model
    def _safe_market_limit(self, company_id, key, default, lower, upper):
        raw = market_setting(self.env, company_id, key, default)
        try:
            value = int(raw)
        except (TypeError, ValueError, OverflowError):
            return default
        # On opening the wizard, recover broken or missing persisted settings.
        return value if lower <= value <= upper else default

    def _compute_market_key_configured(self):
        for wizard in self:
            wizard.market_key_configured = bool(market_setting(self.env, self.env.company.id, "api_key", ""))

    @api.model
    def default_get(self, field_names):
        defaults = super().default_get(field_names)
        company = self.env.company
        defaults.update({
            "company_id": company.id,
            "model_id": company.sale_ai_model_id.id or False,
            "max_output_tokens": company.sale_ai_max_output_tokens,
            "request_timeout": company.sale_ai_request_timeout,
            "context_budget": company.sale_ai_context_budget,
            "context_mode": company._sale_ai_get_agent_parameter(company.id, "context_mode"),
            **{key: company._sale_ai_get_agent_parameter(company.id, key) for key in (
                "max_tool_rounds", "max_tool_calls", "tool_result_chars", "max_turn_seconds")},
            "chat_history_limit": company.sale_ai_chat_history_limit,
            "historical_examples_limit": min(company.sale_ai_history_limit, 5),
            "market_search_enabled": company.sale_ai_allow_online_research,
            **{
                field: self._safe_market_limit(company.id, key, default, lower, upper)
                for field, key, default, lower, upper in self._MARKET_LIMITS
            },
        })
        return defaults

    def _compute_key_configured(self):
        for wizard in self:
            wizard.key_configured = bool(get_gateway_key(self.env, self.env.company.id))

    def action_apply(self):
        self.ensure_one()
        if not self.env.user.has_group("sales_team.group_sale_manager"):
            raise AccessError(_("Solo un administrador de Ventas puede configurar el asistente."))
        if self.model_id and (not self.model_id.active or self.model_id.provider != "vercel_gateway"):
            raise ValidationError(_("Selecciona un modelo activo de Vercel AI Gateway."))
        if not 128 <= self.max_output_tokens <= 65536:
            raise ValidationError(_("El límite de respuesta debe estar entre 128 y 65.536 tokens."))
        if not 5 <= self.request_timeout <= 300:
            raise ValidationError(_("El tiempo de espera debe estar entre 5 y 300 segundos."))
        if not 1000 <= self.context_budget <= 1000000:
            raise ValidationError(_("El contexto aproximado debe estar entre 1.000 y 1.000.000 tokens."))
        if not 0 <= self.chat_history_limit <= 100:
            raise ValidationError(_("El historial debe estar entre 0 y 100."))
        if not 0 <= self.historical_examples_limit <= 5:
            raise ValidationError(_("Los presupuestos históricos por consulta deben estar entre 0 y 5."))
        agent_bounds = {
            "max_tool_rounds": (1, 30),
            "max_tool_calls": (1, 100),
            "tool_result_chars": (1000, 500000),
            "max_turn_seconds": (15, 600),
        }
        if self.context_mode not in ("full", "bounded"):
            raise ValidationError(_("Selecciona un modo de contexto válido."))
        for field, (lower, upper) in agent_bounds.items():
            if not lower <= getattr(self, field) <= upper:
                raise ValidationError(_("%s debe estar entre %s y %s.") % (
                    self._fields[field].string, lower, upper))
        market_values = {}
        for field, key, default, lower, upper in self._MARKET_LIMITS:
            raw = getattr(self, field)
            # Algunos wizards actualizados desde la fase anterior presentan 0
            # al estrenar estos campos. Recuperar el valor seguro por defecto,
            # aunque la búsqueda esté habilitada, en lugar de bloquear el guardado.
            # La casilla market_search_enabled sigue controlando el uso real.
            value = default if raw == 0 else raw
            if not lower <= value <= upper:
                label = self._fields[field].string
                raise ValidationError(_(
                    "%s debe estar entre %s y %s. Deja 0 para restaurar el valor predeterminado (%s)."
                ) % (label, lower, upper, default))
            market_values[key] = value
        configured_market_key = market_setting(self.env, self.env.company.id, "api_key", "")
        if self.market_search_enabled and (self.market_remove_key or not (
                self.market_key or configured_market_key)):
            raise ValidationError(_("Para activar la búsqueda web debes configurar una clave de Tavily."))
        company = self.env.company
        # Sales administrators are not necessarily system administrators.
        # Only these explicit fields on the CURRENT company are elevated.
        company.sudo().write({
            "sale_ai_model_id": self.model_id.id or False,
            "sale_ai_max_output_tokens": self.max_output_tokens,
            "sale_ai_request_timeout": self.request_timeout,
            "sale_ai_context_budget": self.context_budget,
            "sale_ai_chat_history_limit": self.chat_history_limit,
            "sale_ai_history_limit": self.historical_examples_limit,
            "sale_ai_allow_online_research": self.market_search_enabled,
        })
        param = "sale_ai_assistant.vercel_key.%d" % company.id
        params = self.env["ir.config_parameter"].sudo()
        if self.remove_key:
            params.set_param(param, "")
        elif self.api_key and self.api_key.strip():
            params.set_param(param, self.api_key.strip())
        for key in ("context_mode", "max_tool_rounds", "max_tool_calls",
                    "tool_result_chars", "max_turn_seconds"):
            params.set_param("sale_ai_assistant.agent.%s.%s" % (key, company.id),
                             str(getattr(self, key)))
        for key, val in market_values.items():
            params.set_param("sale_ai_assistant.market.%s.%d" % (key, company.id), str(val))
        market_key_param = "sale_ai_assistant.market.api_key.%d" % company.id
        if self.market_remove_key:
            params.set_param(market_key_param, "")
        elif self.market_key and self.market_key.strip():
            params.set_param(market_key_param, self.market_key.strip())
        # A transient record containing an entered key should not keep it stored
        # after the one-time submission.
        if self.api_key or self.market_key:
            self.write({"api_key": False, "market_key": False})
        # Refresh a blank new window so transient's key never lingers in the form.
        return {"type": "ir.actions.act_window_close"}
