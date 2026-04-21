"""
exit_engine.py — Exit signal generation and open-position lifecycle management.

Manages the full 3-phase exit framework for every open trade:

    Phase 1  Hard stop           — close <= position stop-loss  → EXIT immediately
    Phase 2  Partial profit lock — close >= entry + 1.5R       → book 30%, move SL to BE
    Phase 3  Trailing stop       — EMA21 / weekly 2-bar low     → ratchet trailing SL upward

Momentum failure signals (soft alerts):
    RS55 negative      — stock has turned a laggard vs Nifty
    Volume exhaustion  — new 5d high on below-average volume
    Key reversal       — bearish engulf-style bar on high volume

Time-based exits:
    Stale swing        — TYPE_1/TYPE_2 trades sitting flat after 10 sessions
    Review positional  — TYPE_3 trades not progressing after 30 sessions

Positions are persisted to data/open_positions.json between runs.
Atomic write (write to .tmp then rename) prevents partial-write corruption.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

import config
from engine.indicators import ema as _ema

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Storage path — sibling of engine/ inside the package root
# ---------------------------------------------------------------------------
_POSITIONS_FILE = Path(__file__).parent.parent / "data" / "open_positions.json"


# ---------------------------------------------------------------------------
# Position persistence helpers
# ---------------------------------------------------------------------------

def load_positions() -> dict:
    """
    Load open positions from data/open_positions.json.

    Returns:
        Dict {symbol: position_dict}. Returns {} if file is missing, empty,
        or corrupt (logged as warning).
    """
    if not _POSITIONS_FILE.exists():
        return {}
    try:
        text = _POSITIONS_FILE.read_text(encoding="utf-8").strip()
        if not text:
            return {}
        return json.loads(text)
    except Exception as exc:
        log.warning("load_positions: failed to read %s — %s", _POSITIONS_FILE, exc)
        return {}


def save_positions(positions: dict) -> None:
    """
    Save positions to open_positions.json atomically (write tmp → rename).

    Args:
        positions: Dict {symbol: position_dict} to persist.
    """
    _POSITIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _POSITIONS_FILE.with_suffix(".json.tmp")
    try:
        tmp_path.write_text(
            json.dumps(positions, indent=2, default=str), encoding="utf-8"
        )
        tmp_path.replace(_POSITIONS_FILE)
    except Exception as exc:
        log.error("save_positions: failed to write %s — %s", _POSITIONS_FILE, exc)
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def add_position(
    symbol: str,
    entry: float,
    sl: float,
    entry_date: str,
    trade_type: str,
    grade: str,
    shares: int,
    base_low: float,
    regime_at_entry: int,
) -> None:
    """
    Add a new position to open_positions.json.

    Args:
        symbol:          NSE ticker (e.g. 'RELIANCE').
        entry:           Entry price in Rs.
        sl:              Initial stop-loss price in Rs.
        entry_date:      ISO date string 'YYYY-MM-DD'.
        trade_type:      'TYPE_1', 'TYPE_2', or 'TYPE_3'.
        grade:           Scorer grade — 'A', 'B', or 'C'.
        shares:          Number of shares purchased.
        base_low:        Lowest point of the base (for context/journaling).
        regime_at_entry: Market regime state (1-4) at time of entry.
    """
    positions = load_positions()
    positions[symbol] = {
        "symbol": symbol,
        "entry": float(entry),
        "sl": float(sl),
        "initial_sl": float(sl),
        "entry_date": str(entry_date),
        "trade_type": str(trade_type),
        "grade": str(grade),
        "shares": int(shares),
        "base_low": float(base_low),
        "regime_at_entry": int(regime_at_entry),
        "phase": 1,
        "partial_done": False,
        "trailing_sl": None,
        "added_date": date.today().isoformat(),
    }
    save_positions(positions)
    log.info(
        "add_position: %s entry=%.2f sl=%.2f shares=%d type=%s grade=%s",
        symbol, entry, sl, shares, trade_type, grade,
    )


def remove_position(symbol: str) -> None:
    """
    Remove a symbol from open_positions.json.

    Args:
        symbol: NSE ticker to remove.
    """
    positions = load_positions()
    if symbol in positions:
        del positions[symbol]
        save_positions(positions)
        log.info("remove_position: %s removed", symbol)
    else:
        log.debug("remove_position: %s not found in positions", symbol)


def update_position(symbol: str, **kwargs) -> None:
    """
    Update arbitrary fields of an existing position.

    Args:
        symbol: NSE ticker.
        **kwargs: Field name → new value pairs (e.g. sl=1500.0, phase=2).
    """
    positions = load_positions()
    if symbol not in positions:
        log.warning("update_position: %s not in positions, skipping", symbol)
        return
    positions[symbol].update(kwargs)
    save_positions(positions)
    log.debug("update_position: %s updated %s", symbol, list(kwargs.keys()))


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def trading_days_between(start_date: str, end_date: date) -> list:
    """
    Return list of Mon-Fri business days between start_date (inclusive)
    and end_date (inclusive).

    Args:
        start_date: ISO date string 'YYYY-MM-DD'.
        end_date:   datetime.date object (typically date.today()).

    Returns:
        List of datetime.date objects representing each business day.
    """
    try:
        start = date.fromisoformat(start_date)
    except Exception:
        log.warning("trading_days_between: invalid start_date '%s'", start_date)
        return []

    days: list[date] = []
    cursor = start
    while cursor <= end_date:
        if cursor.weekday() < 5:  # 0=Mon … 4=Fri
            days.append(cursor)
        cursor += timedelta(days=1)
    return days


# ---------------------------------------------------------------------------
# Exit signal helpers
# ---------------------------------------------------------------------------

def _alert(
    alert_type: str,
    symbol: str,
    message: str,
    action: str,
    urgency: str = "MEDIUM",
) -> dict:
    """Build a standardised alert dict."""
    return {
        "type": alert_type,
        "symbol": symbol,
        "message": message,
        "action": action,
        "urgency": urgency,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


def _check_phase1_stop(
    symbol: str, close: float, position: dict
) -> dict | None:
    """Phase 1: hard stop-loss hit."""
    sl = float(position.get("sl", 0.0))
    if close <= sl:
        return _alert(
            alert_type="STOP_LOSS",
            symbol=symbol,
            message=(
                f"{symbol}: close {close:.2f} <= stop-loss {sl:.2f}. "
                "Hard stop triggered — exit full position."
            ),
            action="EXIT_FULL",
            urgency="HIGH",
        )
    return None


def _check_phase2_partial(
    symbol: str, close: float, position: dict, df: pd.DataFrame
) -> dict | None:
    """Phase 2: partial profit lock at 1.5R. Move SL to breakeven."""
    if position.get("partial_done", False):
        return None

    entry = float(position.get("entry", 0.0))
    sl = float(position.get("sl", position.get("initial_sl", 0.0)))
    r = entry - sl
    if r <= 0:
        return None

    target = entry + config.PHASE2_REWARD_RATIO * r
    if close >= target:
        update_position(
            symbol,
            sl=entry,          # move stop to breakeven
            phase=2,
            partial_done=True,
        )
        book_pct = int(config.PHASE2_BOOK_PCT * 100)
        return _alert(
            alert_type="PARTIAL_EXIT",
            symbol=symbol,
            message=(
                f"{symbol}: close {close:.2f} >= Phase 2 target {target:.2f} "
                f"({config.PHASE2_REWARD_RATIO:.1f}R). "
                f"Book {book_pct}% of position. Move SL to breakeven ({entry:.2f})."
            ),
            action=f"EXIT_PARTIAL_{book_pct}PCT",
            urgency="MEDIUM",
        )
    return None


def _check_phase3_trail(
    symbol: str,
    close: float,
    position: dict,
    df: pd.DataFrame,
    weekly_df: pd.DataFrame | None,
) -> dict | None:
    """Phase 3: EMA21 + weekly 2-bar low trailing stop (ratchet — never moves down)."""
    if position.get("phase", 1) < 2:
        return None  # Phase 3 only active once partial has been taken

    close_series = df["close"].astype(float)
    if len(close_series) < 21:
        return None

    ema21_series = _ema(close_series, 21)
    ema21_val = float(ema21_series.iloc[-1])

    # Weekly 2-period low component
    if weekly_df is not None and len(weekly_df) >= 3:
        # Last 2 completed weekly bars (exclude the most recent incomplete bar)
        weekly_2period_low = float(weekly_df.iloc[-3:-1]["low"].min())
        trailing_sl_candidate = max(ema21_val, weekly_2period_low)
    else:
        trailing_sl_candidate = ema21_val

    # Ratchet: never move trailing SL downward
    current_trailing = position.get("trailing_sl")
    if current_trailing is not None:
        trailing_sl_candidate = max(float(current_trailing), trailing_sl_candidate)

    # Persist updated trailing SL
    if current_trailing is None or trailing_sl_candidate != float(current_trailing):
        update_position(symbol, trailing_sl=trailing_sl_candidate, phase=3)

    if close < trailing_sl_candidate:
        return _alert(
            alert_type="TRAIL_EXIT",
            symbol=symbol,
            message=(
                f"{symbol}: close {close:.2f} < trailing stop {trailing_sl_candidate:.2f} "
                f"(EMA21={ema21_val:.2f}). Trail exit triggered."
            ),
            action="EXIT_FULL",
            urgency="HIGH",
        )
    return None


def _check_rs55_negative(
    symbol: str, rs55_data: dict
) -> dict | None:
    """Momentum failure: RS55 has turned negative (stock now lagging Nifty)."""
    rs55 = rs55_data.get("rs55", 0.0)
    if rs55 < 0:
        return _alert(
            alert_type="RS55_NEGATIVE",
            symbol=symbol,
            message=(
                f"{symbol}: RS55 = {rs55:.4f} < 0. "
                "Stock has turned a laggard vs Nifty. Consider tightening stop."
            ),
            action="REVIEW_STOP",
            urgency="LOW",
        )
    return None


def _check_volume_exhaustion(
    symbol: str, df: pd.DataFrame
) -> dict | None:
    """
    Volume exhaustion: stock makes a new 5-day high but volume < 70% of 20-day average.
    Signals the move is running out of buying power.
    """
    try:
        if len(df) < 22:
            return None

        high_series = df["high"].astype(float)
        vol_series = df["volume"].astype(float)

        today_high = float(high_series.iloc[-1])
        prior_5d_high = float(high_series.iloc[-6:-1].max())
        today_vol = float(vol_series.iloc[-1])
        avg_vol_20 = float(vol_series.tail(21).iloc[:-1].mean())  # exclude today

        if avg_vol_20 == 0:
            return None

        new_5d_high = today_high > prior_5d_high
        vol_weak = today_vol < 0.70 * avg_vol_20

        if new_5d_high and vol_weak:
            vol_ratio = today_vol / avg_vol_20
            return _alert(
                alert_type="VOLUME_EXHAUSTION",
                symbol=symbol,
                message=(
                    f"{symbol}: new 5d high {today_high:.2f} on weak volume "
                    f"({vol_ratio:.0%} of 20d avg). Potential exhaustion — watch closely."
                ),
                action="WATCH",
                urgency="LOW",
            )
    except Exception as exc:
        log.debug("_check_volume_exhaustion %s: %s", symbol, exc)
    return None


def _check_key_reversal(
    symbol: str, df: pd.DataFrame
) -> dict | None:
    """
    Key reversal: opens in top 20% of today's range, closes in bottom 20%,
    on high volume (>1.3x 20-day average). Classic distribution signal.
    """
    try:
        if len(df) < 22:
            return None

        today = df.iloc[-1]
        open_p = float(today["open"])
        high_p = float(today["high"])
        low_p = float(today["low"])
        close_p = float(today["close"])
        vol = float(today["volume"])

        day_range = high_p - low_p
        if day_range == 0:
            return None

        # Open in top 20% of range
        open_pos = (open_p - low_p) / day_range
        # Close in bottom 20% of range
        close_pos = (close_p - low_p) / day_range

        vol_series = df["volume"].astype(float)
        avg_vol_20 = float(vol_series.tail(21).iloc[:-1].mean())
        if avg_vol_20 == 0:
            return None

        high_vol = vol > 1.3 * avg_vol_20

        if open_pos >= 0.80 and close_pos <= 0.20 and high_vol:
            vol_ratio = vol / avg_vol_20
            return _alert(
                alert_type="KEY_REVERSAL",
                symbol=symbol,
                message=(
                    f"{symbol}: key reversal bar — open in top 20% of range, "
                    f"close in bottom 20%, volume {vol_ratio:.1f}x avg. "
                    "Distribution signal — tighten stop."
                ),
                action="REVIEW_STOP",
                urgency="MEDIUM",
            )
    except Exception as exc:
        log.debug("_check_key_reversal %s: %s", symbol, exc)
    return None


def _check_time_exits(
    symbol: str,
    close: float,
    position: dict,
) -> dict | None:
    """
    Time-based stale trade exits.

    TYPE_1 / TYPE_2: if 10+ sessions have elapsed and close < entry + 1R → STALE_SWING
    TYPE_3:          if 30+ sessions have elapsed and close < entry + 1.5R → REVIEW_POSITIONAL
    """
    entry_date_str = position.get("entry_date", "")
    trade_type = position.get("trade_type", "TYPE_1")
    entry = float(position.get("entry", 0.0))
    initial_sl = float(position.get("initial_sl", position.get("sl", entry)))
    r = entry - initial_sl

    if r <= 0:
        return None

    sessions = len(trading_days_between(entry_date_str, date.today()))

    if trade_type in ("TYPE_1", "TYPE_2"):
        if sessions >= 10 and close < entry + r:
            return _alert(
                alert_type="STALE_SWING",
                symbol=symbol,
                message=(
                    f"{symbol}: {sessions} sessions since entry ({entry_date_str}), "
                    f"close {close:.2f} < entry+1R ({entry + r:.2f}). "
                    "Swing trade not progressing — consider exiting."
                ),
                action="REVIEW_EXIT",
                urgency="MEDIUM",
            )

    elif trade_type == "TYPE_3":
        if sessions >= 30 and close < entry + 1.5 * r:
            return _alert(
                alert_type="REVIEW_POSITIONAL",
                symbol=symbol,
                message=(
                    f"{symbol}: {sessions} sessions since entry ({entry_date_str}), "
                    f"close {close:.2f} < entry+1.5R ({entry + 1.5 * r:.2f}). "
                    "Positional trade under-performing — review."
                ),
                action="REVIEW_EXIT",
                urgency="LOW",
            )
    return None


# ---------------------------------------------------------------------------
# Main public API
# ---------------------------------------------------------------------------

def check_all_exits(
    symbol: str,
    df: pd.DataFrame,
    rs55_data: dict,
    weekly_df: pd.DataFrame = None,
) -> list[dict]:
    """
    Check all exit conditions for an open position and return triggered alerts.

    Checks are evaluated in priority order:
        1. Phase 1 hard stop      (HIGH urgency — exit immediately)
        2. Phase 2 partial exit   (MEDIUM)
        3. Phase 3 trailing stop  (HIGH — after partial taken)
        4. RS55 negative          (LOW — advisory)
        5. Volume exhaustion      (LOW — advisory)
        6. Key reversal           (MEDIUM — advisory)
        7. Time-based stale/review (MEDIUM/LOW — advisory)

    Multiple alerts can fire simultaneously — all are returned.
    Hard stop (Phase 1) terminates further checks for that symbol.

    Args:
        symbol:     NSE ticker string.
        df:         Daily OHLCV DataFrame with DatetimeIndex (latest data).
                    Columns: open, high, low, close, volume.
        rs55_data:  Output dict from compute_rs55().
        weekly_df:  Weekly OHLCV DataFrame (optional). Used for Phase 3 weekly low.

    Returns:
        List of alert dicts. Empty list if no exit signal fires.
        Each dict has: type, symbol, message, action, urgency, timestamp.
    """
    positions = load_positions()
    if symbol not in positions:
        log.debug("check_all_exits: %s has no open position", symbol)
        return []

    position = positions[symbol]
    alerts: list[dict] = []

    if len(df) == 0:
        log.warning("check_all_exits: empty DataFrame for %s", symbol)
        return []

    close = float(df["close"].iloc[-1])

    # --- Phase 1: Hard stop ---
    p1 = _check_phase1_stop(symbol, close, position)
    if p1:
        alerts.append(p1)
        return alerts  # Hard stop fires — no further checks needed

    # --- Phase 2: Partial exit + move SL to BE ---
    p2 = _check_phase2_partial(symbol, close, position, df)
    if p2:
        alerts.append(p2)
        # Reload position after partial update
        positions = load_positions()
        position = positions.get(symbol, position)

    # --- Phase 3: Trailing stop (only after Phase 2 has been taken) ---
    p3 = _check_phase3_trail(symbol, close, position, df, weekly_df)
    if p3:
        alerts.append(p3)
        if p3["type"] == "TRAIL_EXIT":
            return alerts  # Trail exit fires — no further soft checks

    # --- Momentum failures ---
    rs55_alert = _check_rs55_negative(symbol, rs55_data)
    if rs55_alert:
        alerts.append(rs55_alert)

    vol_alert = _check_volume_exhaustion(symbol, df)
    if vol_alert:
        alerts.append(vol_alert)

    reversal_alert = _check_key_reversal(symbol, df)
    if reversal_alert:
        alerts.append(reversal_alert)

    # --- Time-based exits ---
    time_alert = _check_time_exits(symbol, close, position)
    if time_alert:
        alerts.append(time_alert)

    return alerts
