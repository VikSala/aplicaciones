"""post-migrate for open_whatsapp_connector 18.0.27.3.0.

The post_init_hook (_create_default_notification_rules) only runs on a FRESH
install, never on upgrade. v27.3.0 adds a `purchase.order` "Send WhatsApp"
server action and threads a `report_xmlid` into every "Send WhatsApp" server
action's code so the composer attaches the document's PDF on send. To make
those reach UPGRADING databases, re-run the (idempotent) helper here: it
creates the missing purchase.order action and refreshes any existing action
whose code lacks `report_xmlid`.

Safe to re-run.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return  # fresh install — post_init_hook already handled it
    env = api.Environment(cr, SUPERUSER_ID, {})
    try:
        from odoo.addons.open_whatsapp_connector import _create_default_notification_rules
        _create_default_notification_rules(env)
        _logger.info(
            "[owc 18.0.27.3.0] refreshed 'Send WhatsApp' server actions "
            "(purchase.order added + report_xmlid threaded)")
    except Exception:
        _logger.exception(
            "[owc 18.0.27.3.0] failed to refresh Send-WhatsApp server actions")
