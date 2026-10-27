"""Iteración C: proactive technical advice and independent preflight review."""
import json
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSaleAIIterationC(TransactionCase):
    def setUp(self):
        super().setUp()
        group = self.env.ref('sales_team.group_sale_manager')
        if group not in self.env.user.groups_id:
            self.env.user.write({'groups_id': [(4, group.id)]})
        self.session = self.env['sale.ai.session'].create({'name': 'Test Iteración C'})
        self.model = self.env.ref('sale_ai_assistant.sale_ai_model_gpt_mini')
        self.model.write({'supports_tools': True, 'active': True})
        self.session.write({'model_id': self.model.id})
        self.partner = self.env['res.partner'].create({'name': 'Cliente iteración C'})
        self.product = self.env['product.product'].create({
            'name': 'Material iteración C', 'sale_ok': True, 'list_price': 100,
        })
        self.draft = self.session.draft_id
        self.draft.write({
            'partner_id': self.partner.id,
            'description': 'Línea motores ventilación',
            'assumptions': 'Dimensionamiento de protecciones pendiente',
        })
        self.env['sale.ai.draft.line'].create({
            'draft_id': self.draft.id,
            'line_kind': 'line_note', 'name': 'Instalación de tres motores con cable 2,5 mm².',
            'sequence': 10,
        })
        self.env['sale.ai.draft.line'].create({
            'draft_id': self.draft.id,
            'line_kind': 'product', 'name': 'Partida global',
            'product_id': self.product.id, 'product_uom_qty': 1,
            'price_unit': 1100, 'price_source': 'user', 'sequence': 20,
        })
        self.env['sale.ai.message'].create({
            'session_id': self.session.id, 'role': 'user',
            'content': 'Los motores son trifásicos y falta añadir las protecciones al subcuadro.',
        })
        self.env['sale.ai.message'].create({
            'session_id': self.session.id, 'role': 'assistant',
            'content': 'Conviene revisar la descripción y los calibres de las protecciones.',
        })

    def _tool_response(self, findings):
        return {'content': '', 'finish_reason': 'tool_calls',
                'input_tokens': 100, 'output_tokens': 75,
                'latency_ms': 10, 'reported_cost_usd': 0,
                'tool_calls': [{'id': 'c-review', 'type': 'function', 'function': {
                    'name': 'submit_draft_review',
                    'arguments': json.dumps({'findings': findings}, ensure_ascii=False),
                }}]}

    def test_review_reports_confirmed_technical_omission_without_editing(self):
        saved_note = self.draft.line_ids.filtered(lambda x: x.line_kind == 'line_note').name
        saved_price = self.draft.amount_untaxed_estimate
        finding = {'category': 'omision_confirmada',
                   'issue': 'La nota no incorpora que los motores serán trifásicos.',
                   'evidence': 'Usuario: los motores son trifásicos'}
        with patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.get_gateway_key', return_value='test-token'), \
                patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway',
                      return_value=self._tool_response([finding])) as mocked:
            review = self.env['sale.ai.session'].assistant_panel_quotation_preflight(self.session.id)
        self.assertEqual(mocked.call_count, 1)
        self.assertEqual(mocked.call_args.kwargs['tool_choice'], 'required')
        self.assertIn('submit_draft_review', str(mocked.call_args.kwargs['tools']))
        self.assertTrue(any('trifásicos' in warning for warning in review['warnings']))
        self.assertEqual(self.draft.line_ids.filtered(lambda x: x.line_kind == 'line_note').name, saved_note)
        self.assertEqual(self.draft.amount_untaxed_estimate, saved_price)
        self.assertFalse(self.session.sale_order_id)

    def test_review_failure_does_not_block_creation_of_draft(self):
        from odoo.addons.sale_ai_assistant.models.sale_ai_gateway import GatewayError
        with patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.get_gateway_key', return_value='test-token'), \
                patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway',
                      side_effect=GatewayError('test failure')):
            review = self.env['sale.ai.session'].assistant_panel_quotation_preflight(self.session.id)
        self.assertTrue(any('revisión IA' in warning for warning in review['warnings']))
        with patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway',
                   side_effect=AssertionError('Creation must NEVER invoke AI')):
            result = self.env['sale.ai.session'].assistant_panel_create_quotation(
                self.session.id, review['signature'], True)
        order = self.env['sale.order'].browse(result['sale_order_id'])
        self.assertEqual(order.state, 'draft')
        self.assertEqual(order.order_line.filtered(lambda line: not line.display_type).price_unit, 1100)

    def test_review_does_not_fabricate_issues_when_none_found(self):
        with patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.get_gateway_key', return_value='test-token'), \
                patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway',
                      return_value=self._tool_response([])):
            review = self.env['sale.ai.session'].assistant_panel_quotation_preflight(self.session.id)
        self.assertTrue(any('no se detectaron discrepancias' in note for note in review['warnings']))

    def test_review_not_available_without_tool_capable_model(self):
        self.model.write({'supports_tools': False})
        with patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway',
                   side_effect=AssertionError('Should not call AI')):
            review = self.env['sale.ai.session'].assistant_panel_quotation_preflight(self.session.id)
        self.assertTrue(any('no disponible' in warning for warning in review['warnings']))

    def _agent_tool(self, name, args, identifier):
        return {'content': '', 'finish_reason': 'tool_calls',
                'input_tokens': 50, 'output_tokens': 40,
                'latency_ms': 10, 'reported_cost_usd': 0,
                'tool_calls': [{'id': identifier, 'type': 'function', 'function': {
                    'name': name, 'arguments': json.dumps(args, ensure_ascii=False),
                }}]}

    def _agent_text(self, content):
        return {'content': content, 'finish_reason': 'stop',
                'input_tokens': 50, 'output_tokens': 70,
                'latency_ms': 10, 'reported_cost_usd': 0, 'tool_calls': []}

    def test_confirmed_scope_can_update_existing_note_in_same_turn(self):
        note = self.draft.line_ids.filtered(lambda x: x.line_kind == 'line_note')
        updated = ('Instalación de tres motores TRIFÁSICOS, con cable 2,5 mm². '
                   'Se contemplan protecciones en el subcuadro, pendientes de dimensionar '
                   'según intensidades de placa y condiciones reales de la instalación.')
        calls = iter([
            self._agent_tool('plan_turn', {
                'goal': 'Actualizar la nota con las decisiones confirmadas',
                'required_tools': ['get_current_draft', 'update_draft_line'],
                'direct_answer': '', 'write_scope': 'technical_note',
            }, 'c-plan'),
            self._agent_tool('get_current_draft', {}, 'c-read'),
            self._agent_tool('update_draft_line', {'line_id': note.id, 'name': updated}, 'c-update'),
            self._agent_text('He actualizado la nota según las características confirmadas. '
                             'Falta dimensionar las protecciones con las placas de los motores.'),
        ])
        with patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.get_gateway_key', return_value='test-token'), \
                patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway',
                      side_effect=lambda *a, **kw: next(calls)):
            result = self.env['sale.ai.session'].assistant_panel_send(
                self.session.id, 'Confirmado: los motores son trifásicos y deben '
                                 'incluirse protecciones en el subcuadro. Actualiza la nota.')
        self.assertIn('actualizado', result['assistant_message']['content'])
        self.assertEqual(note.name, updated)
        self.assertEqual(len(self.draft.line_ids), 2)
        self.assertEqual(self.draft.amount_untaxed_estimate, 1100)
        self.assertEqual(len(self.draft.change_ids), 1)

    def test_informative_estimate_uses_calculator_but_does_not_edit_draft(self):
        before = [(line.id, line.name, line.price_unit) for line in self.draft.line_ids]
        calls = iter([
            self._agent_tool('plan_turn', {
                'goal': 'Valorar materiales y mano de obra sin cambiar el borrador',
                'required_tools': ['calculate_cost_breakdown'],
                'direct_answer': '', 'write_scope': 'read_only',
            }, 'c-plan'),
            self._agent_tool('calculate_cost_breakdown', {
                'materials': [{'name': 'Cable', 'quantity': 250, 'unit_price': 0.6,
                               'unit': 'm', 'source': 'estimate'}],
                'workers': 2, 'hours_per_worker': 6, 'hourly_rate': 40,
                'markup_percent': 10,
            }, 'c-calc'),
            self._agent_text('Mano de obra: 480 €. Cable estimado: 150 €. '
                             'Base de referencia: 630 €. Con un recargo orientativo del '
                             '10% serían 693 € sin impuestos; revise el alcance.'),
        ])
        with patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.get_gateway_key', return_value='test-token'), \
                patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway',
                      side_effect=lambda *a, **kw: next(calls)):
            result = self.env['sale.ai.session'].assistant_panel_send(
                self.session.id, 'Plantea una valoración orientativa, sin modificar el borrador.')
        self.assertIn('693 €', result['assistant_message']['content'])
        self.assertEqual(before, [(line.id, line.name, line.price_unit) for line in self.draft.line_ids])
        self.assertEqual(len(self.draft.change_ids), 0)
