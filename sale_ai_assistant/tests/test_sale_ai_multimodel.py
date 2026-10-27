"""Profiles use real configured model records and keep all writes in Odoo tools."""
import json
from unittest.mock import patch

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSaleAIMultimodel(TransactionCase):
    def setUp(self):
        super().setUp()
        group = self.env.ref('sales_team.group_sale_manager')
        if group not in self.env.user.groups_id:
            self.env.user.write({'groups_id': [(4, group.id)]})
        Model = self.env['sale.ai.model']
        self.glm = Model.create({
            'name': 'GLM test', 'external_model_id': 'test/glm', 'supports_tools': True,
        })
        self.deepseek = Model.create({
            'name': 'DeepSeek test', 'external_model_id': 'test/deepseek',
            'supports_tools': True, 'price_input_m_usd': 0.2,
            'price_output_m_usd': 0.5,
        })
        self.profile = Model.create({
            'name': 'Híbrido pruebas', 'model_type': 'profile',
            'description_model_id': self.glm.id, 'market_model_id': self.glm.id,
            'commercial_model_id': self.deepseek.id,
            'tools_model_id': self.deepseek.id, 'review_model_id': self.deepseek.id,
            'fallback_model_id': self.deepseek.id,
            'description_style': 'balanced',
        })
        self.session = self.env['sale.ai.session'].create({
            'name': 'Multimodelo', 'model_id': self.profile.id,
        })

    def _response(self, content='', calls=None):
        return {'content': content, 'tool_calls': calls or [],
                'finish_reason': 'stop' if not calls else 'tool_calls',
                'input_tokens': 110, 'output_tokens': 20,
                'latency_ms': 8, 'reported_cost_usd': 0}

    def test_profile_routes_and_company_default(self):
        self.assertEqual(self.profile._role_model('description'), self.glm)
        self.assertEqual(self.profile._role_model('market'), self.glm)
        self.assertEqual(self.profile._role_model('tools'), self.deepseek)
        self.profile.write({'is_default': True})
        self.assertEqual(self.env.company.sale_ai_model_id, self.profile)
        self.assertEqual(self.session.model_id, self.profile)
        created = self.env['sale.ai.session'].create({'name': 'Nueva con perfil'})
        self.assertEqual(created.model_id, self.profile)

    def test_profile_requires_all_roles(self):
        with self.assertRaises(ValidationError):
            self.env['sale.ai.model'].create({
                'name': 'Perfil incompleto', 'model_type': 'profile',
                'tools_model_id': self.deepseek.id,
            })

    def test_profile_plan_and_market_synthesis(self):
        self.env['sale.ai.message'].create({
            'session_id': self.session.id, 'role': 'user',
            'content': 'Dame una valoración estimada de los materiales.',
        })
        plan = self._response(calls=[{'id': 'plan1', 'type': 'function',
             'function': {'name': 'plan_turn', 'arguments': json.dumps({
                 'goal': 'Valorar materiales', 'required_tools': [],
                 'direct_answer': 'Valoración inicial orientativa: 100 €.',
                 'write_scope': 'read_only', 'response_role': 'market',
             })}}])
        synth = self._response(content='Valoración orientativa de materiales: 100 €.')
        requests = []

        def fake_gateway(key, model_id, messages, **kwargs):
            requests.append(model_id)
            return plan if len(requests) == 1 else synth

        with patch('odoo.addons.sale_ai_assistant.models.sale_ai_gateway.get_gateway_key',
                   return_value='test-key'), patch(
                       'odoo.addons.sale_ai_assistant.models.sale_ai_gateway.call_gateway',
                       side_effect=fake_gateway):
            result = self.session._ai_generate_for()
        self.assertEqual(requests, ['test/deepseek', 'test/glm'])
        self.assertIn('100', result['assistant_message']['content'])
        self.assertFalse(self.session.draft_id.line_ids)
        usage = self.env['sale.ai.model.usage'].search([('session_id', '=', self.session.id)])
        self.assertEqual(len(usage), 2)
        self.assertEqual(set(usage.mapped('model_id').ids), {self.glm.id, self.deepseek.id})
        self.assertGreater(result['assistant_message']['estimated_cost_usd'], 0)

    def test_profile_selectable_without_changing_company_default(self):
        result = self.env['sale.ai.session'].assistant_panel_select_model(
            self.session.id, self.glm.id)
        self.assertEqual(result['model_id'], self.glm.id)
        self.assertEqual(self.session.model_id, self.glm)
