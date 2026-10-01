# RF + HTF + OB5m Telegram Alerts (NSE F&O)

GitHub Actions cron during Indian market hours runs a Python scanner that computes:

- **Range Filter CondIni** on 5m (Yahoo Finance)
- **HTF bias** = Range Filter CondIni on resampled **15m** (last *completed* 15m bar only — no lookahead)
- **Order Blocks** (wugamlo): `periods=5`, `threshold=0`, `usewicks=false`

**Signal** = new RF CondIni flip on the latest **completed** 5m bar that also passes:

| Side  | Filters |
|-------|---------|
| LONG  | HTF CondIni = +1 **and** close inside an active bull OB |
| SHORT | HTF CondIni = −1 **and** close inside an active bear OB |

Alerts include suggested **swing/ATR stop** and **0.6R take-profit** for discretionary use.

> **DISCLAIMER:** Not live trading advice. Educational / research alerts only. You are solely responsible for any trading decisions. Yahoo data can be delayed or incomplete.

Logic is aligned with `yahoo_backtest/ob5m_d_regen.py` + `backtest.py`.

---

## Quick start (first-time setup)

### 1. Create a Telegram bot

1. Open Telegram and message **[@BotFather](https://t.me/BotFather)**
2. Send `/newbot` and follow prompts
3. Copy the **bot token** (looks like `123456:ABC-DEF...`)

### 2. Get your chat ID

1. Message **[@userinfobot](https://t.me/userinfobot)** or [@getidsbot](https://t.me/getidsbot), **or**
2. Start a chat with your new bot, send any message, then open:
   `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates`
3. Find `"chat":{"id": ..........}` — that number is your **chat ID**  
   (For a channel/group, add the bot as admin and use the channel/group id.)

### 3. Create a GitHub repository

1. On GitHub → **New repository** (private recommended)
2. Do **not** initialize with README if you will upload this folder as-is

### 4. Upload these files

Upload / push the entire contents of this project to the repo root so that
`.github/workflows/scan.yml`, `src/`, `symbols_fno.txt`, etc. are at the top level.

```bash
git init
git add .
git commit -m "RF HTF OB5m Telegram alerts"
git branch -M main
git remote add origin https://github.com/<YOU>/<REPO>.git
git push -u origin main
```

### 5. Add GitHub secrets

Repo → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**:

| Name | Value |
|------|--------|
| `TELEGRAM_BOT_TOKEN` | BotFather token |
| `TELEGRAM_CHAT_ID` | Your chat / channel id |

### 6. Enable Actions

Repo → **Actions** → enable workflows if prompted.  
Open **RF HTF OB5m Scan** → **Run workflow** (manual test).

Cron runs ~every 5 minutes Mon–Fri **03:45–10:15 UTC** (IST **09:15–15:45**).

---

## Message format

```
🟢 LONG | RELIANCE.NS
Entry ~2850.00 | SL 2830.50 | TP 0.6R 2861.70
RF+HTF+OB5m | 5m | 2026-09-30 10:15 IST

⚠️ DISCLAIMER: Not live trading advice. ...
```

---

## Symbol universe

Default: `symbols_fno_full.txt` (213 NSE F&O names ending in `.NS`). The live scanner uses this full universe by default.

- `symbols_fno.txt` is retained as the smaller 84-name liquid subset for optional, faster local scans.
- To use a different universe, pass `--symbols PATH`; one symbol per line, with `#` comments allowed.

---

## Deduping alerts (Actions cache)

`state/last_signals.json` stores already-sent signal keys.  
The scan workflow **restores/saves** this file via **GitHub Actions cache** (no commit spam).

---

## Local run (scanner)

```bash
cd rf_htf_ob5m_telegram_alerts
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=...
export TELEGRAM_CHAT_ID=...
python -m src.scanner --dry-run --limit 5   # safe test
python -m src.scanner                       # live Telegram
```

---

## Backtest (TP = 0.6R)

Fetches Yahoo 5m, runs the same RF+HTF+OB5m entry rules, swing/ATR SL, 0.6R TP, one trade/day, flat by 15:15 IST.

```bash
python -m backtest.run_backtest --limit 10
python -m backtest.run_backtest              # default backtest universe
```

Outputs under `output/`:

- `rf_htf_ob5m_trades.csv`
- `rf_htf_ob5m_summary.json` — WR / profit factor / expectancy R / net
- `rf_htf_ob5m_per_symbol.csv`

Optional GitHub Action: **Actions → RF HTF OB5m Backtest → Run workflow** (`backtest.yml`).

---

## Resilience

- Failed symbols are skipped; scan continues
- Short pause between Yahoo fetches (rate-limit friendly)
- Fetch retries / timeouts
- Incomplete (forming) 5m bar is dropped before signal evaluation

---

## Layout

```
.github/workflows/scan.yml       # cron + workflow_dispatch scanner
.github/workflows/backtest.yml   # optional manual backtest
src/rf.py                        # Range Filter + HTF map + SL/TP
src/ob.py                        # wugamlo OB5m
src/scanner.py                   # live scan entrypoint
src/telegram_notify.py
backtest/run_backtest.py
symbols_fno_full.txt          # default live-scan universe
symbols_fno.txt               # optional liquid subset
state/last_signals.json
requirements.txt
GUIDE.md                         # non-dev numbered steps
README.md
```
