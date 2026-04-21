"""
results_calendar.py — NSE quarterly results blackout checker.
Fetches NSE event calendar, caches to data/results_calendar_{date}.json.
Gate 5 uses is_in_blackout(). If NSE API fails, returns empty dict and gate is skipped.
"""
import json
import logging
import os
import sys

import requests
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

log = logging.getLogger(__name__)
_DATA_DIR = Path(__file__).parent.parent / "data"


def fetch_results_calendar(cache_date: str) -> dict:
    """
    Fetch NSE quarterly results calendar for the next 30 days.
    Primary: NSE event-calendar API.
    Cache: data/results_calendar_{cache_date}.json (load if exists).
    Fallback: empty dict (Gate 5 skipped, logged).

    Args:
        cache_date: ISO date string YYYY-MM-DD

    Returns:
        Dict {symbol: [date_str, ...]} of upcoming results dates.
    """
    cache_path = _DATA_DIR / f"results_calendar_{cache_date}.json"

    # Return cached data if available
    if cache_path.exists():
        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
            log.debug("Loaded results calendar from cache: %s", cache_path)
            return data
        except Exception as exc:
            log.warning("Failed to load cached calendar %s: %s", cache_path, exc)

    # NSE API fetch
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        }
        url = "https://www.nseindia.com/api/event-calendar"

        session = requests.Session()
        # First GET to nseindia.com to acquire cookies
        session.get("https://www.nseindia.com/", headers=headers, timeout=15)
        # Now fetch the event calendar
        resp = session.get(url, headers=headers, timeout=15)
        resp.raise_for_status()

        events = resp.json()
        if not isinstance(events, list):
            raise ValueError(f"Unexpected response type: {type(events)}")

        # Build {symbol: [date_str, ...]} dict
        calendar: dict[str, list[str]] = {}
        for event in events:
            symbol = event.get("symbol") or event.get("Symbol")
            event_date = event.get("date") or event.get("Date") or event.get("bDDate")
            if symbol and event_date:
                symbol = symbol.strip().upper()
                # Normalise date — keep the ISO substring if full datetime string
                if isinstance(event_date, str) and "T" in event_date:
                    event_date = event_date.split("T")[0]
                elif isinstance(event_date, str) and " " in event_date:
                    event_date = event_date.split(" ")[0]
                calendar.setdefault(symbol, [])
                if event_date not in calendar[symbol]:
                    calendar[symbol].append(event_date)

        # Persist cache
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(calendar, f, indent=2)
        log.info("Results calendar fetched: %d symbols, cached to %s", len(calendar), cache_path)
        return calendar

    except Exception as exc:
        log.warning(
            "NSE results calendar fetch failed (%s). Gate 5 will be skipped.", exc
        )
        return {}


def is_in_blackout(symbol: str, check_date: date, calendar: dict) -> bool:
    """
    Returns True if symbol has results in next config.RESULTS_BLACKOUT_DAYS trading days.

    Trading days = Mon-Fri only (no holiday calendar needed, conservative estimate).

    Args:
        symbol: NSE stock symbol (e.g. 'RELIANCE')
        check_date: The reference date (usually today)
        calendar: Dict {symbol: [date_str, ...]} from fetch_results_calendar()

    Returns:
        True if the symbol has a results date within the blackout window.
    """
    symbol_dates = calendar.get(symbol, [])
    if not symbol_dates:
        return False

    # Generate next N trading days (Mon-Fri) from check_date exclusive
    trading_days: set[str] = set()
    cursor = check_date
    days_counted = 0
    while days_counted < config.RESULTS_BLACKOUT_DAYS:
        cursor = cursor + timedelta(days=1)
        if cursor.weekday() < 5:  # 0=Mon … 4=Fri
            trading_days.add(cursor.isoformat())
            days_counted += 1

    # Also include today itself
    if check_date.weekday() < 5:
        trading_days.add(check_date.isoformat())

    return any(d in trading_days for d in symbol_dates)
