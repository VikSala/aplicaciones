"""Regression tests for failures during a multimodel turn."""
from unittest.mock import patch

from odoo.addons.sale_ai_assistant.models.sale_ai_engine import SaleAISessionEngine

from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSaleAIMultimodelRecovery(TransactionCase):

    def setUp(self):
        super().setUp()
        group = self.env.ref('sales_team.group_sale_manager')
        if group not in self.env.user.groups_id:
            self.env.user.write({'groups_id': [(4, group.id)]})
        self.session = self.env['sale.ai.session'].create({'name': 'Recovery'})

    def test_crashing_agent_does_not_lose_user_message(self):
        model_class = type(self.env['sale.ai.session'])
        with patch.object(model_class, '_ai_generate_for', side_effect=RuntimeError('simulated')):
            result = self.env['sale.ai.session'].assistant_panel_send(
                self.session.id, 'Necesito preparar una instalación eléctrica')
        self.assertIn('error', result)
        self.assertIn('conservado', result['error'])
        messages = self.env['sale.ai.message'].search([('session_id', '=', self.session.id)])
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages.role, 'user')
        self.assertEqual(messages.content, 'Necesito preparar una instalación eléctrica')

    def test_crashing_retry_does_not_duplicate_user_message(self):
        self.env['sale.ai.message'].create({
            'session_id': self.session.id, 'role': 'user', 'content': 'Prueba repetible'})
        model_class = type(self.env['sale.ai.session'])
        with patch.object(model_class, '_ai_generate_for', side_effect=RuntimeError('simulated')):
            result = self.env['sale.ai.session'].assistant_panel_retry(self.session.id)
        self.assertIn('error', result)
        messages = self.env['sale.ai.message'].search([('session_id', '=', self.session.id)])
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages.content, 'Prueba repetible')


    def test_translation_helper_not_shadowed_by_gateway_response(self):
        """A temporary result variable named `_` breaks all `_()` translations.

        This caused UnboundLocalError both after a successful tool write and
        while constructing the error notice on the exceptional path.
        """
        method = SaleAISessionEngine._ai_generate_for
        self.assertNotIn('_', method.__code__.co_varnames)
        self.assertNotIn('_', method.__code__.co_cellvars)

    def test_unexpected_provider_error_returns_recoverable_notice(self):
        """A crashing model must not cause another error while translating."""
        model = self.env['sale.ai.model'].create({
            'name': 'Provider failure test', 'external_model_id': 'test/failure',
            'supports_tools': True,
        })
        self.session.model_id = model
        self.env['sale.ai.message'].create({
            'session_id': self.session.id, 'role': 'user',
            'content': 'Redacta la descripción técnica.',
        })
        with patch(
            'odoo.addons.sale_ai_assistant.models.sale_ai_gateway.get_gateway_key',
            return_value='test-key',
        ), patch(
            'odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway',
            side_effect=ValueError('provider crash'),
        ):
            response = self.session._ai_generate_for()
        self.assertIn('error', response)
        self.assertIn('No se ha podido completar', response['error'])
