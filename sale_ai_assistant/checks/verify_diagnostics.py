"""Isolated tests of actual engine closures; no Odoo or network required.
Run: python checks/verify_diagnostics.py
"""
import ast
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import unittest

SOURCE = Path(__file__).resolve().parents[1] / 'models/sale_ai_engine.py'
tree = ast.parse(SOURCE.read_text())
closures = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
            and n.name in ('invoke', 'record_turn_failure')}
class GatewayError(Exception): pass
class Clock:
    value = 0
    def monotonic(self): return self.value

def harness(outcomes, budget=10):
    clock = Clock(); calls = []; log = Mock(); saved = []
    first = NS(id=1, external_model_id='first', supports_tools=True,
               price_input_m_usd=1, price_output_m_usd=2)
    first._gateway_routing_options = lambda: {'sort': 'cost'}
    second = NS(**dict(vars(first), id=2, external_model_id='second'))
    def gateway(*args, **kwargs):
        calls.append(kwargs)
        seconds, result = outcomes.pop(0); clock.value += seconds
        if isinstance(result, Exception): raise result
        return result
    env = dict(UserError=type("UserError", (Exception,), {}), time=clock, sale_ai_gateway=NS(GatewayError=GatewayError, call_gateway=gateway),
               _logger=log, _=lambda x:x, model=NS(model_type='profile'), fallback_model=second,
               max_seconds=budget, timeout=90, response_tokens=8192, key='not-a-real-key',
               self=NS(id=42), saved=saved)
    prelude = '''def factory():
    total_input = total_output = total_latency = 0
    total_cost = total_estimated_cost = 0.0
    per_model_usage = []
    started = 0
    turn_ref = 'test-reference'
    diagnostic_stage = 'planning'
    diagnostic_model = fallback_model
    diagnostic_operation = 'preparation'
    def save_usage():
        saved.extend(per_model_usage)
        per_model_usage.clear()
'''
    text = prelude + '\n'.join('    '+line for name in ('invoke','record_turn_failure')
                               for line in ast.unparse(closures[name]).splitlines())
    text += '\n    return invoke, record_turn_failure, per_model_usage\n'
    exec(text, env)
    invoke, failure, usage = env['factory']()
    return NS(invoke=invoke, failure=failure, usage=usage, first=first,
              calls=calls, log=log, saved=saved)

def response():
    return dict(input_tokens=5, output_tokens=3, latency_ms=0, reported_cost_usd=0,
                content='Text')

class DiagnosticsTests(unittest.TestCase):
    def test_success_wall_clock_and_reference(self):
        h=harness([(2,response())]); h.invoke('description',h.first,[])
        self.assertEqual(h.usage[0]['latency_ms'],2000)
        self.assertEqual(h.usage[0]['turn_ref'],'test-reference')
    def test_failure_and_fallback_budget(self):
        h=harness([(6,GatewayError('network')), (1,response())])
        _, model = h.invoke('planning',h.first,[],timeout=9)
        self.assertEqual(model.id,2)
        self.assertEqual([c['timeout'] for c in h.calls],[9,4])
        self.assertEqual([u['latency_ms'] for u in h.usage],[6000,1000])
        self.assertEqual(h.usage[0]['error_type'],'GatewayError')
    def test_no_call_after_deadline(self):
        h=harness([(10,GatewayError('timeout'))])
        with self.assertRaises(GatewayError): h.invoke('planning',h.first,[])
        self.assertEqual(len(h.calls),1)
    def test_unexpected_failure_no_retry_and_traceback(self):
        h=harness([(3,ValueError('private details'))])
        try: h.invoke('validation',h.first,[])
        except ValueError as exc: message=h.failure(exc)
        self.assertIn('test-reference',message)
        self.assertNotIn('private details',message)
        self.assertEqual(len(h.calls),1)
        self.assertEqual(h.saved[0]['latency_ms'],3000)
        self.assertEqual(h.saved[-1]['event_kind'],'turn_failure')
        self.assertEqual(h.saved[-1]['stage'],'validation')
        self.assertEqual(h.saved[-1]['turn_elapsed_ms'],3000)
        self.assertEqual(h.saved[-1]['latency_ms'],0)
        self.assertTrue(h.log.error.call_args.kwargs['exc_info'])
    def test_processing_failure_identified(self):
        h=harness([(1,{})])
        try: h.invoke('planning',h.first,[])
        except KeyError as exc: h.failure(exc)
        self.assertEqual(h.saved[-1]['diagnostic_operation'],'procesamiento de respuesta')
        self.assertEqual(h.saved[-1]['error_type'],'KeyError')
    def test_all_provider_attempts_fail(self):
        h=harness([(2,GatewayError('first')), (3,GatewayError('second'))])
        try: h.invoke('description',h.first,[])
        except GatewayError as exc: h.failure(exc)
        self.assertEqual(len(h.saved),3)
        self.assertEqual(h.saved[-1]['model_id'],2)
        self.assertEqual(h.saved[-1]['turn_elapsed_ms'],5000)

if __name__ == '__main__': unittest.main()
