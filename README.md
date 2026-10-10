# Singapore Haze Monitor

A lightweight Python script that pulls the latest **PSI** and **PM2.5** readings
for Singapore from [data.gov.sg](https://data.gov.sg) and sends them to Telegram
when the numbers change.

Runs automatically every hour on GitHub Actions. No server, no hosting fees.

---

## What it does

- Fetches three metrics from NEA real-time APIs:
  - **1-hour PM2.5** (default: enabled)
  - **24-hour PM2.5** (default: enabled)
  - **24-hour PSI** (default: enabled)
- Compares readings against the last run using GitHub Actions cache
- Sends a Telegram message **only if a value changed** — typically 1–3 messages/day
- Colors each metric with a single emoji circle based on the **worst region**

### Example output

```

🌫 10 Oct, 14:00
1h   2.5 🟡 C:48 W:62 S:45 E:41 N:55
24h  2.5 🟢 C:38 W:42 S:35 E:33 N:45
24h  PSI 🟡 C:72 W:78 S:65 E:58 N:82

```

Regions: **C**entral, **W**est, **S**outh, **E**ast, **N**orth.

### Band colors

**PSI (NEA):**

| Range | Band | Circle |
|---|---|---|
| 0 – 50 | Good | 🟢 |
| 51 – 100 | Moderate | 🟡 |
| 101 – 200 | Unhealthy | 🟠 |
| 201 – 300 | Very Unhealthy | 🔴 |
| ≥ 301 | Hazardous | 🟣 |

**PM2.5 µg/m³ (NEA 1-hour):**

| Range | Band | Circle |
|---|---|---|
| 0 – 55 | Normal | 🟢 |
| 56 – 150 | Elevated | 🟡 |
| 151 – 250 | High | 🟠 |
| ≥ 251 | Very High | 🔴 |

---

## Setup

### 1. Create a Telegram bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** (looks like `123456789:AAH...`)
4. Send `/start` to your new bot (required — Telegram blocks bots from messaging users who haven't started the chat)

### 2. Get your Telegram chat ID

1. Search for **@userinfobot** on Telegram
2. Send `/start`
3. Copy the **Id** number it returns

### 3. Add secrets to GitHub

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Your ID from @userinfobot |

### 4. Enable Actions

Go to the **Actions** tab and enable workflows if prompted.

### 5. Test

**Actions → Singapore Haze Monitor → Run workflow**

Check your Telegram — the first run always sends because there's no cached state yet.

---

## Configuration

### Which metrics to send

Edit the toggles near the top of `psi_monitor.py`:

```python
SEND_PSI_24H  = True    # 24-hour PSI
SEND_PM25_24H = True    # 24-hour PM2.5
SEND_PM25_1H  = True    # 1-hour PM2.5
```

Set any to False to hide that metric from the message.

When it runs

Edit .github/workflows/psi_monitor.yml:

```yaml
on:
  schedule:
    - cron: '2,5 * * * *'   # every hour at :02 and :05 UTC
```

GitHub Actions cron is always UTC. Singapore is UTC+8, so 2,5 * * * * fires
at 08:02, 08:05, 09:02, 09:05 SGT, etc.

⚠️ GitHub's scheduler is best-effort. Runs may be delayed 5–30 min or
occasionally skipped during peak load. Avoid minute 0 — it's the busiest.

The two runs per hour provide redundancy: the :02 run usually sends the
message, and the :05 run stays silent because the data hasn't changed.

---

CLI options

Flag Effect
(none) Normal run — send only if readings changed
--preview Print the message, don't send, don't save state
--force Send even if readings are unchanged

Force a send from GitHub Actions

Add a force input to the workflow's workflow_dispatch (see the workflow
file), then tick the checkbox when you tap Run workflow.

Or temporarily change the run command to:

```yaml
run: python psi_monitor.py --force
```

Don't leave --force enabled permanently — it defeats the "only send on
change" design and pings you every hour.

---

Files

File Purpose
psi_monitor.py Main script: fetch, compare, send
requirements.txt Python dependencies (requests)
.github/workflows/psi_monitor.yml Workflow that runs the script hourly

State (.psi_state.json) is stored in GitHub Actions cache between runs and
never committed to the repo.

---

Data sources

· PSI — https://api-open.data.gov.sg/v2/real-time/api/psi
· PM2.5 — https://api-open.data.gov.sg/v2/real-time/api/pm25
· PM2.5 (fallback) — https://api.data.gov.sg/v1/environment/pm25

Data is published by the National Environment Agency (NEA) and refreshed
roughly once per hour. Readings older than 3 hours are rejected as a
staleness guard.

Note: the legacy endpoint api.data.gov.sg/v1/environment/psi is frozen
since June 2025 — this project uses the v2 endpoints instead.

---

Local testing

```bash
pip install -r requirements.txt

export TELEGRAM_BOT_TOKEN="123456:ABC..."
export TELEGRAM_CHAT_ID="123456789"

python psi_monitor.py --preview   # print only
python psi_monitor.py --force     # send even if unchanged
python psi_monitor.py             # normal run
```

---

Troubleshooting

Bad Request: chat not found
You haven't sent /start to your bot, or TELEGRAM_CHAT_ID is wrong.
Re-check setup steps 1 and 2.

Workflow not appearing in Actions tab
The file must be at exactly .github/workflows/<name>.yml — with a leading
dot in .github. Check that folder name carefully.

failed to push some refs
The workflow is using the older commit-based state approach. Switch to the
cache-based version (see the workflow file in this repo).

Message sent every hour despite no change
Update to the current psi_monitor.py — earlier versions compared the
timestamp too, so every run looked like a change.

Data is stale
The NEA API may be having a moment. The next hourly run will retry
automatically.

Force a test send
Either use --force, or delete the psi-state-* entries in
Actions → Caches to reset the dedup state.

---

Cost

Free. GitHub Actions gives unlimited minutes for public repositories.
This project uses roughly 30 seconds per run — about 12 hours of usage per
month.

---

License

MIT — do what you want with it.

```
