"""Explicit quoted literal text and LLM-based nonquoted notes/sections."""
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSaleAIChatCommands(TransactionCase):
    def setUp(self):
        super().setUp()
        group = self.env.ref("sales_team.group_sale_manager")
        if group not in self.env.user.groups_id:
            self.env.user.write({"groups_id": [(4, group.id)]})
        self.session = self.env["sale.ai.session"].create({"name": "Comandos"})
        self.panel = self.env["sale.ai.session"]
        self.part = self.env["product.product"].create({
            "name": "Texto libre material eléctrico y ferretería*", "default_code": "TLMEF_X",
            "sale_ok": True, "list_price": 18,
        })
        self.second = self.env["product.product"].create({
            "name": "Instalación eléctrica", "default_code": "IE_X",
            "sale_ok": True, "list_price": 40,
        })

    def send(self, content):
        return self.panel.assistant_panel_send(self.session.id, content)

    def _mock_gateway(self, output):
        model = self.env.ref("sale_ai_assistant.sale_ai_model_gpt_mini")
        self.session.write({"model_id": model.id})
        return patch(
            "odoo.addons.sale_ai_assistant.models.sale_ai_quick_commands.sale_ai_gateway.call_gateway",
            return_value={"content": output, "input_tokens": 110, "output_tokens": 25,
                          "latency_ms": 5, "reported_cost_usd": 0, "tool_calls": []},
        )

    def test_product_name_price_description_and_quantity_default(self):
        answer = self.send('Producto: nombre "material electrico" precio 1290 descripcion "TOTAL"')
        self.assertIn("añadido", answer["assistant_message"]["content"])
        line = self.session.draft_id.line_ids
        self.assertEqual(len(line), 1)
        self.assertEqual(line.product_id, self.part)
        self.assertEqual(line.name, "TOTAL")
        self.assertEqual(line.price_unit, 1290)
        self.assertEqual(line.product_uom_qty, 1)
        self.assertEqual(line.price_source, "user")
        self.assertEqual(answer["draft"]["amount_untaxed"], 1290)

    def test_literal_product_description_with_reserved_field_words(self):
        description = 'TOTAL: el nombre incluye sku, precio 1.290 y cantidad 2'
        answer = self.send('Producto: nombre "material electrico" precio 1.290 descripcion "%s"' % description)
        self.assertIn("añadido", answer["assistant_message"]["content"])
        line = self.session.draft_id.line_ids
        self.assertEqual(line.name, description)
        self.assertEqual(line.price_unit, 1290)

    def test_two_skus_one_message_and_catalog_price(self):
        result = self.send('Producto:\nsku TLMEF_X cantidad 2 precio 150,50 descripcion "TOTAL"\nsku IE_X')
        self.assertEqual(len(self.session.draft_id.line_ids), 2)
        lines = self.session.draft_id.line_ids.sorted(key=lambda line: (line.sequence, line.id))
        self.assertEqual(lines[0].price_unit, 150.5)
        self.assertEqual(lines[0].product_uom_qty, 2)
        self.assertEqual(lines[1].price_unit, 40)
        self.assertEqual(lines[1].price_source, "odoo")
        self.assertEqual(len(result["draft"]["lines"]), 2)

    def test_multiple_products_and_semicolon_within_description(self):
        self.send('Producto:\nsku IE_X descripcion "Material y mano de obra; revisar" precio 0;\n'
                  'sku TLMEF_X descripcion "TOTAL" precio 1290')
        lines = self.session.draft_id.line_ids.sorted(key=lambda line: (line.sequence, line.id))
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].name, "Material y mano de obra; revisar")
        self.assertEqual(lines[1].name, "TOTAL")

    def test_literal_note_section_and_undo_no_gateway(self):
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_quick_commands.sale_ai_gateway.call_gateway",
                   side_effect=AssertionError("Literal commands must never call an LLM")):
            self.send('Sección: "Mano de obra"')
            self.send('Nota: "Tendido de canalización existente\nVerificar en obra"')
        lines = self.session.draft_id.line_ids
        self.assertEqual([line.line_kind for line in lines], ["line_section", "line_note"])
        self.assertEqual(lines[1].name, "Tendido de canalización existente\nVerificar en obra")
        reply = self.send("Deshacer: último cambio")
        self.assertIn("deshecho", reply["assistant_message"]["content"])
        self.assertEqual(len(self.session.draft_id.line_ids), 1)
        self.assertEqual(self.session.draft_id.line_ids.line_kind, "line_section")

    def test_curly_quotes_and_escaped_quotes_are_literal(self):
        self.send('Nota: «Incluye protección y "cableado" de motores»')
        self.assertEqual(self.session.draft_id.line_ids.name, 'Incluye protección y "cableado" de motores')

    def test_no_implicit_product_if_ambiguous(self):
        self.env["product.product"].create({
            "name": "Material eléctrico segunda variante", "default_code": "TLMEF_2", "sale_ok": True,
        })
        reply = self.send('Producto: nombre "material electrico" precio 1290')
        self.assertIn("SKU exacto", reply["assistant_message"]["content"])
        self.assertFalse(self.session.draft_id.line_ids)

    def test_cannot_add_lines_if_one_entry_has_no_product(self):
        reply = self.send("Producto:\nsku IE_X\nsku SKU_INEXISTENTE")
        self.assertIn("No he modificado", reply["assistant_message"]["content"])
        self.assertFalse(self.session.draft_id.line_ids)

    def test_unquoted_product_name_rejected_without_guessing(self):
        result = self.send("Producto: nombre material electrico precio 1290")
        self.assertIn("entre comillas", result["assistant_message"]["content"])
        self.assertFalse(self.session.draft_id.line_ids)

    def test_unclosed_quoted_note_does_not_write(self):
        result = self.send('Nota: "Una nota sin cerrar')
        self.assertIn("comillas", result["assistant_message"]["content"])
        self.assertFalse(self.session.draft_id.line_ids)

    def test_unquoted_note_always_calls_ai_even_without_magic_words(self):
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_quick_commands.sale_ai_gateway.get_gateway_key",
                   return_value="test"), self._mock_gateway("Suministro e instalación eléctrica revisada.") as gateway:
            self.send("Nota: Comprobar las condiciones de la canalización")
        self.assertTrue(gateway.called)
        self.assertEqual(self.session.draft_id.line_ids.line_kind, "line_note")
        self.assertEqual(self.session.draft_id.line_ids.name, "Suministro e instalación eléctrica revisada.")

    def test_unquoted_section_uses_ai_and_writes_title(self):
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_quick_commands.sale_ai_gateway.get_gateway_key",
                   return_value="test"), self._mock_gateway("Materiales eléctricos") as gateway:
            self.send("Sección: título breve para los materiales de la instalación")
        self.assertTrue(gateway.called)
        self.assertEqual(self.session.draft_id.line_ids.line_kind, "line_section")
        self.assertEqual(self.session.draft_id.line_ids.name, "Materiales eléctricos")

    def test_nonliteral_note_respects_exact_configured_output_budget(self):
        model = self.env.ref("sale_ai_assistant.sale_ai_model_gpt_mini")
        self.session.write({"model_id": model.id})
        self.env.company.write({"sale_ai_max_output_tokens": 900})

        def fake_gateway(*args, **kwargs):
            self.assertEqual(kwargs["max_tokens"], 900)
            return {"content": "Instalación de tres motores de ventilación.\n"
                               "Incluye comprobación de conductores y protecciones.",
                    "input_tokens": 412, "output_tokens": 1080,
                    "finish_reason": "stop", "latency_ms": 2,
                    "reported_cost_usd": 0, "tool_calls": []}

        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_quick_commands.sale_ai_gateway.get_gateway_key",
                   return_value="test"), patch(
                   "odoo.addons.sale_ai_assistant.models.sale_ai_quick_commands.sale_ai_gateway.call_gateway",
                   side_effect=fake_gateway):
            answer = self.send("Nota: Redacta una descripción de los tres motores")
        self.assertIn("Nota añadida", answer["assistant_message"]["content"])
        self.assertIn("protecciones.", self.session.draft_id.line_ids.name)

    def test_truncated_note_is_never_saved(self):
        model = self.env.ref("sale_ai_assistant.sale_ai_model_gpt_mini")
        self.session.write({"model_id": model.id})
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_quick_commands.sale_ai_gateway.get_gateway_key",
                   return_value="test"), patch(
                   "odoo.addons.sale_ai_assistant.models.sale_ai_quick_commands.sale_ai_gateway.call_gateway",
                   return_value={"content": "Suministro e instalación de ventil",
                                 "input_tokens": 412, "output_tokens": 2398,
                                 "finish_reason": "length", "latency_ms": 2,
                                 "reported_cost_usd": 0, "tool_calls": []}):
            reply = self.send("Nota: Redacta una memoria técnica de la instalación")
        self.assertIn("incompleto", reply["assistant_message"]["content"])
        self.assertFalse(self.session.draft_id.line_ids)

    def test_truncated_note_fallback_without_finish_reason(self):
        model = self.env.ref("sale_ai_assistant.sale_ai_model_gpt_mini")
        self.session.write({"model_id": model.id})
        self.env.company.write({"sale_ai_max_output_tokens": 900})
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_quick_commands.sale_ai_gateway.get_gateway_key",
                   return_value="test"), patch(
                   "odoo.addons.sale_ai_assistant.models.sale_ai_quick_commands.sale_ai_gateway.call_gateway",
                   return_value={"content": "Texto insuficiente",
                                 "input_tokens": 400, "output_tokens": 2396,
                                 "latency_ms": 2, "reported_cost_usd": 0,
                                 "tool_calls": []}):
            reply = self.send("Nota: Redacta una memoria técnica de la instalación")
        self.assertIn("incompleto", reply["assistant_message"]["content"])
        self.assertFalse(self.session.draft_id.line_ids)

    def test_product_does_not_create_real_sale_order(self):
        before = self.env["sale.order"].search_count([])
        self.send("Producto: sku TLMEF_X precio 1290")
        self.assertEqual(self.env["sale.order"].search_count([]), before)

    def test_natural_customer_assignment_is_saved_in_preview_without_llm(self):
        customer = self.env["res.partner"].create({"name": "Segalca Rehabilitacion y Construccion EJEMPLO"})
        with patch("odoo.addons.sale_ai_assistant.models.sale_ai_quick_commands.sale_ai_gateway.call_gateway",
                   side_effect=AssertionError("Cliente no debe depender de la IA")):
            reply = self.send("cliente Segalca Rehabilitacion y Construccion EJEMPLO")
        self.assertEqual(self.session.draft_id.partner_id, customer)
        self.assertEqual(reply["draft"]["partner"], customer.display_name)
        self.assertIn("asignado", reply["assistant_message"]["content"])
        refreshed = self.panel.assistant_panel_preview(self.session.id)
        self.assertEqual(refreshed["partner"], customer.display_name)

    def test_short_customer_and_explicit_quoted_command(self):
        customer = self.env["res.partner"].create({"name": "Segalca Rehabilitacion PRUEBA VENTAS"})
        self.send("cliente Segalca Rehabilitacion PRUEBA VENTAS")
        self.assertEqual(self.session.draft_id.partner_id, customer)
        second = self.env["res.partner"].create({"name": "Cliente Unico Siguiente XYZ"})
        result = self.send('Cliente: "Cliente Unico Siguiente XYZ"')
        self.assertEqual(self.session.draft_id.partner_id, second)
        self.assertEqual(result["draft"]["partner"], second.display_name)

    def test_customer_ambiguity_never_changes_draft(self):
        self.env["res.partner"].create({"name": "Costa Ejemplo Alfa XYZ"})
        self.env["res.partner"].create({"name": "Costa Ejemplo Beta XYZ"})
        reply = self.send("cliente Costa Ejemplo")
        self.assertFalse(self.session.draft_id.partner_id)
        self.assertEqual(reply["draft"]["partner"], "")
        self.assertIn("varios clientes", reply["assistant_message"]["content"])

    def test_child_contact_lookup_chooses_unique_commercial_partner(self):
        root = self.env["res.partner"].create({"name": "Cliente del Grupo XXX Estructuras"})
        self.env["res.partner"].create({"name": "Cliente del Grupo XXX Logistica", "parent_id": root.id})
        reply = self.send("cliente Cliente del Grupo XXX")
        self.assertEqual(self.session.draft_id.partner_id, root)
        self.assertEqual(reply["draft"]["partner"], root.display_name)

    def test_customer_assignment_can_be_undone(self):
        customer = self.env["res.partner"].create({"name": "Cliente Deshacer IA XYZ"})
        self.send("cliente Cliente Deshacer IA XYZ")
        self.assertEqual(self.session.draft_id.partner_id, customer)
        self.send("Deshacer: último cambio")
        self.assertFalse(self.session.draft_id.partner_id)
        self.assertEqual(self.panel.assistant_panel_preview(self.session.id)["partner"], "")

    def test_regular_customer_discussion_not_intercepted(self):
        from odoo.addons.sale_ai_assistant.models.sale_ai_quick_commands import _CUSTOMER_SHORT
        self.assertFalse(_CUSTOMER_SHORT.match("¿Qué descuentos tiene este cliente?"))
        self.assertFalse(_CUSTOMER_SHORT.match("El cliente busca motores de ventilación"))
