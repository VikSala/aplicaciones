"""Shared test fixtures + sidecar mock for open_whatsapp_connector tests."""
from contextlib import contextmanager
from unittest.mock import patch

from odoo.tests.common import TransactionCase


class OwaTestCase(TransactionCase):
    """Base test case providing a fixture WhatsApp account with the sidecar
    mocked out, so tests don't need a live Node.js process."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Account = cls.env['owa.account']
        cls.Message = cls.env['owa.message']
        # A fixture connected account so message-send paths can run.
        admin_user = cls.env.ref('base.user_admin')
        cls.account = cls.Account.create({
            'name': 'test-account',
            'sidecar_url': 'http://localhost:9999',
            'session_state': 'connected',
            'phone_number': '+15550000000',
            'webhook_secret': 'fixture-secret',
            'notify_user_ids': [(6, 0, [admin_user.id])],
        })

    @contextmanager
    def mock_sidecar(self, returns=None, side_effect=None):
        """Patch BaileysApi._request so no real HTTP fires.

        :param returns: dict to return from every _request call (default
            ``{'message_id': 'mock-uid'}``)
        :param side_effect: optional callable for per-call behavior
        """
        target = 'odoo.addons.open_whatsapp_connector.tools.baileys_api.BaileysApi._request'
        kwargs = {}
        if side_effect is not None:
            kwargs['side_effect'] = side_effect
        else:
            kwargs['return_value'] = returns if returns is not None else {'message_id': 'mock-uid'}
        with patch(target, **kwargs) as p:
            yield p
