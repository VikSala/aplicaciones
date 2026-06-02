"""Tests for owa.inbound.dedupe atomic claim — Phase 2."""
from odoo.tests import tagged

from .common import OwaTestCase


@tagged('post_install', '-at_install', 'open_whatsapp_connector')
class TestInboundDedupe(OwaTestCase):

    def setUp(self):
        super().setUp()
        self.Dedupe = self.env['owa.inbound.dedupe']

    def test_first_claim_wins(self):
        ok = self.Dedupe.claim('uid-A', self.account.id)
        self.assertTrue(ok)

    def test_second_claim_loses(self):
        self.Dedupe.claim('uid-B', self.account.id)
        ok = self.Dedupe.claim('uid-B', self.account.id)
        self.assertFalse(ok)

    def test_different_uid_independent(self):
        self.Dedupe.claim('uid-C', self.account.id)
        ok = self.Dedupe.claim('uid-D', self.account.id)
        self.assertTrue(ok)

    def test_empty_uid_passes(self):
        # Defensive: no msg_uid means we can't dedupe — let it through.
        self.assertTrue(self.Dedupe.claim('', self.account.id))
        self.assertTrue(self.Dedupe.claim(None, self.account.id))
