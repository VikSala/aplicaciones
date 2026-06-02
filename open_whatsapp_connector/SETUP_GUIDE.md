# Open WhatsApp Connector — Server Setup Guide

A step-by-step guide to install and configure the Open WhatsApp Connector on your server.
Written for non-technical users. Follow each step in order.

---

## What You Need Before Starting

| Requirement | Details |
|-------------|---------|
| **Odoo 19** | Community or Enterprise edition, already installed and running |
| **Node.js 22+** | Download from [nodejs.org](https://nodejs.org/) |
| **Server access** | SSH (Linux) or Remote Desktop (Windows) |
| **A phone with WhatsApp** | The phone number you want to connect |

**Ports used:**
- Odoo: `8069` (default)
- Sidecar: `3100` (default, only needs to be accessible from Odoo, not the internet)

---

## Step 1: Install the Odoo Module

### 1.1 Find your Odoo addons path

First, find where Odoo looks for modules. Open your Odoo configuration file and look for the `addons_path` line:

**Linux:**
```bash
cat /etc/odoo/odoo.conf | grep addons_path
```

**Windows:**
Open `odoo.conf` (usually in the Odoo installation folder) and find the `addons_path` line.

It will look something like:
```
addons_path = /path/to/odoo/addons
```

Remember this path — you'll use it in the next steps. We'll call it **YOUR_ADDONS_PATH** in this guide.

### 1.2 Copy the module to your server

Copy the `open_whatsapp_connector` folder into your addons directory.

**Linux:**
```bash
cp -r open_whatsapp_connector YOUR_ADDONS_PATH/
```

**Windows:**
Copy the `open_whatsapp_connector` folder into your addons directory (the path you found above).

### 1.2 Install in Odoo

1. Open your Odoo in a web browser
2. Go to **Apps** (main menu)
3. Click **Update Apps List** (you may need to enable Developer Mode first)
4. Search for **"Open WhatsApp Connector"**
5. Click **Install**

> **To enable Developer Mode:** Go to Settings > scroll to the bottom > click "Activate the Developer Mode"

---

## Step 2: Set Up the Sidecar Service

The sidecar is a small background program that connects Odoo to WhatsApp. It runs alongside Odoo on the same server.

### 2.1 Install Node.js (if not already installed)

**Linux (Ubuntu/Debian):**
```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
```

**Windows:**
Download and install from [nodejs.org](https://nodejs.org/) (choose the LTS version 22+)

**Verify installation:**
```bash
node -v
# Should show v22.x.x or higher
```

### 2.2 Run the setup script

**Linux:**
```bash
cd YOUR_ADDONS_PATH/open_whatsapp_connector/sidecar
chmod +x setup.sh
./setup.sh
```

**Windows:**
Open the `sidecar` folder and double-click `setup.bat`

You should see output like:
```
[OK] Node.js v22.x.x found
[1/4] Installing dependencies...
[OK] Dependencies installed.
[2/4] Applying patches...
[OK] Patches applied.
[3/4] Creating module alias...
[OK] Module alias created.
[4/4] Building TypeScript...
[OK] Build complete.

Setup Complete!
```

### 2.3 Test the sidecar

Start it manually to verify it works:

```bash
cd YOUR_ADDONS_PATH/open_whatsapp_connector/sidecar
npm start
```

You should see:
```
{"msg":"WhatsApp Baileys sidecar started","port":3100}
```

Press **Ctrl+C** to stop it. We'll set it up as a background service next.

---

## Step 3: Run Sidecar as a Background Service

The sidecar needs to run continuously in the background, and restart automatically if the server reboots.

### Option A: Linux (systemd) — Recommended

#### 3A.1 Create the service file

```bash
sudo nano /etc/systemd/system/whatsapp-sidecar.service
```

Paste this content (adjust paths if needed):

```ini
[Unit]
Description=WhatsApp Sidecar for Odoo
After=network.target

[Service]
Type=simple
User=odoo
WorkingDirectory=YOUR_ADDONS_PATH/open_whatsapp_connector/sidecar
ExecStart=/usr/bin/node dist/index.js
Restart=always
RestartSec=5
Environment=PORT=3100
Environment=LOG_LEVEL=info

# Optional: Add API key for security
# Environment=API_KEY=your-secret-key-here

[Install]
WantedBy=multi-user.target
```

> **Important:** Change `User=odoo` to match your Odoo system user. Change the paths if your addons are in a different location.

#### 3A.2 Enable and start the service

```bash
sudo systemctl daemon-reload
sudo systemctl enable whatsapp-sidecar
sudo systemctl start whatsapp-sidecar
```

#### 3A.3 Verify it's running

```bash
sudo systemctl status whatsapp-sidecar
```

You should see **"active (running)"** in green.

#### Useful commands

| Command | What it does |
|---------|-------------|
| `sudo systemctl start whatsapp-sidecar` | Start the service |
| `sudo systemctl stop whatsapp-sidecar` | Stop the service |
| `sudo systemctl restart whatsapp-sidecar` | Restart the service |
| `sudo systemctl status whatsapp-sidecar` | Check if it's running |
| `sudo journalctl -u whatsapp-sidecar -f` | View live logs |

---

### Option B: Windows (Task Scheduler)

#### 3B.1 Create a start script

Create a file called `start_sidecar.bat` on your Desktop:

```batch
@echo off
cd /d "YOUR_ADDONS_PATH\open_whatsapp_connector\sidecar"
node dist\index.js
```

> **Adjust the path** to match where your Odoo addons are installed.

#### 3B.2 Set up auto-start with Task Scheduler

1. Open **Task Scheduler** (search for it in the Start menu)
2. Click **Create Basic Task**
3. Name: `WhatsApp Sidecar`
4. Trigger: **When the computer starts**
5. Action: **Start a program**
6. Program: `node`
7. Arguments: `dist\index.js`
8. Start in: `YOUR_ADDONS_PATH\open_whatsapp_connector\sidecar`
9. Check **"Open the Properties dialog"** and click **Finish**
10. In Properties: check **"Run whether user is logged on or not"**
11. Click **OK** and enter your Windows password

#### 3B.3 Start it now

Right-click the task and select **Run**. Or simply double-click `start_sidecar.bat`.

### Option C: Start from Odoo (Simplest, but not persistent)

If you don't want to set up a system service, you can start the sidecar directly from Odoo:

1. Go to **Settings > Open WhatsApp Connector**
2. Set **Sidecar Directory** to the full path of the sidecar folder
3. Enable **Auto-start Sidecar**
4. Go to **WhatsApp > Accounts** and click **Start Sidecar**

> **Note:** With this method, the sidecar stops when Odoo restarts. Options A or B are recommended for production.

---

## Step 4: Configure the Module in Odoo

### 4.1 Open module settings

Go to **Settings > Open WhatsApp Connector**

### 4.2 Configure sidecar settings

| Setting | What to enter | Example |
|---------|--------------|---------|
| **Default Sidecar URL** | Leave as default unless sidecar runs on a different port | `http://localhost:3100` |
| **Default API Key** | Leave empty unless you set API_KEY in the sidecar service | (empty) |
| **Sidecar Directory** | Full path to the sidecar folder | `YOUR_ADDONS_PATH/open_whatsapp_connector/sidecar` |
| **Auto-start Sidecar** | Enable if you want Odoo to start sidecar automatically | (your choice) |

### 4.3 Configure contact settings

| Setting | Recommendation |
|---------|---------------|
| **Auto-create Contacts** | **Enable** (default). Creates contact records automatically when messages arrive from unknown numbers. |

### 4.4 Save settings

Click the **Save** button at the top.

---

## Step 5: Connect Your WhatsApp Number

### 5.1 Open the accounts dashboard

Go to **WhatsApp > Accounts**

You'll see a kanban board (card view) showing your WhatsApp accounts.

### 5.2 Create a new account

1. Click **New**
2. Enter a name for this account (e.g. "Sales WhatsApp" or "Support WhatsApp")
3. The other fields are pre-filled with defaults — you don't need to change anything

### 5.3 Start the sidecar (if not already running)

Look at the badge on the account card:
- **"Sidecar Running"** (green) — you're good, skip to 5.4
- **"Sidecar Stopped"** (red) — click the **"Start Sidecar"** button

### 5.4 Connect to WhatsApp

1. Click the **Connect** button
2. A **QR code** will appear on screen
3. On your phone:
   - **Android:** Open WhatsApp > tap the three dots (top right) > **Linked Devices** > **Link a Device**
   - **iPhone:** Open WhatsApp > **Settings** (bottom right) > **Linked Devices** > **Link a Device**
4. Point your phone camera at the QR code on screen
5. Wait 2-3 seconds — the status will change to **"Connected"** (green)

### 5.5 Verify the connection

The account card should now show:
- Status: **Connected** (green badge)
- Phone number: your WhatsApp number
- Sidecar: **Running** (green badge)

> **QR code expired?** QR codes are valid for about 20 seconds. If it expires, click **Connect** again to get a new one.

---

## Step 6: Firewall Configuration

The sidecar runs on port **3100** by default. This port only needs to be accessible **locally** (from Odoo to the sidecar on the same server).

**If Odoo and the sidecar are on the same server:** No firewall changes needed.

**If the sidecar is on a different server:** Open port 3100 between the two servers:

```bash
# Linux (UFW)
sudo ufw allow from ODOO_SERVER_IP to any port 3100

# Linux (iptables)
sudo iptables -A INPUT -p tcp -s ODOO_SERVER_IP --dport 3100 -j ACCEPT
```

> **Security:** Do NOT expose port 3100 to the public internet. It should only be accessible from your Odoo server.

---

## Step 7: Set Up Notification Rules (Optional)

The module comes with 4 pre-built notification rules (disabled by default). These automatically send WhatsApp messages when business events happen.

### 7.1 View the rules

Go to **WhatsApp > Configuration > Notification Rules**

You'll see these rules (all inactive):

| Rule | When it fires |
|------|--------------|
| Sale Order Confirmed | When a sale order is confirmed |
| Invoice Posted | When an invoice is validated |
| Delivery Completed | When a delivery order is marked done |
| Payment Received | When a payment is registered |

### 7.2 Activate a rule

1. Click on a rule to open it
2. Set **WhatsApp Account** — select your connected account
3. Toggle **Active** to ON (or use the toggle in the list view)
4. Click **Save**

### 7.3 Test a rule

1. Create a new Sale Order with a customer who has a phone number
2. Confirm the sale order
3. The customer should receive a WhatsApp message automatically

> **Note:** The customer's contact must have a **phone number** set in Odoo for notifications to work.

---

## Step 8: Set Up Auto-Replies (Optional)

Auto-replies automatically respond to incoming WhatsApp messages.

### 8.1 Create an auto-reply

Go to **WhatsApp > Configuration > Auto-Reply Rules** > click **New**

### Example: Welcome message for new contacts

| Field | Value |
|-------|-------|
| Name | Welcome Message |
| Trigger Type | Welcome |
| Response | Hello! Thank you for contacting us. How can we help you today? |
| Account | (select your account) |

### Example: Away message outside business hours

| Field | Value |
|-------|-------|
| Name | After Hours |
| Trigger Type | Away / Out of Office |
| Response | Thank you for your message! Our office hours are Mon-Fri 9AM-6PM. We'll get back to you soon. |
| Business Hours Start | 09:00 |
| Business Hours End | 18:00 |
| Business Days | 0,1,2,3,4 (Monday to Friday) |
| Account | (select your account) |

---

## Optional: Nginx Reverse Proxy

If you want to run the sidecar behind Nginx (for example, if Odoo and the sidecar are on different servers):

```nginx
# Add this to your Nginx configuration
location /whatsapp-sidecar/ {
    proxy_pass http://localhost:3100/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 300s;
}
```

Then set the **Sidecar URL** in Odoo to: `http://your-domain.com/whatsapp-sidecar`

---

## Optional: Adding API Key Security

To protect the sidecar with an API key:

### Linux (systemd):
Edit the service file:
```bash
sudo nano /etc/systemd/system/whatsapp-sidecar.service
```

Add or uncomment:
```ini
Environment=API_KEY=your-secret-key-here
```

Then restart:
```bash
sudo systemctl daemon-reload
sudo systemctl restart whatsapp-sidecar
```

### In Odoo:
Go to **Settings > Open WhatsApp Connector** and set **Default API Key** to the same key.

Also update each account: open the account form and set **API Key** to the same value.

---

## Optional: Multiple WhatsApp Numbers

You can connect multiple phone numbers. Each number is a separate account.

1. Go to **WhatsApp > Accounts**
2. Click **New**
3. Give it a different name (e.g. "Support WhatsApp")
4. Click **Connect** and scan the QR code with a different phone
5. All accounts share the same sidecar service — no extra setup needed

Each account can have:
- Different notification rules
- Different auto-reply rules
- Different chatbot flows
- Different users to notify

---

## Maintenance

### Viewing logs

**Sidecar logs (Linux systemd):**
```bash
sudo journalctl -u whatsapp-sidecar -f
```

**Sidecar logs (if started from Odoo):**
Check the file: `sidecar/sidecar.log`

**Odoo logs:**
Check your standard Odoo log file (usually `/var/log/odoo/odoo.log`)

### Restarting the sidecar

**Linux:**
```bash
sudo systemctl restart whatsapp-sidecar
```

**Windows:**
Restart the Task Scheduler task, or close and reopen `start_sidecar.bat`

**From Odoo:**
Go to WhatsApp > Accounts > click **Stop Sidecar** then **Start Sidecar**

### Updating the module

1. Replace the `open_whatsapp_connector` folder with the new version
2. Run the sidecar setup script again (`setup.sh` or `setup.bat`)
3. Restart the sidecar service
4. In Odoo: go to **Apps** > search the module > click **Upgrade**

### Session persistence

WhatsApp sessions are stored in `sidecar/sessions/`. When the sidecar restarts, it automatically reconnects all accounts — no need to re-scan QR codes.

> **Backup tip:** Back up the `sidecar/sessions/` folder to preserve WhatsApp authentication. If you lose this folder, you'll need to re-scan QR codes.

---

## Frequently Asked Questions

### Q: Do I need a Meta Business account?
**No.** This module uses the WhatsApp Web protocol, not the Meta Cloud API. You just scan a QR code — no business verification needed.

### Q: Will my number get banned?
WhatsApp may restrict numbers that use unofficial APIs for high-volume messaging. Best practices:
- Don't send more than 200-300 messages per day
- Don't send identical messages to many contacts in a short time
- Respond to opt-out requests (STOP/UNSUBSCRIBE)
- Use it for genuine business communication, not spam

### Q: Can I use it with WhatsApp Business?
Yes. You can scan the QR code with either regular WhatsApp or WhatsApp Business.

### Q: Does it work on Odoo.sh?
You would need to run the sidecar on a separate server, since Odoo.sh doesn't allow running Node.js. Set the Sidecar URL to point to your external server.

### Q: What happens if the sidecar crashes?
If set up as a systemd service (Linux) or Task Scheduler (Windows), it restarts automatically. All WhatsApp sessions reconnect automatically.

### Q: Can multiple Odoo users send from the same WhatsApp number?
Yes. All users listed in the account's **"Users to Notify"** field can see and reply to conversations.

### Q: How do I move to a different server?
1. Copy the `open_whatsapp_connector` folder (including `sidecar/sessions/`)
2. Run the sidecar setup on the new server
3. Set up the sidecar service
4. Install/upgrade the module in Odoo
5. Your WhatsApp sessions will reconnect automatically

### Q: Where are WhatsApp sessions stored?
In `sidecar/sessions/{account_id}/`. Each account has its own folder with credentials.

### Q: Can I change the sidecar port?
Yes. Change the `PORT` environment variable:
- **Linux systemd:** Edit the service file and change `Environment=PORT=3200`
- **Windows:** Add `set PORT=3200` before the `node` command in the batch file
- **Odoo:** Update the **Sidecar URL** in each account to match (e.g. `http://localhost:3200`)
