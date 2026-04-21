"""
run_scan.py — GitHub Actions entry point.

Usage:
    python run_scan.py weekly      # Sunday 6 PM IST full scan
    python run_scan.py morning     # Mon-Fri 9:30 AM IST breakout check
    python run_scan.py afternoon   # Mon-Fri 3:00 PM IST exit check

After each run, exports dashboard-ready JSON to docs/data/ in the repo root
so GitHub Pages refreshes automatically when the commit is pushed.
"""
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

REPO_ROOT   = Path(__file__).parent.parent
SCANNER_DIR = Path(__file__).parent
DATA_DIR    = SCANNER_DIR / "data"
DOCS_DIR    = REPO_ROOT / "docs" / "data"
LOGS_DIR    = SCANNER_DIR / "logs"

DOCS_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "scanner.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("run_scan")


def _load(path: Path):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def _save(data, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


_REGIME_FETCH_FAILED = {
    "state": 0,
    "label": "Data Unavailable",
    "size_multiplier": 0.0,
    "max_positions": 0,
    "description": "Could not fetch market data. Check Actions logs for yfinance errors.",
}


def export_to_docs(regime: dict = None, stats: dict = None) -> None:
    wl = _load(DATA_DIR / "watchlist.json")
    if wl:
        _save(wl, DOCS_DIR / "watchlist.json")
        log.info("docs/data/watchlist.json — %d stocks", len(wl))
    pos = _load(DATA_DIR / "open_positions.json")
    _save(pos or {}, DOCS_DIR / "open_positions.json")
    _save(regime or _REGIME_FETCH_FAILED, DOCS_DIR / "regime.json")
    signals = _parse_signals_log(LOGS_DIR / "signals.log")
    _save(signals, DOCS_DIR / "signals.json")
    if stats:
        stats["scan_timestamp"] = datetime.now(timezone.utc).isoformat()
        stats["scan_date"] = datetime.now().strftime("%Y-%m-%d")
        _save(stats, DOCS_DIR / "scan_meta.json")
    log.info("docs/data/ export complete")


def _parse_signals_log(log_path: Path) -> list[dict]:
    if not log_path.exists():
        return []
    entries = []
    try:
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                parts = [p.strip() for p in line.split("|")]
                if len(parts) >= 3:
                    entry: dict = {"timestamp": parts[0], "alert_type": parts[1], "symbol": parts[2]}
                    if len(parts) >= 9:
                        try:
                            entry["entry"]    = float(parts[3])
                            entry["sl"]       = float(parts[4])
                            entry["target1"]  = float(parts[5])
                            entry["grade"]    = parts[6]
                            entry["score"]    = int(float(parts[7]))
                            entry["rs55_pct"] = float(parts[8])
                        except (ValueError, IndexError):
                            pass
                    entries.append(entry)
    except Exception as exc:
        log.warning("Could not parse signals.log: %s", exc)
    return list(reversed(entries))[-50:]


def run_weekly() -> None:
    log.info("=== WEEKLY SCAN (GitHub Actions) ===")
    from main import run_weekly_scan
    from engine.regime import get_market_regime
    from data.data_provider import get_provider

    try:
        run_weekly_scan()
    except Exception as exc:
        log.error("run_weekly_scan() raised an unhandled exception: %s", exc, exc_info=True)

    try:
        provider = get_provider()
        nifty_df = provider.get_benchmark(400)
        regime = get_market_regime(nifty_df)
    except Exception as exc:
        log.error("Failed to fetch benchmark/regime for dashboard export: %s", exc, exc_info=True)
        regime = None

    wl = _load(DATA_DIR / "watchlist.json") or []
    stats = {
        "total_scanned": 0,
        "total_eligible": 0,
        "watchlist_count": len(wl),
        "blackout_count": 0,
        "sector_leaders": [],
    }
    try:
        with open(LOGS_DIR / "scanner.log") as f:
            for line in reversed(f.readlines()):
                if "Loaded" in line and "symbols" in line:
                    stats["total_scanned"] = int(line.split("Loaded")[1].split("symbols")[0].strip())
                    break
        with open(LOGS_DIR / "scanner.log") as f:
            for line in reversed(f.readlines()):
                if "Eligible after gates" in line:
                    part = line.split("Eligible after gates:")[1].split("/")
                    stats["total_eligible"] = int(part[0].strip())
                    stats["total_scanned"]  = int(part[1].strip())
                    break
    except Exception:
        pass
    if wl:
        from collections import Counter
        sector_counts = Counter(s.get("sector", "Other") for s in wl if s.get("sector") not in (None, "Other", ""))
        stats["sector_leaders"] = [f"{s} ({c})" for s, c in sector_counts.most_common(3)]

    export_to_docs(regime=regime, stats=stats)
    log.info("=== WEEKLY SCAN COMPLETE ===")


def run_morning() -> None:
    log.info("=== MORNING CHECK (GitHub Actions) ===")
    from main import run_morning_check
    from engine.regime import get_market_regime
    from data.data_provider import get_provider

    try:
        run_morning_check()
    except Exception as exc:
        log.error("run_morning_check() raised an unhandled exception: %s", exc, exc_info=True)

    try:
        provider = get_provider()
        nifty_df = provider.get_benchmark(400)
        regime = get_market_regime(nifty_df)
    except Exception as exc:
        log.error("Failed to fetch benchmark/regime: %s", exc, exc_info=True)
        regime = None

    meta = _load(DOCS_DIR / "scan_meta.json") or {}
    export_to_docs(regime=regime, stats=meta)
    log.info("=== MORNING CHECK COMPLETE ===")


def run_afternoon() -> None:
    log.info("=== AFTERNOON CHECK (GitHub Actions) ===")
    from main import run_afternoon_check
    from engine.regime import get_market_regime
    from data.data_provider import get_provider

    try:
        run_afternoon_check()
    except Exception as exc:
        log.error("run_afternoon_check() raised an unhandled exception: %s", exc, exc_info=True)

    try:
        provider = get_provider()
        nifty_df = provider.get_benchmark(400)
        regime = get_market_regime(nifty_df)
    except Exception as exc:
        log.error("Failed to fetch benchmark/regime: %s", exc, exc_info=True)
        regime = None

    meta = _load(DOCS_DIR / "scan_meta.json") or {}
    export_to_docs(regime=regime, stats=meta)
    log.info("=== AFTERNOON CHECK COMPLETE ===")


if __name__ == "__main__":
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "weekly"
    dispatch = {"weekly": run_weekly, "morning": run_morning, "afternoon": run_afternoon}
    if mode not in dispatch:
        log.error("Unknown mode '%s'. Use: weekly | morning | afternoon", mode)
        sys.exit(1)
    dispatch[mode]()
