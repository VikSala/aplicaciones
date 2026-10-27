from odoo.tests import TransactionCase, tagged
from odoo.exceptions import UserError, ValidationError


@tagged("post_install", "-at_install")
class TestSaleAIPhaseZero(TransactionCase):
    def test_creating_session_creates_separate_draft(self):
        session = self.env["sale.ai.session"].create({"name": "Prueba de instalación"})
        self.assertEqual(len(session.draft_ids), 1)
        self.assertFalse(session.sale_order_id)
        self.assertTrue(session.draft_id.review_required)
        second = self.env["sale.ai.session"].create({"name": "Otro presupuesto"})
        self.assertNotEqual(session.draft_id, second.draft_id)
        self.assertFalse(second.message_ids)

    def test_closed_session_blocks_edits(self):
        session = self.env["sale.ai.session"].create({"name": "Cierre"})
        draft = session.draft_id
        draft.write({"description": "Antes"})
        session.action_close()
        with self.assertRaises(UserError):
            draft.write({"description": "Después"})
        with self.assertRaises(UserError):
            self.env["sale.ai.message"].create({
                "session_id": session.id, "content": "Mensaje tardío",
            })
        session.action_reopen()
        draft.write({"description": "Reabierto"})
        self.assertEqual(draft.description, "Reabierto")

    def test_technical_note_no_price(self):
        session = self.env["sale.ai.session"].create({"name": "Notas"})
        line = self.env["sale.ai.draft.line"].create({
            "draft_id": session.draft_id.id,
            "line_kind": "line_note", "name": "Notas técnicas",
            "product_uom_qty": 5, "price_unit": 100,
        })
        self.assertEqual(line.amount_estimate, 0)
        self.assertEqual(line.product_uom_qty, 0)
        self.assertEqual(line.price_unit, 0)

    def test_no_duplicate_draft(self):
        session = self.env["sale.ai.session"].create({"name": "Único"})
        with self.assertRaises(ValidationError):
            self.env["sale.ai.draft"].create({
                "session_id": session.id,
                "currency_id": session.company_id.currency_id.id,
            })
