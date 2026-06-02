"""Phase 25G: granular health-issue rows attached to an account.
Replaces a single aggregated `health_status` selection with per-check rows
so the UI can show *what* is wrong, not just an overall verdict."""
from odoo import api, fields, models


class OwaHealthIssue(models.Model):
    _name = 'owa.health.issue'
    _description = 'WhatsApp Account Health Issue'
    _order = 'severity desc, raised_at desc, id desc'

    wa_account_id = fields.Many2one(
        'owa.account', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, index=True)
    code = fields.Char(required=True, index=True,
        help="Stable identifier of the diagnostic check, e.g. "
             "`sidecar.unreachable`, `frames.stale`, `queue.deep`.")
    label = fields.Char(required=True)
    detail = fields.Char()
    severity = fields.Selection([
        ('info',     'Info'),
        ('warning',  'Warning'),
        ('error',    'Error'),
        ('critical', 'Critical'),
    ], default='warning', required=True)
    raised_at = fields.Datetime(default=fields.Datetime.now)
    resolved = fields.Boolean(default=False, index=True)
    resolved_at = fields.Datetime()

    _sql_constraints = [
        ('uniq_account_code',
         'unique(wa_account_id, code, resolved)',
         'Already an open issue with this code on this account.'),
    ]

    def action_resolve(self):
        self.write({'resolved': True, 'resolved_at': fields.Datetime.now()})

    @api.model
    def raise_issue(self, account, code, label, detail=None, severity='warning'):
        existing = self.search([
            ('wa_account_id', '=', account.id),
            ('code', '=', code),
            ('resolved', '=', False),
        ], limit=1)
        if existing:
            return existing
        return self.create({
            'wa_account_id': account.id,
            'code': code,
            'label': label,
            'detail': detail or '',
            'severity': severity,
        })

    @api.model
    def clear_issue(self, account, code):
        self.search([
            ('wa_account_id', '=', account.id),
            ('code', '=', code),
            ('resolved', '=', False),
        ]).action_resolve()
