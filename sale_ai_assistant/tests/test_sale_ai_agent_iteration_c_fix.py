"""Regression for technical descriptions, estimates and unauthorized free lines."""
import json
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from ..models import sale_ai_turn_policy as policy


def tool(name, args, identifier):
    return {
        'content': None, 'finish_reason': 'tool_calls',
        'input_tokens': 12, 'output_tokens': 20,
        'reported_cost_usd': 0, 'latency_ms': 1,
        'tool_calls': [{'id': identifier, 'type': 'function', 'function': {
            'name': name, 'arguments': json.dumps(args, ensure_ascii=False),
        }}],
    }


def text(content):
    return {'content': content, 'finish_reason': 'stop',
            'input_tokens': 8, 'output_tokens': 10,
            'reported_cost_usd': 0, 'latency_ms': 1, 'tool_calls': []}


@tagged('post_install', '-at_install')
class TestIterationCGuardedTurns(TransactionCase):
    def setUp(self):
        super().setUp()
        group = self.env.ref('sales_team.group_sale_manager')
        if group not in self.env.user.groups_id:
            self.env.user.write({'groups_id': [(4, group.id)]})
        self.session = self.env['sale.ai.session'].create({'name': 'Nota técnica / valoración'})
        self.draft = self.session.draft_id
        self.model = self.env.ref('sale_ai_assistant.sale_ai_model_gpt_mini')
        self.model.write({'active': True, 'supports_tools': True})
        self.session.model_id = self.model.id
        self.env.company.sudo().write({'sale_ai_model_id': self.model.id})

    def send(self, user_message, fake_responses):
        turns = iter(fake_responses)
        with patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.get_gateway_key',
                   return_value='fake-key'), \
             patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway',
                   side_effect=lambda *args, **kwargs: next(turns)):
            return self.env['sale.ai.session'].assistant_panel_send(self.session.id, user_message)

    def test_technical_description_proposes_before_writing(self):
        desc = ('Suministro e instalación de línea eléctrica para tres motores de ventilación. '
                'Cable 2,5 mm², 250 m; tubo Ø25 mm, 50 m; tres cajas estancas. '
                'Comprobar la capacidad de la canalización existente.')
        answer = self.send('Necesito texto descriptivo técnico para presupuesto de la línea de motores.', [
            tool('plan_turn', {'goal': 'Redactar y guardar nota técnica',
                               'write_scope': 'technical_note',
                               'required_tools': ['get_current_draft', 'add_draft_lines'],
                               'direct_answer': ''}, 'plan'),
            text(desc), text('Sin observaciones'),
        ])
        self.assertFalse(self.draft.line_ids)
        self.session.assistant_panel_proposal_action(
            self.session.id, answer['proposal']['token'], 'accept')
        self.assertEqual(len(self.draft.line_ids), 1)
        self.assertEqual(self.draft.line_ids.line_kind, 'line_note')
        self.assertEqual(self.draft.line_ids.name, desc)
        self.assertEqual(self.draft.amount_untaxed_estimate, 0)
        self.assertIn('Propuesta pendiente', answer['assistant_message']['content'])

    def test_valuation_cannot_write_even_if_model_sends_wrong_tool(self):
        note = self.env['sale.ai.draft.line'].create({
            'draft_id': self.draft.id, 'line_kind': 'line_note',
            'name': 'Motores con cable 2,5 mm²',
        })
        reply = self.send('Valora de forma orientativa las protecciones del subcuadro.', [
            tool('plan_turn', {'goal': 'Valoración orientativa sin líneas',
                               'write_scope': 'read_only',
                               'required_tools': ['calculate_cost_breakdown'],
                               'direct_answer': ''}, 'plan'),
            # Deliberately returned even though not in the offered tool list:
            tool('add_draft_lines', {'lines': [{
                'kind': 'product', 'name': 'Subcuadro nuevo', 'price_unit': 65,
                'quantity': 1, 'allow_unlinked': True,
            }]}, 'unauthorized'),
            tool('calculate_cost_breakdown', {'materials': [{
                'name': 'Guardamotores orientativos', 'quantity': 3,
                'unit_price': 50, 'unit': 'ud', 'source': 'estimate',
            }], 'workers': 2, 'hours_per_worker': 6, 'hourly_rate': 40}, 'calc'),
            text('Como orientación, tres guardamotores a 50 € y 480 € de mano de obra. '
                 'El dimensionamiento requiere intensidades nominales.'),
        ])
        self.assertEqual(self.draft.line_ids, note)
        self.assertEqual(self.draft.amount_untaxed_estimate, 0)
        self.assertIn('orientación', reply['assistant_message']['content'])

    def test_confirmed_technical_scope_updates_note_only(self):
        note = self.env['sale.ai.draft.line'].create({
            'draft_id': self.draft.id, 'line_kind': 'line_note',
            'name': 'Tres motores con cable de 2,5 mm².',
        })
        text_updated = (note.name + ' Los motores son trifásicos y se consideran protecciones '
                        'en el subcuadro existente; calibres pendientes de validar.')
        self.send('Faltan protecciones para tres motores trifásicos en el subcuadro.', [
            tool('plan_turn', {'goal': 'Actualizar la nota técnica',
                               'write_scope': 'technical_note',
                               'required_tools': ['get_current_draft', 'update_draft_line'],
                               'direct_answer': ''}, 'plan'),
            text(text_updated), text('Sin observaciones'),
        ])
        self.assertEqual(self.draft.line_ids, note)
        self.assertNotEqual(note.name, text_updated)
        self.session.assistant_panel_proposal_action(
            self.session.id, self.session.technical_proposal['token'], 'accept')
        self.assertEqual(note.name, text_updated)
        self.assertEqual(self.draft.amount_untaxed_estimate, 0)

    def test_free_item_requires_explicit_request_even_in_full_draft_scope(self):
        self.assertIsNotNone(policy.validate_write('full_draft', 'add_draft_lines',
            {'lines': [{'kind': 'product', 'name': 'Protecciones',
                        'allow_unlinked': True, 'price_unit': 285}]},
            self.draft, 'Las protecciones irán instaladas en el subcuadro'))
        self.assertIsNone(policy.validate_write('commercial_lines', 'add_draft_lines',
            {'lines': [{'kind': 'product', 'name': 'Partida libre solicitada',
                        'allow_unlinked': True, 'price_unit': 285}]},
            self.draft, 'Añade una partida libre de 285 € sin referencia de catálogo'))
        self.assertIsNotNone(policy.validate_write('technical_note', 'add_draft_lines',
            {'lines': [{'kind': 'product', 'name': 'Guardamotor', 'price_unit': 55}]},
            self.draft, 'Necesito una descripción técnica'))
