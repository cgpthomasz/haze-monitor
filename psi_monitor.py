#!/usr/bin/env python3
"""
Singapore Haze PSI + PM2.5 Monitor

Pulls 24-hour PSI, 24-hour PM2.5, 1-hour PM2.5, air temperature, and relative
humidity from data.gov.sg (NEA data), and sends a Telegram message only when
the API's timestamp changes.

Runs hourly via GitHub Actions. Credentials come from environment variables
(set as GitHub Secrets):
    TELEGRAM_BOT_TOKEN
    TELEGRAM_CHAT_ID

CLI:
    python psi_monitor.py                          # normal run
    python psi_monitor.py --preview                # print only, no send, no state
    python psi_monitor.py --force                  # send even if unchanged
    python psi_monitor.py --to 123456789           # override chat target (testing)
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
TEMP_URL          = "https://api-open.data.gov.sg/v2/real-time/api/air-temperature"
HUMIDITY_URL      = "https://api-open.data.gov.sg/v2/real-time/api/relative-humidity"

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

# Region display order (left to right) and abbreviations
REGION_ORDER = ["central", "west", "south", "east", "north"]
REGION_ABBR  = {"central": "C", "west": "W", "south": "S", "east": "E", "north": "N"}

# Horizontal rule — placed between title and table
HR = "━" * 25

# =============================================================================
# Logging
# =============================================================================

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("psi_monitor")

# =============================================================================
# Air quality bands
# =============================================================================

# Severity rank used to pick the "worst" emoji for the title
COLOR_RANK = {"🟢": 0, "🟠": 1, "🔴": 2, "🟣": 3, "💀": 4, "⚪": -1}


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


def worst_color(emojis: list[str]) -> str:
    """Return the emoji with the highest severity rank."""
    return max(emojis, key=lambda e: COLOR_RANK.get(e, -1))

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
    """Return (timestamp, readings)."""
    item = payload["data"]["items"][0]
    return item["timestamp"], item["readings"]


def _check_fresh(ts_str: str) -> datetime:
    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    age = datetime.now(SGT) - ts.astimezone(SGT)
    if age > timedelta(hours=MAX_DATA_AGE_HOURS):
        raise RuntimeError(f"Data is stale: {ts_str} ({age} old)")
    return ts


def _parse_stations(payload: dict) -> list[float]:
    """Extract all station values from a v2 weather API response."""
    item = payload["data"]["readings"][0]
    return [float(r["value"]) for r in item["data"]]


def fetch_all() -> dict:
    """Fetch PSI, PM2.5, temperature, and humidity."""
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
    log.info("PSI fetched from data.gov.sg v2 (timestamp %s)", ts)

    # 1-hr PM2.5 (separate endpoint, with v1 fallback)
    try:
        ts, readings = _parse_v2(get_json(PM25_URL))
        _check_fresh(ts)
        result["pm25_1h"] = {k.title(): float(v)
                             for k, v in readings["pm25_one_hourly"].items()}
        timestamps.append(ts)
        log.info("PM2.5 fetched from data.gov.sg v2 (timestamp %s)", ts)
    except Exception as e:
        log.warning("v2 PM2.5 failed (%s); trying v1 fallback", e)
        fallback = get_json(PM25_FALLBACK_URL)
        item = fallback["items"][0]
        ts = item["timestamp"]
        _check_fresh(ts)
        result["pm25_1h"] = {k.title(): float(v)
                             for k, v in item["readings"]["pm25_one_hourly"].items()}
        timestamps.append(ts)
        log.info("PM2.5 fetched from v1 fallback (timestamp %s)", ts)

    result["timestamp"] = max(timestamps)

    # Weather: air temperature + relative humidity (min/max across stations)
    try:
        temp_values = _parse_stations(get_json(TEMP_URL))
        result["temp_min"] = min(temp_values)
        result["temp_max"] = max(temp_values)
        log.info("Temperature fetched: %.1f-%.1f°C",
                 result["temp_min"], result["temp_max"])
    except Exception as e:
        log.warning("Temperature fetch failed: %s", e)
        result["temp_min"] = None
        result["temp_max"] = None

    try:
        hum_values = _parse_stations(get_json(HUMIDITY_URL))
        result["humidity_min"] = min(hum_values)
        result["humidity_max"] = max(hum_values)
        log.info("Humidity fetched: %.0f-%.0f%%",
                 result["humidity_min"], result["humidity_max"])
    except Exception as e:
        log.warning("Humidity fetch failed: %s", e)
        result["humidity_min"] = None
        result["humidity_max"] = None

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


def state_key(data: dict | None) -> str:
    """Return the field used to detect changes: the API's timestamp."""
    if not data:
        return ""
    return data.get("timestamp", "")

# =============================================================================
# Telegram
# =============================================================================

def send_telegram(text: str, chat_id: str | None = None) -> None:
    target = chat_id or TELEGRAM_CHAT_ID
    if not TELEGRAM_BOT_TOKEN or not target:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and a chat ID must be set")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": target, "text": text,
               "disable_web_page_preview": True,
               "parse_mode": "HTML"}

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

def fmt_timestamp(ts_iso: str) -> str:
    """Format the API's timestamp as '10 Oct, 08:01 pm' (SGT)."""
    ts = datetime.fromisoformat(ts_iso.replace("Z", "+00:00"))
    dt = ts.astimezone(SGT)
    ampm = "am" if dt.hour < 12 else "pm"
    return f"{dt.strftime('%d %b, %I:%M')} {ampm}"


