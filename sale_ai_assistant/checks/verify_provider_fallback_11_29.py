"""Standalone checks: python checks/verify_provider_fallback_11_29.py.

No Odoo server or Vercel API key is needed: real model methods are loaded
with tiny Odoo stubs, and HTTP is mocked at the transport boundary.
"""
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

root = Path(__file__).resolve().parents[1]

class Fields:
    def __getattr__(self, key):
        return lambda *args, **kwargs: None

class Api:
    def __getattr__(self, name):
        return lambda *args, **kwargs: lambda fn: fn

class Record:
    def ensure_one(self):
        return self
    def __iter__(self):
        yield self

class ValidationError(Exception):
    pass

fake_odoo = types.ModuleType('odoo')
fake_odoo._ = lambda text: text
fake_odoo.fields = Fields()
fake_odoo.api = Api()
fake_odoo.models = types.SimpleNamespace(Model=Record)
sys.modules['odoo'] = fake_odoo
fake_exc = types.ModuleType('odoo.exceptions')
fake_exc.ValidationError = ValidationError
sys.modules['odoo.exceptions'] = fake_exc

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

model_module = load('model_fallback_1129', root / 'models/sale_ai_model.py')
gateway = load('gateway_fallback_1129', root / 'models/sale_ai_gateway.py')

class Response:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, n):
        return json.dumps({
            'id': 'gen_Z99',
            'choices': [{'message': {'content': 'ok'}, 'finish_reason': 'stop'}],
            'providerMetadata': {'gateway': {'routing': {'finalProvider': 'wafer'}}},
            'usage': {'prompt_tokens': 50000, 'completion_tokens': 1000},
        }).encode('utf8')[:n]

class TestFallback(unittest.TestCase):
    def model(self, mode, main='', backup=''):
        m = model_module.SaleAIModel()
        m.gateway_routing = mode
        m.gateway_fixed_provider = main
        m.gateway_fallback_provider = backup
        m.model_type = 'individual'
        return m

    def test_fixed_with_backup_is_strict_and_ordered(self):
        m = self.model('fixed', 'particle', 'wafer')
        m._validate_gateway_routing()
        expected = {'order': ['particle', 'wafer'], 'only': ['particle', 'wafer']}
        self.assertEqual(m._gateway_routing_options(), expected)
        requests = []
        def respond(request, timeout):
            requests.append(request)
            return Response()
        with patch.object(gateway, 'urlopen', respond):
            result = gateway.call_gateway('dummy-key', 'deepseek/deepseek-chat',
                                          [{'role': 'user', 'content': 'hola'}],
                                          3, 8192, routing=m._gateway_routing_options())
        payload = json.loads(requests[0].data)
        self.assertEqual(payload['providerOptions']['gateway'], expected)
        self.assertEqual(payload['model'], 'deepseek/deepseek-chat')
        self.assertEqual(result['provider_name'], 'wafer')
        self.assertEqual(result['input_tokens'], 50000)
        self.assertEqual(result['output_tokens'], 1000)

    def test_fixed_without_backup_maintains_previous_behavior(self):
        m = self.model('fixed', 'particle')
        self.assertEqual(m._gateway_routing_options(), {'only': ['particle']})

    def test_previous_automatic_and_sorted_modes_unchanged(self):
        for mode, expected in [('auto', {}), ('cost', {'sort':'cost'}),
                               ('ttft', {'sort':'ttft'}), ('tps', {'sort':'tps'})]:
            self.assertEqual(self.model(mode)._gateway_routing_options(), expected)

    def test_invalid_slugs_and_same_provider(self):
        for main, backup in [('wafer', 'wafer'), ('wafer', 'WAFER'),
                             ('wafer', 'bad slug'), ('', 'wafer'), ('../x', 'wafer')]:
            with self.subTest(main=main, backup=backup):
                with self.assertRaises(ValidationError):
                    self.model('fixed', main, backup)._validate_gateway_routing()

    def test_transport_does_not_allow_open_ended_fallback(self):
        invalid = [
            {'order': ['particle', 'wafer']},
            {'order': ['particle', 'wafer'], 'only': ['particle']},
            {'order': ['wafer', 'wafer'], 'only': ['wafer']},
            {'order': ['wafer', 'another'], 'only': ['wafer', 'other']},
            {'order': ['wafer', 'other'], 'only': ['wafer', 'other'], 'sort': 'cost'},
        ]
        with patch.object(gateway, 'urlopen') as network:
            for routing in invalid:
                with self.subTest(routing=routing):
                    with self.assertRaises(gateway.GatewayError):
                        gateway.call_gateway('dummy-key', 'model', [], 3, 100, routing=routing)
            network.assert_not_called()

    def test_model_view_exposes_backup_only_in_fixed_mode(self):
        from xml.etree import ElementTree
        tree = ElementTree.parse(root / 'views/sale_ai_model_views.xml')
        fields = tree.findall('.//field[@name="gateway_fallback_provider"]')
        self.assertEqual(len(fields), 2)
        view_field = next(x for x in fields if 'invisible' in x.attrib)
        self.assertIn("gateway_routing != 'fixed'", view_field.get('invisible'))
        self.assertFalse(view_field.get('required'))

    def test_no_scheduled_cost_refresh_in_manifest(self):
        manifest = (root / '__manifest__.py').read_text()
        self.assertNotIn('sale_ai_cost_refresh.xml', manifest)
        self.assertFalse((root / 'data/sale_ai_cost_refresh.xml').exists())

if __name__ == '__main__':
    unittest.main(verbosity=2)
