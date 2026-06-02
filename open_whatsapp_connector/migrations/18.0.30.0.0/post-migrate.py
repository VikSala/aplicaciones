# -*- coding: utf-8 -*-
"""post-migrate for open_whatsapp_connector 18.0.30.0.0.

The post_init_hook (_create_default_notification_rules) only runs on a FRESH
install, never on upgrade. v30 broadens that helper from 4 to 10 ready-to-use
notification rules (adds Quotation Sent, Purchase Order Confirmed, Repair
Completed, and the stage-based CRM / Project / Helpdesk rules). Re-run the
(idempotent) helper here so upgrading databases pick up the new rules — it
skips any rule that already exists and any model that is not installed. The
paired quick-reply templates, auto-replies and Main Menu chatbot load
automatically from the data files on upgrade.

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
            "[owc 18.0.30.0.0] refreshed default notification rules "
            "(added Quotation Sent / PO Confirmed / Repair / CRM / Project / Helpdesk)")
    except Exception:
        _logger.exception(
            "[owc 18.0.30.0.0] failed to refresh default notification rules")
