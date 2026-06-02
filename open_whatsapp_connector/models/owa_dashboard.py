import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class OwaDashboard(models.AbstractModel):
    """Server-side aggregator for the WhatsApp operations dashboard.

    All KPIs are computed in a single ``get_dashboard_data`` call so the
    OWL component does one round-trip per refresh. Counts use ``read_group``
    where possible (Postgres-side aggregation) instead of Python loops.
    """
    _name = 'owa.dashboard'
    _description = 'WhatsApp Operations Dashboard (data only)'

    _MAX_DATE_RANGE_DAYS = 365

    @api.model
    def get_dashboard_data(self, date_from=None, date_to=None, account_ids=None):
        """Return a dict of all dashboard KPIs, charts, and tables.

        :param date_from: ISO date string ('YYYY-MM-DD') or None for now-30d
        :param date_to:   ISO date string or None for now
        :param account_ids: list of owa.account ids to scope, or None for all
        :return: dict with keys: counters, status_counts, messages_per_day,
                 messages_per_account, top_partners, top_failure_reasons,
                 recent_failures, account_health, filters_echo
        """
        now = fields.Datetime.now()
        if date_to:
            dt_to = fields.Datetime.from_string(date_to + ' 23:59:59') if len(date_to) == 10 else fields.Datetime.from_string(date_to)
        else:
            dt_to = now
        if date_from:
            dt_from = fields.Datetime.from_string(date_from + ' 00:00:00') if len(date_from) == 10 else fields.Datetime.from_string(date_from)
        else:
            dt_from = dt_to - timedelta(days=30)
        if (dt_to - dt_from).days > self._MAX_DATE_RANGE_DAYS:
            dt_from = dt_to - timedelta(days=self._MAX_DATE_RANGE_DAYS)

        account_domain = [('wa_account_id', 'in', account_ids)] if account_ids else []
        Message = self.env['owa.message'].sudo()
        Account = self.env['owa.account'].sudo()
        Channel = self.env['discuss.channel'].sudo()
        Campaign = self.env['owa.campaign'].sudo()
        NotificationRule = self.env['owa.notification.rule'].sudo()
        AutoReply = self.env['owa.auto.reply'].sudo()
        ChatbotSession = self.env['owa.chatbot.session'].sudo()
        CallLog = self.env['owa.call.log'].sudo()

        last_24h = now - timedelta(hours=24)
        last_7d = now - timedelta(days=7)
        range_domain = [('create_date', '>=', dt_from), ('create_date', '<=', dt_to)] + account_domain

        # ── Counters ────────────────────────────────────────────────────────
        counters = {
            'total_messages': Message.search_count(range_domain),
            'messages_sent': Message.search_count(range_domain + [
                ('message_type', '=', 'outbound'),
                ('state', 'in', ['sent', 'delivered', 'read']),
            ]),
            'messages_received': Message.search_count(range_domain + [
                ('message_type', '=', 'inbound'),
            ]),
            'messages_failed_24h': Message.search_count([
                ('create_date', '>=', last_24h),
                ('state', 'in', ['error', 'bounced']),
            ] + account_domain),
            'messages_outgoing_now': Message.search_count([
                ('state', '=', 'outgoing'),
            ] + account_domain),
            'accounts_total': Account.search_count([]),
            'accounts_connected': Account.search_count([('session_state', '=', 'connected')]),
            'accounts_disconnected': Account.search_count([('session_state', '!=', 'connected')]),
            # Sidecar process state — `sidecar_running` is a non-stored
            # computed field so we have to iterate the recordset.
            'sidecars_total': 0,
            'sidecars_running': 0,
            # Per-account detail for offline accounts so the dashboard can
            # explain WHY connectivity is degraded (WhatsApp session vs sidecar
            # process). Capped at 5 to keep the payload small.
            'disconnected_accounts_detail': self._collect_disconnected_account_detail(Account),
            'active_channels': Channel.search_count([
                ('channel_type', '=', 'whatsapp'),
                ('last_interest_dt', '>=', last_7d),
            ]),
            'campaigns_running': Campaign.search_count([('state', '=', 'sending')]),
            'notification_rules_active': NotificationRule.search_count([('active', '=', True)]),
            'auto_reply_rules_active': AutoReply.search_count([('active', '=', True)]),
            'chatbot_sessions_active': ChatbotSession.search_count([('state', '=', 'active')]),
            # Phase 21: incoming-call awareness
            'missed_calls_24h': CallLog.search_count([
                ('started_at', '>=', last_24h),
                ('state', 'in', ['missed', 'rejected', 'timeout']),
            ] + account_domain),
            'calls_total': CallLog.search_count(
                [('started_at', '>=', dt_from), ('started_at', '<=', dt_to)] + account_domain),
            'video_calls_total': CallLog.search_count(
                [('started_at', '>=', dt_from), ('started_at', '<=', dt_to),
                 ('is_video', '=', True)] + account_domain),
        }

        # Sidecar counters only apply to QR accounts — Cloud API accounts use
        # Meta's Graph API and have no sidecar, so they must not drag the
        # "Start Sidecar / All Connected" button toward a never-satisfied state.
        qr_accounts = Account.search([('connection_type', '=', 'qr')])
        counters['sidecars_total'] = len(qr_accounts)
        counters['sidecars_running'] = sum(1 for a in qr_accounts if a.sidecar_running)

        # ── Status distribution (doughnut) ─────────────────────────────────
        status_groups = Message.read_group(
            range_domain, ['state'], ['state'],
        )
        status_counts = {g['state']: g['state_count'] for g in status_groups}

        # ── Messages per day (line) ─────────────────────────────────────────
        per_day_out = Message.read_group(
            range_domain + [('message_type', '=', 'outbound')],
            ['create_date'], ['create_date:day'],
        )
        per_day_in = Message.read_group(
            range_domain + [('message_type', '=', 'inbound')],
            ['create_date'], ['create_date:day'],
        )

        def _day_series(groups):
            out = {}
            for g in groups:
                key = g.get('create_date:day') or g.get('__range', {}).get('create_date:day', {}).get('from')
                if not key:
                    continue
                out[str(key)[:10]] = g['create_date_count']
            return out

        messages_per_day = {
            'outbound': _day_series(per_day_out),
            'inbound': _day_series(per_day_in),
        }

        # ── Per-account bar ─────────────────────────────────────────────────
        per_account = Message.read_group(
            range_domain, ['wa_account_id'], ['wa_account_id'],
        )
        messages_per_account = [
            {
                'account_id': g['wa_account_id'][0] if g.get('wa_account_id') else False,
                'account_name': g['wa_account_id'][1] if g.get('wa_account_id') else 'Unknown',
                'count': g['wa_account_id_count'],
            }
            for g in per_account
        ]

        # ── Top partners by message volume (last 30d, capped at 10) ────────
        # Inbound side uses discuss.channel.whatsapp_partner_id. Exclude
        # partners whose phone matches one of our own registered WhatsApp
        # numbers — those represent the sidecar accounts themselves (e.g.
        # account-A talking to account-B), not real external contacts.
        self_digits = {
            ''.join(c for c in (acc.phone_number or '') if c.isdigit())
            for acc in Account.search([])
            if acc.phone_number
        }
        self_digits.discard('')
        partner_groups = Channel.read_group(
            [('channel_type', '=', 'whatsapp'), ('whatsapp_partner_id', '!=', False)],
            ['whatsapp_partner_id'], ['whatsapp_partner_id'],
            limit=20, orderby='whatsapp_partner_id_count desc',
        )
        top_partners = []
        Partner = self.env['res.partner'].sudo()
        for g in partner_groups:
            partner = Partner.browse(g['whatsapp_partner_id'][0])
            p_digits = ''.join(c for c in (partner.phone or '') if c.isdigit())
            if p_digits and p_digits in self_digits:
                continue
            top_partners.append({
                'partner_id': g['whatsapp_partner_id'][0],
                'name': g['whatsapp_partner_id'][1],
                'channel_count': g['whatsapp_partner_id_count'],
            })
            if len(top_partners) >= 10:
                break

        # ── Top failure reasons ─────────────────────────────────────────────
        failure_groups = Message.read_group(
            [('state', 'in', ['error', 'bounced']),
             ('create_date', '>=', last_7d)] + account_domain,
            ['failure_type'], ['failure_type'],
            limit=10, orderby='failure_type_count desc',
        )
        top_failure_reasons = [
            {
                'failure_type': g['failure_type'] or 'unknown',
                'count': g['failure_type_count'],
            }
            for g in failure_groups
        ]

        # ── Recent failures table (last 10) ────────────────────────────────
        recent_failures_recs = Message.search([
            ('state', 'in', ['error', 'bounced']),
        ] + account_domain, order='create_date desc', limit=10)
        recent_failures = [
            {
                'id': m.id,
                'mobile_number': m.mobile_number_formatted or m.mobile_number,
                'failure_type': m.failure_type or '',
                'failure_reason': m.failure_reason or '',
                'create_date': fields.Datetime.to_string(m.create_date) if m.create_date else '',
                'account_name': m.wa_account_id.name or '',
            }
            for m in recent_failures_recs
        ]

        # ── Account health ──────────────────────────────────────────────────
        account_health = []
        for account in Account.search([]):
            queue_depth = Message.search_count([
                ('wa_account_id', '=', account.id),
                ('state', '=', 'outgoing'),
            ])
            sent_24h = Message.search_count([
                ('wa_account_id', '=', account.id),
                ('create_date', '>=', last_24h),
                ('state', 'in', ['sent', 'delivered', 'read']),
            ])
            last_msg = Message.search([
                ('wa_account_id', '=', account.id),
            ], order='create_date desc', limit=1)
            account_health.append({
                'id': account.id,
                'name': account.name or '',
                'session_state': account.session_state,
                'phone_number': account.phone_number or '',
                'queue_depth': queue_depth,
                'sent_24h': sent_24h,
                'last_message_dt': fields.Datetime.to_string(last_msg.create_date) if last_msg else '',
            })

        # ── Echo of filters used (for client to confirm) ────────────────────
        filters_echo = {
            'date_from': fields.Datetime.to_string(dt_from),
            'date_to': fields.Datetime.to_string(dt_to),
            'account_ids': account_ids or [],
        }

        return {
            'counters': counters,
            'status_counts': status_counts,
            'messages_per_day': messages_per_day,
            'messages_per_account': messages_per_account,
            'top_partners': top_partners,
            'top_failure_reasons': top_failure_reasons,
            'recent_failures': recent_failures,
            'account_health': account_health,
            'filters_echo': filters_echo,
        }

    @api.model
    def action_start_sidecars(self):
        """Start every account's sidecar AND re-connect the WhatsApp
        session so the user only needs a single click to get fully online.

        Returns a dict the OWL dashboard surfaces as a notification:
        {started, already_running, failed, connected, connect_skipped,
         connect_failed} — each is a list of account names (failed/skipped
         entries include the reason).
        """
        import time
        from odoo.addons.open_whatsapp_connector.tools.sidecar_manager import (
            is_sidecar_running,
        )
        Account = self.env['owa.account'].sudo()
        accounts = Account.search([])
        started, already, failed = [], [], []
        for account in accounts:
            name = account.name or str(account.id)
            try:
                if account.sidecar_running:
                    already.append(name)
                    continue
                account.button_start_sidecar()
                started.append(name)
            except Exception as e:
                failed.append({'name': name, 'err': str(e)})

        _logger.info("action_start_sidecars: started=%s already=%s failed=%s",
                     started, already, failed)

        # Wait for freshly-started sidecars to start accepting HTTP. A cold
        # Node + gateway start on Windows can take 10-20s, so give it a
        # generous window — skipping the connect because /health wasn't up
        # yet is exactly what made the button need a second click.
        if started:
            deadline = time.time() + 20
            while time.time() < deadline:
                if all(is_sidecar_running(a.sidecar_url) for a in accounts
                       if a.name in started):
                    break
                time.sleep(1)
            _logger.info("action_start_sidecars: health-wait done, up=%s",
                         {a.name: is_sidecar_running(a.sidecar_url)
                          for a in accounts})

        connected, connect_skipped, connect_failed = [], [], []
        for account in accounts:
            name = account.name or str(account.id)
            # Skip if start failed earlier.
            if any(f['name'] == name for f in failed):
                continue
            # The shared health-wait above already polled until every started
            # sidecar accepted HTTP, so a single non-blocking check here is
            # enough. The old per-account 20s loop multiplied wall-clock by the
            # account count and pushed the request past limit_time_real (120s),
            # killing the worker with a 504. (#start_sidecar)
            if not is_sidecar_running(account.sidecar_url):
                _logger.warning("action_start_sidecars: %s sidecar not responding", name)
                connect_failed.append({'name': name, 'err': 'sidecar not responding'})
                continue
            _logger.info("action_start_sidecars: %s sidecar up, session_state=%s",
                         name, account.session_state)

            # The sidecar auto-restores saved WhatsApp sessions the moment
            # its process starts — it usually reaches 'connected' within a
            # few seconds without any help from us. Poll for that first so
            # we don't fire button_connect() into a session that's already
            # mid-restore (which would tear it down and start over).
            deadline = time.time() + 12
            while time.time() < deadline:
                try:
                    account.button_refresh_status()
                except Exception:
                    pass
                if account.session_state in (
                        'connected', 'logged_out', 'qr_pending'):
                    break
                time.sleep(1)
            _logger.info("action_start_sidecars: %s after auto-restore wait, "
                         "session_state=%s", name, account.session_state)
            if account.session_state == 'connected':
                connected.append(name)
                continue

            # Auto-restore didn't get us there (no saved creds, logged out,
            # etc.) — fall back to an explicit connect.
            if not account.enabled:
                connect_skipped.append({'name': name, 'reason': 'disabled'})
                continue
            if account.pairing_method == 'code' and not account.pairing_phone:
                connect_skipped.append({'name': name, 'reason': 'needs_pairing_phone'})
                continue
            try:
                account.button_connect()
                # button_connect() returns while the socket is still
                # 'connecting'; poll until it settles so the dashboard
                # reload right after sees the final state.
                deadline = time.time() + 12
                while (account.session_state not in ('connected', 'logged_out')
                       and time.time() < deadline):
                    time.sleep(1)
                    try:
                        account.button_refresh_status()
                    except Exception:
                        break
                _logger.info("action_start_sidecars: %s after button_connect "
                             "wait, session_state=%s", name, account.session_state)
                if account.session_state == 'connected':
                    connected.append(name)
                elif account.session_state in ('qr_pending', 'connecting'):
                    connect_skipped.append({'name': name, 'reason': account.session_state})
                else:
                    connect_failed.append({'name': name, 'err': account.session_state or 'unknown'})
            except Exception as e:
                _logger.exception("action_start_sidecars: %s button_connect raised", name)
                connect_failed.append({'name': name, 'err': str(e)})
        _logger.info("action_start_sidecars: RESULT connected=%s skipped=%s failed=%s",
                     connected, connect_skipped, connect_failed)
        return {
            'started': started,
            'already_running': already,
            'failed': failed,
            'connected': connected,
            'connect_skipped': connect_skipped,
            'connect_failed': connect_failed,
        }

    def _collect_disconnected_account_detail(self, Account, limit=5):
        """Return a small list of {name, session_state, sidecar_running, reason}
        dicts for accounts that aren't fully connected. Used by the Connected
        KPI tile so it can explain WHY connectivity is degraded — WhatsApp
        session down, sidecar process stopped, or both."""
        disconnected = Account.search(
            [('session_state', '!=', 'connected')], limit=limit,
        )
        out = []
        for acc in disconnected:
            sidecar_up = bool(acc.sidecar_running)
            wa_state = acc.session_state or 'disconnected'
            if not sidecar_up:
                reason = 'sidecar_stopped'
            elif wa_state == 'qr_pending':
                reason = 'awaiting_qr'
            elif wa_state == 'logged_out':
                reason = 'logged_out'
            elif wa_state == 'connecting':
                reason = 'connecting'
            else:
                reason = 'whatsapp_disconnected'
            out.append({
                'id': acc.id,
                'name': acc.name or '?',
                'session_state': wa_state,
                'sidecar_running': sidecar_up,
                'reason': reason,
            })
        return out
