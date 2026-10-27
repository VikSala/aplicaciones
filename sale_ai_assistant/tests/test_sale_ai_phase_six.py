"""Phase 6 regression tests: explicit confirmation, draft-only, atomic, audit."""
from odoo.exceptions import AccessError, UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSaleAIPhaseSix(TransactionCase):
    def setUp(self):
        super().setUp()
        group = self.env.ref('sales_team.group_sale_manager')
        if group not in self.env.user.groups_id:
            self.env.user.write({'groups_id': [(4, group.id)]})
        self.partner = self.env['res.partner'].create({'name': 'Cliente fase 6'})
        self.product = self.env['product.product'].create({
            'name': 'Material fase 6', 'list_price': 42.0, 'sale_ok': True,
        })
        self.session = self.env['sale.ai.session'].create({'name': 'Instalación fase 6'})
        self.draft = self.session.draft_id
        self.panel = self.env['sale.ai.session']

    def add_lines(self, without_product=False):
        Line = self.env['sale.ai.draft.line']
        Line.create({
            'draft_id': self.draft.id,
            'line_kind': 'line_section', 'name': 'Instalación', 'sequence': 10,
        })
        Line.create({
            'draft_id': self.draft.id,
            'line_kind': 'line_note', 'name': 'Detalle técnico\n3 cajas estancas', 'sequence': 20,
        })
        Line.create({
            'draft_id': self.draft.id,
            'line_kind': 'product', 'name': 'TOTAL', 'sequence': 30,
            'product_id': False if without_product else self.product.id,
            'product_uom_qty': 1, 'price_unit': 1290, 'price_source': 'user',
        })

    def ready(self, without_product=False):
        self.draft.write({
            'partner_id': self.partner.id,
            'description': 'Motores ventilación',
            'assumptions': 'Dimensionar protecciones',
        })
        self.add_lines(without_product=without_product)
        return self.panel.assistant_panel_quotation_preflight(self.session.id)

    def test_requires_customer_and_commercial_line(self):
        with self.assertRaisesRegex(UserError, 'cliente'):
            self.panel.assistant_panel_quotation_preflight(self.session.id)
        self.draft.write({'partner_id': self.partner.id})
        with self.assertRaisesRegex(UserError, 'partida'):
            self.panel.assistant_panel_quotation_preflight(self.session.id)
        self.assertFalse(self.session.sale_order_id)

    def test_create_requires_explicit_confirmation(self):
        review = self.ready()
        with self.assertRaises(UserError):
            self.panel.assistant_panel_create_quotation(self.session.id, review['signature'])
        with self.assertRaises(UserError):
            self.panel.assistant_panel_create_quotation(self.session.id, 'garbage', True)
        self.assertFalse(self.session.sale_order_id)

    def test_quote_creation_preserves_lines_and_closes_chat(self):
        review = self.ready()
        self.assertEqual(review['line_count'], 3)
        result = self.panel.assistant_panel_create_quotation(self.session.id, review['signature'], True)
        order = self.env['sale.order'].browse(result['sale_order_id'])
        self.assertEqual(order.state, 'draft')
        self.assertEqual(order.partner_id, self.partner)
        self.assertEqual(order.company_id, self.env.company)
        self.assertEqual(self.session.state, 'completed')
        self.assertEqual(self.session.sale_order_id, order)
        self.assertTrue(self.session.ended_at)
        self.assertTrue(self.draft.review_required)
        self.assertEqual(order.order_line.mapped('display_type'), ['line_section', 'line_note', False])
        self.assertEqual(order.order_line[1].name, 'Detalle técnico\n3 cajas estancas')
        self.assertEqual(order.order_line[2].price_unit, 1290)
        self.assertEqual(order.order_line[2].product_id, self.product)
        with self.assertRaises(UserError):
            self.panel.assistant_panel_create_quotation(self.session.id, review['signature'], True)
        with self.assertRaises(UserError):
            self.draft.write({'description': 'Reabrir y editar'})
        self.session.action_reopen()
        self.assertEqual(self.session.state, 'consultation')
        with self.assertRaises(UserError):
            self.env['sale.ai.message'].create({
                'session_id': self.session.id, 'role': 'user', 'content': 'Continuación no permitida',
            })
        with self.assertRaises(UserError):
            self.session.write({'name': 'Intento de modificar historial'})
        self.session.action_close()
        self.assertEqual(self.session.state, 'completed')
        history = self.panel.assistant_panel_bootstrap()['history']
        self.assertIn(self.session.id, [item['id'] for item in history])
        self.assertFalse(self.panel.assistant_panel_bootstrap()['active'])

    def test_stale_signature_prevents_creation(self):
        review = self.ready()
        self.draft.line_ids.filtered(lambda l: l.line_kind == 'product').write({'price_unit': 1000})
        with self.assertRaisesRegex(UserError, 'cambiado'):
            self.panel.assistant_panel_create_quotation(self.session.id, review['signature'], True)
        self.assertFalse(self.session.sale_order_id)

    def test_unlinked_line_kept_for_human_review(self):
        review = self.ready(without_product=True)
        self.assertTrue(any('sin producto' in text for text in review['warnings']))
        result = self.panel.assistant_panel_create_quotation(self.session.id, review['signature'], True)
        order = self.env['sale.order'].browse(result['sale_order_id'])
        price_line = order.order_line.filtered(lambda line: not line.display_type)
        self.assertFalse(price_line.product_id)
        self.assertEqual(price_line.price_unit, 1290)
        self.assertEqual(price_line.name, 'TOTAL')
        self.assertEqual(order.state, 'draft')

    def test_prevent_cross_owner_finalize(self):
        self.ready()
        # No sudo in panel. A distinct user must not see or finish this session.
        outsider = self.env['res.users'].with_context(no_reset_password=True).create({
            'name': 'Other quote user', 'login': 'other_quote_user_phase6',
            'groups_id': [(6, 0, [self.env.ref('sales_team.group_sale_manager').id])],
        })
        with self.assertRaises(AccessError):
            self.panel.with_user(outsider).assistant_panel_quotation_preflight(self.session.id)
        self.assertFalse(self.session.sale_order_id)
