"""Phase 4: provisional-only mutations and OWL preview contract."""
import json
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..models.sale_ai_draft_tools import SaleAIDraftTools


@tagged("post_install", "-at_install")
class TestSaleAIPhaseFour(TransactionCase):
    def setUp(self):
        super().setUp()
        manager = self.env.ref("sales_team.group_sale_manager")
        if manager not in self.env.user.groups_id:
            self.env.user.write({"groups_id": [(4, manager.id)]})
        self.company = self.env.company
        self.model = self.env.ref("sale_ai_assistant.sale_ai_model_gpt_mini")
        self.model.write({"supports_tools": True})
        self.company.sudo().write({"sale_ai_model_id": self.model.id})
        self.env["ir.config_parameter"].sudo().set_param(
            "sale_ai_assistant.vercel_key.%d" % self.company.id, "not_a_real_key")
        self.session = self.env["sale.ai.session"].create({"name": "Fase 4"})
        self.tools = SaleAIDraftTools(self.session)
        self.partner = self.env["res.partner"].create({"name": "CLIENTE DEMO FASE4"})
        self.product = self.env["product.product"].create({
            "name": "Material eléctrico prueba IA", "sale_ok": True, "list_price": 12.5})

    def _tool(self, name, **data):
        return self.tools.execute(name, json.dumps(data, ensure_ascii=False))

    def test_draft_header_and_multiline_lines_preview(self):
        header = self._tool("set_draft_header", customer_id=self.partner.id,
                            description="Línea de ventilación",
                            assumptions="Verificar la intensidad de placa")
        self.assertIn("customer_id", header["updated"])
        result = self._tool("add_draft_lines", lines=[
            {"kind": "line_section", "name": "Instalación"},
            {"kind": "line_note", "name": "Cable 2,5 mm²\n3 cajas estancas"},
            {"kind": "product", "name": "TOTAL", "quantity": 1, "allow_unlinked": True,
             "price_unit": 1100, "price_source": "estimate"},
        ])
        self.assertEqual(len(result["created"]), 3)
        preview = self.env["sale.ai.session"].assistant_panel_preview(self.session.id)
        self.assertEqual(preview["partner"], self.partner.display_name)
        self.assertEqual(preview["amount_untaxed"], 1100)
        self.assertEqual([x["kind"] for x in preview["lines"]],
                         ["line_section", "line_note", "product"])
        self.assertIn("\n", preview["lines"][1]["name"])
        self.assertFalse(self.session.sale_order_id)
        self.assertFalse(self.env["sale.order"].search([("name", "=", "Línea de ventilación")]))

    def test_update_remove_undo_without_duplicate(self):
        result = self._tool("add_draft_lines", lines=[
            {"kind": "product", "name": "Partida general", "quantity": 1, "price_unit": 1100, "allow_unlinked": True},
        ])
        line_id = result["created"][0]["id"]
        response = self._tool("update_draft_line", line_id=line_id, price_unit=1290,
                              price_source="user")
        self.assertEqual(response["amount_untaxed_estimate"], 1290)
        self.assertEqual(len(self.session.draft_id.line_ids), 1)
        self.assertTrue(self._tool("undo_last_draft_change")["undone"])
        self.assertEqual(self.session.draft_id.amount_untaxed_estimate, 1100)
        self.assertEqual(len(self.session.draft_id.line_ids), 1)
        # The Iteration B journal retains earlier steps; more than one undo is possible.
        self.assertEqual(len(self.session.draft_id.change_ids), 1)
        current_id = self.session.draft_id.line_ids.id
        self.assertEqual(self._tool("remove_draft_line", line_id=current_id)["removed_id"], current_id)
        self.assertEqual(len(self.session.draft_id.line_ids), 0)

    def test_input_limits_and_atomic_batch(self):
        self.assertIn("error", self._tool("add_draft_lines", lines=[
            {"kind": "line_note", "name": "Notas", "price_unit": 30},
        ]))
        self.assertIn("error", self._tool("add_draft_lines", lines=[
            {"kind": "product", "name": "Partida", "price_unit": 1},
            {"kind": "product", "name": "Inválida", "quantity": -4},
        ]))
        self.assertFalse(self.session.draft_id.line_ids)
        self.assertIn("error", self._tool("add_draft_lines", lines=[
            {"kind": "product", "name": "X", "price_source": "external"},
        ]))
        self.assertIn("error", self._tool("set_draft_header", customer_id=99999999))
        self.assertIn("error", self._tool("add_draft_lines", lines=[
            {"kind": "product", "name": "No real", "product_id": 99999999},
        ]))
        self.assertFalse(self.session.draft_id.line_ids)

    def test_odoo_price_checked_on_server_and_companies(self):
        self._tool("search_products", query="Material eléctrico prueba IA")
        result = self._tool("add_draft_lines", lines=[
            {"kind": "product", "name": "Material", "product_id": self.product.id,
             "price_source": "odoo"},
        ])
        self.assertNotIn("error", result)
        self.assertEqual(self.session.draft_id.line_ids.price_unit, 12.5)
        self.assertEqual(self.session.draft_id.line_ids.price_source, "odoo")
        self.assertIn("error", self._tool("update_draft_line",
            line_id=self.session.draft_id.line_ids.id, price_source="odoo", price_unit=5))
        another = self.env["res.company"].sudo().create({"name": "Otra compañía IA 4"})
        alien = self.env["product.product"].sudo().with_company(another).create({
            "name": "Sólo segunda compañía", "company_id": another.id,
            "sale_ok": True, "list_price": 22})
        self.assertIn("error", self._tool("add_draft_lines", lines=[
            {"kind": "product", "name": "Ajeno", "product_id": alien.id},
        ]))

    def test_undo_does_not_clobber_manual_edit(self):
        self._tool("set_draft_header", description="Primero")
        self.session.draft_id.write({"description": "Edición manual"})
        undo = self._tool("undo_last_draft_change")
        self.assertIn("error", undo)
        self.assertEqual(self.session.draft_id.description, "Edición manual")

    def test_provider_writes_draft_and_web_preview_updates(self):
        responses = []
        def provider(key, model_id, messages, timeout, max_tokens, **kwargs):
            responses.append(kwargs)
            if len(responses) == 1:
                self.assertIn("tools", kwargs)
                return {"content": "", "tool_calls": [{"id": "x1", "type": "function", "function": {
                    "name": "add_draft_lines", "arguments": json.dumps({"lines": [
                        {"kind": "product", "name": "Partida provisional", "price_unit": 300, "allow_unlinked": True},
                    ]})}}], "input_tokens": 20, "output_tokens": 20,
                    "reported_cost_usd": 0.0, "latency_ms": 10}
            return {"content": "He añadido una partida provisional que debes revisar.",
                    "tool_calls": [], "input_tokens": 40, "output_tokens": 50,
                    "reported_cost_usd": 0.0, "latency_ms": 10}
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway", side_effect=provider):
            result = self.env["sale.ai.session"].assistant_panel_send(self.session.id, "Crea partida 300")
        self.assertIn("assistant_message", result)
        self.assertEqual(result["draft"]["amount_untaxed"], 300)
        self.assertEqual(len(result["draft"]["lines"]), 1)
        self.assertFalse(self.session.sale_order_id)

    def test_provider_failure_after_write_must_not_offer_retry(self):
        count = [0]
        def provider(key, model_id, messages, timeout, max_tokens, **kwargs):
            count[0] += 1
            if count[0] == 1:
                return {"content": "", "tool_calls": [{"id": "x1", "type": "function", "function": {
                    "name": "add_draft_lines", "arguments": json.dumps({"lines": [
                        {"kind": "product", "name": "Partida provisional", "price_unit": 300, "allow_unlinked": True},
                    ]})}}], "input_tokens": 20, "output_tokens": 20,
                    "reported_cost_usd": 0.0, "latency_ms": 10}
            from ..models.sale_ai_gateway import GatewayError
            raise GatewayError("error simulado")
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway", side_effect=provider):
            result = self.env["sale.ai.session"].assistant_panel_send(self.session.id, "Crear una partida")
        self.assertIn("assistant_message", result)
        self.assertNotIn("error", result)
        self.assertIn("revisa", result["assistant_message"]["content"].lower())
        self.assertEqual(len(self.session.draft_id.line_ids), 1)

    def test_agent_does_not_force_an_unrequested_second_mutation_call(self):
        calls = []
        def provider(key, model_id, messages, timeout, max_tokens, **kwargs):
            calls.append(kwargs)
            return {"content": "Puedo preparar esa partida si quieres.", "tool_calls": [],
                    "input_tokens": 30, "output_tokens": 25,
                    "reported_cost_usd": 0, "latency_ms": 10}
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway", side_effect=provider):
            result = self.env["sale.ai.session"].assistant_panel_send(
                self.session.id, "Plantéame un presupuesto orientativo de 900 euros")
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.session.draft_id.amount_untaxed_estimate, 0)
        self.assertIn("Puedo preparar", result["assistant_message"]["content"])
        self.assertIn("no se modificó", result["assistant_message"]["content"])

    def test_agent_executes_multiple_edits_and_keeps_its_explanation(self):
        result = self._tool("add_draft_lines", lines=[
            {"kind": "line_note", "name": "Cableado inicial."}])
        note_id = result["created"][0]["id"]
        calls = []
        def provider(key, model_id, messages, timeout, max_tokens, **kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return {"content": "", "tool_calls": [{"id": "append1", "type": "function",
                    "function": {"name": "append_draft_line_text", "arguments": json.dumps({
                        "line_id": note_id, "text": "Protecciones para motores."})}}],
                    "input_tokens": 25, "output_tokens": 30,
                    "reported_cost_usd": 0, "latency_ms": 10}
            if len(calls) == 2:
                return {"content": "", "tool_calls": [{"id": "add2", "type": "function",
                    "function": {"name": "add_draft_lines", "arguments": json.dumps({"lines": [
                        {"kind": "product", "name": "Importe fijado", "quantity": 1, "allow_unlinked": True,
                         "price_unit": 1290, "price_source": "user"}]})}}],
                    "input_tokens": 20, "output_tokens": 30,
                    "reported_cost_usd": 0, "latency_ms": 10}
            return {"content": "He ampliado la nota y registrado el precio acordado.",
                    "tool_calls": [], "input_tokens": 30, "output_tokens": 30,
                    "reported_cost_usd": 0, "latency_ms": 10}
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway", side_effect=provider):
            reply = self.env["sale.ai.session"].assistant_panel_send(
                self.session.id, "Amplía la nota y añade la partida de 1290 EUR")
        self.assertEqual(len(calls), 3)
        self.assertEqual(reply["draft"]["amount_untaxed"], 1290)
        self.assertIn("Protecciones para motores", self.session.draft_id.line_ids.filtered(
            lambda line: line.line_kind == "line_note").name)
        self.assertIn("He ampliado", reply["assistant_message"]["content"])
        self.assertIn("Comprobado en Odoo", reply["assistant_message"]["content"])

    def test_agent_does_not_claim_unexecuted_changes_as_verified(self):
        calls = []
        def provider(key, model_id, messages, timeout, max_tokens, **kwargs):
            calls.append(kwargs)
            return {"content": "Voy a fijar el importe.", "tool_calls": [],
                    "input_tokens": 5, "output_tokens": 5,
                    "reported_cost_usd": 0, "latency_ms": 10}
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway", side_effect=provider):
            result = self.env["sale.ai.session"].assistant_panel_send(
                self.session.id, "Cambia el importe global a 1290 euros")
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.session.draft_id.amount_untaxed_estimate, 0)
        self.assertIn("no se modificó", result["assistant_message"]["content"])

    def test_append_text_preserves_note_and_is_idempotent(self):
        result = self._tool("add_draft_lines", lines=[
            {"kind": "line_note", "name": "Texto de la instalación inicial."},
        ])
        note_id = result["created"][0]["id"]
        self.assertTrue(self._tool("append_draft_line_text", line_id=note_id,
                                   text="Añadir protección para los motores.").get("appended"))
        self.assertIn("unchanged_id", self._tool(
            "append_draft_line_text", line_id=note_id,
            text="Añadir protección para los motores."))
        note = self.session.draft_id.line_ids
        self.assertEqual(note.name.count("Añadir protección"), 1)
        self.assertTrue(note.name.startswith("Texto de la instalación inicial."))

    def test_fingerprint_detects_existing_note_edit_for_safe_retry(self):
        result = self._tool("add_draft_lines", lines=[
            {"kind": "line_note", "name": "Nota original"},
        ])
        before = self.session._ai_draft_fingerprint()
        self._tool("append_draft_line_text", line_id=result["created"][0]["id"],
                   text="Protecciones nuevas")
        self.assertNotEqual(before, self.session._ai_draft_fingerprint())

    def test_market_price_request_declares_no_web_before_estimation(self):
        """The verified ORM summary must not swallow the web-search disclaimer."""
        calls = [0]

        def provider(key, model_id, messages, timeout, max_tokens, **kwargs):
            calls[0] += 1
            if calls[0] == 1:
                self.assertIn("NO tienes herramienta de búsqueda web", messages[0]["content"])
                return {"content": "", "tool_calls": [{"id": "market1", "type": "function", "function": {
                    "name": "add_draft_lines", "arguments": json.dumps({"lines": [
                        {"kind": "product", "name": "Estimación materiales y mano de obra", "allow_unlinked": True,
                         "quantity": 1, "price_unit": 950, "price_source": "estimate"},
                    ]})}}], "input_tokens": 40, "output_tokens": 50,
                        "reported_cost_usd": 0.0, "latency_ms": 10}
            return {"content": "Estimación orientativa, revisar materiales.", "tool_calls": [],
                    "input_tokens": 40, "output_tokens": 50,
                    "reported_cost_usd": 0.0, "latency_ms": 10}

        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway", side_effect=provider):
            result = self.env["sale.ai.session"].assistant_panel_send(
                self.session.id,
                "Plantéame un presupuesto con los precios medios de venta del mercado español")
        answer = result["assistant_message"]["content"]
        self.assertIn("No dispongo de búsqueda web", answer)
        self.assertIn("Cambios guardados", answer)
        self.assertEqual(result["draft"]["amount_untaxed"], 950)

    def test_gateway_503_is_not_misdiagnosed_as_no_web(self):
        from urllib.error import HTTPError
        from ..models import sale_ai_gateway
        with patch.object(sale_ai_gateway, "urlopen", side_effect=HTTPError(
                "https://ai-gateway.vercel.sh/v1/chat/completions", 503,
                "Service Unavailable", {}, None)):
            with self.assertRaises(sale_ai_gateway.GatewayError) as caught:
                sale_ai_gateway.call_gateway("fake-token", "google/gemini-2.5-flash", [
                    {"role": "user", "content": "Hola"}], timeout=5)
        self.assertIn("503", str(caught.exception))
        self.assertIn("no una prueba", str(caught.exception))

    def test_gateway_503_market_question_reports_both_issues(self):
        from ..models.sale_ai_gateway import GatewayError
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway",
                   side_effect=GatewayError("El servicio de IA no está disponible (HTTP 503).")):
            result = self.env["sale.ai.session"].assistant_panel_send(
                self.session.id,
                "Plantéame un presupuesto con precios del mercado español")
        self.assertIn("error", result)
        self.assertIn("HTTP 503", result["error"])
        self.assertIn("No dispongo de búsqueda web", result["error"])
        self.assertEqual(self.session.message_ids.filtered(lambda m: m.role == "user").mapped("content"),
                         ["Plantéame un presupuesto con precios del mercado español"])
