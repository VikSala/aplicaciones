"""Self-contained HTTP mocks: python checks/verify_routing_costs_11_27.py"""
import importlib.util
import io
import json
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.modules.setdefault('odoo', types.SimpleNamespace(_=lambda x:x))
path = Path(__file__).resolve().parents[1] / 'models' / 'sale_ai_gateway.py'
spec = importlib.util.spec_from_file_location('sale_ai_gateway_test_1127', path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class DummyResponse:
    def __init__(self, payload): self.blob = json.dumps(payload).encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, amount): return self.blob[:amount]

class TestVercelRouting(unittest.TestCase):
    def mock_chat(self, routing):
        calls = []
        def fake(req, timeout):
            calls.append((req, timeout))
            return DummyResponse({'id':'gen_ABC123','choices':[{'message':{'content':'ok'},'finish_reason':'stop'}],
                'usage': {'prompt_tokens':34,'completion_tokens':12}})
        with patch.object(mod, 'urlopen', fake):
            resp = mod.call_gateway('fake-key', 'deepseek/deepseek-chat',
                   [{'role':'user','content':'test'}], 5, 512, routing=routing)
        return calls[0][0], resp

    def test_cost_sort_is_sent_to_gateway(self):
        request, resp = self.mock_chat({'sort':'cost'})
        body = json.loads(request.data)
        self.assertEqual(body['providerOptions']['gateway'], {'sort':'cost'})
        self.assertEqual(resp['generation_id'],'gen_ABC123')
        self.assertEqual(resp['cost_status'],'pending')
        self.assertEqual(resp['input_tokens'],34)
        self.assertNotIn('fake-key',str(body))

    def test_fixed_provider_sent_and_auto_absent(self):
        req, _ = self.mock_chat({'only':['morph']})
        self.assertEqual(json.loads(req.data)['providerOptions']['gateway'],{'only':['morph']})
        req, _ = self.mock_chat({})
        self.assertNotIn('providerOptions',json.loads(req.data))

    def test_reject_bad_routes_without_network(self):
        for route in ({'sort':'bad'}, {'only':['x y']},{'other':'secret'}):
            with self.assertRaises(mod.GatewayError):
                mod.call_gateway('key','model',[],1,10,routing=route)

    def test_direct_gateway_metadata_amount_zero_is_known(self):
        def fake(*args,**kw):
            return DummyResponse({'id':'gen_X','choices':[{'message':{'content':'ok'}}],
            'providerMetadata':{'gateway':{'cost':0,'routing':{'finalProvider':'morph'}}}})
        with patch.object(mod,'urlopen',fake):
            r=mod.call_gateway('key','model',[],1,10)
        self.assertEqual(r['cost_status'],'obtained')
        self.assertEqual(r['provider_name'],'morph')
        self.assertEqual(r['reported_cost_usd'],0)

    def test_generation_lookup_is_authoritative(self):
        calls=[]
        def fake(req, timeout):
            calls.append((req.full_url, req.get_header('Authorization')))
            return DummyResponse({'data':{'id':'gen_ABC123','total_cost':0.000012345,
                'provider_name':'morph', 'prompt_tokens':100,'completion_tokens':19}})
        with patch.object(mod,'urlopen',fake):
            result=mod.lookup_generation('test-key','gen_ABC123',5)
        self.assertAlmostEqual(result['reported_cost_usd'],0.000012345)
        self.assertEqual(result['provider_name'],'morph')
        self.assertIn('/v1/generation?id=gen_ABC123',calls[0][0])
        self.assertEqual(calls[0][1],'Bearer test-key')

    def test_not_ready_does_not_masquerade_as_zero(self):
        def fake(*args,**kwargs): return DummyResponse({'error':'not indexed'})
        with patch.object(mod,'urlopen',fake):
            self.assertIsNone(mod.lookup_generation('test-key','gen_ABC123'))
        with patch.object(mod,'urlopen') as network:
            self.assertIsNone(mod.lookup_generation('key','/v1/users/keys'))
            network.assert_not_called()

if __name__=='__main__': unittest.main()
