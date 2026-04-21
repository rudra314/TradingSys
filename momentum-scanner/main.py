"""
main.py — NSE Momentum Scanner scheduler.

Runs three recurring jobs (all times IST):
  Sunday 18:00    — full universe scan, generates weekly watchlist
  Mon-Fri 09:30   — morning breakout check on watchlist stocks
  Mon-Fri 15:00   — afternoon exit / trailing-SL check on open positions
"""
import json
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

import pytz
import schedule

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from data.data_provider import get_provider
from data.universe import UNIVERSE
from engine.rs55_engine import compute_rs55
from engine.gates import apply_all_gates, compute_sector_rs55_map
from engine.scorer import score_universe
from engine.regime import get_market_regime
from engine.breakout import run_breakout_scan
from engine.exit_engine import check_all_exits, load_positions
from notify.notifier import (
    send_weekly_summary, send_exit_alert, send_regime_alert,
)
from notify.results_calendar import fetch_results_calendar

_IST = pytz.timezone("Asia/Kolkata")
_DATA_DIR = Path(__file__).parent / "data"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(Path(__file__).parent / "logs" / "scanner.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("main")


def _save_json(data: object, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _load_json(path: Path) -> dict | list:
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {}


def run_weekly_scan() -> None:
    """Sunday 18:00 IST — full universe scan and weekly watchlist generation."""
    log.info("=== WEEKLY SCAN STARTED ===")
    provider = get_provider()
    today = date.today().isoformat()

    try:
        nifty_df = provider.get_benchmark(400)
    except Exception as exc:
        log.error("Failed to fetch Nifty benchmark: %s", exc)
        return

    calendar = fetch_results_calendar(today)
    regime = get_market_regime(nifty_df)
    log.info("Market regime: State %d — %s", regime["state"], regime["label"])

    if regime["state"] == 4:
        send_regime_alert(regime)
        log.info("CASH MODE: skipping new setups.")
        return

    log.info("Fetching OHLCV for %d symbols…", len(UNIVERSE))
    all_data = provider.get_all_ohlcv(UNIVERSE, 400)
    log.info("Loaded %d symbols", len(all_data))

    rs55_map: dict[str, dict] = {}
    for sym, df in all_data.items():
        try:
            rs55_map[sym] = compute_rs55(df, nifty_df)
        except Exception as exc:
            log.warning("RS55 failed for %s: %s", sym, exc)

    sector_rs55_map = compute_sector_rs55_map(provider, nifty_df)

    eligible: dict = {}
    blackout_count = 0
    for sym, df in all_data.items():
        try:
            passed, reasons = apply_all_gates(sym, df, nifty_df, sector_rs55_map, calendar)
            if passed:
                eligible[sym] = df
            else:
                if any("blackout" in r.lower() or "results" in r.lower() for r in reasons):
                    blackout_count += 1
                log.debug("%s failed gates: %s", sym, reasons)
        except Exception as exc:
            log.error("Gate error for %s: %s", sym, exc)

    log.info("Eligible after gates: %d / %d", len(eligible), len(all_data))

    if not eligible:
        log.warning("No eligible stocks — check gate thresholds or data quality.")
        return

    ranked_df = score_universe(eligible, nifty_df, rs55_map)
    top20 = ranked_df[ranked_df["grade"] != "EXCLUDE"].head(20)

    top20.to_csv(_DATA_DIR / "watchlist.csv", index=False)
    _save_json(top20.to_dict("records"), _DATA_DIR / "watchlist.json")
    log.info("Watchlist saved: %d stocks", len(top20))

    send_weekly_summary(
        top20.to_dict("records"),
        regime,
        len(all_data),
        len(eligible),
        blackout_count,
    )
    log.info("=== WEEKLY SCAN COMPLETE ===")


def run_morning_check() -> None:
    """Mon-Fri 09:30 IST — breakout detection on watchlist stocks."""
    log.info("=== MORNING CHECK STARTED ===")
    provider = get_provider()

    try:
        nifty_df = provider.get_benchmark(400)
    except Exception as exc:
        log.error("Benchmark fetch failed: %s", exc)
        return

    regime = get_market_regime(nifty_df)
    if regime["state"] == 4:
        send_regime_alert(regime)
        return

    watchlist = _load_json(_DATA_DIR / "watchlist.json")
    if not watchlist:
        log.warning("Watchlist empty — run weekly scan first.")
        return

    symbols = [s["symbol"] for s in watchlist if isinstance(s, dict) and "symbol" in s]
    latest_data = provider.get_all_ohlcv(symbols, 400)

    rs55_map: dict[str, dict] = {}
    for sym, df in latest_data.items():
        try:
            rs55_map[sym] = compute_rs55(df, nifty_df)
        except Exception:
            pass

    for sym in symbols:
        if sym not in latest_data:
            continue
        try:
            stock_meta = next(
                (s for s in watchlist if isinstance(s, dict) and s.get("symbol") == sym), {}
            )
            run_breakout_scan(
                sym, latest_data[sym], nifty_df,
                rs55_map.get(sym, {}), stock_meta, regime, provider,
            )
        except Exception as exc:
            log.error("Breakout scan error for %s: %s", sym, exc)

    # Early warning checks on open positions
    positions = load_positions()
    for sym, pos in positions.items():
        if sym in latest_data and sym in rs55_map:
            try:
                alerts = check_all_exits(sym, latest_data[sym], rs55_map[sym])
                for alert in alerts:
                    if alert.get("urgency") == "warning":
                        send_exit_alert(sym, alert["type"], alert["message"], pos)
            except Exception as exc:
                log.error("Exit check error for %s: %s", sym, exc)

    log.info("=== MORNING CHECK COMPLETE ===")


def run_afternoon_check() -> None:
    """Mon-Fri 15:00 IST — exit monitoring on all open positions."""
    log.info("=== AFTERNOON CHECK STARTED ===")
    provider = get_provider()

    try:
        nifty_df = provider.get_benchmark(400)
    except Exception as exc:
        log.error("Benchmark fetch failed: %s", exc)
        return

    positions = load_positions()
    if not positions:
        log.info("No open positions to monitor.")
        return

    symbols = list(positions.keys())
    latest_data = provider.get_all_ohlcv(symbols, 400)

    rs55_map: dict[str, dict] = {}
    for sym, df in latest_data.items():
        try:
            rs55_map[sym] = compute_rs55(df, nifty_df)
        except Exception:
            pass

    for sym, pos in positions.items():
        if sym not in latest_data:
            continue
        try:
            alerts = check_all_exits(sym, latest_data[sym], rs55_map.get(sym, {}))
            for alert in alerts:
                send_exit_alert(sym, alert["type"], alert["message"], pos)
        except Exception as exc:
            log.error("Afternoon exit check error for %s: %s", sym, exc)

    log.info("=== AFTERNOON CHECK COMPLETE ===")


def _schedule_jobs() -> None:
    schedule.every().sunday.at(config.WEEKLY_SCAN_TIME).do(run_weekly_scan)
    for day in ["monday", "tuesday", "wednesday", "thursday", "friday"]:
        getattr(schedule.every(), day).at(config.MORNING_CHECK_TIME).do(run_morning_check)
        getattr(schedule.every(), day).at(config.AFTERNOON_CHECK_TIME).do(run_afternoon_check)


if __name__ == "__main__":
    log.info("NSE Momentum Scanner starting…")
    Path("logs").mkdir(exist_ok=True)
    _schedule_jobs()
    log.info(
        "Scheduled: Weekly scan Sunday %s IST | "
        "Morning %s IST | Afternoon %s IST",
        config.WEEKLY_SCAN_TIME,
        config.MORNING_CHECK_TIME,
        config.AFTERNOON_CHECK_TIME,
    )
    while True:
        schedule.run_pending()
        time.sleep(30)
