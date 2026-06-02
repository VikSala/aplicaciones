# Open WhatsApp Connector for Odoo 18

**Free WhatsApp integration for Odoo 18 using the WhatsApp Web protocol.**
No Meta Business API approval needed — just scan a QR code to connect.

> Current version: **18.0.27.0.0** — feature-parity with the v19.0.27.0.0 branch.

> **Disclaimer**: This module uses the WhatsApp Web protocol (unofficial). WhatsApp may ban numbers that use unofficial APIs. Best suited for low-volume messaging or internal use.

---

## Highlights

- **Zero cost** — no Meta Business verification, no per-conversation fees
- **QR code login** — connect in seconds, just like WhatsApp Web
- **Full Discuss integration** — WhatsApp conversations live inside Odoo Discuss
- **30+ frontend patches** — mirrors the UX of Odoo's built-in WhatsApp module
- **Interactive messages** — button messages, list menus, media headers, footers
- **Multi-account, multi-database** — visual kanban dashboard, per-account credentials
- **Sidecar management** — start/stop the WhatsApp service directly from Odoo
- **No external SaaS** — self-hosted Node.js sidecar communicates directly with WhatsApp
- **Operations Dashboard** — KPI tiles, charts, drill-through, account health
- **Voice + video call detection** — calls log, missed-call auto-reply, click-to-call buttons
- **Customer-360 timeline** — WhatsApp + calls + sale orders + invoices + helpdesk + leads + activities, chronologically interleaved
- **Automation engine** — notification rules, auto-replies, chatbots, campaigns, broadcast groups, standing orders, status broadcasts
- **CRM triage** — assignee, SLA breach activities, inbound auto-create rules (CRM lead / helpdesk ticket / sale order / project task / hr applicant)
- **Enterprise bridges** — helpdesk + CSAT survey on resolve, mass-mailing hooks, POS digital receipts, subscription dunning, recruitment auto-reply
- **Compliance** — outbound throttling (per-min/hour/day caps), opt-in tracking, STOP-keyword auto-blacklist, conversation merge wizard
- **Per-user/per-team marketing visibility** — opt-in setting restricts campaigns/contacts/broadcasts to owner + their `crm.team`; default is shared (no regression for existing customers)

---

## Architecture

```
┌──────────────────┐     HTTP/REST      ┌──────────────────┐    WhatsApp Web
│  Odoo 18         │ <───────────────>  │  Node.js Sidecar │ <──────────────> WhatsApp Servers
│  (this module)   │                    │  (WA Web Engine) │    (WebSocket)
└──────────────────┘                    └──────────────────┘
     ▲  Webhooks                             │  QR code
     │  (inbound msgs, statuses,             │  Multi-session
     │   push-based connection state)        │  Auto-reconnect
     └───────────────────────────────────────┘
```

The sidecar pushes connection-state transitions to Odoo via a webhook
(`/open_whatsapp_connector/webhook/connection`) so the kanban dashboard
flips to "Connected" within ~200 ms of QR-scan — no waiting for the
5-minute heartbeat cron.

---

## Requirements

