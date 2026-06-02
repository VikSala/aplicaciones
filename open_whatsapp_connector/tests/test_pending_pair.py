"""Tests for owa.pending.pair workflow — Phase 7."""
from odoo.tests import tagged

from .common import OwaTestCase


@tagged('post_install', '-at_install', 'open_whatsapp_connector')
class TestPendingPair(OwaTestCase):

    def setUp(self):
        super().setUp()
        self.Pending = self.env['owa.pending.pair']
        self.Allow = self.env['owa.allowlist.entry']

    def test_request_creates_pending(self):
        p = self.Pending.request_pair(self.account, '+919999990010', sender_name='Test')
        self.assertTrue(p)
        self.assertEqual(p.state, 'pending')

    def test_request_refreshes_existing(self):
        p1 = self.Pending.request_pair(self.account, '+919999990011')
        p2 = self.Pending.request_pair(self.account, '+919999990011')
        self.assertEqual(p1.id, p2.id)

    def test_approve_creates_allowlist_entry(self):
        p = self.Pending.request_pair(self.account, '+919999990012')
        before = self.Allow.search_count([('account_id', '=', self.account.id)])
        p.action_approve()
        after = self.Allow.search_count([('account_id', '=', self.account.id)])
        self.assertEqual(p.state, 'approved')
        self.assertEqual(after - before, 1)

    def test_reject_marks_state(self):
        p = self.Pending.request_pair(self.account, '+919999990013')
        p.action_reject()
        self.assertEqual(p.state, 'rejected')

    def test_cron_expire_old_pending(self):
        from datetime import timedelta
        from odoo import fields
        p = self.Pending.request_pair(self.account, '+919999990014')
        p.expires_at = fields.Datetime.now() - timedelta(hours=2)
        self.Pending._cron_expire()
        p.invalidate_recordset()
        self.assertEqual(p.state, 'expired')
