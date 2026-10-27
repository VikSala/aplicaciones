"""Iteración B: products must be real and undo journal must be persistent."""
import json
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..models.sale_ai_draft_tools import SaleAIDraftTools


@tagged("post_install", "-at_install")
class TestAgentIterationB(TransactionCase):
    def setUp(self):
        super().setUp()
        manager = self.env.ref("sales_team.group_sale_manager")
        if manager not in self.env.user.groups_id:
            self.env.user.write({"groups_id": [(4, manager.id)]})
        self.session = self.env["sale.ai.session"].create({"name": "Iteración B test"})
        self.tools = SaleAIDraftTools(self.session)
        self.product = self.env["product.product"].create({
            "name": "TEST B COMPONENTE ELECTRICO INCONFUNDIBLE", "default_code": "BTEST-UNICO-9",
            "sale_ok": True, "list_price": 23.5,
        })
        self.customer = self.env["res.partner"].create({"name": "CLIENTE ITERACION B"})

    def execute(self, name, **data):
        return self.tools.execute(name, json.dumps(data, ensure_ascii=False))

    def test_unlinked_not_accepted_as_silent_product_fallback(self):
        attempt = self.execute("add_draft_lines", lines=[{
            "kind": "product", "name": "PRODUCTO INVENTADO", "quantity": 1,
            "price_unit": 250,
        }])
        self.assertIn("error", attempt)
        self.assertFalse(self.session.draft_id.line_ids)
        allowed = self.execute("add_draft_lines", lines=[{
            "kind": "product", "name": "Partida LIBRE pedida expresamente",
            "price_unit": 100, "allow_unlinked": True,
        }])
        self.assertNotIn("error", allowed)
        self.assertFalse(self.session.draft_id.line_ids.product_id)

    def test_real_product_requires_successful_lookup_in_same_turn(self):
        attempt = self.execute("add_draft_lines", lines=[{
            "kind": "product", "name": "Cable", "product_id": self.product.id,
            "price_source": "odoo",
        }])
        self.assertIn("Busca primero", attempt["error"])
        results = self.execute("search_products", query="BTEST-UNICO-9")
        self.assertTrue(any(p["id"] == self.product.id for p in results["results"]))
        added = self.execute("add_draft_lines", lines=[{
            "kind": "product", "name": "Cable", "product_id": self.product.id,
            "price_source": "odoo",
        }])
        self.assertNotIn("error", added)
        line = self.session.draft_id.line_ids
        self.assertEqual(line.product_id, self.product)
        self.assertEqual(line.price_unit, 23.5)
        # New tool object == next turn; previous results are not transferable.
        next_turn = SaleAIDraftTools(self.session)
        another = next_turn.execute("add_draft_lines", json.dumps({"lines": [{
            "kind": "product", "name": "Otro", "product_id": self.product.id,
        }]}))
        self.assertIn("error", another)
        self.assertEqual(len(self.session.draft_id.line_ids), 1)

    def test_persisted_multilevel_undo_across_tool_instances(self):
        self.execute("add_draft_lines", lines=[{"kind": "line_section", "name": "Obra"}])
        self.execute("add_draft_lines", lines=[{"kind": "line_note", "name": "Nota técnica"}])
        self.execute("set_draft_header", customer_id=self.customer.id)
        self.assertEqual(len(self.session.draft_id.change_ids), 3)
        self.assertEqual(len(self.session.draft_id.line_ids), 2)
        # Simulates closing / reopening the OWL panel and creating new tool objects.
        first = SaleAIDraftTools(self.session).undo_last_draft_change()
        self.assertEqual(first["remaining_changes"], 2)
        self.assertFalse(self.session.draft_id.partner_id)
        second = SaleAIDraftTools(self.session).undo_last_draft_change()
        self.assertEqual(second["remaining_changes"], 1)
        self.assertEqual(self.session.draft_id.line_ids.mapped("line_kind"), ["line_section"])
        third = SaleAIDraftTools(self.session).undo_last_draft_change()
        self.assertEqual(third["remaining_changes"], 0)
        self.assertFalse(self.session.draft_id.line_ids)
        exhausted = self.execute("undo_last_draft_change")
        self.assertIn("error", exhausted)
        self.assertFalse(self.env["sale.order"].search([("name", "=", "Iteración B test")]))

    def test_undo_rebase_after_restoring_deleted_product(self):
        self.execute("search_products", query="BTEST-UNICO-9")
        line = self.execute("add_draft_lines", lines=[{
            "kind": "product", "name": "Artículo", "product_id": self.product.id,
            "price_unit": 50, "price_source": "user",
        }])
        line_id = line["created"][0]["id"]
        self.execute("remove_draft_line", line_id=line_id)
        self.execute("add_draft_lines", lines=[{"kind": "line_note", "name": "Comprobar"}])
        self.assertEqual(len(self.session.draft_id.change_ids), 3)
        self.tools.undo_last_draft_change()  # remove note
        self.tools.undo_last_draft_change()  # restore product with possibly new id
        self.assertEqual(self.session.draft_id.line_ids.product_id, self.product)
        self.tools.undo_last_draft_change()  # undo the original add
        self.assertFalse(self.session.draft_id.line_ids)

    def test_manual_edit_blocks_unsafe_undo(self):
        self.execute("set_draft_header", description="Antes")
        self.session.draft_id.write({"description": "Modificación fuera del historial"})
        rejected = SaleAIDraftTools(self.session).execute("undo_last_draft_change", "{}")
        self.assertIn("error", rejected)
        self.assertEqual(self.session.draft_id.description, "Modificación fuera del historial")
        self.assertEqual(len(self.session.draft_id.change_ids), 1)

    def test_agent_chains_lookup_then_real_product_add(self):
        """Gemini's plan is advisory; Odoo validates the persisted product."""
        model = self.env.ref("sale_ai_assistant.sale_ai_model_gpt_mini")
        model.write({"supports_tools": True})
        self.company = self.env.company
        self.company.sudo().write({
            "sale_ai_model_id": model.id, "sale_ai_max_output_tokens": 2000,
            "sale_ai_request_timeout": 45,
        })
        self.session.write({"model_id": model.id})
        self.env["ir.config_parameter"].sudo().set_param(
            "sale_ai_assistant.vercel_key.%s" % self.company.id, "fake-test-token")

        def response(content="", name=None, args=None, identifier=None):
            calls = []
            if name:
                calls = [{"type": "function", "id": identifier, "function": {
                    "name": name, "arguments": json.dumps(args)}}]
            return {
                "content": content, "tool_calls": calls,
                "input_tokens": 35, "output_tokens": 18,
                "latency_ms": 3, "reported_cost_usd": 0.0,
                "finish_reason": "tool_calls" if name else "stop",
            }

        turns = iter([
            response(name="plan_turn", identifier="bplan", args={
                "goal": "Añadir producto real desde Odoo",
                "required_tools": ["search_products", "add_draft_lines"],
                "direct_answer": "", "write_scope": "commercial_lines",
            }),
            response(name="search_products", identifier="bsearch", args={"query": "BTEST-UNICO-9"}),
            response(name="add_draft_lines", identifier="badd", args={"lines": [{
                "kind": "product", "name": "Material desde catálogo",
                "product_id": self.product.id, "quantity": 1,
                "price_source": "odoo",
            }]}),
            response(content="He añadido el artículo BTEST-UNICO-9 al borrador."),
        ])
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway",
                   side_effect=lambda *a, **kw: next(turns)):
            result = self.env["sale.ai.session"].assistant_panel_send(
                self.session.id, "Añade el producto con SKU BTEST-UNICO-9")
        self.assertEqual(self.session.draft_id.line_ids.product_id, self.product)
        self.assertNotIn("Herramientas ejecutadas", result["assistant_message"]["content"])
        self.assertEqual(result["assistant_message"]["content"].count("Comprobado en Odoo"), 1)

    def test_ambiguous_search_does_not_authorize_arbitrary_product(self):
        other = self.env["product.product"].create({
            "name": "TEST B COMPONENTE ELECTRICO INCONFUNDIBLE alternativa",
            "default_code": "BTEST-ALTERNATIVA-5", "sale_ok": True,
        })
        results = self.execute("search_products", query="TEST B COMPONENTE ELECTRICO")
        self.assertTrue(results["requires_clarification"])
        self.assertIn(self.product.id, [r["id"] for r in results["results"]])
        attempt = self.execute("add_draft_lines", lines=[{
            "kind": "product", "name": "Selección arbitraria", "product_id": other.id,
        }])
        self.assertIn("error", attempt)
        self.assertFalse(self.session.draft_id.line_ids)
