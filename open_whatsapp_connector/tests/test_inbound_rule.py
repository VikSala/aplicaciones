"""Tests for the Inbound Auto-create Rules engine (Phase 22C / 27B)."""
from odoo.exceptions import ValidationError
from odoo.tests.common import tagged

from .common import OwaTestCase


@tagged('post_install', '-at_install')
class TestInboundRule(OwaTestCase):
    """Coverage matrix:
      - 4 match_types: regex, keyword, sender_pattern, unknown_sender
      - 5 target_models: crm.lead, helpdesk.ticket, sale.order, project.task, hr.applicant
      - Edge cases: priority ordering, once_per_partner dedupe, account scoping,
        bad regex, bad extras dict, group-chat guard, regex DoS truncation,
        auto-reply short-circuit, helpdesk back-link.

    Cross-app targets that aren't installed (helpdesk / hr.recruitment etc.)
    are skipped gracefully — tests check `model in self.env` before exercising.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Rule = cls.env['owa.inbound.rule']
        cls.partner = cls.env['res.partner'].create({
            'name': 'Bob Test',
            'phone': '+15551234567',
        })
        cls.partner2 = cls.env['res.partner'].create({
            'name': 'Alice Other',
            'phone': '+15559876543',
        })

    # ───────────────────────── match_type ─────────────────────────

    def test_keyword_match(self):
        rule = self.Rule.create({
            'name': 'kw',
            'match_type': 'keyword',
            'match_value': 'refund, return',
            'target_model': 'crm.lead',
            'auto_reply_template': 'Got it {{partner_name}}.',
        })
        self.assertTrue(rule._matches('I need a refund please', self.partner, ''))
        self.assertTrue(rule._matches('please RETURN', self.partner, ''))
        self.assertFalse(rule._matches('something else', self.partner, ''))

    def test_regex_match(self):
        rule = self.Rule.create({
            'name': 're',
            'match_type': 'regex',
            'match_value': r'order\s+#?\d{4,}',
            'target_model': 'crm.lead',
        })
        self.assertTrue(rule._matches('about order 12345', self.partner, ''))
        self.assertTrue(rule._matches('Order #98765 status?', self.partner, ''))
        self.assertFalse(rule._matches('order 12', self.partner, ''))

    def test_sender_pattern_match(self):
        rule = self.Rule.create({
            'name': 'sender',
            'match_type': 'sender_pattern',
            'match_value': r'^\+1555',
            'target_model': 'crm.lead',
        })
        self.assertTrue(rule._matches('hi', self.partner, '+15551234567'))
        self.assertFalse(rule._matches('hi', self.partner, '+919876543210'))

    def test_unknown_sender_match(self):
        rule = self.Rule.create({
            'name': 'unknown',
            'match_type': 'unknown_sender',
            'target_model': 'crm.lead',
        })
        self.assertTrue(rule._matches('hi', None, '+919876543210'))
        self.assertFalse(rule._matches('hi', self.partner, '+15551234567'))

    # ───────────────────────── constraints ─────────────────────────

    def test_empty_match_value_rejected(self):
        for mt in ('regex', 'keyword', 'sender_pattern'):
            with self.assertRaises(ValidationError):
                self.Rule.create({
                    'name': 'bad-' + mt,
                    'match_type': mt,
                    'match_value': '',
                    'target_model': 'crm.lead',
                })

    def test_invalid_regex_rejected(self):
        with self.assertRaises(ValidationError):
            self.Rule.create({
                'name': 'bad-regex',
                'match_type': 'regex',
                'match_value': '(unclosed',
                'target_model': 'crm.lead',
            })

    def test_unknown_sender_with_partner_required_target_rejected(self):
        if 'sale.order' not in self.env:
            self.skipTest("sale.order not installed")
        with self.assertRaises(ValidationError):
            self.Rule.create({
                'name': 'impossible',
                'match_type': 'unknown_sender',
                'target_model': 'sale.order',
            })

    def test_invalid_extras_dict_rejected(self):
        with self.assertRaises(ValidationError):
            self.Rule.create({
                'name': 'bad-extras',
                'match_type': 'keyword',
                'match_value': 'x',
                'target_model': 'crm.lead',
                'target_default_vals_text': 'not a python literal {',
            })
        with self.assertRaises(ValidationError):
            self.Rule.create({
                'name': 'bad-extras-2',
                'match_type': 'keyword',
                'match_value': 'x',
                'target_model': 'crm.lead',
                'target_default_vals_text': '[1, 2, 3]',  # list, not dict
            })

    # ───────────────────────── per-target create ─────────────────────────

    def test_create_crm_lead(self):
        if 'crm.lead' not in self.env:
            self.skipTest("crm not installed")
        rule = self.Rule.create({
            'name': 'lead',
            'match_type': 'keyword',
            'match_value': 'lead',
            'target_model': 'crm.lead',
        })
        rec, replied = self.Rule._evaluate_and_create(
            self.account, self.partner, 'I want to be a lead', sender_phone='+15551234567')
        self.assertTrue(rec)
        self.assertEqual(rec._name, 'crm.lead')
        self.assertEqual(rec.partner_id, self.partner)
        # description is Html → check our plaintext2html wrap actually escaped
        self.assertIn('<p>', rec.description or '')
        self.assertFalse(replied)  # no auto_reply_template
        rule = rule.exists()
        self.assertEqual(rule.fired_count, 1)
        self.assertTrue(rule.last_fired_at)
        self.assertFalse(rule.last_error)

    def test_create_helpdesk_ticket_with_back_link(self):
        if 'helpdesk.ticket' not in self.env:
            self.skipTest("helpdesk not installed")
        self.Rule.create({
            'name': 'tkt',
            'match_type': 'keyword',
            'match_value': 'broken',
            'target_model': 'helpdesk.ticket',
        })
        # Need a channel for the back-link path
        channel = self.env['discuss.channel'].create({
            'name': '+15551234567',
            'channel_type': 'whatsapp',
            'whatsapp_number': '+15551234567',
            'whatsapp_partner_id': self.partner.id,
            'owa_account_id': self.account.id,
        })
        rec, _replied = self.Rule._evaluate_and_create(
            self.account, self.partner, 'My device is broken',
            channel=channel, sender_phone='+15551234567')
        self.assertTrue(rec)
        # Channel got the back-link
        self.assertEqual(channel.helpdesk_ticket_id_int, rec.id)

    def test_create_sale_order_unknown_sender_skipped(self):
        if 'sale.order' not in self.env:
            self.skipTest("sale not installed")
        # Setting up via direct write to bypass the @api.constrains that
        # would reject this at save (we want to test the run-time guard).
        rule = self.Rule.create({
            'name': 'so',
            'match_type': 'keyword',
            'match_value': 'order',
            'target_model': 'sale.order',
        })
        # Unknown sender: rule should not fire (returns False, False)
        rec, replied = self.Rule._evaluate_and_create(
            self.account, False, 'I want to order something', sender_phone='+15550000999')
        self.assertFalse(rec)
        self.assertFalse(replied)
        rule = rule.exists()
        self.assertEqual(rule.fired_count, 0)

    def test_create_hr_applicant_uses_correct_fields(self):
        if 'hr.applicant' not in self.env:
            self.skipTest("hr_recruitment not installed")
        self.Rule.create({
            'name': 'applicant',
            'match_type': 'keyword',
            'match_value': 'apply, applying, candidate',
            'target_model': 'hr.applicant',
        })
        rec, _r = self.Rule._evaluate_and_create(
            self.account, self.partner, 'I would like to apply for the role',
            sender_phone='+15551234567')
        self.assertTrue(rec)
        # The bug we fixed: partner_name is the rec_name, not name
        self.assertEqual(rec.partner_name, self.partner.name)
        # No bogus 'description' field write (would have raised before fix)
        # applicant_notes (Html) should contain our wrapped body
        self.assertIn('<p>', rec.applicant_notes or '')

    # ───────────────────────── once_per_partner ─────────────────────────

    def test_once_per_partner_dedupe_within_window(self):
        if 'crm.lead' not in self.env:
            self.skipTest("crm not installed")
        self.Rule.create({
            'name': 'opp',
            'match_type': 'keyword',
            'match_value': 'help',
            'target_model': 'crm.lead',
            'once_per_partner': True,
        })
        rec1, _ = self.Rule._evaluate_and_create(
            self.account, self.partner, 'help')
        rec2, _ = self.Rule._evaluate_and_create(
            self.account, self.partner, 'help again')
        self.assertEqual(rec1, rec2)  # 2nd call returns the existing record

    def test_once_per_partner_doesnt_block_different_partner(self):
        if 'crm.lead' not in self.env:
            self.skipTest("crm not installed")
        self.Rule.create({
            'name': 'opp2',
            'match_type': 'keyword',
            'match_value': 'help',
            'target_model': 'crm.lead',
            'once_per_partner': True,
        })
        rec1, _ = self.Rule._evaluate_and_create(self.account, self.partner, 'help')
        rec2, _ = self.Rule._evaluate_and_create(self.account, self.partner2, 'help')
        self.assertNotEqual(rec1, rec2)

    # ───────────────────────── priority + scoping ─────────────────────────

    def test_priority_first_match_wins(self):
        if 'crm.lead' not in self.env:
            self.skipTest("crm not installed")
        r_low = self.Rule.create({
            'name': 'low-prio', 'priority': 1,
            'match_type': 'keyword', 'match_value': 'common',
            'target_model': 'crm.lead',
            'auto_reply_template': 'low',
        })
        r_high = self.Rule.create({
            'name': 'high-prio', 'priority': 99,
            'match_type': 'keyword', 'match_value': 'common',
            'target_model': 'crm.lead',
            'auto_reply_template': 'high',
        })
        rec, replied = self.Rule._evaluate_and_create(
            self.account, self.partner, 'something common', sender_phone='+15551234567')
        self.assertTrue(rec)
        self.assertTrue(replied)
        # Low priority (1) fires first; check via fired_count
        self.assertEqual(r_low.exists().fired_count, 1)
        self.assertEqual(r_high.exists().fired_count, 0)

    def test_account_scoping(self):
        if 'crm.lead' not in self.env:
            self.skipTest("crm not installed")
        account2 = self.Account.create({
            'name': 'test-account-2',
            'sidecar_url': 'http://localhost:9999',
            'webhook_secret': 'secret-2',
        })
        rule_acct1 = self.Rule.create({
            'name': 'r1', 'wa_account_id': self.account.id,
            'match_type': 'keyword', 'match_value': 'go',
            'target_model': 'crm.lead',
        })
        # Inbound on account 2 → rule scoped to account 1 must NOT fire
        rec, _r = self.Rule._evaluate_and_create(
            account2, self.partner, 'go please')
        self.assertFalse(rec)
        self.assertEqual(rule_acct1.fired_count, 0)
        # Inbound on account 1 → fires
        rec, _r = self.Rule._evaluate_and_create(
            self.account, self.partner, 'go please')
        self.assertTrue(rec)

    # ───────────────────────── auto-reply ─────────────────────────

    def test_auto_reply_creates_outbound_message_and_replied_flag(self):
        self.Rule.create({
            'name': 'reply',
            'match_type': 'keyword', 'match_value': 'hi',
            'target_model': 'crm.lead' if 'crm.lead' in self.env else 'project.task',
            'auto_reply_template': 'Hello {{partner_name}}, thanks!',
        })
        before = self.Message.search_count([])
        _rec, replied = self.Rule._evaluate_and_create(
            self.account, self.partner, 'hi there', sender_phone='+15551234567')
        after = self.Message.search_count([])
        self.assertTrue(replied)
        self.assertEqual(after - before, 1)
        msg = self.Message.search([], order='id desc', limit=1)
        self.assertIn('Hello Bob Test', msg.body)

    def test_auto_reply_works_for_unknown_sender(self):
        self.Rule.create({
            'name': 'reply-unknown',
            'match_type': 'unknown_sender',
            'target_model': 'crm.lead' if 'crm.lead' in self.env else 'project.task',
            'auto_reply_template': 'Hello {{partner_name}}, we received your message.',
        })
        _rec, replied = self.Rule._evaluate_and_create(
            self.account, False, 'anything', sender_phone='+15559998888')
        self.assertTrue(replied)
        msg = self.Message.search([], order='id desc', limit=1)
        # {{partner_name}} → 'there' fallback when partner is False
        self.assertIn('Hello there', msg.body)
        self.assertEqual(msg.mobile_number, '+15559998888')

    def test_unknown_placeholder_passes_through_with_warning(self):
        # Just check rendering doesn't crash with unknown placeholders
        rule = self.Rule.create({
            'name': 'unk-pl',
            'match_type': 'keyword', 'match_value': 'x',
            'target_model': 'crm.lead' if 'crm.lead' in self.env else 'project.task',
            'auto_reply_template': 'Hello {{partner_name}}, see {{some_unknown}}',
        })
        out = rule._render_template(
            rule.auto_reply_template, self.partner, None, '+15551234567', self.account)
        self.assertIn('Hello Bob Test', out)
        self.assertIn('{{some_unknown}}', out)  # left as-is

    # ───────────────────────── group-chat guard ─────────────────────────

    def test_group_chat_skipped_by_default(self):
        if 'crm.lead' not in self.env:
            self.skipTest("crm not installed")
        rule = self.Rule.create({
            'name': 'g',
            'match_type': 'keyword', 'match_value': 'urgent',
            'target_model': 'crm.lead',
            'fire_in_groups': False,
        })
        rec, _r = self.Rule._evaluate_and_create(
            self.account, self.partner, 'urgent issue', is_group=True)
        self.assertFalse(rec)
        self.assertEqual(rule.fired_count, 0)

    def test_group_chat_fires_when_opted_in(self):
        if 'crm.lead' not in self.env:
            self.skipTest("crm not installed")
        rule = self.Rule.create({
            'name': 'g-on',
            'match_type': 'keyword', 'match_value': 'urgent',
            'target_model': 'crm.lead',
            'fire_in_groups': True,
        })
        rec, _r = self.Rule._evaluate_and_create(
            self.account, self.partner, 'urgent issue', is_group=True)
        self.assertTrue(rec)
        self.assertEqual(rule.exists().fired_count, 1)

    # ───────────────────────── ReDoS mitigation ─────────────────────────

    def test_body_truncated_before_regex(self):
        rule = self.Rule.create({
            'name': 'redos',
            'match_type': 'regex',
            'match_value': 'NEEDLE',
            'target_model': 'crm.lead' if 'crm.lead' in self.env else 'project.task',
        })
        # 10 KB body — should still match if NEEDLE is in the first 4 KB
        body = ('x' * 100) + 'NEEDLE' + ('y' * 10000)
        self.assertTrue(rule._matches(body, self.partner, ''))
        # NEEDLE past the 4 KB cap → should NOT match (truncation guard)
        body2 = ('z' * 5000) + 'NEEDLE'
        self.assertFalse(rule._matches(body2, self.partner, ''))

    # ───────────────────────── observability ─────────────────────────

    def test_error_count_increments_on_create_failure(self):
        rule = self.Rule.create({
            'name': 'will-fail',
            'match_type': 'keyword', 'match_value': 'fail',
            'target_model': 'crm.lead' if 'crm.lead' in self.env else 'project.task',
            # Inject a bad value that crm.lead create() will reject
            'target_default_vals_text': "{'user_id': 99999999}",
        })
        _rec, _r = self.Rule._evaluate_and_create(
            self.account, self.partner, 'fail please')
        rule = rule.exists()
        self.assertGreaterEqual(rule.error_count, 1)
        self.assertTrue(rule.last_error)
