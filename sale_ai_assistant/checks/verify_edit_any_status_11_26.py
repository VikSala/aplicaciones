"""Standalone checks for editing sale orders in all states, without Odoo running."""
import ast
import importlib.util
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]

odoo = types.ModuleType('odoo')
odoo._ = lambda text: text
odoo.api = types.SimpleNamespace(model=lambda method: method)
odoo.fields = types.SimpleNamespace(Datetime=types.SimpleNamespace(to_string=lambda dt: str(dt)))
odoo.models = types.SimpleNamespace(Model=type('Model', (), {}))
exceptions = types.ModuleType('odoo.exceptions')
for name in ('AccessError', 'UserError', 'ValidationError'):
    setattr(exceptions, name, type(name, (Exception,), {}))
sys.modules['odoo'] = odoo
sys.modules['odoo.exceptions'] = exceptions
spec = importlib.util.spec_from_file_location('sale_ai_quote_edit', ROOT / 'models/sale_ai_quote_edit.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


class Ref:
    def __init__(self, id):
        self.id = id


class TestAllOrderStates(unittest.TestCase):
    def test_edit_order_accepts_any_state(self):
        for state in ('draft', 'sent', 'sale', 'cancel', 'custom_state'):
            order = types.SimpleNamespace(state=state, company_id=Ref(1))
            order.exists = lambda: True
            class Session:
                def ensure_one(self): pass
                def _edit_access(self): pass
                edit_order_id = order
                company_id = order.company_id
            result = mod.SaleAIQuotationEditing._edit_order(Session())
            self.assertIs(result, order, state)

    def test_state_included_in_snapshot(self):
        class Lines(list):
            def sorted(self, key): return sorted(self, key=key)
        for state in ('draft', 'sent', 'sale', 'cancel'):
            order = types.SimpleNamespace(
                id=10, state=state, order_line=Lines(), write_date='2026-10-29 10:00:00',
                currency_id=Ref(1), partner_id=Ref(2), pricelist_id=Ref(3), _fields={},
            )
            snap = mod.SaleAIQuotationEditing._edit_snapshot(types.SimpleNamespace(_edit_comments=lambda order: ''), order)
            self.assertEqual(snap['state'], state)
            self.assertEqual(snap['order_id'], 10)

    def test_no_state_rejection_in_backend_path(self):
        tree = ast.parse((ROOT / 'models/sale_ai_quote_edit.py').read_text())
        cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == 'SaleAIQuotationEditing')
        # All three server entry points must remain free of state-dependent rejection.
        for method_name in ('_edit_order', 'assistant_panel_load_quotation', 'assistant_panel_update_quotation'):
            method = next(node for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == method_name)
            conditions = [ast.unparse(node.test) for node in ast.walk(method) if isinstance(node, ast.If)]
            self.assertFalse(any('order.state' in test for test in conditions), (method_name, conditions))

    def test_js_button_not_filtered_to_draft(self):
        js = (ROOT / 'static/src/js/sale_ai_chat.js').read_text()
        section = js.split('async refreshCurrentPV()', 1)[1].split('get editingQuotation()', 1)[0]
        self.assertNotIn('=== "draft"', section)
        self.assertIn('if (records.length)', section)
        self.assertIn('Estado actual:', js)

    def test_creation_still_in_draft(self):
        # Editing any order state must not affect how new quotes are created.
        text = (ROOT / 'models/sale_ai_session.py').read_text()
        self.assertIn('order.state != "draft"', text)


if __name__ == '__main__':
    unittest.main()
