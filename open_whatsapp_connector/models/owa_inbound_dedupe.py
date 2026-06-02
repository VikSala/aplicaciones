from datetime import timedelta

from odoo import api, fields, models


class OwaInboundDedupe(models.Model):
    """Phase 2 — explicit inbound message deduplication.

    The sidecar already does in-memory dedupe per session, but on multi-worker
    Odoo deployments two workers can both receive the same webhook POST (when
    the sidecar retries on transient errors). A short-lived DB table keyed by
    ``msg_uid`` lets ``_process_inbound_message`` reject the second hit.
    """
    _name = 'owa.inbound.dedupe'
    _description = 'WhatsApp inbound dedupe key'
    _order = 'id desc'

    msg_uid = fields.Char(string="Message UID", required=True, index=True)
    account_id = fields.Many2one(
        'owa.account', required=True, ondelete='cascade', index=True)
    create_date = fields.Datetime(readonly=True)

    _sql_constraints = [
        ('uid_per_account_uniq',
         'UNIQUE(msg_uid, account_id)',
         'Message already processed.'),
    ]

    @api.model
    def claim(self, msg_uid, account_id):
        """Try to claim this msg_uid; return True if first-write, False if dup.

        Uses raw INSERT ... ON CONFLICT DO NOTHING RETURNING so the dedupe is
        atomic against concurrent workers. ORM ``create`` would defer the
        UNIQUE constraint check until flush and miss the race.
        """
        if not msg_uid:
            return True
        self.env.cr.execute("""
            INSERT INTO owa_inbound_dedupe (msg_uid, account_id, create_date, write_date)
            VALUES (%s, %s, NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')
            ON CONFLICT (msg_uid, account_id) DO NOTHING
            RETURNING id
        """, [msg_uid, account_id or None])
        return bool(self.env.cr.fetchone())

    @api.model
    def _cron_gc(self):
        """Drop dedupe rows older than 7 days. Inbound webhook retries always
        happen within seconds; 7d is generous and keeps the table tiny."""
        threshold = fields.Datetime.now() - timedelta(days=7)
        self.search([('create_date', '<', threshold)]).unlink()
