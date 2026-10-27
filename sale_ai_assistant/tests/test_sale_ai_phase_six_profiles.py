"""Regression: real product IDs, company rules, idempotency and safe drafting."""
from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestQuotationProfiles(TransactionCase):
    def setUp(self):
        super().setUp()
        manager = self.env.ref('sales_team.group_sale_manager')
        if manager not in self.env.user.groups_id:
            self.env.user.write({'groups_id': [(4, manager.id)]})
        self.ie = self.env['product.product'].create({
            'name': 'Instalación eléctrica pruebas IA', 'default_code': 'IA_IE_TEST',
            'sale_ok': True, 'list_price': 0})
        self.global_line = self.env['product.product'].create({
            'name': 'Texto libre materiales pruebas IA', 'default_code': 'IA_GLOBAL_TEST',
            'sale_ok': True, 'list_price': 0})
        self.rule = self.env['sale.ai.quotation.profile'].create({
            'name': 'Instalaciones eléctricas pruebas', 'code': 'electrical_test',
            'company_id': self.env.company.id,
            'priority': 110, 'keywords': 'instalacion electrica de prueba\nlinea de alimentacion motores',
            'main_product_id': self.ie.id, 'global_product_id': self.global_line.id,
            'global_line_label': 'TOTAL',
        })
        self.session = self.env['sale.ai.session'].create({'name': 'Instalacion electrica de prueba'})
        self.draft = self.session.draft_id
        self.Line = self.env['sale.ai.draft.line']

    def _materials(self):
        self.Line.create({'draft_id': self.draft.id, 'line_kind': 'line_note',
                          'name': 'Cable 2,5 mm², tubo 25 mm, tres cajas estancas', 'sequence': 10})
        for sequence, name, quantity, price in ((20, 'Instaladores', 12, 40),
                                                (30, 'Cable', 250, .6),
                                                (40, 'Tubo', 50, .5),
                                                (50, 'Bridas', 1, 15),
                                                (60, 'Cajas', 3, 5)):
            self.Line.create({'draft_id': self.draft.id, 'line_kind': 'product',
                              'name': name, 'product_uom_qty': quantity,
                              'price_unit': price, 'sequence': sequence})

    def test_company_profile_and_composition(self):
        self._materials()
        self.assertAlmostEqual(self.draft.amount_untaxed_estimate, 685)
        selected = self.env['sale.ai.quotation.profile']._select_for_text(
            'Preparar la linea de alimentacion motores', self.env.company)
        self.assertEqual(selected, self.rule)
        result = self.session._ai_compose_profile(self.rule)
        self.assertTrue(result['applied'])
        lines = self.draft.line_ids.sorted(key=lambda l: (l.sequence, l.id))
        self.assertEqual(lines.mapped('commercial_role'), ['main', 'technical', 'global'])
        self.assertEqual(lines.mapped('line_kind'), ['product', 'line_note', 'product'])
        self.assertEqual(lines[0].product_id, self.ie)
        self.assertEqual(lines[1].name, 'Cable 2,5 mm², tubo 25 mm, tres cajas estancas')
        self.assertEqual(lines[2].product_id, self.global_line)
        self.assertAlmostEqual(lines[2].price_unit, 685)
        self.assertAlmostEqual(self.draft.amount_untaxed_estimate, 685)
        self.assertIn('Instaladores', self.draft.estimate_details)
        unchanged = self.session._ai_compose_profile(self.rule)
        self.assertFalse(unchanged['applied'])
        self.assertEqual(len(self.draft.line_ids), 3)
        self.assertAlmostEqual(self.draft.amount_untaxed_estimate, 685)

    def test_explicit_global_amount_and_add_note(self):
        self._materials()
        self.session._ai_compose_profile(self.rule, target_total=1290)
        self.assertAlmostEqual(self.draft.amount_untaxed_estimate, 1290)
        self.Line.create({'draft_id': self.draft.id, 'line_kind': 'line_note',
                          'name': 'Protecciones trifásicas pendientes de dimensionar'})
        self.session._ai_compose_profile(self.rule)
        notes = self.draft.line_ids.filtered(lambda l: l.line_kind == 'line_note')
        self.assertEqual(len(notes), 1)
        self.assertIn('Protecciones', notes.name)
        self.assertIn('Cable 2,5', notes.name)
        self.assertAlmostEqual(self.draft.amount_untaxed_estimate, 1290)
        self.assertEqual(len(self.draft.line_ids), 3)

    def test_missing_catalog_product_does_not_destroy_lines(self):
        self._materials()
        before = [(l.id, l.name, l.price_unit) for l in self.draft.line_ids]
        self.rule.global_product_id = False
        self.rule.global_product_code = 'NONEXISTING_GLOBAL_PRODUCT_TEST'
        with self.assertRaises(UserError):
            self.session._ai_compose_profile(self.rule)
        self.assertEqual(before, [(l.id, l.name, l.price_unit) for l in self.draft.line_ids])
        self.assertEqual(self.draft.amount_untaxed_estimate, 685)

    def test_undo_restores_original_detailed_lines(self):
        from odoo.addons.sale_ai_assistant.models.sale_ai_draft_tools import SaleAIDraftTools
        self._materials()
        self.session._ai_compose_profile(self.rule)
        tools = SaleAIDraftTools(self.session)
        result = tools.undo_last_draft_change()
        self.assertTrue(result['undone'])
        self.assertEqual(len(self.draft.line_ids), 6)
        self.assertFalse(self.draft.quotation_profile_id)
        self.assertAlmostEqual(self.draft.amount_untaxed_estimate, 685)
