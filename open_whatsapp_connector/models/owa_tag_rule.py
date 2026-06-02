"""Phase 26E: auto-tag rules. On first inbound from a partner with no tags,
evaluate active rules and apply the matching res.partner.category tags."""
import logging
import re

from odoo import api, fields, models, _

_logger = logging.getLogger(__name__)


class OwaTagRule(models.Model):
    _name = 'owa.tag.rule'
    _description = 'WhatsApp Inbound Auto-tag Rule'
    _inherit = ['mail.thread']
    _order = 'priority asc, id'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    priority = fields.Integer(default=10)
    match_type = fields.Selection([
        ('regex',   'Regex'),
        ('keyword', 'Keyword (any of, comma-separated)'),
    ], default='keyword', required=True)
    match_value = fields.Text(required=True)
    target_tag_ids = fields.Many2many(
        'res.partner.category', string="Tags to apply", required=True)
    one_shot_per_partner = fields.Boolean(
        default=True,
        help="Skip if the partner already has any tag.")
    fired_count = fields.Integer(readonly=True)

    def _matches(self, body):
        self.ensure_one()
        if not body:
            return False
        if self.match_type == 'regex':
            try:
                return bool(re.search(self.match_value or '', body, re.I))
            except re.error:
                return False
        # keyword
        keywords = [k.strip().lower() for k in (self.match_value or '').split(',') if k.strip()]
        text = body.lower()
        return any(k in text for k in keywords)

    @api.model
    def _evaluate(self, partner, body):
        if not partner:
            return False
        applied = self.env['res.partner.category']
        rules = self.search([('active', '=', True)], order='priority asc, id asc')
        for rule in rules:
            if rule.one_shot_per_partner and partner.category_id:
                # Help text promises "skip if the partner already has any
                # tag" — honour that literally (the old code only skipped when
                # the partner already carried THIS rule's own tags). (#labels)
                continue
            if rule._matches(body):
                applied |= rule.target_tag_ids
                rule.fired_count += 1
        if applied:
            partner.write({'category_id': [(4, t.id) for t in applied]})
        return applied
