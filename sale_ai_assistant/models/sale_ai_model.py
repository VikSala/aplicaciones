from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class SaleAIModel(models.Model):
    """Provider/model registry; these flags are operator-declared, not automatic discovery."""

    _name = "sale.ai.model"
    _description = "Modelo de IA disponible para Ventas"
    _order = "name, id"

    name = fields.Char(string="Nombre", required=True)
    model_type = fields.Selection([
        ("individual", "Modelo individual"), ("profile", "Perfil multimodelo"),
    ], string="Tipo", default="individual", required=True, index=True)
    description_model_id = fields.Many2one(
        "sale.ai.model", string="Redacción técnica", ondelete="restrict",
        domain="[('model_type','=','individual'),('provider','=','vercel_gateway'),('active','=',True)]")
    market_model_id = fields.Many2one(
        "sale.ai.model", string="Síntesis de búsquedas y precios", ondelete="restrict",
        domain="[('model_type','=','individual'),('provider','=','vercel_gateway'),('active','=',True)]")
    commercial_model_id = fields.Many2one(
        "sale.ai.model", string="Propuesta comercial", ondelete="restrict",
        domain="[('model_type','=','individual'),('provider','=','vercel_gateway'),('active','=',True)]")
    tools_model_id = fields.Many2one(
        "sale.ai.model", string="Planificación y operaciones de Odoo", ondelete="restrict",
        domain="[('model_type','=','individual'),('provider','=','vercel_gateway'),('active','=',True)]")
    review_model_id = fields.Many2one(
        "sale.ai.model", string="Revisión antes de crear presupuesto", ondelete="restrict",
        domain="[('model_type','=','individual'),('provider','=','vercel_gateway'),('active','=',True)]")
    fallback_model_id = fields.Many2one(
        "sale.ai.model", string="Modelo de respaldo (fallback)", ondelete="restrict",
        domain="[('model_type','=','individual'),('provider','=','vercel_gateway'),('active','=',True)]")
    description_style = fields.Selection([
        ('brief', 'Breve'), ('balanced', 'Equilibrado'), ('detailed', 'Detallado'),
    ], string="Estilo de redacción técnica", default='balanced', required=True)
    active = fields.Boolean(default=True)
    provider = fields.Selection(
        [("vercel_gateway", "Vercel AI Gateway"), ("other", "Otro (futuro)")],
        default="vercel_gateway", required=True, string="Proveedor"
    )
    external_model_id = fields.Char(
        string="Identificador exacto del modelo", required=False,
        help="Por ejemplo, el identificador publicado en el catálogo actual de AI Gateway."
    )
    is_default = fields.Boolean(
        string="Modelo por defecto",
        compute="_compute_is_default", inverse="_inverse_is_default",
        help="Modelo predeterminado para nuevas conversaciones de la compañía activa. "
             "Al marcar otro modelo, el anterior deja de ser el predeterminado.",
    )
    supports_tools = fields.Boolean(string="Admite herramientas", default=False)
    supports_images = fields.Boolean(string="Admite imágenes", default=False)
    supports_pdf = fields.Boolean(string="Admite PDF", default=False)
    supports_text_files = fields.Boolean(string="Admite archivos de texto", default=False)
    supports_native_web_search = fields.Boolean(string="Búsqueda web nativa", default=False)
    context_window_tokens = fields.Integer(string="Ventana de contexto (tokens)")
    price_input_m_usd = fields.Float(
        string="Coste entrada ($ / millón tokens)", digits=(12, 6),
        help="Referencia manual; valor 0 significa NO informado, no modelo gratuito."
    )
    price_output_m_usd = fields.Float(
        string="Coste salida ($ / millón tokens)", digits=(12, 6),
        help="Referencia manual; valor 0 significa NO informado, no modelo gratuito."
    )
    price_checked_on = fields.Date(string="Fecha de comprobación de tarifas")
    notes = fields.Text(string="Observaciones")

    _sql_constraints = [
        ("provider_external_model_unique", "unique(provider, external_model_id)",
         "El identificador del modelo debe ser único para cada proveedor."),
    ]

    @api.depends_context("company")
    def _compute_is_default(self):
        current_id = self.env.company.sale_ai_model_id.id
        for record in self:
            record.is_default = record.id == current_id

    def _inverse_is_default(self):
        if not self.env.user.has_group("sales_team.group_sale_manager"):
            from odoo.exceptions import AccessError
            raise AccessError(_("Solo un administrador de Ventas puede cambiar el modelo predeterminado."))
        company = self.env.company
        for record in self:
            if record.is_default:
                if not record.active or record.provider != "vercel_gateway":
                    raise ValidationError(_("El modelo predeterminado debe estar activo y usar Vercel AI Gateway."))
                # One Many2one on the company is the source of truth. Setting a
                # new default implicitly unchecks the old model for this company.
                # Elevate ONLY this field: Sales managers need not administer companies.
                company.sudo().write({"sale_ai_model_id": record.id})
            elif company.sale_ai_model_id.id == record.id:
                # Explicitly removing the only default leaves the company without
                # one until another model is selected; never changes other companies.
                company.sudo().write({"sale_ai_model_id": False})

    @api.constrains("context_window_tokens", "price_input_m_usd", "price_output_m_usd")
    def _check_context_window_tokens(self):
        for record in self:
            if record.price_input_m_usd < 0 or record.price_output_m_usd < 0:
                raise ValidationError(_("Los costes por millón de tokens no pueden ser negativos."))
            if record.context_window_tokens < 0:
                raise ValidationError(_("La ventana de contexto no puede ser negativa."))

    @api.constrains("model_type", "external_model_id", "description_model_id", "market_model_id",
                    "commercial_model_id", "tools_model_id", "review_model_id", "fallback_model_id")
    def _check_profile_roles(self):
        role_names = ("description_model_id", "market_model_id", "commercial_model_id",
                      "tools_model_id", "review_model_id", "fallback_model_id")
        for record in self:
            if record.model_type == "individual":
                if not (record.external_model_id or "").strip():
                    raise ValidationError(_("Un modelo individual necesita su identificador Vercel."))
                if any(record[name] for name in role_names):
                    raise ValidationError(_("Los modelos individuales no pueden contener roles multimodelo."))
            else:
                if not all(record[name] for name in role_names):
                    raise ValidationError(_("Asigna los seis modelos del perfil multimodelo antes de guardarlo."))
                if record.external_model_id:
                    raise ValidationError(_("Un perfil multimodelo no tiene identificador Vercel propio."))
                for name in role_names:
                    sub = record[name]
                    if sub.model_type != "individual" or sub.provider != "vercel_gateway" or not sub.active:
                        raise ValidationError(_("Los roles deben usar modelos individuales activos de Vercel."))
                if not record.tools_model_id.supports_tools:
                    raise ValidationError(_("El modelo de operaciones debe admitir herramientas."))
                if not record.review_model_id.supports_tools:
                    raise ValidationError(_("El modelo de revisión debe admitir herramientas."))
                if not record.fallback_model_id.supports_tools:
                    raise ValidationError(_("El modelo de respaldo debe admitir herramientas para recuperar acciones."))

    def _role_model(self, role):
        """Return a concrete provider model; profiles never call Vercel themselves."""
        self.ensure_one()
        if self.model_type == "individual":
            return self
        roles = {
            'description': 'description_model_id',
            'market': 'market_model_id',
            'commercial': 'commercial_model_id',
            'tools': 'tools_model_id',
            'review': 'review_model_id',
            'fallback': 'fallback_model_id',
        }
        if role not in roles:
            raise ValueError('Unknown AI role')
        result = self[roles[role]]
        if not result or not result.active:
            raise ValidationError(_("El perfil multimodelo tiene un rol sin modelo activo: %s") % role)
        return result

    def _profile_style_prompt(self):
        self.ensure_one()
        return {
            'brief': 'Redacta preferentemente en uno o dos párrafos compactos, alrededor de 120 palabras salvo que los datos confirmados exijan más. Sin listas extensas, repeticiones ni verificaciones académicas; conserva mediciones y alcance.',
            'balanced': 'Redacta en párrafos profesionales y concisos. Conserva materiales, mediciones y alcance; evita repeticiones y explicaciones académicas. Incluye solo comprobaciones esenciales, sin convertir hipótesis en hechos.',
            'detailed': 'Redacta de forma detallada y profesional, sin inventar hechos; separa alcance, mediciones y comprobaciones pendientes.',
        }[self.description_style or 'balanced']
