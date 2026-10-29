"""Check 11.28 doesn't schedule any Vercel cost lookups."""
import ast
import pathlib
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]


class TestManualCostsOnly(unittest.TestCase):
    def test_no_cron_definition_or_manifest_entry(self):
        manifest = ast.literal_eval((ROOT / '__manifest__.py').read_text(encoding='utf8'))
        self.assertNotIn('data/sale_ai_cost_refresh.xml', manifest['data'])
        self.assertFalse((ROOT / 'data/sale_ai_cost_refresh.xml').exists())
        for item in manifest['data']:
            if item.endswith('.xml'):
                tree = ET.parse(ROOT / item)
                self.assertFalse(any(r.get('model') == 'ir.cron' for r in tree.iter('record')),
                                 'Un cron no deseado en %s' % item)

    def test_manual_button_wires_lookup(self):
        tree = ET.parse(ROOT / 'views/sale_ai_model_usage_views.xml')
        buttons = [n for n in tree.iter('button') if n.get('name') == 'action_refresh_gateway_costs']
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].get('type'), 'object')
        source = (ROOT / 'models/sale_ai_model_usage.py').read_text(encoding='utf8')
        self.assertIn('def action_refresh_gateway_costs(self):', source)
        self.assertIn("self.env['sale.ai.model.usage']._refresh_pending_gateway_costs()", source)
        self.assertIn('def _refresh_pending_gateway_costs(self):', source)
        self.assertNotIn('def cron_refresh_gateway_costs', source)

    def test_manual_limit_only(self):
        source = (ROOT / 'models/sale_ai_model_usage.py').read_text(encoding='utf8')
        self.assertEqual(source.count('lookup_generation('), 1)
        for path in ROOT.rglob('*.py'):
            if path == pathlib.Path(__file__):
                continue
            if path.name != 'sale_ai_model_usage.py':
                self.assertNotIn('._refresh_pending_gateway_costs(', path.read_text(encoding='utf8'), str(path))


if __name__ == '__main__':
    unittest.main()
