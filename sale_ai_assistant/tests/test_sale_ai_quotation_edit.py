"""Integration checks to run in an Odoo 18 test database, never against production."""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSaleAIQuotationEditing(TransactionCase):
    def setUp(self):
        super().setUp()
        group = self.env.ref('sales_team.group_sale_manager')
        if group not in self.env.user.groups_id:
            self.env.user.write({'groups_id': [(4, group.id)]})
        self.partner = self.env['res.partner'].create({'name': 'Cliente edición IA'})
        self.product = self.env['product.product'].create({
            'name': 'LED test edición', 'list_price': 15, 'sale_ok': True,
        })
        self.order = self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom': self.product.uom_id.id,
                'name': 'LED original', 'product_uom_qty': 10,
                'price_unit': 12,
            })],
        })
        self.line = self.order.order_line[:1]
        self.panel = self.env['sale.ai.session']
        self.edit = self.panel.assistant_panel_load_quotation(self.order.id)
        self.session = self.panel.browse(self.edit['id'])
        self.draft_line = self.session.draft_id.line_ids[:1]

    def test_load_never_writes_real_quotation(self):
        self.assertEqual(self.order.state, 'draft')
        self.assertEqual(self.draft_line.source_sale_line_id, self.line.id)
        self.assertEqual(self.draft_line.product_uom_qty, 10)
        self.assertEqual(self.line.product_uom_qty, 10)
        self.assertEqual(self.edit['edit_order_id'], self.order.id)
        self.assertFalse(self.session.sale_order_id)

    def test_update_existing_line_in_place(self):
        self.draft_line.write({'product_uom_qty': 14})
        review = self.panel.assistant_panel_update_preflight(self.session.id)
        result = self.panel.assistant_panel_update_quotation(
            self.session.id, review['signature'], review['current_signature'], True,
        )
        self.assertEqual(result['sale_order_id'], self.order.id)
        self.assertEqual(self.line.product_uom_qty, 14)
        self.assertEqual(self.line.id, self.order.order_line[:1].id)
        self.assertEqual(self.session.state, 'active')
        self.assertEqual(self.session.draft_id.line_ids[:1].source_sale_line_id, self.line.id)

    def test_external_nonoverlapping_change_is_preserved(self):
        self.draft_line.write({'product_uom_qty': 17})
        self.line.write({'price_unit': 9})
        review = self.panel.assistant_panel_update_preflight(self.session.id)
        self.assertFalse(review['conflicts'])
        self.panel.assistant_panel_update_quotation(
            self.session.id, review['signature'], review['current_signature'], True,
        )
        self.assertEqual(self.line.product_uom_qty, 17)
        self.assertEqual(self.line.price_unit, 9)

    def test_conflict_requires_explicit_override(self):
        self.draft_line.write({'product_uom_qty': 13})
        self.line.write({'product_uom_qty': 11})
        review = self.panel.assistant_panel_update_preflight(self.session.id)
        self.assertTrue(review['conflicts'])
        with self.assertRaises(UserError):
            self.panel.assistant_panel_update_quotation(
                self.session.id, review['signature'], review['current_signature'], True,
            )
        self.assertEqual(self.line.product_uom_qty, 11)
        self.panel.assistant_panel_update_quotation(
            self.session.id, review['signature'], review['current_signature'], True, True,
        )
        self.assertEqual(self.line.product_uom_qty, 13)

    def test_preflight_expires_after_external_change(self):
        self.draft_line.write({'product_uom_qty': 20})
        review = self.panel.assistant_panel_update_preflight(self.session.id)
        self.line.write({'price_unit': 8})
        with self.assertRaisesRegex(UserError, 'cambiaron'):
            self.panel.assistant_panel_update_quotation(
                self.session.id, review['signature'], review['current_signature'], True,
            )
        self.assertEqual(self.line.product_uom_qty, 10)

    def test_cannot_update_sent_quotation(self):
        self.draft_line.write({'product_uom_qty': 17})
        self.order.write({'state': 'sent'})
        with self.assertRaisesRegex(UserError, 'en borrador'):
            self.panel.assistant_panel_update_preflight(self.session.id)
        self.assertEqual(self.line.product_uom_qty, 10)

    def test_archive_previous_chat_instead_of_deleting(self):
        self.env['sale.ai.message'].create({
            'session_id': self.session.id, 'role': 'user', 'content': 'Nota previa',
        })
        other_order = self.order.copy({'name': 'Otro PV'} )
        loaded = self.panel.assistant_panel_load_quotation(other_order.id, self.session.id, True)
        self.assertEqual(self.session.state, 'archived')
        self.assertEqual(self.session.message_ids[:1].content, 'Nota previa')
        self.assertNotEqual(loaded['id'], self.session.id)

    def test_loaded_pv_without_interaction_starts_new_chat_silently(self):
        self.assertFalse(self.edit['has_work'])
        self.assertFalse(self.panel._panel_session_has_work(self.session))
        old_id = self.session.id
        fresh = self.panel.assistant_panel_new(old_id)
        self.assertNotEqual(fresh['id'], old_id)
        self.assertFalse(self.session.exists(), 'Pristine loaded quotation must not enter the history')
        self.assertEqual(self.order.state, 'draft')

    def test_loaded_pv_without_interaction_can_load_another_without_archiving(self):
        another = self.order.copy({'name': 'Otro borrador para carga limpia'})
        old_id = self.session.id
        loaded = self.panel.assistant_panel_load_quotation(another.id, old_id)
        self.assertEqual(loaded['edit_order_id'], another.id)
        self.assertFalse(self.session.exists())
        self.assertFalse(loaded['has_work'])

    def test_discard_and_load_removes_only_current_conversation(self):
        previous_archive = self.panel.create({'name': 'Historial que no se toca'})
        previous_archive.action_close()
        self.env['sale.ai.message'].create({
            'session_id': self.session.id, 'role': 'user', 'content': 'Texto para descartar',
        })
        another = self.order.copy({'name': 'Destino de descarte'})
        with self.assertRaisesRegex(UserError, 'Archivar y cargar o Descartar'):
            self.panel.assistant_panel_load_quotation(another.id, self.session.id)
        loaded = self.panel.assistant_panel_load_quotation(another.id, self.session.id, False, True)
        self.assertFalse(self.session.exists())
        self.assertTrue(previous_archive.exists())
        self.assertEqual(previous_archive.state, 'archived')
        self.assertEqual(loaded['edit_order_id'], another.id)
        self.assertEqual(self.order.state, 'draft')

    def test_draft_changes_count_as_real_work(self):
        self.draft_line.write({'product_uom_qty': 22})
        self.assertTrue(self.panel._panel_session_has_work(self.session))
        fresh = self.panel.assistant_panel_new(self.session.id)
        self.assertTrue(fresh['id'])
        self.assertEqual(self.session.state, 'archived')

    def test_mutually_exclusive_replace_actions(self):
        with self.assertRaisesRegex(UserError, 'Selecciona archivar o descartar'):
            self.panel.assistant_panel_load_quotation(self.order.id, self.session.id, True, True)
