# Singapore Haze Monitor

Hourly Singapore air quality updates — PSI, PM2.5, temperature, and humidity — pulled from [data.gov.sg](https://data.gov.sg) and posted to Telegram when the data changes.

Runs on GitHub Actions. No server, no hosting fees.

---

## Example output

```

🟠 PSI Updated: 11 Oct, 12:30 am
━━━━━━━━━━━━━━━━━━
┃ Reg  | 1h 2.5 | 24h 2.5 | 24h PSI
┃      |   🟠   |   🟢    |   🟠
┃ -----+--------+---------+--------
┃  C   |    100 |     102 |   149
┃  W   |     98 |     104 |   151
┃  S   |     98 |      69 |   115
┃  E   |     84 |      90 |   136
┃  N   |     68 |      71 |   118
🌡️ 29.1-30.9°c | 💧 70-85%

```

Regions: **C**entral · **W**est · **S**outh · **E**ast · **N**orth

Columns ordered by reactivity — fastest-changing (most actionable) on the left:
**1h PM2.5** → **24h PM2.5** → **24h PSI**

### Colour code

One circle per column, based on the worst region in that column.

**PM2.5 (µg/m³):** 🟢 0–55 · 🟠 56–150 · 🔴 151–250 · 💀 ≥251

**PSI:** 🟢 0–50 · 🟠 51–100 · 🔴 101–200 · 🟣 201–300 · 💀 ≥301

---

## Setup

**1. Create a Telegram bot**
- Message **@BotFather** → `/newbot` → copy the token
- Send `/start` to your new bot

**2. Create a Telegram channel**
- Add the bot as an **Administrator** with **Post Messages** permission

**3. Add secrets to GitHub**
Settings → Secrets and variables → Actions → New repository secret:

| Name | Value |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Bot token from BotFather |
| `TELEGRAM_CHAT_ID` | Channel `@username` |
| `TELEGRAM_CHAT_ID_TEST` | *(optional)* your personal chat ID for testing |

**4. Test**
Actions → Singapore Haze Monitor → Run workflow

---

## Scheduling

GitHub's native cron is best-effort — runs can be delayed or skipped. For reliable hourly triggers, use **cron-job.org**:

1. Create a **GitHub PAT** (Fine-grained, `Actions: Read and write`)
2. In cron-job.org, create a job:
   - **URL:** `https://api.github.com/repos/<user>/<repo>/actions/workflows/psi_monitor.yml/dispatches`
   - **Method:** `POST`
   - **Body:** `{"ref":"main"}`
   - **Headers:**
     - `Accept: application/vnd.github+json`
     - `Authorization: Bearer <your-PAT>`
     - `X-GitHub-Api-Version: 2022-11-28`
     - `Content-Type: application/json`
   - **Schedule:** hourly, minute 5, timezone Asia/Singapore
3. Successful trigger returns **204 No Content**
4. **Renew the PAT every ~90 days** or triggering stops silently

---

## Configuration

**Toggle metrics** — edit `psi_monitor.py`:

```python
SEND_PSI_24H  = True
SEND_PM25_24H = True
SEND_PM25_1H  = True
```

Ruler width:

```python
HR = "━" * 18    # 18 chars ≈ 50% width
```

Region order:

```python
REGION_ORDER = ["central", "west", "south", "east", "north"]
```

---

CLI

Flag Effect
(none) Send only if timestamp changed
--preview Print only, no send, no state
--force Send even if unchanged
--to CHAT_ID Send to a different chat (testing)

```bash
python psi_monitor.py --preview
python psi_monitor.py --force --to 123456789
```

---

Test branch

The workflow targets different chats based on branch:

Branch Target Force send?
main Channel Only on change
test Your DM (TELEGRAM_CHAT_ID_TEST) Yes

Use the test branch to iterate on format without spamming the channel. Merge to main when happy.

---

Files

File Purpose
psi_monitor.py Main script
requirements.txt Dependencies (requests)
.github/workflows/psi_monitor.yml Workflow

State is stored in GitHub Actions cache — never committed to the repo.

---

Troubleshooting

Bad Request: chat not found — Bot not added to channel, or wrong TELEGRAM_CHAT_ID

Workflow missing from Actions tab — File must be at .github/workflows/<name>.yml (leading dot)

Failed to save: Unable to reserve cache — Use a fresh run (Actions → Run workflow), not "Re-run all jobs"

Message sent every hour — Dedup uses API timestamp; ensure state_key() is used, not full-dict comparison

Scheduled runs not firing — Check Actions tab for a disabled banner; confirm workflow is on main; use cron-job.org for reliability

Force a test send — Use --force, or delete psi-state-* entries in Actions → Caches

---

Data sources

· PSI + 24h PM2.5: api-open.data.gov.sg/v2/real-time/api/psi
· 1h PM2.5: api-open.data.gov.sg/v2/real-time/api/pm25
· Temperature: api-open.data.gov.sg/v2/real-time/api/air-temperature
· Humidity: api-open.data.gov.sg/v2/real-time/api/relative-humidity

Source: NEA. Readings older than 3 hours are rejected.

---

Cost

Free. GitHub Actions is unlimited for public repos. ~30 seconds per run.

License

MIT

```
