from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    sale_ai_model_id = fields.Many2one(
        related="company_id.sale_ai_model_id", readonly=False,
        string="Modelo predeterminado"
    )
    sale_ai_context_budget = fields.Integer(
        related="company_id.sale_ai_context_budget", readonly=False,
        string="Tokens orientativos de contexto"
    )
    sale_ai_chat_history_limit = fields.Integer(
        related="company_id.sale_ai_chat_history_limit", readonly=False,
        string="Máximo de conversaciones visibles"
    )
    sale_ai_history_limit = fields.Integer(
        related="company_id.sale_ai_history_limit", readonly=False,
        string="Ejemplos históricos máximos"
    )
    sale_ai_allow_online_research = fields.Boolean(
        related="company_id.sale_ai_allow_online_research", readonly=False,
        string="Autorizar futuras búsquedas externas"
    )
