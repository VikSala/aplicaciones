from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    odoo_ai_chat_appointments_ai_fallback_enabled = fields.Boolean(
        string="Activar fallback IA",
        config_parameter="odoo_ai_chat_appointments.ai_fallback_enabled",
        default=True,
        help=(
            "Compatibilidad con Fase 7.2: la activación efectiva depende de que exista una URL HTTP(S) válida. "
            "La IA solo genera texto conversacional y no tiene autoridad para reservar ni modificar el estado."
        ),
    )
    odoo_ai_chat_appointments_webhook_url = fields.Char(
        string="URL del webhook",
        config_parameter="odoo_ai_chat_appointments.webhook_url",
        help="Webhook HTTP(S) de fallback conversacional, por ejemplo un flujo de n8n.",
    )
    odoo_ai_chat_appointments_title = fields.Char(
        string="Título del chatbot",
        config_parameter="odoo_ai_chat_appointments.title",
        default="Asistente de citas",
    )
    odoo_ai_chat_appointments_welcome_message = fields.Char(
        string="Mensaje de bienvenida",
        config_parameter="odoo_ai_chat_appointments.welcome_message",
        default="Hola, ¿en qué puedo ayudarte?",
    )
    odoo_ai_chat_appointments_primary_color = fields.Char(
        string="Color primario",
        config_parameter="odoo_ai_chat_appointments.primary_color",
        default="#0e273b",
    )
    odoo_ai_chat_appointments_secondary_color = fields.Char(
        string="Color secundario",
        config_parameter="odoo_ai_chat_appointments.secondary_color",
        default="#4caf50",
    )
    odoo_ai_chat_appointments_text_color = fields.Char(
        string="Color de letra",
        config_parameter="odoo_ai_chat_appointments.text_color",
        default="#ffffff",
    )
    odoo_ai_chat_appointments_morning_from = fields.Float(
        string="Mañana desde",
        config_parameter="odoo_ai_chat_appointments.morning_from",
        default=8.0,
    )
    odoo_ai_chat_appointments_morning_to = fields.Float(
        string="Mañana hasta",
        config_parameter="odoo_ai_chat_appointments.morning_to",
        default=14.0,
    )
    odoo_ai_chat_appointments_afternoon_from = fields.Float(
        string="Tarde desde",
        config_parameter="odoo_ai_chat_appointments.afternoon_from",
        default=15.0,
    )
    odoo_ai_chat_appointments_afternoon_to = fields.Float(
        string="Tarde hasta",
        config_parameter="odoo_ai_chat_appointments.afternoon_to",
        default=21.0,
    )
    odoo_ai_chat_appointments_session_timeout_hours = fields.Integer(
        string="Caducidad de sesión (horas)",
        config_parameter="odoo_ai_chat_appointments.session_timeout_hours",
        default=24,
        help="Una reserva incompleta se considera abandonada tras este número de horas sin actividad. La siguiente interacción iniciará un proceso nuevo.",
    )
    odoo_ai_chat_appointments_page_ids = fields.Many2many(
        comodel_name="website.page",
        string="Páginas donde aparece el chatbot",
        help="Si no seleccionas ninguna página, el chatbot permanecerá desactivado.",
    )
    odoo_ai_chat_appointments_whatsapp_enabled = fields.Boolean(
        string="Activar chatbot en WhatsApp",
        config_parameter="odoo_ai_chat_appointments.whatsapp_enabled",
        default=False,
        help="Activa la integración Python-first del chatbot de citas en las cuentas de WhatsApp seleccionadas.",
    )
    odoo_ai_chat_appointments_whatsapp_account_ids = fields.Many2many(
        comodel_name="owa.account",
        string="Cuentas WhatsApp del chatbot",
        help="Solo estas cuentas serán interceptadas por el chatbot de citas. El resto conserva el comportamiento nativo de Open WhatsApp Connector.",
    )

    @api.model
    def get_values(self):
        values = super().get_values()
        config = self.env["ir.config_parameter"].sudo()
        raw_page_ids = config.get_param("odoo_ai_chat_appointments.page_ids", default="") or ""
        page_ids = [int(value.strip()) for value in raw_page_ids.split(",") if value.strip().isdigit()]
        existing_ids = self.env["website.page"].sudo().browse(page_ids).exists().ids

        raw_account_ids = config.get_param("odoo_ai_chat_appointments.whatsapp_account_ids", default="") or ""
        account_ids = [int(value.strip()) for value in raw_account_ids.split(",") if value.strip().isdigit()]
        existing_account_ids = self.env["owa.account"].sudo().browse(account_ids).exists().ids

        values.update(
            odoo_ai_chat_appointments_page_ids=[(6, 0, existing_ids)],
            odoo_ai_chat_appointments_whatsapp_account_ids=[(6, 0, existing_account_ids)],
        )
        return values

    def set_values(self):
        super().set_values()
        self.env["ir.config_parameter"].sudo().set_param(
            "odoo_ai_chat_appointments.page_ids",
            ",".join(str(page_id) for page_id in self.odoo_ai_chat_appointments_page_ids.ids),
        )
        self.env["ir.config_parameter"].sudo().set_param(
            "odoo_ai_chat_appointments.whatsapp_account_ids",
            ",".join(str(account_id) for account_id in self.odoo_ai_chat_appointments_whatsapp_account_ids.ids),
        )

    @api.constrains("odoo_ai_chat_appointments_session_timeout_hours")
    def _check_session_timeout_hours(self):
        for settings in self:
            if settings.odoo_ai_chat_appointments_session_timeout_hours < 1:
                raise ValidationError(_("La caducidad de sesión debe ser de al menos 1 hora."))
            if settings.odoo_ai_chat_appointments_session_timeout_hours > 24 * 30:
                raise ValidationError(_("La caducidad de sesión no puede superar 30 días."))

    @api.constrains(
        "odoo_ai_chat_appointments_morning_from",
        "odoo_ai_chat_appointments_morning_to",
        "odoo_ai_chat_appointments_afternoon_from",
        "odoo_ai_chat_appointments_afternoon_to",
    )
    def _check_chat_dayparts(self):
        for settings in self:
            ranges = [
                (settings.odoo_ai_chat_appointments_morning_from, settings.odoo_ai_chat_appointments_morning_to, _("mañana")),
                (settings.odoo_ai_chat_appointments_afternoon_from, settings.odoo_ai_chat_appointments_afternoon_to, _("tarde")),
            ]
            for start, end, label in ranges:
                if start < 0 or end > 24 or end <= start:
                    raise ValidationError(_("La franja de %(label)s debe estar entre 00:00 y 24:00 y su hora final debe ser posterior a la inicial.", label=label))

