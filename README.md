# Singapore Haze Monitor

A lightweight Python script that pulls the latest **PSI** and **PM2.5** readings for Singapore from [data.gov.sg](https://data.gov.sg) and sends them to a Telegram chat — but only when the numbers actually change.

Runs automatically every hour on GitHub Actions. No server, no hosting fees.

---

## What it does

- Fetches three metrics from the NEA real-time APIs:
  - **1-hour PM2.5** (default: enabled)
  - **24-hour PM2.5** (default: disabled)
  - **24-hour PSI** (default: disabled)
- Compares the readings against the last run
- Sends a Telegram message **only if a value changed** — so you get pinged at most a few times a day, not 24 times
- Stores state between runs using GitHub Actions cache (no files committed to the repo)

### Example Telegram message

```

10 Oct, 14:00
1-hr 2.5 - C:12 W:15 S:11 E:9 N:18
24-hr 2.5 - C:18 W:21 S:16 E:14 N:23
24-hr PSI C:62 W:66 S:58 E:55 N:70

```

Regions: **C**entral, **W**est, **S**outh, **E**ast, **N**orth.

---

## Setup

### 1. Create a Telegram bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** it gives you (looks like `123456789:AAH...`)
4. Send `/start` to **your new bot** (required — Telegram blocks bots from messaging users who haven't started the chat)

### 2. Get your Telegram chat ID

1. Search for **@userinfobot** on Telegram
2. Send `/start`
3. Copy the **Id** number it returns

### 3. Add the secrets to GitHub

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Your bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Your ID from @userinfobot |

### 4. Enable Actions

Go to the **Actions** tab and enable workflows if prompted.

### 5. Test

**Actions → Singapore Haze Monitor → Run workflow**. Within ~30 seconds you'll see the log output with the preview message. If any reading changed since the last run, a Telegram message is sent.

---

## Configuration

### Which metrics to send

Edit `psi_monitor.py`, near the top:

```python
SEND_PSI_24H  = False   # set True to include 24-hour PSI
SEND_PM25_24H = False   # set True to include 24-hour PM2.5
SEND_PM25_1H  = True    # 1-hour PM2.5 (default on)
```

When it runs

Edit .github/workflows/psi_monitor.yml:

```yaml
on:
  schedule:
    - cron: '17 * * * *'   # every hour at minute 17 (UTC)
```

GitHub Actions cron is always UTC. Singapore is UTC+8, so 17 * * * * fires at 08:17, 09:17, 10:17 SGT, etc.

⚠️ GitHub's scheduler is best-effort. Runs can be delayed 5–30 minutes or occasionally skipped during peak load. Avoid minute 0 — it's the busiest.

---

Files

File Purpose
psi_monitor.py Main script: fetch, compare, send
requirements.txt Python dependencies (requests)
.github/workflows/psi_monitor.yml GitHub Actions workflow that runs the script hourly

State (.psi_state.json) is stored in GitHub's cache between runs and never committed to the repo.

---

Data sources

· PSI: https://api-open.data.gov.sg/v2/real-time/api/psi
· PM2.5: https://api-open.data.gov.sg/v2/real-time/api/pm25
· Fallback PM2.5: https://api.data.gov.sg/v1/environment/pm25

Data is published by the National Environment Agency (NEA) and refreshed roughly once per hour. The script rejects readings older than 3 hours as a staleness guard.

---

Manually trigger an update

Actions → Singapore Haze Monitor → Run workflow

Or, from the command line:

```bash
gh workflow run psi_monitor.yml --repo <your-username>/haze-monitor
```

Preview output locally

```bash
python3 psi_monitor.py --preview
```

Prints the formatted message without sending it or touching state.

---

Troubleshooting

Bad Request: chat not found
You haven't sent /start to your bot, or TELEGRAM_CHAT_ID is wrong. Re-check step 1 and 2 above.

Workflow not appearing in Actions tab
The file must be at exactly .github/workflows/<name>.yml — with a leading dot. Check that folder name carefully.

Push rejected / failed to push some refs
Your workflow is using the older commit-based state approach. Switch to the cache-based version (see .github/workflows/psi_monitor.yml in this repo).

Data is stale
The NEA API may be having a moment. The next hourly run will retry automatically.

---

Cost

Free. GitHub Actions gives unlimited minutes for public repositories. This project uses roughly 30 seconds per hourly run — about 12 hours of usage per month.

---

License

MIT — do what you want with it.
