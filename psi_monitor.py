#!/usr/bin/env python3
"""
Singapore Haze PSI + PM2.5 Monitor

Pulls 24-hour PSI, 24-hour PM2.5, and 1-hour PM2.5 from data.gov.sg (NEA data)
and sends a Telegram message only when any regional reading changes.

Runs hourly via GitHub Actions. Credentials come from environment variables
(set as GitHub Secrets):
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID

CLI:
    python psi_monitor.py             # normal run
    python psi_monitor.py --preview   # print only, no send, no state write
    python psi_monitor.py --force     # send even if readings unchanged
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import requests

# =============================================================================
# Configuration
# =============================================================================

# Metric toggles — flip to True to include in the message.
SEND_PSI_24H  = True
SEND_PM25_24H = True
SEND_PM25_1H  = True

# Endpoints (verified 2026-10)
PSI_URL           = "https://api-open.data.gov.sg/v2/real-time/api/psi"
PM25_URL          = "https://api-open.data.gov.sg/v2/real-time/api/pm25"
PM25_FALLBACK_URL = "https://api.data.gov.sg/v1/environment/pm25"

# Runtime settings
HTTP_TIMEOUT       = 30          # seconds
MAX_RETRIES        = 3
MAX_DATA_AGE_HOURS = 3           # reject stale readings
TELEGRAM_RETRIES   = 3

# Singapore time
SGT = timezone(timedelta(hours=8))

# State file (cached between GitHub Actions runs, not committed)
STATE_FILE = Path(__file__).with_name(".psi_state.json")

# Telegram credentials
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID")

# Metric display order (top to bottom in the message)
METRIC_ORDER = ["pm25_1h", "pm25_24h", "psi_24h"]

METRICS: dict[str, dict[str, Any]] = {
    "psi_24h":  {"label": "24-hr PSI", "enabled": SEND_PSI_24H,
                 "prefix": "24h", "short": "PSI"},
    "pm25_24h": {"label": "24-hr 2.5", "enabled": SEND_PM25_24H,
                 "prefix": "24h", "short": "2.5"},
    "pm25_1h":  {"label": "1-hr 2.5",  "enabled": SEND_PM25_1H,
                 "prefix": "1h",  "short": "2.5"},
}

# Region display order (left to right) and abbreviations
REGION_ORDER = ["central", "west", "south", "east", "north"]
REGION_ABBR  = {"central": "C", "west": "W", "south": "S", "east": "E", "north": "N"}

# =============================================================================
# Logging
# =============================================================================

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("psi_monitor")

# =============================================================================
# Air quality bands
# =============================================================================

def band_emoji(value: float, is_psi: bool = False) -> str:
    """Return a single colored circle representing the air-quality band."""
    if is_psi:
        if value <= 50:   return "🟢"   # Good
        if value <= 100:  return "🟠"   # Moderate
        if value <= 200:  return "🔴"   # Unhealthy
        if value <= 300:  return "🟣"   # Very Unhealthy
        return "💀"                     # Hazardous

    # PM2.5 µg/m³ (NEA 1-hour bands)
    if value <= 55:   return "🟢"       # Normal
    if value <= 150:  return "🟠"       # Elevated
    if value <= 250:  return "🔴"       # High
    return "💀"                         # Very High

# =============================================================================
# HTTP helpers
# =============================================================================

def get_json(url: str) -> dict:
    """GET a URL and return JSON, with retries and exponential backoff."""
    last_error: Exception | None = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            r = requests.get(url, timeout=HTTP_TIMEOUT,
                             headers={"Accept": "application/json"})
            r.raise_for_status()
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last_error = e
            log.warning("Attempt %d/%d %s failed: %s",
                        attempt, MAX_RETRIES, url, e)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"Failed to fetch {url}: {last_error}")

# =============================================================================
# Data fetching
# =============================================================================

def _parse_v2(payload: dict) -> tuple[str, dict]:
    item = payload["data"]["items"][0]
    return item["timestamp"], item["readings"]


def _check_fresh(ts_str: str) -> datetime:
    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    age = datetime.now(SGT) - ts.astimezone(SGT)
    if age > timedelta(hours=MAX_DATA_AGE_HOURS):
        raise RuntimeError(f"Data is stale: {ts_str} ({age} old)")
    return ts


def fetch_all() -> dict:
    """Fetch PSI + PM2.5 for all regions."""
    result: dict[str, Any] = {"psi_24h": {}, "pm25_24h": {}, "pm25_1h": {}}
    timestamps: list[str] = []

    # PSI + 24-hr PM2.5 (both come from the PSI endpoint)
    ts, readings = _parse_v2(get_json(PSI_URL))
    _check_fresh(ts)
    result["psi_24h"]  = {k.title(): int(v)
                          for k, v in readings["psi_twenty_four_hourly"].items()}
    result["pm25_24h"] = {k.title(): int(v)
                          for k, v in readings["pm25_twenty_four_hourly"].items()}
    timestamps.append(ts)
    log.info("PSI fetched from data.gov.sg v2")

    # 1-hr PM2.5 (separate endpoint, with v1 fallback)
    try:
        ts, readings = _parse_v2(get_json(PM25_URL))
        _check_fresh(ts)
        result["pm25_1h"] = {k.title(): float(v)
                             for k, v in readings["pm25_one_hourly"].items()}
        timestamps.append(ts)
        log.info("PM2.5 fetched from data.gov.sg v2")
    except Exception as e:
        log.warning("v2 PM2.5 failed (%s); trying v1 fallback", e)
        fallback = get_json(PM25_FALLBACK_URL)
        item = fallback["items"][0]
        _check_fresh(item["timestamp"])
        result["pm25_1h"] = {k.title(): float(v)
                             for k, v in item["readings"]["pm25_one_hourly"].items()}
        timestamps.append(item["timestamp"])
        log.info("PM2.5 fetched from v1 fallback")

    result["timestamp"] = max(timestamps)
    return result

# =============================================================================
# State persistence
# =============================================================================

def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            log.warning("State file corrupt; starting fresh")
    return {}


def save_state(state: dict) -> None:
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE_FILE)


def readings_only(data: dict | None) -> dict:
    """Strip the timestamp so two snapshots can be compared meaningfully."""
    if not data:
        return {}
    return {k: data.get(k, {}) for k in METRICS}

# =============================================================================
# Telegram
# =============================================================================

def send_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text,
               "disable_web_page_preview": True}

    for attempt in range(1, TELEGRAM_RETRIES + 1):
        try:
            r = requests.post(url, json=payload, timeout=HTTP_TIMEOUT)
            data = r.json()

            if data.get("ok"):
                return

            if r.status_code == 429:
                wait = data.get("parameters", {}).get("retry_after", 5)
                log.warning("Telegram rate-limited; sleeping %ss", wait)
                time.sleep(wait)
                continue

            raise RuntimeError(f"Telegram error: {data}")

        except requests.RequestException as e:
            log.warning("Telegram attempt %d/%d failed: %s",
                        attempt, TELEGRAM_RETRIES, e)
            time.sleep(2 ** attempt)

    raise RuntimeError("Telegram send failed after retries")

# =============================================================================
# Message formatting
# =============================================================================

def fmt_num(v: float) -> str:
    return f"{v:.1f}" if isinstance(v, float) and not v.is_integer() else str(int(v))


def ordered_items(region_map: dict) -> list[tuple[str, float]]:
    """Return region items in REGION_ORDER; unknown regions sorted after."""
    rank = {r: i for i, r in enumerate(REGION_ORDER)}
    return sorted(region_map.items(),
                  key=lambda kv: (rank.get(kv[0].lower(), len(rank)), kv[0].lower()))


def format_message(readings: dict) -> str:
    """Build the Telegram message.

    One colored circle per metric row — based on that row's highest value.
    """
    lines: list[str] = []

    # Header
    if readings.get("timestamp"):
        ts = datetime.fromisoformat(readings["timestamp"].replace("Z", "+00:00"))
        lines.append("🌫 " + ts.astimezone(SGT).strftime("%d %b, %H:%M"))

    # One line per enabled metric
    for key in METRIC_ORDER:
        meta = METRICS[key]
        if not meta["enabled"]:
            continue

        data = readings.get(key, {})
        if not data:
            continue

        # Single circle for the whole row — pick the worst (highest) region
        worst = max(data.values())
        dot = band_emoji(worst, is_psi=(key == "psi_24h"))

        # Readings, in region order
        parts = []
        for region, val in ordered_items(data):
            abbr = REGION_ABBR.get(region.lower(), region[0].upper())
            parts.append(f"{abbr}:{fmt_num(val)}")

        # Aligned prefix like "1h   2.5" / "24h  PSI"
        prefix = meta["prefix"].ljust(4) + meta["short"].rjust(3)
        lines.append(f"{prefix} {dot} " + " ".join(parts))

    return "\n".join(lines)

# =============================================================================
# Entry point
# =============================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description="Singapore haze monitor")
    ap.add_argument("--preview", action="store_true",
                    help="Print the message without sending or saving state")
    ap.add_argument("--force", action="store_true",
                    help="Send even if readings are unchanged")
    args = ap.parse_args()

    try:
        current = fetch_all()
    except Exception as e:
        log.error("Fetch failed: %s", e)
        return 1

    text = format_message(current)

    # Always print so it shows up in GitHub Actions logs
    print("--- Message preview ---")
    print(text)
    print("-----------------------")

    if args.preview:
        return 0

    state = load_state()
    prev = state.get("last_reading")

    if not args.force and readings_only(current) == readings_only(prev):
        log.info("Readings unchanged; skipping Telegram message")
        return 0

    try:
        send_telegram(text)
    except Exception as e:
        log.error("Telegram send failed: %s", e)
        return 1

    state["last_reading"] = current
    state["last_sent_at"] = datetime.now(SGT).isoformat()
    save_state(state)
    log.info("Message sent to Telegram (force=%s)", args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