- **Odoo 18** (Community or Enterprise)
- **Node.js 22+** — Download from [nodejs.org](https://nodejs.org/)
- **Python packages**: `phonenumbers` (declared in `external_dependencies`)
- **Odoo dependencies** (auto-installed): `mail`, `phone_validation`, `sales_team`

---

## Installation

### Step 1: Install the Odoo Module

Copy `open_whatsapp_connector/` to your Odoo addons path and install via **Apps** menu.

```bash
# Or symlink into your addons directory
ln -s /path/to/open_whatsapp_connector /path/to/odoo/addons/
```

Then in Odoo: **Apps** > search "Open WhatsApp Connector" > **Install**

### Step 2: Set Up the Sidecar Service

The sidecar is a small Node.js service that bridges Odoo and WhatsApp.

**One-Click Setup (Recommended):**

- **Windows:** Open the `sidecar/` folder and double-click `setup.bat`
- **Linux/macOS:** Run `cd sidecar && chmod +x setup.sh && ./setup.sh`

The script installs dependencies, applies patches, creates aliases, and builds automatically.

**Manual Setup:**

```bash
cd open_whatsapp_connector/sidecar
npm install                  # Install dependencies + auto-apply patches
npm run build                # Build TypeScript
```

Then create the module alias (required):

- **Windows:** `cd node_modules && mklink /J baileys @whiskeysockets\baileys`
- **Linux/macOS:** `ln -s @whiskeysockets/baileys node_modules/baileys`

### Step 3: Configure Sidecar in Odoo

1. Go to **Settings > Open WhatsApp Connector**
2. Set **Sidecar Directory** to the full path of the `sidecar/` folder (e.g. `/opt/odoo/addons/open_whatsapp_connector/sidecar`)
3. Optionally enable **Auto-start Sidecar** — this starts the sidecar automatically when you click Connect

### Step 4: Connect Your First WhatsApp Account

1. Go to **WhatsApp > Accounts** (opens the kanban dashboard)
2. Click **New**
3. Enter a name (e.g. "Sales WhatsApp")
4. Click **Start Sidecar** (green button) — or start manually via `npm start` in the sidecar folder
5. Click **Connect** — a QR code appears
6. On your phone: open **WhatsApp > Settings > Linked Devices > Link a Device**
7. Scan the QR code — status changes to **Connected**

You're done! You can now send and receive WhatsApp messages from Odoo.

### Adding More WhatsApp Numbers

Go to **WhatsApp > Accounts**, click **New**, and repeat the connect process. Each account connects a different phone number. All accounts share the same sidecar service.

### Sidecar Auto-Restore

When the sidecar restarts, it automatically reconnects all previously connected accounts. No manual re-scanning needed.

---

## Menu Structure

```
WhatsApp
├── Dashboard                             KPI tiles, charts, account health
├── Messages                              View all sent/received messages
├── Compose                               Send to any phone number (wizard)
├── Status                                Post a WhatsApp Story (24h expiry)
├── Chats
│   ├── Groups                            WhatsApp groups your accounts are in
│   ├── New Group / Join Group            Wizards to create or join groups
│   ├── Communities / New Community       WhatsApp Community + subgroups
│   └── Newsletters / New / Subscribe     WhatsApp Channels (broadcasts)
├── Calls                                 Voice + video call log per contact
├── Marketing
│   ├── Campaigns                         Bulk messaging to contact lists
│   ├── Broadcast Groups                  Saved recipient lists, per-recipient session
│   ├── Standing Orders                   Recurring scheduled sends (daily/weekly/monthly)
│   └── Status Broadcasts                 Scheduled WhatsApp Stories
├── CSAT                                  Satisfaction-survey scores per conversation
└── Configuration (Admin only)
    ├── Accounts                          Connect & manage WhatsApp numbers
    ├── Quick Replies                     Message templates (text/button/list)
    ├── Notification Rules                Auto-send on record state changes
    ├── Auto-Reply Rules                  Keyword/welcome/away auto-responses
    ├── Inbound Rules                     Auto-create CRM lead / ticket / SO / task / applicant
    ├── Blacklist                         Blocked phone numbers
    ├── DM Allowlist                      Explicit-allow DM senders (when DM policy = allowlist)
    ├── Pending Approvals                 Inbound pairing requests awaiting admin OK
    ├── Contact Lists                     Recipient groups for campaigns
    ├── Conversation Labels               Color-coded multi-tag triage
    ├── Auto-tag Rules                    Regex/keyword → res.partner.category on first inbound
    ├── Health Issues                     Per-account problem panel with severity + resolve
    ├── Chatbots                          Automated conversation flows
    ├── Chatbot Sessions                  Monitor active chatbot conversations
    ├── Slash Commands                    /help /menu /start /stop /agent registry
    └── Settings                          Global module configuration
```

---

## Settings (Configuration)

Go to **Settings > Open WhatsApp Connector** to configure global module settings.

### Sidecar Defaults

| Setting | Description |
|---------|-------------|
| **Default Sidecar URL** | URL where the sidecar runs (default: `http://localhost:3100`). New accounts inherit this. |
| **Default API Key** | Shared authentication key for sidecar. Leave empty if not using authentication. |
| **Sidecar Directory** | Full path to the `sidecar/` folder. Required for Start/Stop Sidecar buttons. |
| **Auto-start Sidecar** | When enabled, clicking "Connect" on an account will automatically start the sidecar if it's not running. |

### Contacts

| Setting | Description |
|---------|-------------|
| **Auto-create Contacts** | When a message arrives from an unknown number, automatically create a contact record in Odoo. Enabled by default. |

### Website WhatsApp Widget

| Setting | Description |
|---------|-------------|
| **Enable Widget** | Show a floating WhatsApp chat button on your website. |
| **Widget Phone Number** | The WhatsApp number visitors will message (e.g. +1234567890). |
| **Default Message** | Pre-filled message when visitors click the button. |
| **Widget Embed Code** | Auto-generated HTML code. Copy and paste into your website to add the button. |

### Marketing Visibility

| Setting | Description |
|---------|-------------|
| **Campaign & Contact Visibility** | `Shared across company` (default — everyone sees all marketing records) or `Restricted to owner + their Sales Team` (users only see records they own or where their `crm.team` matches; admins still see everything). Flips 12 toggle-able `ir.rule` rows + 6 toggle-able `ir.model.access` rows at runtime. Ships in shared mode so existing customers see zero behavioural change. |

---

## Feature Guide

### WhatsApp > Accounts

**What it does:** Manage your WhatsApp connections. Each account links one phone number to Odoo.

**Dashboard (Kanban View):** Shows all accounts as cards with:
- Account name and phone number
- Connection status badge (Connected / Disconnected / Awaiting QR Scan)
- Sidecar status badge (Running / Stopped)
- Quick action buttons: Connect, Disconnect, Refresh, Start Sidecar

**Account Form:** When you open an account, you see:
- **Quick Start Guide** — step-by-step instructions (shown for new/disconnected accounts)
- **Connection Settings** — Sidecar URL, API Key, Callback URL, Webhook Secret
- **Account Settings** — Phone number, allowed companies, users to notify, debug logging
- **QR Code** — appears when you click Connect (scan with your phone)

**Header Buttons:**

| Button | When Visible | What It Does |
|--------|-------------|--------------|
| **Connect** | When disconnected | Starts a new session, shows QR code to scan |
| **Refresh Status** | When connecting/connected | Syncs the latest session state from the sidecar |
| **Disconnect** | When connected | Pauses the connection (can reconnect without re-scanning) |
| **Logout** | When connected/disconnected | Fully deletes the session — requires re-scanning QR |
| **Test Connection** | When not connected | Checks if the sidecar service is reachable |
| **Start Sidecar** | When sidecar is stopped | Starts the Node.js sidecar service |
| **Stop Sidecar** | When sidecar is running | Stops the sidecar service (affects all accounts) |

---

### WhatsApp > Messages

**What it does:** View all WhatsApp messages sent and received across all accounts.

**List View:** Shows messages with date, phone number, type (inbound/outbound), account, and delivery status.

**Filters:** Outbound, Inbound, In Queue, Sent, Delivered, Read, Failed

**Group By:** Account, State, Type

**Message States:**

| State | Meaning |
|-------|---------|
| In Queue | Waiting to be sent (processed by cron every minute) |
| Sent | Delivered to WhatsApp servers |
| Delivered | Delivered to recipient's phone |
| Read | Recipient opened the message |
| Failed | Send error (click to see reason, can retry) |
| Cancelled | Manually cancelled before sending |

**Actions on failed messages:** Click **Resend** to retry, or **Cancel** to abandon.

---

### WhatsApp > Configuration > Quick Replies (Message Templates)

**What it does:** Create reusable message templates with variable placeholders.

**Where:** WhatsApp > Configuration > Quick Replies

**Three Template Types:**

#### Text Templates
Plain text messages with `{{variable}}` placeholders. Example:
```
Hello {{partner_name}}, your order {{record_name}} has been confirmed!
Amount: {{amount_total}} {{currency}}
```

#### Button Templates
Interactive messages with up to 3 clickable reply buttons.

| Field | Description |
|-------|-------------|
| Header | Optional: text, image, video, or document |
| Body | Message text with `{{variable}}` placeholders |
| Footer | Optional small text below the message |
| Buttons | 1-3 buttons (max 20 characters each) |

When the recipient taps a button, the response appears in Odoo as `[Button] button text`.

#### List Templates
Interactive messages with a scrollable menu.

| Field | Description |
|-------|-------------|
| Body | Message text with `{{variable}}` placeholders |
| Footer | Optional small text |
| Menu Button Text | Label on the button that opens the list (default: "Menu") |
| Sections | One or more groups, each with a title and rows |
| Rows | Each row has a title (max 24 chars) and optional description (max 72 chars). Max 10 rows total. |

When the recipient selects a row, the response appears in Odoo as `[List] row title - description`.

**Built-in Variables (auto-detected from records):**

| Variable | Source |
|----------|--------|
| `{{partner_name}}` | Customer name |
| `{{record_name}}` | Document name (e.g. SO001, INV/2024/001) |
| `{{amount_total}}` | Total amount |
| `{{currency}}` | Currency symbol (e.g. $, EUR) |
| `{{date}}` | Date (auto-detected from date_order, invoice_date, etc.) |

You can also define **custom variables** with field paths (e.g. `partner_id.email`) and default values.

**Pre-installed Templates:**
- Sale Order Confirmed
- Invoice Posted
- Delivery Completed
- Payment Received

---

### WhatsApp > Configuration > Notification Rules

**What it does:** Automatically send WhatsApp messages when a record changes state.

**Where:** WhatsApp > Configuration > Notification Rules

**How to create a rule:**

1. **Name** — e.g. "Sale Order Confirmed"
2. **Model** — select the Odoo model to watch (e.g. Sale Order, Invoice, Delivery)
3. **Trigger Field** — which field to monitor (e.g. `state`)
4. **Trigger Value** — the value that fires the rule (e.g. `sale`, `posted`, `done`)
5. **WhatsApp Account** — which account sends the message
6. **Message Template** — select a Quick Reply, or write a custom message
7. **Phone Field** — where to find the recipient's phone (default: `partner_id.phone`)

**Optional settings:**

| Setting | Description |
|---------|-------------|
| **Attach PDF** | Include a generated report (invoice PDF, delivery slip, etc.) |
| **Notify Once** | Only send one notification per record (prevents duplicates) |
| **Active** | Toggle the rule on/off directly from the list view |

**Pre-installed Rules (inactive by default):**
- Sale Order Confirmed → sends when order `state` = `sale`
- Invoice Posted → sends when invoice `state` = `posted`
- Payment Received → sends when payment `state` = `posted`

To activate: go to the list, toggle the **Active** switch, and select a WhatsApp Account.

---

### WhatsApp > Configuration > Auto-Reply Rules

**What it does:** Automatically reply to incoming WhatsApp messages.

**Where:** WhatsApp > Configuration > Auto-Reply Rules

**Trigger Types:**

| Type | When it fires |
|------|--------------|
| **Keyword** | When incoming message contains/matches specific words |
| **Welcome** | First message from a new contact |
| **Away / Out of Office** | Messages received outside business hours |
| **Reply to All** | Every incoming message gets a response |

**Key fields:**

| Field | Description |
|-------|-------------|
| **Keywords** | Comma-separated words to match (for keyword type) |
| **Match Type** | Contains, Exact Match, or Regex pattern |
| **Response Message** | The auto-reply text |
| **Business Hours** | Start/end time and working days (for away type) |
| **Cooldown (minutes)** | Minimum time between replies to the same number (prevents spam) |
| **Account** | Apply to a specific account, or leave empty for all accounts |

---

### WhatsApp > Configuration > Blacklist

**What it does:** Block specific phone numbers from receiving WhatsApp messages.

**Where:** WhatsApp > Configuration > Blacklist

**How it works:**
- Add phone numbers manually with an optional reason
- Numbers are **auto-blacklisted** when someone replies with STOP, UNSUBSCRIBE, or OPT-OUT
- Blacklisted numbers are blocked **before sending** — messages are never sent
- Campaigns automatically skip blacklisted contacts
- Click **Remove** to unblacklist a number

---

### WhatsApp > Configuration > Contact Lists

**What it does:** Create groups of contacts for bulk campaign messaging.

**Where:** WhatsApp > Configuration > Contact Lists

**How to use:**
1. Create a new list and give it a name
2. Add contacts manually (name + phone number)
3. Or click **Import from Contacts** to bulk-import all Odoo contacts that have phone numbers
4. Each contact can be linked to an Odoo partner record
5. Toggle individual contacts active/inactive to include/exclude from campaigns

---

### WhatsApp > Marketing > Campaigns

**What it does:** Send bulk WhatsApp messages to an entire contact list.

**Where:** WhatsApp > Marketing > Campaigns

**How to create a campaign:**

1. **Name** — campaign title
2. **WhatsApp Account** — must be connected
3. **Contact List** — select the recipient group
4. **Message Template** — choose a Quick Reply template, or write a custom message
5. **Attachments** — optional files to include
6. **Scheduled Date** — leave empty to send now, or set a future date/time

**Campaign Workflow:**

```
Draft → [Launch] → Sending → [Auto] → Sent
  ↓                   ↓
[Cancel]           [Cancel]
  ↓                   ↓
Cancelled ← [Reset to Draft]
```

**Statistics (visible after launch):**

| Stat | Description |
|------|-------------|
| Total | Number of messages created |
| Sent | Confirmed sent to WhatsApp |
| Delivered | Confirmed delivered to phone |
| Read | Recipient opened the message |
| Failed | Send errors |

---

### WhatsApp > Configuration > Chatbots

**What it does:** Build automated conversation flows with interactive menus.

**Where:** WhatsApp > Configuration > Chatbots

**How to create a chatbot:**

1. **Name** — chatbot identifier
2. **WhatsApp Account** — which account runs this bot
3. **Welcome Message** — greeting sent when bot starts (e.g. "Hello! How can I help you?")
4. **Session Timeout** — minutes of inactivity before session expires (default: 30)
5. **Steps** — define the conversation flow

**Step Types:**

| Type | What it does |
|------|-------------|
| **Send Message** | Send a text message, then move to the next step |
| **Show Menu** | Display numbered options (e.g. "1. Sales, 2. Support"). User replies with a number or keyword. |
| **Route to User** | Hand off the conversation to a human agent in Odoo |
| **Create Lead** | Automatically create a CRM lead from the conversation |
| **End Conversation** | Send a closing message and end the session |

**Menu Options:** Each menu step can have multiple options, each with:
- **Label** — what the user sees (e.g. "Sales Department")
- **Keyword** — what the user types to select it (e.g. "1" or "sales")
- **Next Step** — where to go when selected

### WhatsApp > Configuration > Chatbot Sessions

**What it does:** Monitor active chatbot conversations in real-time.

**Where:** WhatsApp > Configuration > Chatbot Sessions (read-only)

Shows: chatbot name, phone number, current step, state (Active/Routed/Completed/Expired), last activity time.

---

## Discuss Integration

The module adds full WhatsApp support to Odoo's Discuss messaging interface.

### WhatsApp Sidebar

A dedicated **"WhatsApp"** section appears in the Discuss sidebar, showing all active WhatsApp conversations. Conversations are sorted by most recent activity.

### Messaging Menu

A **WhatsApp tab** appears in the top-bar messaging menu (bell icon) with an unread message counter. Click any conversation to open it.

### Chat Windows

WhatsApp conversations open in chat windows, just like regular Odoo chats. New incoming messages **auto-open** the chat window.

### Message Status Icons

Each outbound message shows a WhatsApp icon with color-coded delivery status:
- **Yellow** — In Queue (being processed)
- **Green** — Sent / Delivered / Read
- **Red** — Failed / Error

Hover over the icon to see the detailed status.

### Conversation Expiration

WhatsApp conversations have a 7-day messaging window. When expired, a yellow banner appears: *"This conversation has been closed as the messaging window has expired."* Click **"Revive WhatsApp Conversation"** to start a new message.

### WhatsApp User Badge

WhatsApp contacts are shown with a green WhatsApp icon in the member list, in a dedicated "WhatsApp User" section.

### Single Attachment Rule

WhatsApp only supports one attachment per message. The composer enforces this — if you try to upload multiple files, you'll see a warning.

---

## Chatter Integration (Shift+W)

A **"WhatsApp"** button appears in the chatter of every Odoo document (Sale Orders, Invoices, Contacts, etc.).

**Keyboard Shortcut:** Press **Shift + W** to quickly open the WhatsApp composer.

The composer opens with:
- Phone number auto-detected from the record
- Option to select a message template
- Text area for custom message
- Attachment upload
- Scheduled send option

### Send WhatsApp from Contact List

Select one or more contacts in the Contacts list view, then click **Action > Send WhatsApp** to send a bulk message using the composer wizard.

---

## Keyboard Shortcuts

| Shortcut | Action |
|----------|--------|
| **Shift + W** | Open WhatsApp composer from any document's chatter |

---

## Background Jobs (Cron)

12 jobs run automatically in the background:

| Job | Interval | What it does |
|-----|----------|-------------|
| Send Queued Messages | Every 1 min | Sends queued outbound messages (batch of 500) |
| Sync Session Status | Every 5 min | Polls account connection status from the sidecar (fallback for the push webhook) |
| Account Heartbeat | Every 5 min | Refreshes `last_seen_dt` + computes health badge per account |
| Clean Old Messages | Every 1 day | Deletes processed messages older than 15 days |
| Update Campaign State | Every 5 min | Moves campaigns from "Sending" to "Sent" when complete |
| Dispatch Standing Orders | Every 15 min | Fires recurring scheduled sends (daily/weekly/monthly) |
| Expire Status Broadcasts | Every 1 hour | Marks WhatsApp Stories expired after 24 hours |
| Expire Chatbot Sessions | Every 10 min | Expires inactive chatbot sessions past the session timeout |
| Expire Pending Pair Requests | Every 30 min | Auto-rejects inbound DM pair requests older than the configured window |
| GC Inbound Dedupe | Every 1 day | Cleans the inbound-msg dedupe table (idempotency cache) |
| Check Triage SLA | Every 15 min | Creates breach activities on whatsapp channels past their SLA |
| Refresh Partner Avatars | Every 1 day | Pulls WhatsApp profile pictures into `res.partner.image_1920` |

> Note: the push-based `/open_whatsapp_connector/webhook/connection` endpoint flips
> connection state within ~200 ms of QR-scan, so the 5-minute **Sync Session Status**
> cron is a fallback — not the primary path.

---

## Security & Permissions

| Group | What they can do |
|-------|-----------------|
| **Internal User** | Read marketing records (read-only by default), view messages, send via composer, use chatter button |
| **WhatsApp Admin** | Full access: accounts, templates, rules, campaigns, broadcast groups, standing orders, status broadcasts, chatbots, settings |

- **85** `ir.model.access` rows + **17** `ir.rule` company-isolation rules baseline.
- Accounts are **company-scoped** via `wa_account.allowed_company_ids` (multi-company safe).
- Marketing records inherit account-scope (so company isolation applies to campaigns/broadcasts too).
- Webhook endpoints validate per-account `webhook_secret` (set in account form, hidden from non-admins).
- API keys + webhook secrets are only visible to **WhatsApp Admin**.

### Per-user / per-team marketing visibility (opt-in)

A toggleable layer ships **inactive by default** (zero regression for existing customers):

- **12 toggle-able `ir.rule` rows** — 6 user-scoped (`own + team`) + 6 admin-all pairs covering `owa.campaign`, `owa.contact.list`, `owa.contact.list.member`, `owa.broadcast.group`, `owa.standing.order`, `owa.status.broadcast`.
- **6 toggle-able `ir.model.access` rows** — grant non-admin users CRUD on their own marketing records when isolation mode is on.
- Flipped on/off via **Settings → Campaign & Contact Visibility** (`shared` ⇄ `own_team`).
- A post-init migration back-fills `user_id = create_uid` + best-effort `team_id` on existing rows so flipping to `own_team` keeps creators' access intact.

---

## Troubleshooting

### Sidecar won't start
- Make sure **Node.js 22+** is installed: `node -v`
- Check that the **Sidecar Directory** is correctly set in Settings
- Run `setup.bat` (Windows) or `setup.sh` (Linux) in the sidecar folder
- Check `sidecar/sidecar.log` for errors

### "Cannot find package 'baileys'"
The module alias is missing. Run the setup script again, or create it manually:
- **Windows:** `mklink /J node_modules\baileys node_modules\@whiskeysockets\baileys`
- **Linux:** `ln -s @whiskeysockets/baileys node_modules/baileys`

### QR code doesn't appear
- Make sure the sidecar is running (check the badge on the account card)
- Click **Test Connection** to verify the sidecar is reachable
- Click **Connect** again — QR codes expire in ~20 seconds

### Messages stuck in "In Queue"
- Check that the WhatsApp account is **Connected** (green badge)
- The send cron runs every minute — wait a moment
- Check **WhatsApp > Messages** and filter by **Failed** to see errors

### Variables not replaced in templates (showing {{partner_name}})
- Make sure the notification rule has a **Quick Reply template** selected
- Verify the account is connected and the rule is active
- After module upgrade, restart Odoo to clear Python bytecode cache

### Sidecar freezes / health check times out
- Check `sidecar/sidecar.log` for errors
- Stop and restart the sidecar from the account dashboard

---

## Comparison with Odoo Built-in WhatsApp

| Feature | Built-in (Cloud API) | Open WhatsApp Connector |
|---------|---------------------|------------------------|
| API | Meta Cloud API (official) | WhatsApp Web Protocol (unofficial) |
| Cost | Paid per conversation | Free |
| Setup | Meta Business verification | Scan QR code |
| Templates | Meta-approved HSM templates | Local message templates |
| 24h window | Enforced | 7-day window (flexible) |
| Discuss integration | Full | Full (30+ patches) |
| Interactive messages | Buttons, lists | Buttons (max 3), lists (sections + rows) |
| Chatbot | Basic | IVR menus + agent routing + CRM leads |
| Notification rules | Via automation | Built-in model watcher |
| Campaigns | Basic bulk | Full campaign + contact lists + stats |
| Auto-reply | No | Keyword, welcome, away, reply-all |
| Blacklist | Via templates | STOP keyword auto-blacklist |
| Scheduled messages | No | Date/time scheduler |
| Website widget | No | Embeddable chat button |
| CRM lead from chat | Yes | Yes (via chatbot) |
| Multi-account | Yes | Yes (kanban dashboard) |
| Sidecar management | N/A | Start/stop from Odoo |
| Voice/video calls | No | No (protocol limitation) |
| Reliability | Production-grade | Best for low-volume messaging or internal use |

---

## Module Structure

```
open_whatsapp_connector/
├── __manifest__.py                # version 18.0.27.0.0
├── __init__.py
├── controllers/
│   └── main.py                    # Inbound webhooks (messages + statuses + push connection-state)
├── data/                          # 7 XML data files, 41 records total
│   ├── ir_cron_data.xml           # 12 cron jobs
│   ├── owa_server_action_data.xml # "Send WhatsApp" server action
│   ├── owa_quick_reply_data.xml   # 4 default message templates
│   ├── owa_slash_command_data.xml # /help /menu /start /stop /agent
│   ├── owa_sale_templates.xml     # 12 sales templates (Quote/Order/Invoice/Refund)
│   ├── owa_dunning_templates.xml  # 3 subscription-dunning templates
│   └── owa_recruitment_templates.xml # 4 recruitment auto-reply templates
├── migrations/
│   └── 18.0.27.0.0/post-migrate.py  # idempotent upgrade pass (consolidates 19.0.2 + 19.0.26.1 + 19.0.27)
├── models/                        # 38 owned models + 8 _inherit extensions
├── security/
│   ├── res_groups.xml             # group_owa_admin (implies base.group_user; base.group_system implies admin)
│   ├── ir_rules.xml               # 17 company-isolation rules + 12 toggleable marketing-visibility rules
│   ├── ir.model.access.csv        # 85 ACL rows covering 47 distinct models
│   └── ir_model_access_marketing.xml # 6 toggleable user-CRUD ACLs (flipped by Settings)
├── sidecar/                       # Node.js WhatsApp Web service
│   ├── setup.bat                  # Windows one-click setup
│   ├── setup.sh                   # Linux/macOS one-click setup
│   ├── SETUP.md                   # Detailed setup guide
│   ├── package.json               # Baileys 7.0.0-rc10 + patch-package
│   ├── patches/                   # Pinned WhatsApp-library patches
│   └── src/                       # TypeScript source (services/session-manager.ts, postWebhook, etc.)
├── static/src/                    # 60+ frontend files (JS + XML + SCSS)
├── tools/                         # API client, phone validation, sidecar manager
├── views/                         # 26 XML view files
└── wizard/                        # 11 wizard view files (composer, group/community/newsletter create, merge, react, etc.)
```

---

## Sidecar Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `3100` | HTTP server port |
| `API_KEY` | (none) | API key for authentication |
| `SESSIONS_DIR` | `./sessions` | Where WhatsApp sessions are stored |
| `LOG_LEVEL` | `info` | Logging level (debug, info, warn, error) |
