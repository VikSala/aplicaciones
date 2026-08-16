import logging
import re

from odoo import models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class OwaAccount(models.Model):
    _inherit = "owa.account"

    def _appointment_chatbot_account_ids(self):
        raw = self.env["ir.config_parameter"].sudo().get_param(
            "odoo_ai_chat_appointments.whatsapp_account_ids",
            default="",
        ) or ""
        return {
            int(value.strip())
            for value in raw.split(",")
            if value.strip().isdigit()
        }

    def _appointment_chatbot_is_enabled(self):
        self.ensure_one()
        config = self.env["ir.config_parameter"].sudo()
        enabled = str(config.get_param(
            "odoo_ai_chat_appointments.whatsapp_enabled",
            default="False",
        )).strip().lower() in {"1", "true", "yes", "on"}
        return enabled and self.id in self._appointment_chatbot_account_ids()

    def _appointment_chatbot_clean_inbound_text(self, value):
        """Extrae el texto útil del inbound que entrega el conector.

        Open WhatsApp Connector puede anteponer un <blockquote> cuando el
        usuario responde citando un mensaje anterior. Ese bloque no forma
        parte de la nueva intención y confundiría al parser incremental.
        """
        value = str(value or "")
        value = re.sub(
            r"<blockquote\b[^>]*>.*?</blockquote>",
            " ",
            value,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return (html2plaintext(value) or "").strip()

    def _appointment_chatbot_get_channel(self, from_number):
        self.ensure_one()
        return self.env["discuss.channel"].sudo()._get_whatsapp_channel(
            from_number,
            self,
            create_if_not_found=False,
        )

    def _appointment_chatbot_process_inbound(self, from_number, message_text):
        """Procesa un DM WhatsApp con el mismo cerebro que el widget Web.

        Devuelve True solo cuando el mensaje pertenece a una cuenta activada
        y ha sido asumido por el chatbot de citas. De ese modo el pipeline del
        conector no dispara además su chatbot nativo ni sus auto-respuestas.
        """
        self.ensure_one()
        if not self._appointment_chatbot_is_enabled():
            return False

        channel = self._appointment_chatbot_get_channel(from_number)
        if not channel or channel.channel_type != "whatsapp" or channel.is_whatsapp_group:
            return False

        clean_text = self._appointment_chatbot_clean_inbound_text(message_text)
        if not clean_text:
            return False

        Session = self.env["odoo.ai.appointment.session"].sudo()
        session = Session.get_or_create_whatsapp_session(channel)
        if not session:
            return False

        inbound_message = channel.last_wa_mail_message_id
        if inbound_message:
            session.whatsapp_last_inbound_message_id = inbound_message.id

        conversation = self.env["odoo.ai.appointment.conversation"].sudo()
        result = conversation.process_message(session, clean_text)
        result_session_id = result.get("session_id")
        if result_session_id and result_session_id != session.id:
            new_session = Session.browse(result_session_id).exists()
            if new_session:
                session = new_session
                if inbound_message:
                    session.whatsapp_last_inbound_message_id = inbound_message.id
        reply = (result.get("reply") or "").strip()

        # Fase 7: n8n solo entra cuando Python declara explícitamente que no
        # ha comprendido la entrada. La IA recibe contexto/histórico, pero su
        # única salida aceptada es texto; nunca se interpreta como una acción.
        if result.get("fallback"):
            ai_service = self.env["odoo.ai.appointment.ai.fallback"].sudo()
            if ai_service.is_available():
                payload = ai_service.build_payload(
                    session=session,
                    user_message=clean_text,
                    python_result=result,
                    source="whatsapp",
                    session_key="whatsapp-channel-%s" % channel.id,
                    whatsapp_channel=channel,
                )
                ai_result = ai_service.call_webhook(payload)
                if ai_result.get("ok") and ai_result.get("reply"):
                    reply = ai_result["reply"]
                else:
                    _logger.warning(
                        "Fallback IA no disponible para WhatsApp channel=%s session=%s error=%s; se usa respuesta Python",
                        channel.id,
                        session.id,
                        ai_result.get("error"),
                    )

        if not reply:
            _logger.warning(
                "AI Chat Citas no generó respuesta para WhatsApp channel=%s session=%s",
                channel.id,
                session.id,
            )
            return True

        # message_type='whatsapp_message' hace que Open WhatsApp Connector
        # cree el mail.message, el owa.message y lo envíe por el transporte
        # configurado (Baileys o Cloud API), conservando el histórico Discuss.
        outbound_message = channel.sudo().message_post(
            body=reply,
            message_type="whatsapp_message",
            subtype_xmlid="mail.mt_comment",
            author_id=self.env.ref("base.partner_root").id,
        )
        if outbound_message:
            session.whatsapp_last_outbound_message_id = outbound_message.id

        _logger.info(
            "AI Chat Citas procesó WhatsApp account=%s channel=%s session=%s state=%s handled=%s fallback=%s",
            self.id,
            channel.id,
            session.id,
            session.state,
            result.get("handled"),
            result.get("fallback"),
        )
        return True

    def _check_chatbot(self, from_number, message_text, is_new_channel=False):
        """Inserta el chatbot de citas en el punto oficial del pipeline inbound.

        Para cuentas no seleccionadas se conserva al 100%% el comportamiento
        original de Open WhatsApp Connector.
        """
        self.ensure_one()
        if self._appointment_chatbot_is_enabled():
            try:
                if self._appointment_chatbot_process_inbound(from_number, message_text):
                    return True
            except Exception:
                # No dejamos caer el webhook del conector. Si la integración
                # falla, permitimos que continúe su chatbot/auto-reply nativo.
                _logger.exception(
                    "Error procesando WhatsApp con AI Chat Citas account=%s from=%s",
                    self.id,
                    from_number,
                )
        return super()._check_chatbot(
            from_number,
            message_text,
            is_new_channel=is_new_channel,
        )
