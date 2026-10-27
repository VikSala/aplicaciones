"""Phase 5 — pricing calculations, consent, Tavily usage and isolation."""
import json
from unittest.mock import Mock, patch

from odoo.tests import TransactionCase, tagged

from ..models.sale_ai_market import SaleAICommercialTools


@tagged("post_install", "-at_install")
class TestPhaseFive(TransactionCase):
    def setUp(self):
        super().setUp()
        group = self.env.ref("sales_team.group_sale_manager")
        if group not in self.env.user.groups_id:
            self.env.user.write({"groups_id": [(4, group.id)]})
        self.company = self.env.company
        self.company.sudo().write({"sale_ai_allow_online_research": False})
        self.session = self.env["sale.ai.session"].create({"name": "Cálculo económico"})
        self.tools = SaleAICommercialTools(self.session)
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("sale_ai_assistant.market.api_key.%s" % self.company.id, "key_fake")
        params.set_param("sale_ai_assistant.market.per_session.%s" % self.company.id, "1")
        params.set_param("sale_ai_assistant.market.per_month.%s" % self.company.id, "10")

    def test_calculation_is_deterministic_and_does_not_write_sale_order(self):
        result = self.tools.execute("calculate_cost_breakdown", json.dumps({
            "materials": [
                {"name": "Cable", "quantity": 250, "unit_price": 0.48,
                 "unit": "m", "source": "estimate"},
                {"name": "Tubo", "quantity": 50, "unit_price": 0.85,
                 "unit": "m", "source": "estimate"},
            ], "workers": 2, "hours_per_worker": 6, "hourly_rate": 40,
        }))
        self.assertEqual(result["materials_subtotal_eur"], 162.5)
        self.assertEqual(result["labor_subtotal_eur"], 480)
        self.assertEqual(result["suggested_sales_base_eur"], 642.5)
        self.assertEqual(result["taxes"], "NOT_CALCULATED")
        self.assertFalse(self.session.sale_order_id)
        self.assertFalse(self.session.draft_id.line_ids)

    def test_rejects_invalid_numbers_and_unknown_sources(self):
        base = {"materials": [], "workers": 2, "hours_per_worker": 6, "hourly_rate": 40}
        for override in ({"workers": -1}, {"hourly_rate": float("nan")},
                         {"markup_percent": 210}):
            response = self.tools.execute("calculate_cost_breakdown", json.dumps({**base, **override}))
            self.assertIn("error", response)
        invalid = self.tools.execute("calculate_cost_breakdown", json.dumps({**base,
            "materials": [{"name": "Cable", "quantity": 1, "unit_price": 2,
                           "unit": "m", "source": "source_not_allowed"}]}))
        self.assertIn("error", invalid)

    def test_customer_pricelist_is_evaluated_in_odoo_not_written_by_model(self):
        partner = self.env["res.partner"].create({"name": "Cliente de prueba Fase 5"})
        product = self.env["product.product"].create({
            "name": "Cable especial Fase 5", "sale_ok": True, "list_price": 15.0})
        self.tools.execute("set_draft_header", json.dumps({"customer_id": partner.id}))
        result = self.tools.execute("get_customer_pricelist_price", json.dumps({
            "product_id": product.id, "quantity": 2}))
        self.assertEqual(result["source"], "odoo.product.pricelist")
        self.assertEqual(result["taxes"], "NOT_CALCULATED")
        self.assertIn("currency", result)
        creation = self.tools.execute("add_draft_lines", json.dumps({"lines": [{
            "kind": "product", "name": "Cable especial", "product_id": product.id,
            "quantity": 2, "price_source": "pricelist"}]}))
        self.assertNotIn("error", creation)
        line = self.session.draft_id.line_ids
        self.assertEqual(line.price_source, "pricelist")
        self.assertAlmostEqual(line.price_unit, result["unit_price"], places=2)
        self.assertIn("error", self.tools.execute("update_draft_line", json.dumps({
            "line_id": line.id, "price_source": "pricelist", "price_unit": 1})))
        self.assertFalse(self.session.sale_order_id)

    def test_search_opt_in_and_quota_and_sources(self):
        self.assertNotIn("search_market_prices", [t["function"]["name"]
                         for t in self.tools.definitions()])
        self.company.sudo().write({"sale_ai_allow_online_research": True})
        self.assertIn("search_market_prices", [t["function"]["name"]
                      for t in self.tools.definitions()])
        web_reply = Mock(status_code=200)
        web_reply.json.return_value = {"results": [
            {"title": "Precio catalogo de ejemplo", "url": "https://example.com/producto",
             "content": "Cable 2,5 mm precio indicativo 0,48 EUR/m"},
            {"title": "No cifrado", "url": "http://example.com/inseguro", "content": "x"},
        ]}
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_market.requests.post", return_value=web_reply) as request:
            data = self.tools.execute("search_market_prices", json.dumps({"query": "cable 2,5 mm precio"}))
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["source"], "tavily_web_search_snippets")
        self.assertEqual(request.call_args.kwargs["timeout"], 9)
        self.assertFalse(self.session.sale_order_id)
        self.assertEqual(self.env["sale.ai.market.usage"].search_count([
            ("session_id", "=", self.session.id)]), 1)
        # Another network request must never be made when the quota is exhausted.
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_market.requests.post") as request:
            second = self.tools.execute("search_market_prices", json.dumps({"query": "tubo 25 mm precio"}))
        self.assertIn("error", second)
        request.assert_not_called()

    def test_search_rejects_personal_data(self):
        self.company.sudo().write({"sale_ai_allow_online_research": True})
        for query in ("contacto jose@example.com precio", "http://proveedor.es precio"):
            self.assertIn("error", self.tools.execute("search_market_prices", json.dumps({"query": query})))

    def test_company_specific_credentials(self):
        other = self.env["res.company"].sudo().create({"name": "Compañía distinta fase 5"})
        self.assertFalse(self.env["ir.config_parameter"].sudo().get_param(
            "sale_ai_assistant.market.api_key.%s" % other.id))


