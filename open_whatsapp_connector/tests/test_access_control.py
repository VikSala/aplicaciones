"""Tests for DM allowlist + dm_policy gate — Phase 5."""
from odoo.tests import tagged

from .common import OwaTestCase


@tagged('post_install', '-at_install', 'open_whatsapp_connector')
class TestAllowlist(OwaTestCase):

    def setUp(self):
        super().setUp()
        self.Allow = self.env['owa.allowlist.entry']

    def test_open_policy_default(self):
        self.assertEqual(self.account.dm_policy, 'open')

    def test_is_allowed_match(self):
        self.Allow.create({'account_id': self.account.id, 'phone': '+919999990000'})
        self.assertTrue(self.Allow.is_allowed(self.account.id, '+919999990000'))

    def test_is_allowed_normalized_match(self):
        # Stored '+91999...' should match '919999...' (no plus) thanks to formatting.
        self.Allow.create({'account_id': self.account.id, 'phone': '+919999990001'})
        self.assertTrue(self.Allow.is_allowed(self.account.id, '919999990001'))

    def test_is_allowed_no_entry(self):
        self.assertFalse(self.Allow.is_allowed(self.account.id, '+918888888888'))

    def test_is_allowed_wrong_account(self):
        admin = self.env.ref('base.user_admin')
        other = self.Account.create({
            'name': 'other', 'sidecar_url': 'http://localhost:9999',
            'session_state': 'connected', 'webhook_secret': 'x',
            'notify_user_ids': [(6, 0, [admin.id])],
        })
        self.Allow.create({'account_id': other.id, 'phone': '+919999990002'})
        self.assertFalse(self.Allow.is_allowed(self.account.id, '+919999990002'))
        self.assertTrue(self.Allow.is_allowed(other.id, '+919999990002'))
