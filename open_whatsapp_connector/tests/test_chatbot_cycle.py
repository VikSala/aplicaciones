"""Tests for chatbot _present_step cycle detection — Phase 11 audit fix."""
from odoo.tests import tagged

from .common import OwaTestCase


@tagged('post_install', '-at_install', 'open_whatsapp_connector')
class TestChatbotCycle(OwaTestCase):

    def test_message_step_cycle_does_not_recurse_forever(self):
        """A message-step that loops back to itself should NOT raise
        RecursionError thanks to the depth-cap + visited-set guard."""
        # Deactivate any existing active bot to satisfy the single-active rule.
        existing = self.env['owa.chatbot'].search([
            ('wa_account_id', '=', self.account.id), ('active', '=', True),
        ])
        existing.active = False

        bot = self.env['owa.chatbot'].create({
            'name': 'cycle bot',
            'wa_account_id': self.account.id,
            'active': True,
        })
        Step = self.env['owa.chatbot.step']
        s1 = Step.create({
            'chatbot_id': bot.id, 'name': 's1',
            'step_type': 'message', 'message': 'hi 1',
        })
        s2 = Step.create({
            'chatbot_id': bot.id, 'name': 's2',
            'step_type': 'message', 'message': 'hi 2',
        })
        s1.next_step_id = s2.id
        s2.next_step_id = s1.id  # cycle

        # Mock the sidecar so _send_bot_message doesn't try real HTTP.
        with self.mock_sidecar():
            try:
                s1._present_step('+919999990030')
            except RecursionError:
                self.fail("Cycle detection failed — RecursionError raised")
