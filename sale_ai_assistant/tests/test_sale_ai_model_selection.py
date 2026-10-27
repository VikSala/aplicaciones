"""Regression tests for phase-3 model switching and per-company defaults."""
from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSaleAIModelSelection(TransactionCase):
    def setUp(self):
        super().setUp()
        manager = self.env.ref("sales_team.group_sale_manager")
        if manager not in self.env.user.groups_id:
            self.env.user.write({"groups_id": [(4, manager.id)]})
        self.company = self.env.company
        self.a = self.env.ref("sale_ai_assistant.sale_ai_model_gpt_mini")
        self.b = self.env.ref("sale_ai_assistant.sale_ai_model_beam_free")
        self.a.write({"active": True, "provider": "vercel_gateway"})
        self.b.write({"active": True, "provider": "vercel_gateway"})
        self.company.sudo().write({"sale_ai_model_id": self.a.id})

    def test_one_company_default_using_existing_fk(self):
        self.assertTrue(self.a.is_default)
        self.assertFalse(self.b.is_default)
        self.b.write({"is_default": True})
        self.assertEqual(self.company.sale_ai_model_id, self.b)
        self.a.invalidate_recordset(["is_default"])
        self.b.invalidate_recordset(["is_default"])
        self.assertFalse(self.a.is_default)
        self.assertTrue(self.b.is_default)
        wizard = self.env["sale.ai.gateway.settings"].create({})
        self.assertEqual(wizard.model_id, self.b)

    def test_current_company_default_is_independent(self):
        other = self.env["res.company"].sudo().create({"name": "Otra compañía modelos IA"})
        other.sudo().write({"sale_ai_model_id": self.a.id})
        self.b.write({"is_default": True})
        self.assertEqual(self.company.sale_ai_model_id, self.b)
        self.assertEqual(other.sale_ai_model_id, self.a)
        self.assertTrue(self.a.sudo().with_company(other).is_default)
        self.assertFalse(self.b.sudo().with_company(other).is_default)

    def test_switching_chat_does_not_change_company_default(self):
        session = self.env["sale.ai.session"].create({"name": "Comprobación de selector"})
        self.assertEqual(session.model_id, self.a)
        self.b.write({"is_default": True})
        # Existing sessions keep their own model even when default changes.
        self.assertEqual(session.model_id, self.a)
        new_session = self.env["sale.ai.session"].create({"name": "Nueva sesión"})
        self.assertEqual(new_session.model_id, self.b)
        result = self.env["sale.ai.session"].assistant_panel_select_model(new_session.id, self.a.id)
        self.assertEqual(result["model_id"], self.a.id)
        self.assertEqual(new_session.model_id, self.a)
        self.assertEqual(self.company.sale_ai_model_id, self.b)
        self.assertFalse(new_session.sale_order_id)
        self.assertFalse(new_session.draft_id.line_ids)

    def test_reject_invalid_or_closed_chat_switch(self):
        session = self.env["sale.ai.session"].create({"name": "Sesión cerrada"})
        with self.assertRaises(ValidationError):
            self.env["sale.ai.session"].assistant_panel_select_model(session.id, 0)
        with self.assertRaises(ValidationError):
            self.env["sale.ai.session"].assistant_panel_select_model(session.id, 9999999)
        session.action_close()
        with self.assertRaises(UserError):
            self.env["sale.ai.session"].assistant_panel_select_model(session.id, self.b.id)
