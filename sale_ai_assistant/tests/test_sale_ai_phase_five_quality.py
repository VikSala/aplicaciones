"""Regression tests for 18.0.0.6.2: valuation ≠ draft editing, market relevance.

Run with: odoo -d DB -u sale_ai_assistant --test-enable --stop-after-init
"""
import json
from unittest.mock import Mock, patch

from odoo.tests import TransactionCase, tagged

from ..models.sale_ai_engine import SaleAISessionEngine
from ..models.sale_ai_market import SaleAICommercialTools


@tagged("post_install", "-at_install")
class TestSaleAIPhaseFiveQuality(TransactionCase):
    def setUp(self):
        super().setUp()
        group = self.env.ref("sales_team.group_sale_manager")
        if group not in self.env.user.groups_id:
            self.env.user.write({"groups_id": [(4, group.id)]})
        self.company = self.env.company
        self.model = self.env.ref("sale_ai_assistant.sale_ai_model_gpt_mini")
        self.model.write({"supports_tools": True})
        self.company.sudo().write({"sale_ai_model_id": self.model.id,
                                  "sale_ai_allow_online_research": False})
        self.env["ir.config_parameter"].sudo().set_param(
            "sale_ai_assistant.vercel_key.%d" % self.company.id, "fake-key")
        self.session = self.env["sale.ai.session"].create({"name": "Ensayo Fase 5.2"})
        self.tools = SaleAICommercialTools(self.session)

    def test_intent_valuation_not_mutation(self):
        message = ("GRACIAS! Ahora, en base a 40€/h + iva por cada instalador "
                   "(6 horas cada uno) y a los precios medios de venta en el "
                   "mercado español de los materiales descritos, plantéame un presupuesto")
        self.assertTrue(SaleAISessionEngine._ai_valuation_only(message))
        self.assertFalse(SaleAISessionEngine._ai_change_request(
            message, self.session.draft_id)["required"])
        self.assertFalse(SaleAISessionEngine._ai_valuation_only(
            "Actualiza la vista previa con el presupuesto de 1.290 €"))
        self.assertFalse(SaleAISessionEngine._ai_valuation_only(
            "Añade esta valoración al borrador"))

    def test_valuation_never_changes_a_user_fixed_total(self):
        result = self.tools.execute("add_draft_lines", json.dumps({"lines": [{
            "kind": "product", "name": "Importe global fijado", "quantity": 1,
            "price_unit": 1290, "price_source": "user",
        }]}))
        self.assertNotIn("error", result)
        original_id = self.session.draft_id.line_ids.id
        turns = []

        def provider(key, model, messages, timeout, max_tokens, **kwargs):
            turns.append(kwargs)
            if len(turns) == 1:
                names = [item["function"]["name"] for item in kwargs["tools"]]
                self.assertIn("calculate_cost_breakdown", names)
                self.assertNotIn("add_draft_lines", names)
                self.assertNotIn("set_draft_header", names)
                return {"content": "", "tool_calls": [{"id": "calc1", "type": "function",
                    "function": {"name": "calculate_cost_breakdown", "arguments": json.dumps({
                        "materials": [], "workers": 2, "hours_per_worker": 6,
                        "hourly_rate": 40})}}],
                    "input_tokens": 60, "output_tokens": 30,
                    "latency_ms": 20, "reported_cost_usd": 0}
            return {"content": "Mano de obra estimada y materiales por contrastar.",
                    "tool_calls": [], "input_tokens": 50, "output_tokens": 50,
                    "latency_ms": 20, "reported_cost_usd": 0}

        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway",
                   side_effect=provider):
            res = self.env["sale.ai.session"].assistant_panel_send(
                self.session.id,
                "Plantea un presupuesto orientativo. 2 instaladores 6 horas a 40€/h, "
                "con precios de materiales estimados.")
        self.assertEqual(res["draft"]["amount_untaxed"], 1290)
        self.assertEqual(self.session.draft_id.line_ids.id, original_id)
        self.assertIn("480.00", res["assistant_message"]["content"])
        self.assertIn("no se ha modificado el borrador", res["assistant_message"]["content"])
        self.assertLessEqual(len(turns), 3)
        self.assertFalse(self.session.sale_order_id)

    def test_server_rejects_provider_write_in_valuation_mode(self):
        turns = []

        def provider(key, model, messages, timeout, max_tokens, **kwargs):
            turns.append(kwargs)
            if len(turns) == 1:
                return {"content": "", "tool_calls": [{"id": "write1", "type": "function",
                    "function": {"name": "add_draft_lines", "arguments": json.dumps({
                        "lines": [{"kind": "product", "name": "Falsa línea", "price_unit": 500}]
                    })}}],
                    "input_tokens": 5, "output_tokens": 5,
                    "latency_ms": 5, "reported_cost_usd": 0}
            return {"content": "Hay que revisar los precios.", "tool_calls": [],
                    "input_tokens": 5, "output_tokens": 5,
                    "latency_ms": 5, "reported_cost_usd": 0}

        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway",
                   side_effect=provider):
            result = self.env["sale.ai.session"].assistant_panel_send(
                self.session.id, "Plantéame una valoración de materiales")
        self.assertIn("assistant_message", result)
        self.assertFalse(self.session.draft_id.line_ids)

    def test_labor_fallback_uses_only_explicit_current_data(self):
        self.tools.execute("add_draft_lines", json.dumps({"lines": [{
            "kind": "line_note", "name": "Trabajos previstos: 2 personas media jornada",
        }]}))
        fallback = SaleAISessionEngine._ai_labor_from_explicit_data(
            "En base a 40€/h por instalador (6 horas cada uno), valora", self.session.draft_id)
        self.assertIn("480.00", fallback)
        self.assertFalse(SaleAISessionEngine._ai_labor_from_explicit_data(
            "¿Cuánto costaría una instalación?", self.session.draft_id))

    def test_market_avoids_generic_queries_and_dictionary_pages(self):
        self.company.sudo().write({"sale_ai_allow_online_research": True})
        self.env["ir.config_parameter"].sudo().set_param(
            "sale_ai_assistant.market.api_key.%s" % self.company.id, "fake-tavily")
        for query in ("precio", "precios medios en España", "cable 2,5 mm tubo 25 mm"):
            self.assertIn("error", self.tools.execute("search_market_prices",
                json.dumps({"query": query})))

        reply = Mock(status_code=200)
        reply.json.return_value = {"results": [
            {"title": "PRECIO - English translation",
             "url": "https://www.collinsdictionary.com/dictionary/spanish-english/precio",
             "content": "Translation of price to Spanish"},
            {"title": "Cable 1,5 mm² de cobre",
             "url": "https://ejemplo.es/cable-15mm", "content": "Cable 1,5 mm2 0,29 €/m"},
            {"title": "Cable de cobre H07Z1-K 2,5 mm²",
             "url": "https://ejemplo.es/cable-25mm", "content": "Cable 2,5 mm2 0,48 €/m"},
        ]}
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_market.requests.post",
                   return_value=reply) as request:
            result = self.tools.execute("search_market_prices",
                json.dumps({"query": "cable de cobre 2,5 mm2"}))
        self.assertEqual(len(result["results"]), 1)
        self.assertIn("25mm", result["results"][0]["url"])
        self.assertFalse(result["results"][0]["price_verified"])
        self.assertEqual(result["results"][0]["explicit_unit_price_text"], "0,48 €/m")
        self.assertIn("exclude_domains", request.call_args.kwargs["json"])
