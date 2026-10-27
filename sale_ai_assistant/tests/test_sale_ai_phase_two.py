"""Mocked provider tests: no network/credits are used by the suite."""
from unittest.mock import patch

from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged

from ..models.sale_ai_gateway import GatewayError, get_gateway_key


@tagged("post_install", "-at_install")
class TestSaleAIPhaseTwo(TransactionCase):
    def setUp(self):
        super().setUp()
        group = self.env.ref("sales_team.group_sale_manager")
        if group not in self.env.user.groups_id:
            self.env.user.write({"groups_id": [(4, group.id)]})
        self.company = self.env.company
        self.model = self.env.ref("sale_ai_assistant.sale_ai_model_gpt_mini")
        self.company.sudo().write({
            "sale_ai_model_id": self.model.id,
            "sale_ai_context_budget": 1000,
            "sale_ai_max_output_tokens": 400,
            "sale_ai_request_timeout": 15,
        })
        self.param_name = "sale_ai_assistant.vercel_key.%d" % self.company.id
        self.env["ir.config_parameter"].sudo().set_param(self.param_name, "ai_gateway_test_secret")
        self.panel = self.env["sale.ai.session"]

    def _fake_answer(self, key, model_id, messages, timeout, max_tokens):
        self.assertEqual(key, "ai_gateway_test_secret")
        self.assertEqual(model_id, "openai/gpt-5.4-mini")
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[-1]["role"], "user")
        self.assertEqual(timeout, 15)
        self.assertEqual(max_tokens, 400)
        return {
            "content": "Puedo ayudarte a redactar la partida. ¿Qué cantidades estimas?",
            "input_tokens": 135,
            "output_tokens": 21,
            "latency_ms": 65,
            "reported_cost_usd": 0.0002,
        }

    def test_new_company_settings_need_no_database_columns(self):
        # Key regression: Fase 2 may load the registry while res_company is
        # still at Fase 1 schema. These fields must never need SQL columns.
        self.assertFalse(self.env["res.company"]._fields["sale_ai_max_output_tokens"].store)
        self.assertFalse(self.env["res.company"]._fields["sale_ai_request_timeout"].store)
        self.company.sudo().write({
            "sale_ai_max_output_tokens": 730,
            "sale_ai_request_timeout": 47,
        })
        self.env.invalidate_all()
        self.assertEqual(self.company.sale_ai_max_output_tokens, 730)
        self.assertEqual(self.company.sale_ai_request_timeout, 47)
        self.assertEqual(
            self.env["ir.config_parameter"].sudo().get_param(
                "sale_ai_assistant.max_output_tokens.%s" % self.company.id
            ), "730",
        )

    def test_writing_one_gateway_limit_does_not_reset_other(self):
        self.company.sudo().write({"sale_ai_max_output_tokens": 820})
        self.env.invalidate_all()
        self.assertEqual(self.company.sale_ai_max_output_tokens, 820)
        self.assertEqual(self.company.sale_ai_request_timeout, 15)
        self.company.sudo().write({"sale_ai_request_timeout": 22})
        self.env.invalidate_all()
        self.assertEqual(self.company.sale_ai_max_output_tokens, 820)
        self.assertEqual(self.company.sale_ai_request_timeout, 22)

    def test_gateway_limits_are_per_company(self):
        second_company = self.env["res.company"].sudo().create({
            "name": "Otra compañía para probar límites de IA",
        })
        second_company.sudo().write({
            "sale_ai_max_output_tokens": 1200,
            "sale_ai_request_timeout": 60,
        })
        self.env.invalidate_all()
        self.assertEqual(second_company.sale_ai_max_output_tokens, 1200)
        self.assertEqual(second_company.sale_ai_request_timeout, 60)
        # Values configured in setUp remain independent.
        self.assertEqual(self.company.sale_ai_max_output_tokens, 400)
        self.assertEqual(self.company.sale_ai_request_timeout, 15)

    def test_messages_flow_and_token_usage(self):
        session_id = self.panel.assistant_panel_get_or_create()["id"]
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway", side_effect=self._fake_answer):
            result = self.panel.assistant_panel_send(session_id, "Necesito instalar tres motores")
        self.assertEqual(result["content"], "Necesito instalar tres motores")
        self.assertIn("ayudarte", result["assistant_message"]["content"])
        response = self.panel.assistant_panel_open(session_id)
        self.assertEqual([msg["role"] for msg in response["messages"]], ["user", "assistant"])
        self.assertEqual(response["messages"][-1]["input_tokens"], 135)
        self.assertEqual(response["messages"][-1]["reported_cost_usd"], 0.0002)
        self.assertEqual(len(self.panel.browse(session_id).draft_id.line_ids), 0)
        self.assertFalse(self.panel.browse(session_id).sale_order_id)

    def test_context_never_mixes_sessions(self):
        first = self.panel.create({"name": "Motor"})
        second = self.panel.create({"name": "Otra venta"})
        self.env["sale.ai.message"].create({"session_id": first.id, "content": "SECRETO OTRA CONVERSACION"})
        self.env["sale.ai.message"].create({"session_id": second.id, "content": "Presupuesto actual"})
        prompt = second._ai_context_messages()
        content = "\n".join(message["content"] for message in prompt)
        self.assertIn("Presupuesto actual", content)
        self.assertNotIn("SECRETO OTRA CONVERSACION", content)

    def test_provider_failure_persists_only_user_and_retry(self):
        session_id = self.panel.assistant_panel_get_or_create()["id"]
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway", side_effect=GatewayError("Límite 429")):
            result = self.panel.assistant_panel_send(session_id, "Prueba de red")
        self.assertEqual(result["error"], "Límite 429")
        self.assertEqual(len(self.panel.assistant_panel_open(session_id)["messages"]), 1)
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway", side_effect=self._fake_answer):
            retry = self.panel.assistant_panel_retry(session_id)
        self.assertIn("assistant_message", retry)
        self.assertEqual(len(self.panel.assistant_panel_open(session_id)["messages"]), 2)
        with self.assertRaises(UserError):
            self.panel.assistant_panel_retry(session_id)

    def test_provider_configuration_never_returns_key(self):
        wizard = self.env["sale.ai.gateway.settings"].create({
            "api_key": "secret_new_key",
            "model_id": self.model.id,
            "context_budget": 2200,
        })
        wizard.action_apply()
        self.assertEqual(get_gateway_key(self.env, self.company.id), "secret_new_key")
        self.assertFalse(wizard.api_key)
        data = self.panel.assistant_panel_bootstrap()
        self.assertNotIn("secret_new_key", repr(data))
        self.assertEqual(self.company.sale_ai_context_budget, 2200)

    def test_salesperson_denied_setup(self):
        sales_user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "Vendedor fase 2", "login": "sales_fase2_denied",
            "groups_id": [(6, 0, [
                self.env.ref("base.group_user").id,
                self.env.ref("sales_team.group_sale_salesman").id,
            ])],
        })
        with self.assertRaises(AccessError):
            self.env["sale.ai.gateway.settings"].with_user(sales_user).create({})

    def test_cancel_cascades_messages_and_draft(self):
        sid = self.panel.assistant_panel_get_or_create()["id"]
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway", side_effect=self._fake_answer):
            self.panel.assistant_panel_send(sid, "Instalación")
        new = self.panel.assistant_panel_new(sid)
        self.assertNotEqual(new["id"], sid)
        self.assertFalse(self.panel.browse(sid).exists())
