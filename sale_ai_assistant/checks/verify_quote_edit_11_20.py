"""Run without Odoo: exercise the actual field-level concurrency diff method."""
import importlib.util
import sys
import types
import unittest
from pathlib import Path

odoo = types.ModuleType('odoo')
odoo._ = lambda message: message
odoo.api = types.SimpleNamespace(model=lambda method: method)
odoo.fields = types.SimpleNamespace(Datetime=types.SimpleNamespace(to_string=str))
odoo.models = types.SimpleNamespace(Model=type('Model', (), {}))
errors = types.ModuleType('odoo.exceptions')
errors.AccessError = type('AccessError', (Exception,), {})
errors.UserError = type('UserError', (Exception,), {})
errors.ValidationError = type('ValidationError', (Exception,), {})
sys.modules['odoo'] = odoo
sys.modules['odoo.exceptions'] = errors
spec = importlib.util.spec_from_file_location('quote_edit', Path(__file__).parents[1] / 'models' / 'sale_ai_quote_edit.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Ref:
    def __init__(self, id=0):
        self.id = id


class Line:
    def __init__(self, source, quantity=10, price=5, sequence=10, name='Tira LED'):
        self.source_sale_line_id = source
        self.id = source or 999
        self.sequence = sequence
        self.line_kind = 'product'
        self.name = name
        self.product_id = Ref(50)
        self.product_uom_id = Ref(1)
        self.product_uom_qty = quantity
        self.price_unit = price
        self.discount = 0


class Lines(list):
    def sorted(self, key):
        return sorted(self, key=key)


class Draft:
    partner_id = Ref(7)
    pricelist_id = Ref(4)
    description = 'Original'

    def __init__(self, lines):
        self.line_ids = Lines(lines)


class Session:
    def __init__(self, draft):
        self.draft_id = draft


def row(id, quantity=10, price=5):
    return {'id': id, 'sequence': 10, 'kind': 'product', 'name': 'Tira LED',
            'product_id': 50, 'uom_id': 1, 'quantity': quantity, 'price_unit': price,
            'discount': 0, 'stamp': '2026-10-28 11:00:00'}


def snapshot(lines):
    return {'order_id': 8, 'stamp': '2026-10-28 11:00:00', 'partner_id': 7,
            'pricelist_id': 4, 'comments': 'Original', 'lines': lines}


class TestQuotationDiff(unittest.TestCase):
    def diff(self, original, current, lines, **header):
        draft = Draft(lines)
        for k, v in header.items():
            setattr(draft, k, v)
        return module.SaleAIQuotationEditing._edit_plan(Session(draft), original, current)

    def test_quantity_change_only(self):
        original = snapshot([row(11)])
        plan = self.diff(original, original, [Line(11, quantity=12)])
        self.assertEqual(plan['edits'][11], {'quantity': 12})
        self.assertEqual(plan['removed'], [])
        self.assertEqual(plan['added'], [])
        self.assertFalse(plan['conflicts'])

    def test_external_price_change_preserved(self):
        original = snapshot([row(11)])
        current = snapshot([row(11, price=7)])
        plan = self.diff(original, current, [Line(11, quantity=12)])
        self.assertEqual(plan['edits'][11], {'quantity': 12})
        self.assertFalse(plan['conflicts'])
        self.assertTrue(plan['external_changes'])

    def test_overlapping_change_must_be_confirmed(self):
        original = snapshot([row(11)])
        current = snapshot([row(11, quantity=14)])
        plan = self.diff(original, current, [Line(11, quantity=12)])
        self.assertIn('Línea 11: cantidad', plan['conflicts'])

    def test_external_added_line_never_deleted(self):
        original = snapshot([row(11)])
        current = snapshot([row(11), row(17)])
        plan = self.diff(original, current, [Line(11, quantity=12)])
        self.assertEqual(plan['removed'], [])
        self.assertIn('Línea 17 añadida', plan['external_changes'])

    def test_draft_removed_line_and_new_line(self):
        original = snapshot([row(11)])
        plan = self.diff(original, original, [Line(0, name='Nueva línea')])
        self.assertEqual(plan['removed'], [11])
        self.assertEqual(len(plan['added']), 1)

    def test_deleted_by_another_user_is_not_recreated(self):
        original = snapshot([row(11)])
        current = snapshot([])
        plan = self.diff(original, current, [Line(11, quantity=12)])
        self.assertEqual(plan['missing_lines'], [11])

    def test_duplicate_origin_line_rejected(self):
        original = snapshot([row(11)])
        with self.assertRaises(errors.UserError):
            self.diff(original, original, [Line(11), Line(11)])

    def test_partner_concurrent_conflict(self):
        original = snapshot([row(11)])
        current = snapshot([row(11)])
        current['partner_id'] = 9
        plan = self.diff(original, current, [Line(11, quantity=12)], partner_id=Ref(10))
        self.assertIn('Cabecera: cliente', plan['conflicts'])


if __name__ == '__main__':
    unittest.main()
