"""Iteration A: configured limits, context isolation, untruncated notes."""
from unittest.mock import patch
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestAgentIterationA(TransactionCase):
    def setUp(self):
        super().setUp()
        group = self.env.ref("sales_team.group_sale_manager")
        if group not in self.env.user.groups_id:
            self.env.user.write({"groups_id": [(4, group.id)]})
        self.company = self.env.company
        self.model = self.env.ref("sale_ai_assistant.sale_ai_model_gpt_mini")
        self.company.sudo().write({"sale_ai_model_id": self.model.id,
            "sale_ai_max_output_tokens": 2000, "sale_ai_request_timeout": 45})
        self.params = self.env["ir.config_parameter"].sudo()
        self.params.set_param("sale_ai_assistant.vercel_key.%s" % self.company.id, "mock-key")
        self.session = self.env["sale.ai.session"].create({"name": "Contexto largo"})

    def test_context_mode_default_and_full_transcript(self):
        self.assertEqual(self.company._sale_ai_get_agent_parameter(
            self.company.id, "context_mode"), "full")
        first = "PRIMER DATO " + "cable 2,5 mm². " * 1300
        self.env["sale.ai.message"].create({"session_id": self.session.id,
                                               "role": "user", "content": first})
        self.env["sale.ai.message"].create({"session_id": self.session.id,
                                               "role": "assistant", "content": "Entendido."})
        messages = self.session._ai_context_messages()
        self.assertEqual(messages[1]["content"], first)
        self.assertEqual(messages[2]["content"], "Entendido.")
        other = self.env["sale.ai.session"].create({"name": "Separada"})
        self.assertNotIn("PRIMER DATO", str(other._ai_context_messages()))

    def test_wizard_persists_limits_per_company(self):
        wizard = self.env["sale.ai.gateway.settings"].create({
            "context_mode": "bounded", "context_budget": 24000,
            "max_output_tokens": 6000, "request_timeout": 75,
            "max_tool_rounds": 12, "max_tool_calls": 35,
            "tool_result_chars": 125000, "max_turn_seconds": 175,
        })
        wizard.action_apply()
        self.env.invalidate_all()
        self.assertEqual(self.company.sale_ai_max_output_tokens, 6000)
        self.assertEqual(self.company._sale_ai_get_agent_parameter(
            self.company.id, "max_tool_rounds"), 12)
        self.assertEqual(self.company._sale_ai_get_agent_parameter(
            self.company.id, "context_mode"), "bounded")

    def test_note_uses_exact_ui_output_limit(self):
        user = self.env["sale.ai.message"].create({"session_id": self.session.id,
            "role": "user", "content": "Nota: redacta una descripción técnica"})
        def fake_call(key, model, messages, timeout, max_tokens, **kwargs):
            self.assertEqual(max_tokens, 2000)
            self.assertEqual(timeout, 45)
            return {"content": "Suministro e instalación revisada.",
                "finish_reason": "stop", "output_tokens": 22,
                "input_tokens": 200, "latency_ms": 2, "reported_cost_usd": 0}
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway",
                   side_effect=fake_call):
            content, _model, _response = self.session._quick_generate_line_text(
                "redacta una descripción técnica", "line_note", user)
        self.assertEqual(content, "Suministro e instalación revisada.")

    def test_plain_chat_passes_exact_ui_output_limit(self):
        self.model.write({"supports_tools": False})
        def fake_call(key, model, messages, timeout, max_tokens, **kwargs):
            self.assertEqual(max_tokens, 2000)
            self.assertEqual(timeout, 45)
            return {"content": "Prepararemos el presupuesto.", "tool_calls": [],
                "finish_reason": "stop", "input_tokens": 50,
                "output_tokens": 12, "latency_ms": 2, "reported_cost_usd": 0}
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway",
                   side_effect=fake_call):
            reply = self.env["sale.ai.session"].assistant_panel_send(
                self.session.id, "Vamos a empezar")
        self.assertIn("Prepararemos", reply["assistant_message"]["content"])
