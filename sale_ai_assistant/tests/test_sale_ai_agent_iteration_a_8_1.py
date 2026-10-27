"""Regressions for Iteration A.1: explicit tool planning before synthesis."""
import json
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


def response(content="", calls=None, input_tokens=60, output_tokens=35):
    return {"content": content, "tool_calls": calls or [],
            "finish_reason": "tool_calls" if calls else "stop",
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "latency_ms": 5, "reported_cost_usd": 0.0}


def tool_call(name, arguments, identifier):
    return {"id": identifier, "type": "function", "function": {
        "name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}


@tagged("post_install", "-at_install")
class TestAgentPlanningA1(TransactionCase):
    def setUp(self):
        super().setUp()
        group = self.env.ref("sales_team.group_sale_manager")
        if group not in self.env.user.groups_id:
            self.env.user.write({"groups_id": [(4, group.id)]})
        self.company = self.env.company
        self.model = self.env.ref("sale_ai_assistant.sale_ai_model_gpt_mini")
        self.model.write({"supports_tools": True})
        self.company.sudo().write({
            "sale_ai_model_id": self.model.id,
            "sale_ai_max_output_tokens": 2000,
            "sale_ai_request_timeout": 45,
            "sale_ai_allow_online_research": True,
        })
        self.env["ir.config_parameter"].sudo().set_param(
            "sale_ai_assistant.vercel_key.%s" % self.company.id, "fake-key")
        self.env["ir.config_parameter"].sudo().set_param(
            "sale_ai_assistant.market.api_key.%s" % self.company.id, "fake-tavily")
        self.session = self.env["sale.ai.session"].create({"name": "Plan de herramientas"})

    def test_search_then_cost_then_final_without_draft_changes(self):
        planned = ["search_market_prices", "calculate_cost_breakdown"]
        replies = iter([
            response(calls=[tool_call("plan_turn", {
                "goal": "Buscar y valorar cable y mano de obra",
                "required_tools": planned, "direct_answer": "", "write_scope": "read_only",
            }, "plan_1")]),
            response(calls=[tool_call("search_market_prices", {
                "query": "cable cobre 2,5 mm2"
            }, "search_1")]),
            response(calls=[tool_call("calculate_cost_breakdown", {
                "materials": [{"name": "Cable", "quantity": 250, "unit_price": 0.6,
                               "unit": "m", "source": "estimate"}],
                "workers": 2, "hours_per_worker": 6, "hourly_rate": 40,
            }, "calc_1")]),
            response("Mano de obra: 480 EUR; materiales: 150 EUR; "
                     "base de referencia: 630 EUR sin IVA. "
                     "Propuesta comercial orientativa: 700 EUR."),
        ])
        choices = []

        def provider(key, model, messages, timeout, max_tokens, **kwargs):
            self.assertEqual(max_tokens, 2000)  # UI is the sole output limit.
            choices.append(kwargs.get("tool_choice", "none"))
            return next(replies)

        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway",
                   side_effect=provider), patch(
                   "odoo.addons.sale_ai_assistant.models.sale_ai_market.SaleAICommercialTools.search_market_prices",
                   return_value={"results": [], "no_relevant_results": True}):
            reply = self.env["sale.ai.session"].assistant_panel_send(
                self.session.id,
                "Presupuesta 250 m de cable 2,5 mm2, dos instaladores 6 horas a 40 EUR/h. "
                "Busca referencias de mercado y valora.")
        self.assertEqual(choices, ["required", "required", "required", "auto"])
        content = reply["assistant_message"]["content"]
        self.assertIn("Propuesta comercial", content)
        self.assertIn("search_market_prices (1)", content)
        self.assertIn("calculate_cost_breakdown (1)", content)
        self.assertFalse(self.session.draft_id.line_ids)
        self.assertEqual(reply["assistant_message"]["input_tokens"], 240)

    def test_premature_text_does_not_claim_research_done(self):
        turns = iter([
            response(calls=[tool_call("plan_turn", {
                "goal": "Calcular mano de obra", "required_tools": ["calculate_cost_breakdown"],
                "direct_answer": "", "write_scope": "read_only",
            }, "plan_2")]),
            response("Voy a calcular el presupuesto."),  # provider ignored required
        ])
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway",
                   side_effect=lambda *a, **kw: next(turns)):
            reply = self.env["sale.ai.session"].assistant_panel_send(
                self.session.id, "Calcula 2 operarios x 6 horas x 40 euros.")
        self.assertIn("sin ejecutar las herramientas necesarias",
                      reply["assistant_message"]["content"])
        self.assertFalse(self.session.draft_id.line_ids)

    def test_direct_answer_is_allowed_without_tools(self):
        calls = []
        def provider(key, model, messages, timeout, max_tokens, **kwargs):
            calls.append(kwargs.get("tool_choice"))
            return response(calls=[tool_call("plan_turn", {
                "goal": "Explicar el concepto de borrador de presupuesto",
                "required_tools": [],
                "direct_answer": "El borrador no es una venta confirmada.", "write_scope": "read_only",
            }, "plan_3")])
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway",
                   side_effect=provider):
            reply = self.env["sale.ai.session"].assistant_panel_send(
                self.session.id, "¿Qué diferencia hay entre presupuesto y pedido confirmado?")
        self.assertEqual(calls, ["required"])
        self.assertIn("no es una venta confirmada", reply["assistant_message"]["content"])
