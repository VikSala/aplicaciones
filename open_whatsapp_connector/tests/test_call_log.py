"""Phase 21: tests for owa.call.log incoming-call awareness."""
from odoo.tests.common import tagged
from odoo.exceptions import ValidationError

from .common import OwaTestCase


@tagged('post_install', '-at_install', 'open_whatsapp_connector')
class TestCallLog(OwaTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.CallLog = cls.env['owa.call.log']
        cls.partner = cls.env['res.partner'].create({
            'name': 'Acme Caller',
            'mobile': '+919999990001',
        })

    # ── intake basics ──────────────────────────────────────────────────────

    def test_record_call_offer_creates_ringing(self):
        log = self.CallLog._record_call_event(self.account, {
            'id': 'call-1',
            'from': '919999990001@s.whatsapp.net',
            'status': 'offer',
            'isVideo': False,
        })
        self.assertTrue(log)
        self.assertEqual(log.state, 'ringing')
        self.assertEqual(log.partner_id, self.partner)
        self.assertEqual(log.from_phone, '+919999990001')
        self.assertFalse(log.ended_at)
        self.assertFalse(log.is_video)

    def test_record_terminal_status_sets_ended_at(self):
        log = self.CallLog._record_call_event(self.account, {
            'id': 'call-2', 'from': '919999990001@s.whatsapp.net', 'status': 'timeout',
        })
        self.assertEqual(log.state, 'missed')
        self.assertTrue(log.ended_at)

    def test_record_video_call_sets_flag(self):
        log = self.CallLog._record_call_event(self.account, {
            'id': 'call-vid', 'from': '919999990001@s.whatsapp.net',
            'status': 'reject', 'isVideo': True,
        })
        self.assertTrue(log.is_video)
        self.assertEqual(log.state, 'rejected')

    def test_idempotent_intake_updates_existing(self):
        self.CallLog._record_call_event(self.account, {
            'id': 'call-3', 'from': '919999990001@s.whatsapp.net', 'status': 'offer',
        })
        log = self.CallLog._record_call_event(self.account, {
            'id': 'call-3', 'from': '919999990001@s.whatsapp.net', 'status': 'timeout',
        })
        # only one row, but state advanced
        rows = self.CallLog.search([('call_id', '=', 'call-3')])
        self.assertEqual(len(rows), 1)
        self.assertEqual(log.state, 'missed')

    def test_uniq_account_call_id_constraint(self):
        self.CallLog.create({
            'wa_account_id': self.account.id,
            'from_jid': '111@s.whatsapp.net',
            'call_id': 'dup',
            'state': 'ringing',
        })
        with self.assertRaises(Exception):  # IntegrityError wrapped by Odoo
            self.CallLog.create({
                'wa_account_id': self.account.id,
                'from_jid': '222@s.whatsapp.net',
                'call_id': 'dup',
                'state': 'ringing',
            })

    def test_malformed_payload_returns_false(self):
        self.assertFalse(self.CallLog._record_call_event(self.account, {}))
        self.assertFalse(self.CallLog._record_call_event(self.account, {'id': 'x'}))

    # ── partner resolution ────────────────────────────────────────────────

    def test_partner_resolution_by_full_digits(self):
        partner = self.CallLog._resolve_partner_from_phone('919999990001')
        self.assertEqual(partner, self.partner)

    def test_partner_resolution_last10_fallback(self):
        # caller country code differs from stored partner country code
        partner = self.CallLog._resolve_partner_from_phone('1929999990001')
        self.assertEqual(partner, self.partner,
                         "Should match by trailing 10 digits when full match fails")

    def test_partner_resolution_no_match_returns_empty(self):
        partner = self.CallLog._resolve_partner_from_phone('999999999')
        self.assertFalse(partner)

    # ── group calls ───────────────────────────────────────────────────────

    def test_group_call_does_not_crash_partner_resolution(self):
        log = self.CallLog._record_call_event(self.account, {
            'id': 'grp-call', 'from': '999999999@g.us',
            'status': 'offer', 'isGroup': True,
        })
        self.assertTrue(log)
        self.assertTrue(log.is_group)

    # ── auto-reply ────────────────────────────────────────────────────────

    def test_auto_reply_fires_once_on_missed(self):
        self.account.write({
            'auto_reply_on_missed_call': True,
            'missed_call_reply_template': 'Sorry I missed your call, {{partner_name}}!',
        })
        log = self.CallLog._record_call_event(self.account, {
            'id': 'autoreply-1', 'from': '919999990001@s.whatsapp.net',
            'status': 'timeout',
        })
        self.assertTrue(log.auto_replied)
        # second event for same call id should NOT re-queue
        log2 = self.CallLog._record_call_event(self.account, {
            'id': 'autoreply-1', 'from': '919999990001@s.whatsapp.net',
            'status': 'timeout',
        })
        self.assertEqual(log, log2)
        # exactly one outbound owa.message queued
        queued = self.env['owa.message'].search([
            ('mobile_number', '=', '+919999990001'),
            ('state', '=', 'outgoing'),
        ])
        self.assertEqual(len(queued), 1)
        # owa.message has no `body_text` field — the text lives on `body`
        # (related to mail_message_id.body). (#calls)
        self.assertIn('Acme Caller', queued.body or '')

    def test_auto_reply_skipped_when_toggle_off(self):
        self.account.auto_reply_on_missed_call = False
        log = self.CallLog._record_call_event(self.account, {
            'id': 'noreply-1', 'from': '919999990001@s.whatsapp.net',
            'status': 'timeout',
        })
        self.assertFalse(log.auto_replied)

    def test_auto_reply_skipped_on_accepted(self):
        self.account.write({
            'auto_reply_on_missed_call': True,
            'missed_call_reply_template': 'Tpl',
        })
        log = self.CallLog._record_call_event(self.account, {
            'id': 'accepted-1', 'from': '919999990001@s.whatsapp.net',
            'status': 'accept',
        })
        self.assertEqual(log.state, 'accepted')
        self.assertFalse(log.auto_replied)

    # ── duration ──────────────────────────────────────────────────────────

    def test_duration_computes_when_ended(self):
        from datetime import datetime, timedelta
        log = self.CallLog.create({
            'wa_account_id': self.account.id,
            'from_jid': '919999990001@s.whatsapp.net',
            'call_id': 'dur-1',
            'state': 'accepted',
            'started_at': datetime(2026, 4, 29, 14, 0, 0),
            'ended_at': datetime(2026, 4, 29, 14, 1, 30),
        })
        self.assertEqual(log.duration_seconds, 90)

    def test_duration_zero_without_ended_at(self):
        log = self.CallLog.create({
            'wa_account_id': self.account.id,
            'from_jid': '919999990001@s.whatsapp.net',
            'call_id': 'dur-2',
            'state': 'ringing',
        })
        self.assertEqual(log.duration_seconds, 0)

    # ── display name ──────────────────────────────────────────────────────

    def test_display_name_voice(self):
        log = self.CallLog._record_call_event(self.account, {
            'id': 'dn-1', 'from': '919999990001@s.whatsapp.net', 'status': 'reject',
        })
        self.assertIn('Voice', log.display_name)
        self.assertIn('Acme Caller', log.display_name)
        self.assertIn('rejected', log.display_name)

    def test_display_name_video(self):
        log = self.CallLog._record_call_event(self.account, {
            'id': 'dn-2', 'from': '919999990001@s.whatsapp.net',
            'status': 'reject', 'isVideo': True,
        })
        self.assertIn('Video', log.display_name)
