#!/usr/bin/env python3
"""
Singapore Haze PSI + PM2.5 Monitor
- Pulls 24-hour PSI, 24-hour PM2.5, and 1-hour PM2.5 from data.gov.sg (NEA data)
- Sends Telegram message ONLY when any regional reading changes vs. last poll
- Runs hourly via GitHub Actions

Credentials are read from environment variables (set as GitHub Secrets):
  TELEGRAM_BOT_TOKEN
  TELEGRAM_CHAT_ID
"""

import json
import os
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

# ---------- Metric toggles ----------
# Default: only 1-hour PM2.5. Flip to True to include the others.
SEND_PSI_24H  = True
SEND_PM25_24H = True
SEND_PM25_1H  = True
# ------------------------------------

SGT = timezone(timedelta(hours=8))
STATE_FILE = Path(__file__).with_name(".psi_state.json")

PSI_URL = "https://api-open.data.gov.sg/v2/real-time/api/psi"
PM25_URL = "https://api-open.data.gov.sg/v2/real-time/api/pm25"
PM25_FALLBACK_URL = "https://api.data.gov.sg/v1/environment/pm25"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

HTTP_TIMEOUT = 30
MAX_RETRIES = 3
MAX_DATA_AGE_HOURS = 3

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("psi_monitor")

METRIC_ORDER = ["pm25_1h", "pm25_24h", "psi_24h"]
METRICS = {
    "psi_24h":  {"label": "24-hr PSI", "enabled": SEND_PSI_24H,
                 "prefix": "24h", "short": "PSI"},
    "pm25_24h": {"label": "24-hr 2.5", "enabled": SEND_PM25_24H,
                 "prefix": "24h", "short": "2.5"},
    "pm25_1h":  {"label": "1-hr 2.5",  "enabled": SEND_PM25_1H,
                 "prefix": "1h",  "short": "2.5"},
}

def _band_emoji(v, is_psi=False):
    """Colored circle indicating the air-quality band."""
    if is_psi:
        if v <= 50:   return "🟢"   # Good
        if v <= 100:  return "🟡"   # Moderate
        if v <= 200:  return "🟠"   # Unhealthy
        if v <= 300:  return "🔴"   # Very Unhealthy
        return "🟣"                 # Hazardous
    # PM2.5 µg/m³ (roughly aligned with WHO 24h guidelines)
    if v <= 12:   return "🟢"
    if v <= 35:   return "🟡"
    if v <= 55:   return "🟠"
    if v <= 150:  return "🔴"
    return "🟣"

REGION_ORDER = ["central", "west", "south", "east", "north"]
REGION_ABBR  = {"central": "C", "west": "W", "south": "S", "east": "E", "north": "N"}


def _ordered_items(region_map):
    rank = {r: i for i, r in enumerate(REGION_ORDER)}
    return sorted(region_map.items(),
                  key=lambda kv: (rank.get(kv[0].lower(), len(rank)), kv[0].lower()))


def _get_json(url):
    last = None
    for i in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT,
                             headers={"Accept": "application/json"})
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last = e
            log.warning("Attempt %d/%d %s failed: %s", i, MAX_RETRIES, url, e)
            time.sleep(2 ** i)
    raise RuntimeError(f"Failed to fetch {url}: {last}")


def _parse_v2(payload):
    item = payload["data"]["items"][0]
    return item["timestamp"], item["readings"]


def _check_fresh(ts_str):
    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    age = datetime.now(SGT) - ts.astimezone(SGT)
    if age > timedelta(hours=MAX_DATA_AGE_HOURS):
        raise RuntimeError(f"Data is stale: timestamp {ts_str} ({age} old)")
    return ts


def fetch_all():
    result = {"psi_24h": {}, "pm25_24h": {}, "pm25_1h": {}}
    timestamps = []

    ts, r = _parse_v2(_get_json(PSI_URL))
    _check_fresh(ts)
    result["psi_24h"]  = {k.title(): int(v) for k, v in r["psi_twenty_four_hourly"].items()}
    result["pm25_24h"] = {k.title(): int(v) for k, v in r["pm25_twenty_four_hourly"].items()}
    timestamps.append(ts)
    log.info("PSI fetched from data.gov.sg v2")

    try:
        ts, r = _parse_v2(_get_json(PM25_URL))
        _check_fresh(ts)
        result["pm25_1h"] = {k.title(): float(v) for k, v in r["pm25_one_hourly"].items()}
        timestamps.append(ts)
        log.info("PM2.5 fetched from data.gov.sg v2")
    except Exception as e:
        log.warning("v2 PM2.5 failed (%s); trying v1 fallback", e)
        dg = _get_json(PM25_FALLBACK_URL)
        item = dg["items"][0]
        _check_fresh(item["timestamp"])
        result["pm25_1h"] = {k.title(): float(v)
                             for k, v in item["readings"]["pm25_one_hourly"].items()}
        timestamps.append(item["timestamp"])
        log.info("PM2.5 fetched from v1 fallback")

    result["timestamp"] = min(timestamps)
    return result


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("State file corrupt; starting fresh")
    return {}


def save_state(state):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text,
               "disable_web_page_preview": True}

    for attempt in range(1, 4):
        try:
            r = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
            data = r.json()
            if data.get("ok"):
                return
            # Respect Telegram's retry_after on 429
            if r.status_code == 429:
                wait = data.get("parameters", {}).get("retry_after", 5)
                log.warning("Telegram rate-limited; sleeping %ss", wait)
                time.sleep(wait)
                continue
            raise RuntimeError(f"Telegram error: {data}")
        except requests.RequestException as e:
            log.warning("Telegram attempt %d/3 failed: %s", attempt, e)
            time.sleep(2 ** attempt)

    raise RuntimeError("Telegram send failed after retries")

def _fmt(v):
    return f"{v:.1f}" if isinstance(v, float) and not v.is_integer() else str(int(v))


def format_message(readings):
    lines = []

    if readings.get("timestamp"):
        ts = datetime.fromisoformat(readings["timestamp"].replace("Z", "+00:00"))
        lines.append("🌫 " + ts.astimezone(SGT).strftime("%d %b, %H:%M"))

    for key in METRIC_ORDER:
        meta = METRICS[key]
        if not meta["enabled"]:
            continue
        data = readings.get(key, {})
        if not data:
            continue
        parts = []
        for region, val in _ordered_items(data):
            abbr = REGION_ABBR.get(region.lower(), region[0].upper())
            dot = _band_emoji(val, is_psi=(key == "psi_24h"))
            parts.append(f"{abbr}:{_fmt(val)}{dot}")
        # "1h   2.5" / "24h  2.5" / "24h  PSI" -- fixed 4-char window + 2-char metric
        prefix = meta["prefix"].ljust(4) + meta["short"].rjust(3)
        lines.append(f"{prefix} " + " ".join(parts))

    return "\n".join(lines)


def main():
    try:
        current = fetch_all()
    except Exception as e:
        log.error("Fetch failed: %s", e)
        return 1

    state = load_state()
    prev = state.get("last_reading")
    text = format_message(current)

    # Always print so it shows up in GitHub Actions logs
    print("--- Message preview ---")
    print(text)
    print("-----------------------")

    if current == prev:
        log.info("No change in readings; skipping Telegram message")
        return 0

    try:
        send_telegram(text)
    except Exception as e:
        log.error("Telegram send failed: %s", e)
        return 1

    state["last_reading"] = current
    state["last_sent_at"] = datetime.now(SGT).isoformat()
    save_state(state)
    log.info("Change detected; message sent to Telegram")
    return 0


if __name__ == "__main__":
    sys.exit(main())
