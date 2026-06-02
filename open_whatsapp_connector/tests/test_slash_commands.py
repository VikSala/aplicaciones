"""Tests for slash command dispatch — Phase 9."""
from odoo.tests import tagged

from .common import OwaTestCase


@tagged('post_install', '-at_install', 'open_whatsapp_connector')
class TestSlashCommands(OwaTestCase):

    def setUp(self):
        super().setUp()
        self.Slash = self.env['owa.slash.command']

    def test_seed_commands_present(self):
        cmds = {c.command for c in self.Slash.search([])}
        self.assertIn('/help', cmds)
        self.assertIn('/menu', cmds)
        self.assertIn('/stop', cmds)
        self.assertIn('/agent', cmds)

    def test_dispatch_unknown_command(self):
        ok = self.Slash.parse_and_dispatch(self.account, '+919999990020', '/nope', None)
        self.assertFalse(ok)

    def test_dispatch_non_slash(self):
        ok = self.Slash.parse_and_dispatch(self.account, '+919999990021', 'hello', None)
        self.assertFalse(ok)

    def test_dispatch_help_queues_message(self):
        before = self.Message.search_count([])
        ok = self.Slash.parse_and_dispatch(
            self.account, '+919999990022', '/help', None,
        )
        self.assertTrue(ok)
        after = self.Message.search_count([])
        self.assertEqual(after - before, 1)

    def test_dispatch_stop_blacklists(self):
        Bl = self.env['owa.blacklist']
        before = Bl.search_count([])
        self.Slash.parse_and_dispatch(self.account, '+919999990023', '/stop', None)
        after = Bl.search_count([])
        self.assertEqual(after - before, 1)
