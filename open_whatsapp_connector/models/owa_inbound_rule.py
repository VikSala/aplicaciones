"""Phase 22C: Inbound → auto-create record rule engine.

Generalises chatbot's "create CRM lead" capability into a configurable
rule that can target any installed Odoo model. Rules evaluate in priority
order; the first match fires and the rest are skipped per inbound.

Phase 27B audit-fix pass: short-circuit duplicate replies, multi-company
correctness, regex DoS mitigation, observability, group-chat handling,
hr.applicant field correctness, Html-safe descriptions, and structural
constraints (no empty match_value, no unknown_sender+partner-required
target, no archived assignee).
"""
import ast
import logging
import re
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError
from odoo.tools import plaintext2html

_logger = logging.getLogger(__name__)


# Targets that hard-require partner_id (rule cannot fire on unknown senders).
_PARTNER_REQUIRED_TARGETS = {'sale.order'}

# Max body length re.search is allowed to scan — caps ReDoS impact.
_REGEX_BODY_TRUNCATE = 4096

# Default once_per_partner dedupe window. Rules can override via constants
# on a target-by-target basis (see _once_per_partner_domain).
_DEDUPE_WINDOW_DAYS = 30

# Cache compiled regex objects across calls; bounded so an admin pasting
# 1000 distinct patterns can't OOM us.
_REGEX_CACHE = {}
_REGEX_CACHE_CAP = 512


def _compile_regex(pattern, flags=0):
    """Compile-and-cache a regex pattern. Returns None on re.error."""
    if not pattern:
        return None
    key = (pattern, flags)
    if key in _REGEX_CACHE:
        return _REGEX_CACHE[key]
    try:
        compiled = re.compile(pattern, flags)
    except re.error:
        return None
    if len(_REGEX_CACHE) >= _REGEX_CACHE_CAP:
        _REGEX_CACHE.clear()
    _REGEX_CACHE[key] = compiled
    return compiled


