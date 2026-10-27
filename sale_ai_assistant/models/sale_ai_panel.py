"""Backend contract for the OWL panel: persistence and phase-2 AI generation."""
import logging

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError

_logger = logging.getLogger(__name__)


class SaleAISessionPanel(models.Model):
    _inherit = "sale.ai.session"

    def unlink(self):
        # The only supported deletion is a voluntary cancellation of an OPEN conversation.
        # Regular Odoo ACL and record rules remain in effect (no sudo).
        for session in self:
            if session.user_id != self.env.user or session.company_id not in self.env.companies:
                raise AccessError(_("No puedes descartar conversaciones de otro usuario o compañía."))
            if session.state != "active" or session.sale_order_id:
                raise UserError(_("Solo se pueden descartar conversaciones activas sin presupuesto creado."))
        return super().unlink()

    @api.model
    def _panel_find(self, session_id):
        """Search, don't browse/sudo: the global owner/company rules are never bypassed."""
        if not isinstance(session_id, int) or isinstance(session_id, bool):
            raise ValidationError(_("Identificador de conversación no válido."))
        session = self.search([
            ("id", "=", session_id),
            ("user_id", "=", self.env.uid),
            ("company_id", "=", self.env.company.id),
        ], limit=1)
        if not session:
            raise AccessError(_("No tienes acceso a esta conversación."))
        return session

    @api.model
    def _panel_info(self, session):
        if not session:
            return False
        return {
            "id": session.id,
            "name": session.name,
            "state": session.state,
            "created_at": fields.Datetime.to_string(session.create_date) if session.create_date else "",
            "ended_at": fields.Datetime.to_string(session.ended_at) if session.ended_at else "",
            "sale_order_id": session.sale_order_id.id or False,
            "sale_order_name": session.sale_order_id.name or "",
            "message_count": self.env["sale.ai.message"].search_count([("session_id", "=", session.id)]),
            "model_id": (session.model_id or session.company_id.sale_ai_model_id).id or False,
            "model_name": (session.model_id or session.company_id.sale_ai_model_id).name or "Sin configurar",
        }

    @api.model
    def _panel_details(self, session):
        info = self._panel_info(session)
        # Most recent 150 messages. Never use previous sessions as automatic AI context.
        messages = self.env["sale.ai.message"].search(
            [("session_id", "=", session.id)], order="id desc", limit=150,
        )
        info["messages_has_more"] = info["message_count"] > len(messages)
        info["messages"] = [
            {
                "id": msg.id,
                "role": msg.role,
                "content": msg.content,
                "created_at": fields.Datetime.to_string(msg.create_date) if msg.create_date else "",
                "model": ((msg.model_id.name or "") +
                          (" · " + msg.models_used_summary if msg.models_used_summary else "")),
                "input_tokens": msg.input_tokens,
                "output_tokens": msg.output_tokens,
                "latency_ms": msg.latency_ms,
                "reported_cost_usd": msg.reported_cost_usd,
                "estimated_cost_usd": msg.estimated_cost_usd,
            }
            for msg in reversed(messages)
        ]
        draft = session.draft_id
        info["has_work"] = bool(
            info["message_count"] or (draft and (
                draft.line_ids or draft.partner_id or draft.pricelist_id or
                draft.description or draft.assumptions or draft.estimate_details
            ))
        )
        info["proposal"] = session.technical_proposal or False
        info["draft"] = self._panel_draft_payload(session)
        return info

    @api.model
    def _panel_draft_payload(self, session):
        draft = session.draft_id
        if not draft:
            return False
        return {
            "id": draft.id,
            "description": draft.description or "",
            "partner": draft.partner_id.display_name if draft.partner_id else "",
            "currency": draft.currency_id.symbol or "€",
            "currency_code": draft.currency_id.name or "",
            "amount_untaxed": draft.amount_untaxed_estimate,
            "assumptions": draft.assumptions or "",
            "estimate_details": draft.estimate_details or "",
            "review_required": True,
            "lines": [
                {
                    "id": line.id,
                    "kind": line.line_kind,
                    "name": line.name,
                    "product_ref": line.product_id.default_code or "" if line.product_id else "",
                    "product_name": line.product_id.display_name if line.product_id else "",
                    "quantity": line.product_uom_qty,
                    "uom": line.product_uom_id.name if line.product_uom_id else "",
                    "price_unit": line.price_unit,
                    "discount": line.discount,
                    "price_source": line.price_source,
                    "price_evidence": line.price_evidence or "",
                    "amount": line.amount_estimate,
                }
                for line in draft.line_ids.sorted(key=lambda l: (l.sequence, l.id))
            ],
        }

    @api.model
    def assistant_panel_preview(self, session_id):
        """Refresh after manual edits in draft form; never writes anything."""
        session = self._panel_find(session_id)
        return self._panel_draft_payload(session)

    @api.model
    def assistant_panel_bootstrap(self):
        # The OWL component must not assume a JS "user" service exists.
        # Server-side group membership is authoritative. Avoid reading protected
        # session records when the current user is not a Sales administrator.
        allowed = self.env.user.has_group("sales_team.group_sale_manager")
        if not allowed:
            return {
                "allowed": False,
                "history_limit": 0,
                "active": False,
                "history": [],
                "history_has_more": False,
                "models": [],
            }
        company = self.env.company
        domain = [("user_id", "=", self.env.uid), ("company_id", "=", company.id)]
        active = self.search(domain + [("state", "=", "active")], order="id desc", limit=1)
        history_limit = company.sale_ai_chat_history_limit
        closed_domain = domain + [("state", "in", ["completed", "consultation", "archived"])]
        # A zero limit means unlimited history, but it must be paginated to avoid
        # loading years of conversations into the browser on each open.
        page_size = history_limit or 30
        history_plus_one = self.search(
            closed_domain, order="write_date desc, id desc", limit=page_size + 1
        )
        return {
            "allowed": True,
            "company_id": company.id,
            "history_limit": history_limit,
            "active": self._panel_details(active) if active else False,
            "history": [self._panel_info(rec) for rec in history_plus_one[:page_size]],
            "history_has_more": history_limit == 0 and len(history_plus_one) > page_size,
            "models": [
                {"id": model.id, "name": model.name, "supports_tools": (model.supports_tools if model.model_type == 'individual' else model.tools_model_id.supports_tools), "is_profile": model.model_type == 'profile'}
                for model in self.env["sale.ai.model"].search([
                    ("active", "=", True), ("provider", "=", "vercel_gateway"),
                ], order="name, id")
            ],
        }

    @api.model
    def assistant_panel_select_model(self, session_id, model_id):
        """Switch the CURRENT active chat only, keeping its existing messages.

        Does not change the company's default and never permits editing history.
        """
        if not self.env.user.has_group("sales_team.group_sale_manager"):
            raise AccessError(_("Solo un administrador de Ventas puede usar el asistente."))
        session = self._panel_find(session_id)
        session._ensure_can_edit_draft()
        if not isinstance(model_id, int) or isinstance(model_id, bool) or model_id <= 0:
            raise ValidationError(_("Selecciona un modelo de IA válido."))
        selected = self.env["sale.ai.model"].search([
            ("id", "=", model_id), ("active", "=", True),
            ("provider", "=", "vercel_gateway"),
        ], limit=1)
        if not selected:
            raise ValidationError(_("El modelo seleccionado no está disponible en Vercel."))
        if session.model_id != selected:
            # Exclude a model switch from overlapping an active AI request.
            session._ai_lock_session()
            session.write({"model_id": selected.id})
        return {"model_id": selected.id, "model_name": selected.name}

    @api.model
    def assistant_panel_history_page(self, offset=0):
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValidationError(_("Paginación de historial no válida."))
        if self.env.company.sale_ai_chat_history_limit:
            return {"history": [], "has_more": False}
        domain = [
            ("user_id", "=", self.env.uid),
            ("company_id", "=", self.env.company.id),
            ("state", "in", ["completed", "consultation", "archived"]),
        ]
        rows = self.search(domain, order="write_date desc, id desc", offset=offset, limit=31)
        return {
            "history": [self._panel_info(rec) for rec in rows[:30]],
            "has_more": len(rows) > 30,
        }

    @api.model
    def assistant_panel_older_messages(self, session_id, before_id):
        session = self._panel_find(session_id)
        if not isinstance(before_id, int) or isinstance(before_id, bool) or before_id <= 0:
            raise ValidationError(_("Paginación de mensajes no válida."))
        messages = self.env["sale.ai.message"].search([
            ("session_id", "=", session.id), ("id", "<", before_id),
        ], order="id desc", limit=101)
        return {
            "messages": [
                {
                    "id": msg.id,
                    "role": msg.role,
                    "content": msg.content,
                    "created_at": fields.Datetime.to_string(msg.create_date) if msg.create_date else "",
                    "model": ((msg.model_id.name or "") +
                          (" · " + msg.models_used_summary if msg.models_used_summary else "")),
                    "input_tokens": msg.input_tokens,
                    "output_tokens": msg.output_tokens,
                    "latency_ms": msg.latency_ms,
                    "reported_cost_usd": msg.reported_cost_usd,
                    "estimated_cost_usd": msg.estimated_cost_usd,
                }
                for msg in reversed(messages[:100])
            ],
            "has_more": len(messages) > 100,
        }

    @api.model
    def assistant_panel_open(self, session_id):
        session = self._panel_find(session_id)
        return self._panel_details(session)

    @api.model
    def assistant_panel_get_or_create(self):
        domain = [("user_id", "=", self.env.uid),
                  ("company_id", "=", self.env.company.id), ("state", "=", "active")]
        active = self.search(domain, order="id desc", limit=1)
        if not active:
            active = self.create({"name": _("Nuevo presupuesto IA")})
        return self._panel_details(active)

    @api.model
    def assistant_panel_send(self, session_id, content):
        session = self._panel_find(session_id)
        session._ensure_can_edit_draft()
        if not isinstance(content, str) or not content.strip():
            raise ValidationError(_("Escribe un mensaje antes de enviarlo."))
        session._ai_lock_session()
        message = self.env["sale.ai.message"].create({
            "session_id": session.id,
            "role": "user",
            "content": content.strip(),
        })
        if session.name == _("Nuevo presupuesto IA"):
            # A meaningful, compact heading helps audit conversations in history.
            subject = " ".join(content.split())[:76]
            session.write({"name": subject})
        result = {
            "session_name": session.name,
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "created_at": fields.Datetime.to_string(message.create_date) if message.create_date else "",
        }
        # Return an error as data so the user's message is committed even if
        # Vercel is unreachable. The UI offers Retry without sending it twice.
        # Isolate unexpected multimodel engine errors from the user's message.
        # If the agent crashes (including a database INSERT in usage metering),
        # roll back ONLY its side effects, log the full Python traceback, and
        # keep the original user request so it can be retried safely.
        try:
            with self.env.cr.savepoint():
                ai_result = session._ai_generate_for()
        except Exception:
            _logger.exception(
                'sale_ai_assistant: unhandled AI generation error; session=%s', session.id
            )
            ai_result = {"error": _(
                "Error interno al ejecutar el perfil de IA. "
                "El mensaje se ha conservado; revisa el traceback de Odoo "
                "(sale_ai_assistant, sesión %s) antes de reintentar."
            ) % session.id}
        result.update(ai_result)
        result["proposal"] = session.technical_proposal or False
        result["draft"] = self._panel_draft_payload(session)
        result["model_name"] = (session.model_id or session.company_id.sale_ai_model_id).name or "Sin configurar"
        return result

    @api.model
    def assistant_panel_new(self, current_session_id=False):
        """One RPC transaction: discard the given active session and start a fresh one."""
        if current_session_id:
            current = self._panel_find(current_session_id)
            if current.state != "active" or current.sale_order_id:
                raise UserError(_("Esta conversación está cerrada y no puede descartarse."))
            current.unlink()  # ondelete=cascade removes messages, drafts and lines.
        session = self.create({"name": _("Nuevo presupuesto IA")})
        return self._panel_details(session)