def fmt_weather(readings: dict) -> str:
    """Return the temp/humidity line, or '' if unavailable."""
    t_min = readings.get("temp_min")
    t_max = readings.get("temp_max")
    h_min = readings.get("humidity_min")
    h_max = readings.get("humidity_max")

    if t_min is None and h_min is None:
        return ""

    parts = []
    if t_min is not None and t_max is not None:
        parts.append(f"🌡️ {t_min:.1f}-{t_max:.1f}°c")
    if h_min is not None and h_max is not None:
        parts.append(f"💧 {h_min:.0f}-{h_max:.0f}%")

    return " | ".join(parts)


def format_message(readings: dict) -> str:
    """Build the Telegram message (HTML) as a monospace table inside a blockquote.

    Layout:
        🟠 PSI Updated: 11 Oct, 12:30 am
        ━━━━━━━━━━━━━━━━━━━━━━━━━
        > Reg  |  PSI | 1h 2.5 | 24h 2.5
        >      |  🟠  |   🟠   |   🟢
        > -----+------+--------+--------
        >  C   |  149 |  100.0 |    102
        >  W   |  151 |   98.0 |    104
        >  S   |  115 |   98.0 |     69
        >  E   |  136 |   84.0 |     90
        >  N   |  118 |   68.0 |     71

        🌡️ 29.1-30.9°c | 💧 70-85%

    - Horizontal rule sits directly above the table (no gap).
    - Colored circles sit on their own row directly below the header.
    - Title circle uses the worst color from the three column circles.
    """
    lines: list[str] = []

    # Pull readings per metric
    psi_vals  = readings.get("psi_24h",  {})
    pm1_vals  = readings.get("pm25_1h", {})
    pm24_vals = readings.get("pm25_24h", {})

    psi_max  = max(psi_vals.values())  if psi_vals  else None
    pm1_max  = max(pm1_vals.values())  if pm1_vals  else None
    pm24_max = max(pm24_vals.values()) if pm24_vals else None

    # Circle per column — based on column max
    psi_dot  = band_emoji(psi_max,  is_psi=True)  if psi_max  is not None else "⚪"
    pm1_dot  = band_emoji(pm1_max,  is_psi=False) if pm1_max  is not None else "⚪"
    pm24_dot = band_emoji(pm24_max, is_psi=False) if pm24_max is not None else "⚪"

    # Title circle = worst of the three column circles
    title_dot = worst_color([psi_dot, pm1_dot, pm24_dot])

    # Title line + horizontal rule (no blank line — ruler hugs the table)
    if readings.get("timestamp"):
        lines.append(f"{title_dot} <b>PSI Updated:</b> {fmt_timestamp(readings['timestamp'])}")
        lines.append(HR)

    # Table — header row, then circle row, then dash separator
    header     = "Reg  |  PSI | 1h 2.5 | 24h 2.5"
    circle_row = f"     |  {psi_dot}  |   {pm1_dot}   |   {pm24_dot}   "
    sep        = "-----+------+--------+--------"

    table = [
        f"<code>{header}</code>",
        f"<code>{circle_row}</code>",
        f"<code>{sep}</code>",
    ]

    for region_key in REGION_ORDER:
        region_title = region_key.title()
        abbr = REGION_ABBR[region_key]

        psi_v  = psi_vals.get(region_title)
        pm1_v  = pm1_vals.get(region_title)
        pm24_v = pm24_vals.get(region_title)

        reg_cell  = f" {abbr}   "
        psi_cell  = f"{int(psi_v):>5} "   if psi_v  is not None else "   -- "
        pm1_cell  = f"{pm1_v:>7.1f} "     if pm1_v  is not None else "     -- "
        pm24_cell = f"{int(pm24_v):>7} "  if pm24_v is not None else "     -- "

        table.append(f"<code>{reg_cell}|{psi_cell}|{pm1_cell}|{pm24_cell}</code>")

    # Wrap table in a blockquote
    lines.append("<blockquote>" + "\n".join(table) + "</blockquote>")

    # Weather line — outside the blockquote
    weather = fmt_weather(readings)
    if weather:
        lines.append(f"<code>{weather}</code>")

    return "\n".join(lines)

# =============================================================================
# Entry point
# =============================================================================

def main() -> int:
    ap = argparse.ArgumentParser(description="Singapore haze monitor")
    ap.add_argument("--preview", action="store_true",
                    help="Print the message without sending or saving state")
    ap.add_argument("--force", action="store_true",
                    help="Send even if timestamp is unchanged")
    ap.add_argument("--to", metavar="CHAT_ID", default=None,
                    help="Send to this chat ID instead of TELEGRAM_CHAT_ID (testing)")
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

    # Dedup: only the API's timestamp matters
    if not args.force and state_key(current) == state_key(prev):
        log.info("timestamp unchanged (%s); skipping Telegram message",
                 state_key(current))
        return 0

    try:
        send_telegram(text, chat_id=args.to)
    except Exception as e:
        log.error("Telegram send failed: %s", e)
        return 1

    state["last_reading"] = current
    state["last_sent_at"] = datetime.now(SGT).isoformat()
    save_state(state)
    log.info("Message sent to Telegram (force=%s, to=%s)",
             args.force, args.to or "default")
    return 0


if __name__ == "__main__":
    sys.exit(main())
