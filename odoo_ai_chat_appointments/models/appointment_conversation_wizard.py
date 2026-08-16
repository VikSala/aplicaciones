import uuid

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class OdooAIAppointmentConversationWizard(models.TransientModel):
    _name = "odoo.ai.appointment.conversation.wizard"
    _description = "Prueba de máquina de estados del chatbot de citas"

    session_id = fields.Many2one(
        "odoo.ai.appointment.session",
        string="Sesión de prueba",
        readonly=True,
        ondelete="set null",
    )
    user_message = fields.Char(string="Mensaje del usuario")
    bot_reply = fields.Text(string="Última respuesta", readonly=True)
    handled = fields.Boolean(string="Entendido por Python", readonly=True)
    fallback = fields.Boolean(string="Requiere fallback IA", readonly=True)
    ai_used = fields.Boolean(string="IA ejecutada", readonly=True)
    ai_error = fields.Char(string="Error fallback IA", readonly=True)
    current_state = fields.Selection(
        related="session_id.state",
        string="Estado actual",
        readonly=True,
    )
    line_ids = fields.One2many(
        "odoo.ai.appointment.conversation.wizard.line",
        "wizard_id",
        string="Conversación",
        readonly=True,
    )

    def action_send(self):
        self.ensure_one()
        message = (self.user_message or "").strip()
        if not message:
            raise ValidationError(_("Escribe un mensaje para probar el parser."))

        session = self._ensure_test_session()
        result = self.env["odoo.ai.appointment.conversation"].process_message(session, message)
        result_session_id = result.get("session_id")
        if result_session_id and result_session_id != session.id:
            replacement = self.env["odoo.ai.appointment.session"].browse(result_session_id).exists()
            if replacement:
                session = replacement
                self.session_id = replacement

        # El wizard de prueba debe recorrer el mismo fallback que los canales
        # reales. En Fase 7 el parser marca fallback=True, pero la llamada a
        # n8n se hacía solo desde Web/WhatsApp. Eso hacía que este asistente
        # mostrase siempre la aclaración Python aunque el fallback estuviese
        # correctamente configurado.
        final_reply = result.get("reply") or ""
        ai_used = False
        ai_error = False
        if result.get("fallback"):
            ai_service = self.env["odoo.ai.appointment.ai.fallback"].sudo()
            if ai_service.is_available():
                payload = ai_service.build_payload(
                    session=session,
                    user_message=message,
                    python_result=result,
                    source="web",
                    session_key=session.web_session_id or session.name,
                    page_title="Probar conversación",
                )
                ai_result = ai_service.call_webhook(payload)
                if ai_result.get("ok") and ai_result.get("reply"):
                    final_reply = ai_result["reply"]
                    ai_used = True
                else:
                    ai_error = ai_result.get("error") or "webhook_error"
            else:
                url = ai_service.get_webhook_url()
                ai_error = "missing_webhook_url" if not url else "invalid_webhook_url"

        commands = [fields.Command.create({"role": "user", "message": message})]
        commands.append(fields.Command.create({
            "role": "assistant",
            "message": final_reply,
            "handled": bool(result.get("handled")),
            "fallback": bool(result.get("fallback")),
            "ai_used": ai_used,
            "ai_error": ai_error or False,
            "state": result.get("state") or session.state,
        }))
        self.write({
            "line_ids": commands,
            "user_message": False,
            "bot_reply": final_reply,
            "handled": bool(result.get("handled")),
            "fallback": bool(result.get("fallback")),
            "ai_used": ai_used,
            "ai_error": ai_error or False,
        })
        return self._reopen()

    def action_reset(self):
        self.ensure_one()
        if self.session_id:
            self.session_id.unlink()
        self.write({
            "session_id": False,
            "user_message": False,
            "bot_reply": False,
            "handled": False,
            "fallback": False,
            "ai_used": False,
            "ai_error": False,
            "line_ids": [fields.Command.clear()],
        })
        return self._reopen()

    def _ensure_test_session(self):
        self.ensure_one()
        if self.session_id and self.session_id.exists():
            return self.session_id
        session = self.env["odoo.ai.appointment.session"].create({
            "source": "web",
            "web_session_id": "phase3-test-%s" % uuid.uuid4().hex,
            "state": "new",
            "is_test": True,
        })
        self.session_id = session
        return session

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Probar conversación"),
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }


class OdooAIAppointmentConversationWizardLine(models.TransientModel):
    _name = "odoo.ai.appointment.conversation.wizard.line"
    _description = "Línea de prueba conversacional"
    _order = "id"

    wizard_id = fields.Many2one(
        "odoo.ai.appointment.conversation.wizard",
        required=True,
        ondelete="cascade",
    )
    role = fields.Selection(
        [("user", "Usuario"), ("assistant", "Bot")],
        required=True,
        readonly=True,
    )
    message = fields.Text(string="Mensaje", required=True, readonly=True)
    handled = fields.Boolean(string="Python", readonly=True)
    fallback = fields.Boolean(string="Fallback IA", readonly=True)
    ai_used = fields.Boolean(string="IA ejecutada", readonly=True)
    ai_error = fields.Char(string="Error IA", readonly=True)
    state = fields.Char(string="Estado tras mensaje", readonly=True)