class OwaInboundRule(models.Model):
    _name = 'owa.inbound.rule'
    _description = 'WhatsApp Inbound Auto-create Rule'
    _inherit = ['mail.thread']
    _order = 'priority asc, id'

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    priority = fields.Integer(default=10, tracking=True,
        help="Rules evaluated low to high; first match wins. "
             "Tie-break is by id (oldest rule wins).")
    wa_account_id = fields.Many2one(
        'owa.account', string="Account",
        help="Restrict rule to a single account, or leave blank for any "
             "account in the same company.")
    company_id = fields.Many2one(
        'res.company', default=lambda self: self.env.company, index=True,
        help="Company this rule belongs to. Created records inherit this "
             "company.")

    match_type = fields.Selection([
        ('regex',          'Regex on body'),
        ('keyword',        'Any keyword (comma-separated)'),
        ('sender_pattern', 'Sender phone pattern'),
        ('unknown_sender', 'Unknown sender (no res.partner match)'),
    ], string="Match", default='keyword', required=True, tracking=True)
    match_value = fields.Text(
        string="Match value",
        help="• regex: a Python regex string (case-insensitive)\n"
             "• keyword: comma-separated keywords (any-of, case-insensitive)\n"
             "• sender_pattern: regex on the caller phone digits\n"
             "• unknown_sender: leave blank")

    target_model = fields.Selection(
        selection='_selection_target_model',
        string="Target", required=True, default='crm.lead', tracking=True,
    )
    # Cross-app references stored as plain ints so the rule installs even
    # without crm/etc. Cross-app glue addons can populate these.
    target_team_id_int = fields.Integer(
        string="Target team id",
        help="Numeric id of a crm.team / helpdesk.team record, when those "
             "modules are installed. Validated against the live table at "
             "fire time — if the id no longer exists it is silently dropped.")
    target_user_id = fields.Many2one(
        'res.users', string="Assignee",
        domain=[('active', '=', True), ('share', '=', False)],
        help="Active internal user the new record is assigned to. Archived "
             "users are excluded from the picker; if the saved user becomes "
             "archived later it is silently dropped at fire time.")
    target_stage_id_int = fields.Integer(
        string="Target stage id",
        help="Numeric id of a crm.stage / helpdesk.stage record. Validated "
             "before injection — missing id is silently dropped.")
    target_project_id_int = fields.Integer(
        string="Target project id",
        help="Numeric id of a project.project record (project.task target "
             "only). Falls back to the account's default_project_id_int.")
    target_job_id_int = fields.Integer(
        string="Target job id",
        help="Numeric id of an hr.job record (hr.applicant target only). "
             "Required for hr.applicant rules in most recruitment setups.")
    target_default_vals_text = fields.Text(
        string="Extra defaults",
        help="Python literal dict of extra create() values, e.g.\n"
             "{'priority': '2', 'tag_ids': [(4, 5)]}\n\n"
             "Validated at save — invalid Python or non-dict values are "
             "rejected.")

    auto_reply_template = fields.Text(
        string="Auto-reply template",
        help="Optional WhatsApp text reply queued after the record is created. "
             "Supports placeholders: {{partner_name}}, {{record_name}}, "
             "{{record_id}}, {{sender_phone}}, {{account_name}}. Empty "
             "{{partner_name}} renders as 'there'.")
    once_per_partner = fields.Boolean(
        string="Once per partner", default=True,
        help=("If checked, won't fire again for the same partner if a "
              "matching record already exists. The dedupe is scoped to:\n"
              "• same rule + same partner\n"
              "• records active (not archived)\n"
              "• created within the last %d days\n"
              "• target-specific state (e.g. sale.order in draft/sent only)"
              ) % _DEDUPE_WINDOW_DAYS)
    fire_in_groups = fields.Boolean(
        string="Fire in groups", default=False,
        help="By default rules only evaluate on 1-on-1 chats. Enable to "
             "evaluate inbound from WhatsApp groups too — useful for "
             "keyword triage in support groups.")

    # ─── Observability ────────────────────────────────────────────────
    fired_count = fields.Integer(default=0, readonly=True)
    error_count = fields.Integer(default=0, readonly=True,
        help="How many times the create() raised since this rule was created.")
    last_fired_at = fields.Datetime(readonly=True)
    last_error = fields.Text(readonly=True,
        help="Last exception swallowed by the create() guard. Cleared on "
             "the next successful fire.")

    @api.model
    def _selection_target_model(self):
        """Filtered to installed apps so options gracefully degrade."""
        candidates = [
            ('crm.lead',        _('CRM Lead')),
            ('helpdesk.ticket', _('Helpdesk Ticket')),
            ('sale.order',      _('Sale Order (draft)')),
            ('project.task',    _('Project Task')),
            ('hr.applicant',    _('Recruitment Applicant')),
        ]
        return [(m, lbl) for m, lbl in candidates if m in self.env]

    # ─── Constraints ──────────────────────────────────────────────────

    @api.constrains('match_type', 'match_value')
    def _check_match_value_not_empty(self):
        """Empty match_value on regex/keyword/sender_pattern would match
        every inbound — guard against the silent foot-gun."""
        for r in self:
            if r.match_type in ('regex', 'keyword', 'sender_pattern'):
                if not (r.match_value or '').strip():
                    raise ValidationError(_(
                        "Match value is required for match type '%s'.",
                        dict(r._fields['match_type'].selection).get(r.match_type)))

    @api.constrains('match_type', 'match_value')
    def _check_regex_compiles(self):
        """Reject regexes that won't compile so admins find out at save time
        instead of at first inbound."""
        for r in self:
            if r.match_type in ('regex', 'sender_pattern') and r.match_value:
                try:
                    re.compile(r.match_value)
                except re.error as e:
                    raise ValidationError(_(
                        "Invalid regular expression for rule '%s': %s",
                        r.name, str(e)))

    @api.constrains('match_type', 'target_model')
    def _check_unknown_sender_compatible(self):
        """unknown_sender + target requiring partner_id is structurally
        impossible — would always silently skip. Reject at save."""
        for r in self:
            if (r.match_type == 'unknown_sender'
                    and r.target_model in _PARTNER_REQUIRED_TARGETS):
                raise ValidationError(_(
                    "Rule '%s' cannot match 'unknown sender' AND target '%s' "
                    "(this target requires a known partner). Pick a different "
                    "match type or a different target.", r.name, r.target_model))

    @api.constrains('target_default_vals_text')
    def _check_extras_is_dict(self):
        """Reject bad Python at save time so the admin catches the typo
        immediately, not 5 minutes later in the log."""
        for r in self:
            txt = (r.target_default_vals_text or '').strip()
            if not txt:
                continue
            try:
                value = ast.literal_eval(txt)
            except (SyntaxError, ValueError) as e:
                raise ValidationError(_(
                    "Extra defaults for rule '%s' is not a valid Python "
                    "literal: %s", r.name, str(e)))
            if not isinstance(value, dict):
                raise ValidationError(_(
                    "Extra defaults for rule '%s' must be a dict, got %s.",
                    r.name, type(value).__name__))

    # ─── Match logic ──────────────────────────────────────────────────

    def _matches(self, body, partner, sender_phone):
        self.ensure_one()
        if not self.active:
            return False
        # Truncate body before any regex scan to cap ReDoS exposure to a
        # bounded ~4 KB worst case per inbound.
        body_truncated = (body or '')[:_REGEX_BODY_TRUNCATE]
        if self.match_type == 'regex':
            pattern = _compile_regex(self.match_value or '', re.I)
            if pattern is None:
                return False
            try:
                return bool(pattern.search(body_truncated))
            except Exception:
                return False
        if self.match_type == 'keyword':
            keywords = [k.strip().lower() for k in (self.match_value or '').split(',') if k.strip()]
            text = body_truncated.lower()
            return any(k in text for k in keywords)
        if self.match_type == 'sender_pattern':
            pattern = _compile_regex(self.match_value or '', 0)
            if pattern is None:
                return False
            try:
                return bool(pattern.search(sender_phone or ''))
            except Exception:
                return False
        if self.match_type == 'unknown_sender':
            return not partner
        return False

    # ─── Vals builders (per target) ───────────────────────────────────

    def _resolve_int_fk(self, model_name, raw_id):
        """Return raw_id only if it points at a live record on `model_name`.
        Returns 0 if missing/uninstalled so vals can drop it cleanly."""
        if not raw_id or model_name not in self.env:
            return 0
        rec = self.env[model_name].sudo().browse(raw_id).exists()
        return raw_id if rec else 0

    def _render_template(self, template, partner, rec, sender_phone, account):
        """Tiny placeholder renderer. Unknown placeholders are left as-is
        with a single warning log so admins notice in development."""
        if not template:
            return ''
        partner_name = (partner.name if partner else None) or _('there')
        record_name = ''
        record_id = ''
        if rec is not None and rec.exists():
            try:
                record_name = rec.display_name or ''
                record_id = str(rec.id)
            except Exception:
                pass
        substitutions = {
            '{{partner_name}}': partner_name,
            '{{record_name}}':  record_name,
            '{{record_id}}':    record_id,
            '{{sender_phone}}': sender_phone or '',
            '{{account_name}}': (account.name if account else '') or '',
        }
        out = template
        for k, v in substitutions.items():
            out = out.replace(k, v)
        # Detect any unsubstituted {{var}} and warn — helps admins fix typos.
        leftover = re.findall(r'\{\{[a-zA-Z_]+\}\}', out)
        if leftover:
            _logger.warning(
                "Inbound rule '%s' auto-reply has unresolved placeholders: %s",
                self.name, leftover)
        return out

    def _build_create_vals(self, partner, body, channel, sender_phone=None):
        """Build a create() dict for the target model. Per-target field
        normalisation is centralised here; descriptions are Html-escaped
        because crm.lead / helpdesk.ticket / project.task all use Html
        fields and a raw body containing '<' breaks rendering and risks
        XSS."""
        self.ensure_one()
        vals = {}
        # plaintext2html converts to safe <p>...</p> with <br/> for newlines
        # and escapes &/</> characters. Always wrap the inbound body before
        # storing into an Html field.
        body_html = plaintext2html(body) if body else ''
        title = body[:80] if body else _('WhatsApp inbound')

        # Resolve cross-app integer FKs ONCE, dropping any that no longer
        # point at a live record.
        team_id = self._resolve_int_fk(
            'crm.team' if self.target_model == 'crm.lead' else 'helpdesk.team',
            self.target_team_id_int,
        )
        if self.target_model == 'helpdesk.ticket' and not team_id and self.target_team_id_int:
            # fallback: maybe the int is actually a helpdesk.team in a v19 schema
            team_id = self._resolve_int_fk('helpdesk.team', self.target_team_id_int)

        if self.target_model == 'crm.lead':
            stage_id = self._resolve_int_fk('crm.stage', self.target_stage_id_int)
            vals = {
                'name':        title[:60],
                'partner_id':  partner.id if partner else False,
                'description': body_html,
                'team_id':     team_id or False,
                'user_id':     self.target_user_id.id if (self.target_user_id and self.target_user_id.active) else False,
                'stage_id':    stage_id or False,
            }
        elif self.target_model == 'helpdesk.ticket':
            stage_id = self._resolve_int_fk('helpdesk.stage', self.target_stage_id_int)
            vals = {
                'name':        title,
                'partner_id':  partner.id if partner else False,
                'description': body_html,
                'team_id':     team_id or False,
                'user_id':     self.target_user_id.id if (self.target_user_id and self.target_user_id.active) else False,
                'stage_id':    stage_id or False,
            }
        elif self.target_model == 'sale.order':
            vals = {
                'partner_id':  partner.id if partner else False,
                'origin':      _('WhatsApp: %s', (sender_phone or partner.phone or '?')),
                'user_id':     self.target_user_id.id if (self.target_user_id and self.target_user_id.active) else False,
                'team_id':     team_id or False,
            }
        elif self.target_model == 'project.task':
            project_id = self._resolve_int_fk(
                'project.project',
                self.target_project_id_int
                    or (self.wa_account_id and self.wa_account_id.default_project_id_int)
                    or 0,
            )
            vals = {
                'name':        title,
                'partner_id':  partner.id if partner else False,
                'description': body_html,
                'project_id':  project_id or False,
                'user_ids':    [(6, 0, [self.target_user_id.id])]
                                   if (self.target_user_id and self.target_user_id.active)
                                   else False,
            }
        elif self.target_model == 'hr.applicant':
            # v19 hr.applicant uses partner_name (rec_name), email_from,
            # partner_phone and applicant_notes — NOT name/description.
            job_id = self._resolve_int_fk('hr.job', self.target_job_id_int)
            vals = {
                'partner_name':   (partner.name if partner else '') or sender_phone or _('WhatsApp inbound'),
                'partner_id':     partner.id if partner else False,
                'email_from':     partner.email if partner else False,
                'partner_phone':  sender_phone or (partner.phone if partner else False),
                'applicant_notes': body_html,
                'job_id':         job_id or False,
                'user_id':        self.target_user_id.id if (self.target_user_id and self.target_user_id.active) else False,
            }
        # Inject any extra defaults the admin configured (validated at save).
        if self.target_default_vals_text:
            try:
                extras = ast.literal_eval(self.target_default_vals_text)
                if isinstance(extras, dict):
                    vals.update(extras)
            except Exception:
                # @api.constrains validates at save; should not hit here.
                _logger.exception(
                    "Inbound rule %s: target_default_vals_text re-parse failed",
                    self.name)
        # Drop only None values; False/0/'' are legitimate Odoo write values.
        return {k: v for k, v in vals.items() if v is not None}

    def _once_per_partner_domain(self, partner):
        """Build the dedupe domain. Scoped to the LAST ``_DEDUPE_WINDOW_DAYS``
        days + target-specific 'still relevant' state so stale records don't
        block fresh inbound forever."""
        cutoff = fields.Datetime.now() - timedelta(days=_DEDUPE_WINDOW_DAYS)
        base = [
            ('partner_id', '=', partner.id),
            ('create_date', '>=', cutoff),
        ]
        # Target-specific 'live' state filter.
        if self.target_model == 'sale.order':
            base += [('state', 'in', ['draft', 'sent'])]
        elif self.target_model == 'crm.lead':
            base += [('active', '=', True), ('probability', '<', 100)]
        elif self.target_model == 'helpdesk.ticket':
            base += [('active', '=', True)]
        elif self.target_model == 'project.task':
            base += [('active', '=', True)]
        elif self.target_model == 'hr.applicant':
            base += [('active', '=', True)]
        return base

    # ─── Main entry point ─────────────────────────────────────────────

    @api.model
    def _evaluate_and_create(self, account, partner, body, channel=None,
                             sender_phone=None, is_group=False):
        """Evaluate active rules against an inbound message.

        Returns ``(rec, replied)`` where ``rec`` is the created (or pre-
        existing if once-per-partner deduped) record or False, and
        ``replied`` is True when an auto-reply was queued — letting the
        webhook controller short-circuit the chatbot/auto-reply pipeline
        to avoid duplicate customer-facing messages.
        """
        rules = self.search([
            ('active', '=', True),
            '|', ('wa_account_id', '=', False),
                 ('wa_account_id', '=', account.id),
        ], order='priority asc, id asc')
        for rule in rules:
            # Group-chat guard — keyword rules in groups would create a
            # lead per message unless explicitly opted in.
            if is_group and not rule.fire_in_groups:
                continue
            if not rule._matches(body, partner, sender_phone):
                continue
            if rule.target_model not in self.env:
                continue
            # Hard guard: targets that require partner_id can't fire on
            # unknown senders. @api.constrains rejects this combo at save,
            # but legacy rules might still slip through.
            if rule.target_model in _PARTNER_REQUIRED_TARGETS and not partner:
                _logger.info(
                    "Inbound rule %s: skipped — target %s requires partner_id, sender unknown",
                    rule.name, rule.target_model,
                )
                continue
            # Wrap in the rule's company context so the created record
            # inherits the correct company.
            Target = self.env[rule.target_model].with_company(
                rule.company_id or self.env.company).sudo()

            if rule.once_per_partner and partner:
                existing = Target.search(
                    rule._once_per_partner_domain(partner), limit=1)
                if existing:
                    return existing, False

            try:
                vals = rule._build_create_vals(partner, body, channel, sender_phone=sender_phone)
                # Inject company_id when the target has one — otherwise it
                # lands in main company regardless of the rule's scope.
                if 'company_id' in Target._fields and 'company_id' not in vals:
                    vals['company_id'] = (rule.company_id or self.env.company).id
                rec = Target.create(vals)
                # Phase 27A: bi-directional helpdesk bridge back-link.
                if (rule.target_model == 'helpdesk.ticket'
                        and channel and channel.exists()):
                    try:
                        channel.sudo().helpdesk_ticket_id_int = rec.id
                        if 'wa_channel_id_int' in rec._fields:
                            rec.sudo().wa_channel_id_int = channel.id
                    except Exception:
                        _logger.exception(
                            "Inbound rule %s: helpdesk back-link failed", rule.name)
                # Audit trail on both sides.
                rule.message_post(body=_(
                    "Created %(model)s record %(name)s for inbound from %(partner)s",
                ) % {
                    'model':   rule.target_model,
                    'name':    rec.display_name or rec.id,
                    'partner': (partner and partner.display_name) or sender_phone or '?',
                })
                # Subscribe partner so they see chatter updates.
                if partner and hasattr(rec, 'message_subscribe'):
                    try:
                        rec.message_subscribe(partner_ids=[partner.id])
                    except Exception:
                        pass
                rule.sudo().write({
                    'fired_count':   rule.fired_count + 1,
                    'last_fired_at': fields.Datetime.now(),
                    'last_error':    False,
                })
                # Auto-reply: works for both known and unknown senders now.
                replied = False
                if rule.auto_reply_template:
                    mobile = sender_phone or (partner.phone if partner else '')
                    if mobile:
                        body_out = rule._render_template(
                            rule.auto_reply_template, partner, rec, sender_phone, account)
                        self.env['owa.message'].sudo().create({
                            'wa_account_id':       account.id,
                            'mobile_number':       mobile,
                            'body':                body_out,
                            'message_type':        'outbound',
                            'state':               'outgoing',
                            'whatsapp_partner_id': partner.id if partner else False,
                        })
                        replied = True
                return rec, replied
            except Exception as exc:
                _logger.exception("Inbound rule %s: create failed", rule.name)
                # Record the error on the rule so admins can see what's
                # going wrong without grepping the server log. Use a
                # savepoint so the rollback doesn't lose the error log.
                try:
                    with self.env.cr.savepoint():
                        rule.sudo().write({
                            'error_count': rule.error_count + 1,
                            'last_error':  ('%s: %s' % (type(exc).__name__, str(exc)))[:2000],
                        })
                except Exception:
                    pass
                continue
        return False, False
