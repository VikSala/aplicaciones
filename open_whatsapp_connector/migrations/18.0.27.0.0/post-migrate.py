"""Consolidated post-migrate for open_whatsapp_connector 18.0.27.0.0.

Layers the work of v19 migrations 19.0.2.0.0, 19.0.26.1.0, and 19.0.27.0.0
into one idempotent pass that runs on upgrades from any prior 18.0.x version.

Section A — schema sanity check (originally 19.0.2.0.0): verifies the four
new tables for Phases 0-11 (owa_inbound_dedupe, owa_allowlist_entry,
owa_pending_pair, owa_slash_command) exist after the ORM upgrade step.

Section B — notification-rule PDF defaults (originally 19.0.26.1.0): enables
PDF attachment on the shipped "Sale Order Confirmed" + "Invoice Posted"
rules, but ONLY where attach_pdf=False AND report_id=False (so manual admin
choices are preserved).

Section C — marketing-visibility owner/team backfill (originally
19.0.27.0.0): for the 5 marketing models (owa.campaign, owa.contact.list,
owa.broadcast.group, owa.standing.order, owa.status.broadcast), fills in
user_id/team_id on rows that don't have them yet — so an admin who flips
the visibility setting to 'own_team' doesn't lock anyone out of pre-existing
records.

Safe to re-run on any 18.0.x -> 18.0.27.0.0 upgrade.
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        # Fresh install — nothing to back-fill (post_init_hook handles defaults).
        return

    _logger.info("[owc 18.0.27.0.0] starting consolidated migration from %s", version)

    _migrate_schema_check(cr)
    _migrate_notification_rule_pdfs(cr)
    _migrate_marketing_owner_team(cr)

    _logger.info("[owc 18.0.27.0.0] migration complete")


# ----- Section A: from 19.0.2.0.0 -----

def _migrate_schema_check(cr):
    """Verify Phase 0-11 schema additions are present after ORM upgrade."""
    expected_tables = (
        'owa_inbound_dedupe',
        'owa_allowlist_entry',
        'owa_pending_pair',
        'owa_slash_command',
    )
    cr.execute("""
        SELECT table_name FROM information_schema.tables
         WHERE table_schema = 'public' AND table_name IN %s
    """, (expected_tables,))
    found = {r[0] for r in cr.fetchall()}
    missing = set(expected_tables) - found
    if missing:
        _logger.warning(
            "[owc] Expected tables still missing after upgrade: %s. "
            "Try restarting Odoo and running -u open_whatsapp_connector again.",
            sorted(missing),
        )
    else:
        _logger.info("[owc] All Phase 0-11 schema additions present.")


# ----- Section B: from 19.0.26.1.0 -----

_PDF_DEFAULTS = [
    ('Sale Order Confirmed', 'sale.order', 'sale.action_report_saleorder'),
    ('Invoice Posted', 'account.move', 'account.account_invoices'),
]


def _migrate_notification_rule_pdfs(cr):
    """Enable PDF attachment on the shipped default rules, idempotently."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Rule = env['owa.notification.rule']
    for rule_name, model_name, report_xmlid in _PDF_DEFAULTS:
        report = env.ref(report_xmlid, raise_if_not_found=False)
        if not report:
            continue
        # Only touch rules that still look like the shipped defaults.
        rules = Rule.search([
            ('name', '=', rule_name),
            ('model_name', '=', model_name),
            ('attach_pdf', '=', False),
            ('report_id', '=', False),
        ])
        if rules:
            rules.write({'attach_pdf': True, 'report_id': report.id})
            _logger.info(
                "[owc] enabled PDF attachment on %d '%s' rule(s) -> %s",
                len(rules), rule_name, report_xmlid,
            )


# ----- Section C: from 19.0.27.0.0 -----

_MARKETING_MODELS = (
    'owa.campaign',
    'owa.contact.list',
    'owa.broadcast.group',
    'owa.standing.order',
    'owa.status.broadcast',
)


def _migrate_marketing_owner_team(cr):
    """Backfill user_id/team_id on the 5 marketing models for the visibility toggle."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    Team = env['crm.team']

    team_cache = {}

    def _team_for(uid):
        if uid not in team_cache:
            try:
                team_cache[uid] = Team.with_user(uid)._get_default_team_id(
                    user_id=uid) or Team.browse()
            except Exception:
                team_cache[uid] = Team.browse()
        return team_cache[uid]

    for model_name in _MARKETING_MODELS:
        if model_name not in env:
            # Model didn't load — skip (e.g. feature flagged off, dep missing)
            continue
        Model = env[model_name].with_context(active_test=False)
        if 'user_id' not in Model._fields:
            continue
        records = Model.search(['|',
                                ('user_id', '=', False),
                                ('team_id', '=', False)])
        count = 0
        for rec in records:
            vals = {}
            if not rec.user_id:
                vals['user_id'] = rec.create_uid.id or SUPERUSER_ID
            if not rec.team_id and 'team_id' in Model._fields:
                team = _team_for(rec.create_uid.id or SUPERUSER_ID)
                if team:
                    vals['team_id'] = team.id
            if vals:
                rec.write(vals)
                count += 1
        if count:
            _logger.info(
                "[owc] backfilled owner/team on %d %s record(s)",
                count, model_name,
            )
