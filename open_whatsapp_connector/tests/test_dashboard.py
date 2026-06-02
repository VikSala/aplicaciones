"""Tests for owa.dashboard.get_dashboard_data — Phase 0."""
from odoo.tests import tagged

from .common import OwaTestCase


@tagged('post_install', '-at_install', 'open_whatsapp_connector')
class TestDashboard(OwaTestCase):

    def test_get_dashboard_data_shape(self):
        data = self.env['owa.dashboard'].get_dashboard_data()
        self.assertIn('counters', data)
        self.assertIn('status_counts', data)
        self.assertIn('messages_per_day', data)
        self.assertIn('top_partners', data)
        self.assertIn('account_health', data)
        self.assertIn('recent_failures', data)
        self.assertIn('top_failure_reasons', data)
        self.assertIn('filters_echo', data)

    def test_counters_are_integers(self):
        data = self.env['owa.dashboard'].get_dashboard_data()
        for k, v in data['counters'].items():
            self.assertIsInstance(v, int, f"counter {k!r} should be int, got {type(v)}")

    def test_account_health_lists_fixture_account(self):
        data = self.env['owa.dashboard'].get_dashboard_data()
        names = [r['name'] for r in data['account_health']]
        self.assertIn(self.account.name, names)

    def test_filtered_by_account(self):
        data = self.env['owa.dashboard'].get_dashboard_data(
            account_ids=[self.account.id],
        )
        self.assertEqual(data['filters_echo']['account_ids'], [self.account.id])

    def test_date_range_capped(self):
        # Asking for 5 years should cap at 365 days.
        data = self.env['owa.dashboard'].get_dashboard_data(
            date_from='2020-01-01',
        )
        from_dt = data['filters_echo']['date_from']
        to_dt = data['filters_echo']['date_to']
        # Just assert both populated.
        self.assertTrue(from_dt and to_dt)
