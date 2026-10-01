# Simple setup guide (non-developers)

Follow these numbered steps once. After that, alerts arrive on Telegram during market hours.

---

### Step 1 — Create a Telegram bot

1. Open Telegram.
2. Search for **@BotFather** and open it.
3. Tap **Start**, then type `/newbot`.
4. Choose a name (example: `My RF Alerts`) and a username ending in `bot`.
5. BotFather replies with a **token**. Copy and save it somewhere private.

### Step 2 — Get your Chat ID

1. Search Telegram for **@userinfobot** (or **@getidsbot**).
2. Start it; it will show your **Id** number. Copy that number.  
   **OR** message your new bot, then open this URL in a browser (paste your token):  
   `https://api.telegram.org/botYOUR_TOKEN_HERE/getUpdates`  
   Look for `"chat":{"id": 123456789}`.

### Step 3 — Create a GitHub account & repository

1. Go to [https://github.com](https://github.com) and sign in (or create a free account).
2. Click **+** → **New repository**.
3. Name it (example: `rf-htf-ob5m-alerts`). Choose **Private**.
4. Click **Create repository**.

### Step 4 — Upload this project

**Easiest (website):**

1. Unzip `rf_htf_ob5m_telegram_alerts.zip` on your computer.
2. On the new empty GitHub repo page, click **uploading an existing file**.
3. Drag **all files and folders** from inside the unzipped folder (including `.github`) onto the page.  
   If `.github` does not appear, use the command-line method below.
4. Click **Commit changes**.

**Command line (recommended so `.github` is included):**

```bash
cd rf_htf_ob5m_telegram_alerts
git init
git add .
git commit -m "Initial RF HTF OB5m alerts"
git branch -M main
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

### Step 5 — Add secrets (bot token + chat id)

1. On GitHub, open your repo → **Settings**.
2. Left sidebar: **Secrets and variables** → **Actions**.
3. Click **New repository secret**.
4. Name: `TELEGRAM_BOT_TOKEN` — paste the BotFather token → **Add secret**.
5. Again → Name: `TELEGRAM_CHAT_ID` — paste your chat id → **Add secret**.

### Step 6 — Turn on Actions and test

1. Click the **Actions** tab.
2. If asked, click **I understand my workflows, go ahead and enable them**.
3. Open **RF HTF OB5m Scan**.
4. Click **Run workflow** → **Run workflow**.
5. Wait 2–10 minutes. Check the log (green check = OK).
6. If there is a new signal, you get a Telegram message. If none, that is normal — the bot only texts on **new** setups.

### Step 7 — Leave it running

You do not need to do anything else on trading days.  
GitHub will run the scan about every 5 minutes between **9:15 AM and 3:45 PM India time** (Mon–Fri).

---

## Optional — run a backtest yourself

On your computer (needs Python 3.10+):

```bash
cd rf_htf_ob5m_telegram_alerts
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m backtest.run_backtest --limit 10
```

Results appear in the `output/` folder.  
Or on GitHub: **Actions → RF HTF OB5m Backtest → Run workflow**.

---

## Optional — more stocks

Edit `symbols_fno.txt` and add more lines like `SBIN.NS` (one per line).  
More symbols = longer runs; the default list is sized for free GitHub Actions.

---

## If something fails

| Problem | What to try |
|---------|-------------|
| No Telegram message ever | Re-check secrets names exactly: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Message your bot once so it can reply. |
| Workflow disabled | Actions tab → enable workflows. Free accounts must have run at least one workflow recently. |
| Many Yahoo errors | Normal occasionally; scanner skips failures. Try again later. |
| Duplicate alerts | Cache stores last signals; first runs after cache expiry might re-notify rarely. |

---

## Reminder

These alerts are **not** financial advice and are **not** an auto-trading system. Use them only as discretionary ideas and manage your own risk.