@tagged("post_install", "-at_install")
class TestPhaseFiveSettings(TransactionCase):
    """Regresión del 0 recibido en nuevos campos del wizard en upgrades."""

    def setUp(self):
        super().setUp()
        manager = self.env.ref("sales_team.group_sale_manager")
        if manager not in self.env.user.groups_id:
            self.env.user.write({"groups_id": [(4, manager.id)]})
        self.settings_model = self.env["sale.ai.gateway.settings"]
        self.params = self.env["ir.config_parameter"].sudo()
        self.company = self.env.company

    def test_zero_values_do_not_block_save_and_use_safe_defaults(self):
        wizard = self.settings_model.create({
            "market_search_enabled": False,
            "market_queries_per_session": 0,
            "market_queries_per_month": 0,
            "market_results": 0,
            "market_timeout": 0,
        })
        wizard.action_apply()
        for field, expected in (("per_session", "4"), ("per_month", "60"),
                                ("results", "4"), ("timeout", "9")):
            self.assertEqual(self.params.get_param(
                "sale_ai_assistant.market.%s.%s" % (field, self.company.id)), expected)

    def test_default_get_recovers_legacy_zero_or_empty_params(self):
        self.params.set_param("sale_ai_assistant.market.per_session.%s" % self.company.id, "0")
        self.params.set_param("sale_ai_assistant.market.per_month.%s" % self.company.id, "")
        self.params.set_param("sale_ai_assistant.market.results.%s" % self.company.id, "99")
        self.params.set_param("sale_ai_assistant.market.timeout.%s" % self.company.id, "n/a")
        defaults = self.settings_model.default_get([
            "market_queries_per_session", "market_queries_per_month",
            "market_results", "market_timeout"])
        self.assertEqual(defaults["market_queries_per_session"], 4)
        self.assertEqual(defaults["market_queries_per_month"], 60)
        self.assertEqual(defaults["market_results"], 4)
        self.assertEqual(defaults["market_timeout"], 9)

    def test_real_out_of_range_values_are_still_rejected(self):
        from odoo.exceptions import ValidationError
        wizard = self.settings_model.create({"market_queries_per_session": 13})
        with self.assertRaisesRegex(ValidationError, "Consultas web por conversación"):
            wizard.action_apply()
