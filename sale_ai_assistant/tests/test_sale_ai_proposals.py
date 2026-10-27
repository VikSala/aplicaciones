"""11.3: exact author text, explicit acceptance, stale/duplicate protection."""
import json
from unittest.mock import patch
from odoo.exceptions import UserError
from odoo.tests import tagged
from .test_sale_ai_multimodel import TestSaleAIMultimodel


@tagged('post_install', '-at_install')
class TestSaleAIProposals(TestSaleAIMultimodel):
    def generate(self, action='propose', truncated=False, target_id=0):
        self.env['sale.ai.message'].create({
            'session_id': self.session.id, 'role': 'user',
            'content': 'Añade una nota.' if action == 'save' else 'Necesito una descripción.',
        })
        plan = self._response(calls=[{'id': 'p', 'type': 'function', 'function': {
            'name': 'plan_turn', 'arguments': json.dumps({
                'goal': 'Redactar nota', 'required_tools': [], 'direct_answer': '',
                'write_scope': 'technical_note', 'response_role': 'description',
                'note_action': action, 'note_line_id': target_id,
            })}}])
        description = self._response('Texto exacto del redactor: 2,5 mm²; una mañana.')
        if truncated:
            description['finish_reason'] = 'length'
        with patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.get_gateway_key',
                   return_value='test'), patch(
                'odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway',
                side_effect=[plan, description]) as gateway:
            result = self.session._ai_generate_for()
        self.assertEqual(gateway.call_count, 2)
        self.assertEqual(gateway.call_args_list[1].args[1], self.glm.external_model_id)
        return result

    def test_proposal_exact_acceptance_and_duplicate(self):
        result = self.generate()
        self.assertNotIn('error', result)
        self.assertFalse(self.session.draft_id.line_ids)
        proposal = result['proposal']
        self.assertEqual(self.session._panel_details(self.session)['proposal'], proposal)
        self.session.assistant_panel_proposal_action(self.session.id, proposal['token'], 'accept')
        self.assertEqual(self.session.draft_id.line_ids.name, proposal['text'])
        with self.assertRaises(UserError):
            self.session.assistant_panel_proposal_action(self.session.id, proposal['token'], 'accept')

    def test_explicit_save_new_note(self):
        self.generate('save')
        self.assertEqual(len(self.session.draft_id.line_ids), 1)
        self.assertFalse(self.session.technical_proposal)

    def test_existing_note_requires_acceptance(self):
        note = self.env['sale.ai.draft.line'].create({
            'draft_id': self.session.draft_id.id, 'line_kind': 'line_note', 'name': 'Original',
        })
        self.generate('save', target_id=note.id)
        self.assertEqual(note.name, 'Original')
        self.assertEqual(self.session.technical_proposal['line_id'], note.id)

    def test_changed_draft_blocks_acceptance(self):
        proposal = self.generate()['proposal']
        self.session.draft_id.write({'description': 'Cambio posterior'})
        with self.assertRaises(UserError):
            self.session.assistant_panel_proposal_action(self.session.id, proposal['token'], 'accept')
        self.assertFalse(self.session.draft_id.line_ids)

    def test_discard_and_stale_revision(self):
        old = self.generate()['proposal']
        new = self.generate()['proposal']
        with self.assertRaises(UserError):
            self.session.assistant_panel_proposal_action(self.session.id, old['token'], 'accept')
        self.session.assistant_panel_proposal_action(self.session.id, new['token'], 'discard')
        self.assertFalse(self.session.technical_proposal)
        self.assertFalse(self.session.draft_id.line_ids)

    def test_truncated_text_not_stored(self):
        result = self.generate(truncated=True)
        self.assertIn('error', result)
        self.assertFalse(self.session.technical_proposal)
        self.assertFalse(self.session.draft_id.line_ids)

    def test_improve_keeps_edits_without_draft_write(self):
        proposal = self.generate()['proposal']
        with patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway') as gateway:
            result = self.session.assistant_panel_proposal_action(
                self.session.id, proposal['token'], 'improve', 'Texto corregido por mí.')
        gateway.assert_not_called()
        self.assertFalse(self.session.draft_id.line_ids)
        self.assertEqual(result['proposal']['text'], 'Texto corregido por mí.')
        self.assertNotEqual(result['proposal']['token'], proposal['token'])
        self.assertEqual(result['proposal']['fingerprint'], proposal['fingerprint'])
        self.assertTrue(result['proposal']['edited_by_user'])

    def test_manual_edit_and_accept(self):
        proposal = self.generate()['proposal']
        with patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway') as gateway:
            self.session.assistant_panel_proposal_action(
                self.session.id, proposal['token'], 'accept', 'Mi texto\nCon dos párrafos.')
        gateway.assert_not_called()
        self.assertEqual(self.session.draft_id.line_ids.name, 'Mi texto\nCon dos párrafos.')
        self.assertFalse(self.session.technical_proposal)

    def test_empty_manual_edit_rejected(self):
        proposal = self.generate()['proposal']
        with self.assertRaises(UserError):
            self.session.assistant_panel_proposal_action(
                self.session.id, proposal['token'], 'accept', '   ')
        self.assertFalse(self.session.draft_id.line_ids)
        self.assertEqual(self.session.technical_proposal['text'], proposal['text'])

    def test_removed_actions_rejected_without_ai(self):
        proposal = self.generate()['proposal']
        for action in ('save', 'review'):
            with patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway') as gateway:
                with self.assertRaises(UserError):
                    self.session.assistant_panel_proposal_action(
                        self.session.id, proposal['token'], action, 'No guardar')
            gateway.assert_not_called()
            self.assertEqual(self.session.technical_proposal, proposal)


    def test_product_id_cannot_block_new_description_without_notes(self):
        product_line = self.env['sale.ai.draft.line'].create({
            'draft_id': self.session.draft_id.id, 'line_kind': 'product',
            'name': 'Ref. CONTRADICTORIO', 'price_unit': 0, 'sequence': 10,
        })
        proposal = self.generate(target_id=product_line.id)['proposal']
        self.assertEqual(proposal['line_id'], 0)
        self.session.assistant_panel_proposal_action(self.session.id, proposal['token'], 'accept')
        lines = self.session.draft_id.line_ids.sorted(key=lambda l: (l.sequence, l.id))
        self.assertEqual(lines.mapped('line_kind'), ['product', 'line_note'])
        self.assertEqual(product_line.name, 'Ref. CONTRADICTORIO')
        self.assertEqual(product_line.price_unit, 0)

    def test_new_description_does_not_replace_existing_note(self):
        note = self.env['sale.ai.draft.line'].create({
            'draft_id': self.session.draft_id.id, 'line_kind': 'line_note',
            'name': 'Conservar', 'sequence': 10,
        })
        proposal = self.generate()['proposal']
        self.assertEqual(proposal['line_id'], 0)
        self.session.assistant_panel_proposal_action(self.session.id, proposal['token'], 'accept')
        self.assertEqual(note.name, 'Conservar')
        self.assertEqual(len(self.session.draft_id.line_ids), 2)
