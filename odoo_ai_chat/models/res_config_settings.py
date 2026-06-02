from odoo import api, fields, models


# Modelo de configuración que expone en Ajustes los parámetros del addon de chat IA.
class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    odoo_ai_chat_webhook_url = fields.Char(
        string="URL del webhook de n8n",
        config_parameter="odoo_ai_chat.webhook_url",
        help="Pega la URL publicada del webhook de n8n. Si pegas la Test URL con localhost/webhook-test, el addon la normaliza automáticamente a http://n8n_local:5678/webhook/odoo-ai-chat dentro de Docker.",
    )

    odoo_ai_chat_page_ids = fields.Many2many(
        comodel_name="website.page",
        string="Páginas donde aparece el chatbot",
        help="Elige una o varias páginas del sitio web donde se mostrará el chatbot. Si no seleccionas ninguna, no se mostrará en ninguna página.",
    )

    # Carga desde parámetros del sistema la configuración del addon.
    @api.model
    def get_values(self):
        res = super().get_values()
        config = self.env["ir.config_parameter"].sudo()
        raw_page_ids = config.get_param("odoo_ai_chat.page_ids", default="") or ""

        page_ids = []
        for value in raw_page_ids.split(","):
            value = value.strip()
            if value.isdigit():
                page_ids.append(int(value))

        existing_page_ids = self.env["website.page"].sudo().browse(page_ids).exists().ids
        res.update(
            odoo_ai_chat_page_ids=[(6, 0, existing_page_ids)],
        )
        return res

    # Guarda en parámetros del sistema la configuración del addon.
    def set_values(self):
        super().set_values()
        config = self.env["ir.config_parameter"].sudo()
        page_ids = self.odoo_ai_chat_page_ids.ids
        config.set_param("odoo_ai_chat.page_ids", ",".join(str(page_id) for page_id in page_ids))
