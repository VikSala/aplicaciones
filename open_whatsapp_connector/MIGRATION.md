# Migration notes

## 19.0.2.x → 19.0.26.0.0

This release ships **six major upgrades** (Phases 21 → 26) bundled into one
free upgrade for existing customers. All schema changes happen automatically
on `-u open_whatsapp_connector`; no manual SQL is required.

### New tables (Phases 21–26)

| Table | Phase | Purpose |
|---|---|---|
| `owa_call_log` | 21 | Inbound voice/video call audit log |
| `owa_inbound_rule` | 22C | Auto-create CRM lead / ticket / SO from inbound |
| `owa_satisfaction_score` | 23B | CSAT scores from survey responses |
| `owa_broadcast_group` | 25A | Saved recipient lists with per-recipient session isolation |
| `owa_standing_order` | 25B | Recurring schedule (daily/weekly/monthly) for templates |
| `owa_status_broadcast` | 25C | WhatsApp Status / Stories with 24h expiry |
| `owa_group_session` | 25D | Per-group state record |
| `owa_health_issue` | 25G | Granular per-account health-issue rows |
| `owa_channel_label` | 26B | Color-coded conversation labels |
| `owa_tag_rule` | 26E | Auto-tag rules on inbound messages |

### New columns on existing models

- `owa.account`: `auto_reply_on_missed_call`, `missed_call_reply_template`,
  `sla_minutes`, `auto_csat`, `csat_minimum_score`, `default_project_id_int`,
  `messages_per_minute`, `messages_per_hour`, `messages_per_day`,
  `throttle_preset`, `throttle_backoff_until`, `auto_sync_avatars`
- `discuss.channel`: `assignee_id`, `crm_team_id_int`, `helpdesk_ticket_id_int`,
  `triage_state`, `sla_due_at`, `assigned_at`, `resolved_at`, `sla_breached`,
  `wa_label_ids`
- `owa.message`: `wa_reactions_json`
- `res.partner`: `owa_call_count`, `owa_call_log_ids`, `owa_wa_link`,
  `owa_wa_call_link`, `owa_wa_video_link`, `wa_is_opted_in`, `wa_opt_in_at`,
  `wa_opt_in_source`

### New crons

- `WhatsApp: Check Triage SLA` (every 5 min)
- `WhatsApp: Dispatch Standing Orders` (every 15 min)
- `WhatsApp: Expire Status Broadcasts` (hourly)
- `WhatsApp: Refresh Partner Avatars` (daily)

### New webhook

- `/open_whatsapp_connector/webhook/call` — sidecar forwards Baileys
  `call` events here. Idempotent on `(wa_account_id, call_id)`.

### Sidecar changes

- `sock.ev.on('call')` subscribed; events forwarded to the new `/webhook/call`
- `forwardCallEvent()` helper added to `session-manager.ts`

After upgrade, **rebuild the sidecar**:

```bash
cd <addon>/sidecar
npm install
npm run build
```

Then restart the Odoo service so the child sidecar process loads the new build.

### New menus (under WhatsApp)

- Calls (Phase 21)
- CSAT (Phase 23B)
- Marketing → Broadcast Groups (Phase 25A)
- Marketing → Standing Orders (Phase 25B)
- Marketing → Status Broadcasts (Phase 25C)
- Configuration → Inbound Rules (Phase 22C)
- Configuration → Auto-tag Rules (Phase 26E)
- Configuration → Labels (Phase 26B)
- Configuration → Health Issues (Phase 25G)

### Cross-app references

Cross-app links are stored as plain integer fields (`crm_team_id_int`,
`helpdesk_ticket_id_int`, `target_team_id_int`, `target_stage_id_int`,
`default_project_id_int`, `survey_user_input_id_int`) so the addon installs
even when crm/helpdesk/survey/project are not installed. Future glue addons
(`open_whatsapp_connector_crm`, `_helpdesk`, etc.) can populate these from
real Many2one fields they own.

### Ready-to-use template data (post_init seed)

12 sales templates (`Quote Sent`, `Quote Expiring`, `Order Confirmed/Shipped/
Delivered`, `Invoice Sent/Overdue/Paid/Refund`, `Returning Customer`),
3 dunning templates, 4 recruitment templates — created as `owa.quick.reply`
records with `noupdate="1"` so user edits are preserved.

## 19.0.1.x → 19.0.2.0.0

This release ships 12 phases of feature work plus 9 phases of platform-fit
improvements. All schema additions happen automatically on
`-u open_whatsapp_connector`; no manual SQL is required. The
`migrations/19.0.2.0.0/post-migrate.py` hook verifies the new tables landed
and logs a warning if anything is missing.

### New tables

| Table | Phase | Purpose |
|---|---|---|
| `owa_inbound_dedupe` | 2 | Atomic dedupe keys for inbound webhook retries |
| `owa_allowlist_entry` | 5 | Per-account DM allowlist |
| `owa_pending_pair` | 7 | Pending pairing approval queue |
| `owa_slash_command` | 9 | Pluggable `/command` registry |

### New columns on existing models

- `owa.account`: `media_max_mb`, `text_chunk_limit`, `chunk_mode`, `reaction_level`,
  `ack_reaction_emoji`, `ack_reaction_dm`, `ack_reaction_group`,
  `remove_ack_after_reply`, `send_read_receipts`, `self_chat_mode`,
  `reply_to_mode`, `dm_policy`, `group_policy`, `group_allow_jids`,
  `group_intro_message`, `last_seen_dt`, `is_listening`, `health_status`,
  `display_name`, `label`, `enabled`, `auth_dir`
- `discuss.channel`: `is_whatsapp_group`, `require_mention`, `group_intro_sent`
- `owa.message`: `reply_to_mode_override`
- `owa.notification.rule`, `owa.auto.reply`, `owa.campaign`: `reply_to_mode_override`

### New crons

- `WhatsApp: GC Inbound Dedupe` (weekly)
- `WhatsApp: Expire Pending Pair Requests` (every 10 min)
- `WhatsApp: Account Heartbeat` (every 5 min)

### New menus (under WhatsApp)

- Dashboard (landing page, sequence 5)
- Configuration → DM Allowlist
- Configuration → Pending Approvals
- Configuration → Slash Commands

### New chatter on rule / approval models

`owa.notification.rule`, `owa.auto.reply`, `owa.chatbot`, `owa.pending.pair`
now inherit `mail.thread` and gain `<chatter/>` in their forms — historical
records will start tracking from this version forward.

### Sidecar changes

- `messages.update` event handler forwards delivery / read receipts to the
  Odoo `/webhook/status` endpoint so campaign Delivered / Read counters
  actually move (Phase: pre-Phase-12 fix).
- Per-session `sendReadReceipts` flag honoured by the sidecar; toggleable
  live via `/session/<id>/config`.
- New routes: `/send/poll`, `/send/contact`, `/session/<id>/config`.

After upgrade, **rebuild the sidecar**:

```bash
cd <addon>/sidecar
npm install
npm run build
```

Then restart the Odoo service so its child sidecar picks up the rebuilt
`dist/` output.

## Earlier versions

This is the first formal `MIGRATION.md`. Version `19.0.1.1.0` was the
post-port-from-18.0 baseline; releases between then and `19.0.2.0.0` were
incremental fixes documented in commit messages on the `19.0` branch.
