# Singapore Haze Monitor

A lightweight Python script that pulls the latest **PSI** and **PM2.5** readings
for Singapore from [data.gov.sg](https://data.gov.sg) and sends them to Telegram
when the numbers change.

Runs hourly on GitHub Actions. No server, no hosting fees.

---

## What it does

- Fetches three metrics from NEA real-time APIs:
  - **1-hour PM2.5** (µg/m³) — current fine-particle level
  - **24-hour PM2.5** (µg/m³) — daily average
  - **24-hour PSI** — official haze index
- Compares readings against the last run using GitHub Actions cache
- Sends a Telegram message **only if a value changed** — typically 1–3 messages/day
- Each row shows **one colored circle** based on the worst (highest) region

### Example output

```

🌫 10 Oct, 14:00
1h   2.5 🟠 C:48 W:62 S:45 E:41 N:55
24h  2.5 🟢 C:38 W:42 S:35 E:33 N:45
24h  PSI 🟠 C:72 W:78 S:65 E:58 N:82

```

Regions: **C**entral, **W**est, **S**outh, **E**ast, **N**orth.

### Band colors

**PM2.5 µg/m³ (NEA 1-hour bands):**

| Range | Band | Circle |
|---|---|---|
| 0 – 55 | Normal | 🟢 |
| 56 – 150 | Elevated | 🟠 |
| 151 – 250 | High | 🔴 |
| ≥ 251 | Very High | 💀 |

**PSI (NEA bands):**

| Range | Band | Circle |
|---|---|---|
| 0 – 50 | Good | 🟢 |
| 51 – 100 | Moderate | 🟠 |
| 101 – 200 | Unhealthy | 🔴 |
| 201 – 300 | Very Unhealthy | 🟣 |
| ≥ 301 | Hazardous | 💀 |

---

## Setup

### 1. Create a Telegram bot

1. Open Telegram, search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the **bot token** (looks like `123456789:AAH...`)
4. Send `/start` to your new bot (required — Telegram blocks bots from
   messaging users who haven't started the chat)

### 2. Get your Telegram chat ID

1. Search for **@userinfobot** on Telegram
2. Send `/start`
3. Copy the **Id** number it returns

### 3. Add secrets to GitHub

Repo → **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `TELEGRAM_CHAT_ID` | ID from @userinfobot |

### 4. Enable Actions

Go to the **Actions** tab and enable workflows if prompted.

### 5. Test

**Actions → Singapore Haze Monitor → Run workflow**

Check Telegram — the first run always sends because there's no cached state yet.

---

## Scheduling

You have two options. Pick one.

### Option A — cron-job.org (reliable, recommended)

GitHub's native scheduler is best-effort: runs can be delayed 5–30 minutes
or silently skipped. For dependable hourly triggers, use **cron-job.org** —
a free external scheduler that calls GitHub's API on a precise schedule.

**Setup:**

1. **Create a GitHub PAT** (Personal Access Token):
   - GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens**
   - **Name:** `cron-job-trigger`
   - **Expiration:** 90 days
   - **Repository access:** Only select repositories → your repo
   - **Permissions → Repository permissions → Actions:** Read and write
   - Generate and copy the token (`github_pat_...`)

2. **Create the cron job** at [cron-job.org](https://cron-job.org):

   | Field | Value |
   |---|---|
   | Title | `SG Haze Monitor` |
   | URL | `https://api.github.com/repos/<user>/<repo>/actions/workflows/psi_monitor.yml/dispatches` |
   | Schedule | Every 1 hour at minute **5** (timezone Asia/Singapore) |
   | Request method | `POST` |
   | Request body | `{"ref":"main"}` |

   **Headers:**

   | Header | Value |
   |---|---|
   | `Accept` | `application/vnd.github+json` |
   | `Authorization` | `Bearer github_pat_YOUR_TOKEN_HERE` |
   | `X-GitHub-Api-Version` | `2022-11-28` |
   | `Content-Type` | `application/json` |

3. **Test run** — a successful trigger returns **204 No Content**.

4. **Set a calendar reminder** to renew the PAT every ~80 days. When the
   token expires, cron-job.org silently stops triggering.

**Note:** With this option you can remove the `schedule:` block from the
workflow and keep only `workflow_dispatch:`.

### Option B — GitHub native cron (simpler, less reliable)

Keep the `schedule:` block in `.github/workflows/psi_monitor.yml`:

```yaml
on:
  schedule:
    - cron: '5 * * * *'
  workflow_dispatch:
```
Tips for best reliability:

· Avoid minute 0 — it's the busiest. Use 5, 17, or 37.
· Cron is in UTC. Singapore is UTC+8. 5 * * * * = 13:05 SGT.
· Scheduled runs only fire from the default branch (main).
· GitHub may auto-disable scheduled workflows after 60 days of repo
  inactivity. Check the Actions tab for a disabled banner and re-enable.

---

Configuration

Which metrics to send

Edit the toggles near the top of psi_monitor.py:

```python
SEND_PSI_24H  = True    # 24-hour PSI
SEND_PM25_24H = True    # 24-hour PM2.5
SEND_PM25_1H  = True    # 1-hour PM2.5
```

Set any to False to hide that metric from the message.

Order of metrics

Edit METRIC_ORDER in psi_monitor.py:

```python
METRIC_ORDER = ["pm25_1h", "pm25_24h", "psi_24h"]
```

Region order

Edit REGION_ORDER:

```python
REGION_ORDER = ["central", "west", "south", "east", "north"]
```

---

CLI options

Flag Effect
(none) Normal run — send only if readings changed
--preview Print the message, don't send, don't save state
--force Send even if readings are unchanged

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

Files

File Purpose
psi_monitor.py Main script: fetch, compare, send
requirements.txt Python dependencies (requests)
.github/workflows/psi_monitor.yml Workflow that runs the script

State (.psi_state.json) is stored in GitHub Actions cache between runs and
never committed to the repo.

---

Data sources

· PSI + 24-hr PM2.5 — https://api-open.data.gov.sg/v2/real-time/api/psi
· 1-hr PM2.5 — https://api-open.data.gov.sg/v2/real-time/api/pm25
· PM2.5 fallback — https://api.data.gov.sg/v1/environment/pm25

Data is published by the National Environment Agency (NEA) and refreshed
roughly once per hour. Readings older than 3 hours are rejected as a
staleness guard.

Note: the legacy endpoint api.data.gov.sg/v1/environment/psi is frozen
since June 2025. This project uses the v2 endpoints instead.

---

Troubleshooting

Bad Request: chat not found
You haven't sent /start to your bot, or TELEGRAM_CHAT_ID is wrong.
Re-check setup steps 1 and 2.

Workflow not appearing in Actions tab
The file must be at exactly .github/workflows/<name>.yml — with a leading
dot in .github. Check that folder name carefully.

Failed to save: Unable to reserve cache with key ...
You're re-running the same workflow run. The cache key already exists.
The workflow uses -${{ github.run_attempt }} to avoid this on re-runs.
Trigger a fresh run via Actions → Run workflow.

Message sent every hour despite no change
Update psi_monitor.py. Earlier versions compared the timestamp too, so
every run looked like a change.

Data is stale
The NEA API may be having a moment. The next hourly run retries automatically.

Force a test send
Either use --force, or delete the psi-state-* entries in
Actions → Caches to reset the dedup state.

Scheduled runs not firing (GitHub native cron)
Check the Actions tab for a "This workflow is disabled" banner and
re-enable. Also confirm the workflow is on main. GitHub's scheduler is
best-effort — use cron-job.org for reliable timing.

cron-job.org stops working
Usually an expired GitHub PAT. Regenerate the token and update the
Authorization header in cron-job.org.

---

Cost

Free. GitHub Actions gives unlimited minutes for public repositories.
This project uses roughly 30 seconds per run — about 12 hours of usage per
month. cron-job.org is free for hourly schedules.

---

License

MIT — do what you want with it.

```

---
