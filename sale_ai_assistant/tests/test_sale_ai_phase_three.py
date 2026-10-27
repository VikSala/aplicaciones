"""Phase 3 acceptance tests. HTTP model replies are mocked: no Vercel credit used."""
import json
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..models.sale_ai_read_tools import SaleAIReadTools
from ..models.sale_ai_gateway import call_gateway


@tagged("post_install", "-at_install")
class TestSaleAIPhaseThree(TransactionCase):
    def setUp(self):
        super().setUp()
        manager_group = self.env.ref("sales_team.group_sale_manager")
        if manager_group not in self.env.user.groups_id:
            self.env.user.write({"groups_id": [(4, manager_group.id)]})
        self.company = self.env.company
        self.model = self.env.ref("sale_ai_assistant.sale_ai_model_gpt_mini")
        self.model.write({"supports_tools": True})
        self.company.sudo().write({
            "sale_ai_model_id": self.model.id,
            "sale_ai_history_limit": 2,
            "sale_ai_context_budget": 2400,
            "sale_ai_max_output_tokens": 400,
        })
        self.env["ir.config_parameter"].sudo().set_param(
            "sale_ai_assistant.vercel_key.%s" % self.company.id, "example_only_secret")
        self.partner = self.env["res.partner"].create({"name": "CLIENTE VENTILACION TEST"})
        self.other_partner = self.env["res.partner"].create({"name": "CLIENTE SUMINISTROS TEST"})
        self.order = self.env["sale.order"].create({
            "partner_id": self.partner.id, "company_id": self.company.id,
            "order_line": [(0, 0, {
                "name": "Linea alimentacion motores ventilacion trifasicos 2,5 mm",
                "product_uom_qty": 1,
                "price_unit": 1000,
            })],
        })
        self.session = self.env["sale.ai.session"].create({"name": "Prueba Fase 3"})

    def test_search_without_any_commercial_mutations(self):
        tools = SaleAIReadTools(self.session)
        self.assertTrue(tools.search_customers("VENTILACION TEST")["results"])
        products = tools.search_products("motor")
        self.assertEqual(products["source"], "odoo.product.product")
        historical = tools.search_quotations("motores ventilacion")
        self.assertIn(self.order.id, [r["id"] for r in historical["results"]])
        lines = tools.get_quotation_lines(self.order.id)
        self.assertIn("alimentacion", lines["lines"][0]["description"])
        self.assertTrue(tools.get_customer_history(self.partner.id)["orders"])
        self.assertEqual(self.order.amount_untaxed, 1000)
        self.assertFalse(self.session.draft_id.line_ids)

    def test_unknown_tool_bad_args_and_denied_id(self):
        tools = SaleAIReadTools(self.session)
        self.assertIn("error", tools.execute("delete_sale_order", "{}"))
        self.assertIn("error", tools.execute("search_customers", '{"query":"a", "sudo":true}'))
        self.assertIn("error", tools.execute("get_quotation_lines", '{"order_id":-1}'))
        self.assertTrue(tools.get_quotation_lines(9999999)["not_found_or_denied"])

    def test_other_company_quotations_are_never_returned(self):
        foreign_company = self.env["res.company"].sudo().create({"name": "Compañía ajena IA Fase 3"})
        other = self.env["sale.order"].sudo().with_company(foreign_company).create({
            "partner_id": self.other_partner.id,
            "company_id": foreign_company.id,
            "order_line": [(0, 0, {"name": "prueba aislamiento ventilacion X123",
                                    "product_uom_qty": 1, "price_unit": 999})],
        })
        tools = SaleAIReadTools(self.session)
        self.assertTrue(tools.get_quotation_lines(other.id)["not_found_or_denied"])
        found = tools.search_quotations("X123")
        self.assertNotIn(other.id, [row["id"] for row in found["results"]])

    def test_history_limit_zero_disables_historical_tools(self):
        self.company.sudo().write({"sale_ai_history_limit": 0})
        tools = SaleAIReadTools(self.session)
        names = [t["function"]["name"] for t in tools.definitions()]
        self.assertNotIn("search_quotations", names)
        self.assertNotIn("get_customer_history", names)
        self.assertIn("search_products", names)
        self.assertIn("error", tools.execute("search_quotations", '{"query":"ventilacion"}'))

    def test_gateway_tool_turn_and_token_accumulation(self):
        outputs = []

        def fake_provider(key, model_id, messages, timeout, max_tokens, **kwargs):
            self.assertEqual(key, "example_only_secret")
            outputs.append((list(messages), kwargs))
            if len(outputs) == 1:
                self.assertIn("tools", kwargs)
                return {"content": "", "tool_calls": [{
                    "id": "call_123", "type": "function", "function": {
                        "name": "search_quotations", "arguments": '{"query":"motores ventilacion"}'}}],
                    "input_tokens": 60, "output_tokens": 15,
                    "reported_cost_usd": 0.002, "latency_ms": 20}
            self.assertTrue(any(x["role"] == "tool" for x in messages))
            self.assertNotIn("example_only_secret", json.dumps(messages))
            return {"content": "Encontré un presupuesto anterior, pero revisa el precio.",
                    "tool_calls": [], "input_tokens": 120, "output_tokens": 35,
                    "reported_cost_usd": 0.003, "latency_ms": 30}

        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway", side_effect=fake_provider):
            result = self.env["sale.ai.session"].assistant_panel_send(
                self.session.id, "Consulta trabajos anteriores de motores ventilacion")
        self.assertEqual(len(outputs), 2)
        self.assertIn("assistant_message", result)
        self.assertEqual(result["assistant_message"]["input_tokens"], 180)
        self.assertEqual(result["assistant_message"]["output_tokens"], 50)
        self.assertFalse(self.session.sale_order_id)
        self.assertFalse(self.session.draft_id.line_ids)
        saved = self.env["sale.ai.message"].search([("session_id", "=", self.session.id)])
        self.assertEqual(saved.mapped("role"), ["user", "assistant"])
        # Tool results are only passed to this request, never saved to history.
        self.assertNotIn("call_123", " ".join(saved.mapped("content")))

    def test_legacy_chat_works_without_tool_support(self):
        self.model.write({"supports_tools": False})

        def fake_provider(key, model_id, messages, timeout, max_tokens):
            self.assertFalse(any(m["role"] == "tool" for m in messages))
            return {"content": "¿Cuántas unidades necesitas?", "input_tokens": 5,
                    "output_tokens": 5, "reported_cost_usd": 0, "latency_ms": 10}

        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway", side_effect=fake_provider):
            result = self.env["sale.ai.session"].assistant_panel_send(self.session.id, "Hola")
        self.assertIn("assistant_message", result)

    def test_transport_accepts_tool_only_responses(self):
        raw = json.dumps({"choices": [{"message": {"role": "assistant", "content": None,
            "tool_calls": [{"id": "call_1", "type": "function", "function": {
                "name": "search_customers", "arguments": '{"query":"VENTILACION"}'}}]}}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 12}}).encode()

        class FakeResponse:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self, number):
                return raw

        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.urlopen", return_value=FakeResponse()) as urlopen:
            response = call_gateway("example_only_secret", "example/tool-model",
                [{"role": "user", "content": "Busca cliente"}], timeout=5, max_tokens=200,
                tools=SaleAIReadTools(self.session).definitions())
        self.assertEqual(response["content"], "")
        self.assertEqual(response["tool_calls"][0]["function"]["name"], "search_customers")
        sent = json.loads(urlopen.call_args[0][0].data.decode())
        self.assertEqual(sent["tool_choice"], "auto")
        self.assertTrue(sent["tools"])
