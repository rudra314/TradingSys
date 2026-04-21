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

# Ensure momentum-scanner/ is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── Paths ─────────────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).parent.parent          # TradingSys/
SCANNER_DIR = Path(__file__).parent                 # momentum-scanner/
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


# ── JSON helpers ──────────────────────────────────────────────────────────────
def _load(path: Path):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return None


def _save(data, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ── Export to docs/data/ ──────────────────────────────────────────────────────
def export_to_docs(regime: dict = None, stats: dict = None) -> None:
    """
    Copy / transform scanner output files into docs/data/ for GitHub Pages.
    Called after every scan type. Missing files are skipped gracefully.
    """
    # watchlist.json — used directly by the dashboard table
    wl = _load(DATA_DIR / "watchlist.json")
    if wl:
        _save(wl, DOCS_DIR / "watchlist.json")
        log.info("docs/data/watchlist.json — %d stocks", len(wl))

    # open_positions.json — positions table
    pos = _load(DATA_DIR / "open_positions.json")
    _save(pos or {}, DOCS_DIR / "open_positions.json")

    # regime.json — regime card
    if regime:
        _save(regime, DOCS_DIR / "regime.json")

    # signals.json — recent alerts (parsed from signals.log)
    signals = _parse_signals_log(LOGS_DIR / "signals.log")
    _save(signals, DOCS_DIR / "signals.json")

    # scan_meta.json — stats bar + last updated
    if stats:
        stats["scan_timestamp"] = datetime.now(timezone.utc).isoformat()
        stats["scan_date"] = datetime.now().strftime("%Y-%m-%d")
        _save(stats, DOCS_DIR / "scan_meta.json")

    log.info("docs/data/ export complete")


def _parse_signals_log(log_path: Path) -> list[dict]:
    """
    Parse logs/signals.log into a list of dicts for the dashboard.
    Format: {timestamp} | {alert_type} | {symbol} | {entry} | {sl} | {target1} | {grade} | {score} | {rs55_pct}
    Returns last 50 entries, newest first.
    """
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
                            entry["entry"]   = float(parts[3])
                            entry["sl"]      = float(parts[4])
                            entry["target1"] = float(parts[5])
                            entry["grade"]   = parts[6]
                            entry["score"]   = int(float(parts[7]))
                            entry["rs55_pct"]= float(parts[8])
                        except (ValueError, IndexError):
                            pass
                    entries.append(entry)
    except Exception as exc:
        log.warning("Could not parse signals.log: %s", exc)
    return list(reversed(entries))[-50:]  # newest first, cap at 50


# ── Scan runners ──────────────────────────────────────────────────────────────
def run_weekly() -> None:
    log.info("=== WEEKLY SCAN (GitHub Actions) ===")
    from main import run_weekly_scan
    from engine.regime import get_market_regime
    from data.data_provider import get_provider

    run_weekly_scan()

    # Collect stats for dashboard
    try:
        provider = get_provider()
        nifty_df = provider.get_benchmark(400)
        regime = get_market_regime(nifty_df)
    except Exception:
        regime = None

    wl = _load(DATA_DIR / "watchlist.json") or []
    stats = {
        "total_scanned": 0,      # updated inside run_weekly_scan via log
        "total_eligible": 0,
        "watchlist_count": len(wl),
        "blackout_count": 0,
        "sector_leaders": [],
    }

    # Try to read counts from the last log lines
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

    # Top sectors from watchlist
    if wl:
        from collections import Counter
        sector_counts = Counter(s.get("sector","Other") for s in wl if s.get("sector") not in (None,"Other",""))
        stats["sector_leaders"] = [f"{s} ({c})" for s, c in sector_counts.most_common(3)]

    export_to_docs(regime=regime, stats=stats)
    log.info("=== WEEKLY SCAN COMPLETE ===")


def run_morning() -> None:
    log.info("=== MORNING CHECK (GitHub Actions) ===")
    from main import run_morning_check
    from engine.regime import get_market_regime
    from data.data_provider import get_provider

    run_morning_check()

    try:
        provider = get_provider()
        nifty_df = provider.get_benchmark(400)
        regime = get_market_regime(nifty_df)
    except Exception:
        regime = None

    meta = _load(DOCS_DIR / "scan_meta.json") or {}
    export_to_docs(regime=regime, stats=meta)
    log.info("=== MORNING CHECK COMPLETE ===")


def run_afternoon() -> None:
    log.info("=== AFTERNOON CHECK (GitHub Actions) ===")
    from main import run_afternoon_check
    from engine.regime import get_market_regime
    from data.data_provider import get_provider

    run_afternoon_check()

    try:
        provider = get_provider()
        nifty_df = provider.get_benchmark(400)
        regime = get_market_regime(nifty_df)
    except Exception:
        regime = None

    meta = _load(DOCS_DIR / "scan_meta.json") or {}
    export_to_docs(regime=regime, stats=meta)
    log.info("=== AFTERNOON CHECK COMPLETE ===")


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    mode = sys.argv[1].lower() if len(sys.argv) > 1 else "weekly"
    dispatch = {"weekly": run_weekly, "morning": run_morning, "afternoon": run_afternoon}
    if mode not in dispatch:
        log.error("Unknown mode '%s'. Use: weekly | morning | afternoon", mode)
        sys.exit(1)
    dispatch[mode]()
