from unittest import TestCase

from ..models.sale_order import SaleOrder
from ..models.stock_picking import StockPicking


class TestSendcloudPureHelpers(TestCase):
    def test_carrier_aliases_are_canonical(self):
        self.assertEqual(SaleOrder._optima_sendcloud_canonical_carrier("Mondial Relay"), "inpost_es")
        self.assertEqual(SaleOrder._optima_sendcloud_canonical_carrier("inpost_iberia"), "inpost_es")
        self.assertEqual(SaleOrder._optima_sendcloud_canonical_carrier("Correos Express"), "correos_express")
        self.assertEqual(SaleOrder._optima_sendcloud_canonical_carrier("correos"), "correos")

    def test_dimension_conversion_is_non_negative(self):
        self.assertEqual(SaleOrder._optima_sendcloud_dimension_to_mm(1.2, "meter"), 1200.0)
        self.assertEqual(SaleOrder._optima_sendcloud_dimension_to_mm(100, "centimeter"), 1000.0)
        self.assertEqual(SaleOrder._optima_sendcloud_dimension_to_mm(25, "cm"), 250.0)
        self.assertEqual(SaleOrder._optima_sendcloud_dimension_to_mm(-3, "millimeter"), 0.0)
        self.assertEqual(SaleOrder._optima_sendcloud_dimension_to_mm("bad", "millimeter"), 0.0)

    def test_snapshot_json_parser_accepts_dict_and_json(self):
        payload, text = StockPicking._optima_sendcloud_json_payload({"id": 123})
        self.assertEqual(payload, {"id": 123})
        self.assertIn('"id": 123', text)

        payload, text = StockPicking._optima_sendcloud_json_payload('{"id": 456}')
        self.assertEqual(payload, {"id": 456})
        self.assertEqual(text, '{"id": 456}')

    def test_snapshot_json_parser_fails_closed_on_invalid_json(self):
        payload, text = StockPicking._optima_sendcloud_json_payload("not-json")
        self.assertEqual(payload, {})
        self.assertEqual(text, "not-json")
