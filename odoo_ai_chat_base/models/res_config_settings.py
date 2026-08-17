from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    """Configuración mínima y reutilizable del chatbot."""

    _inherit = "res.config.settings"

    odoo_ai_chat_base_webhook_url = fields.Char(
        string="URL del webhook",
        config_parameter="odoo_ai_chat_base.webhook_url",
        help="Webhook HTTP(S) que recibirá los mensajes del chatbot, por ejemplo un flujo de n8n.",
    )

    odoo_ai_chat_base_title = fields.Char(
        string="Título del chatbot",
        config_parameter="odoo_ai_chat_base.title",
        default="Asistente",
    )

    odoo_ai_chat_base_welcome_message = fields.Char(
        string="Mensaje de bienvenida",
        config_parameter="odoo_ai_chat_base.welcome_message",
        default="Hola, ¿en qué puedo ayudarte?",
    )

    odoo_ai_chat_base_page_ids = fields.Many2many(
        comodel_name="website.page",
        string="Páginas donde aparece el chatbot",
        help="Si no seleccionas ninguna página, el chatbot permanecerá desactivado.",
    )

    @api.model
    def get_values(self):
        values = super().get_values()
        config = self.env["ir.config_parameter"].sudo()
        raw_page_ids = config.get_param("odoo_ai_chat_base.page_ids", default="") or ""

        page_ids = []
        for value in raw_page_ids.split(","):
            value = value.strip()
            if value.isdigit():
                page_ids.append(int(value))

        existing_ids = self.env["website.page"].sudo().browse(page_ids).exists().ids
        values.update(
            odoo_ai_chat_base_page_ids=[(6, 0, existing_ids)],
        )
        return values

    def set_values(self):
        super().set_values()
        config = self.env["ir.config_parameter"].sudo()
        config.set_param(
            "odoo_ai_chat_base.page_ids",
            ",".join(str(page_id) for page_id in self.odoo_ai_chat_base_page_ids.ids),
        )
