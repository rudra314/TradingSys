"""
breakout.py — Breakout detection state machine.

Detects two types of breakouts on the daily chart:
  TYPE_1: Classic pivot breakout — close breaks above the base high on volume surge.
  TYPE_2: VCP (Volatility Contraction Pattern) — tightening base + volume dry-up + breakout.

Position sizing:
  shares = floor(CAPITAL * BASE_RISK_PCT * size_multiplier / (entry - sl))
  position_value = shares * entry
  Capped at MAX_SINGLE_STOCK_PCT of CAPITAL.

Sends alert via notifier.send_breakout_alert() on confirmed signal.
State is persisted in data/breakout_state_{symbol}.json between runs.
"""
import json
import logging
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from engine.base_analyzer import base_quality_score
from engine.indicators import atr as _atr, rsi as _rsi

log = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent / "data"
_STATE_DIR = _DATA_DIR / "cache"


def _load_state(symbol: str) -> dict:
    """Load per-symbol breakout state from JSON cache."""
    path = _STATE_DIR / f"breakout_state_{symbol}.json"
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_state(symbol: str, state: dict) -> None:
    """Persist per-symbol breakout state to JSON cache."""
    _STATE_DIR.mkdir(parents=True, exist_ok=True)
    path = _STATE_DIR / f"breakout_state_{symbol}.json"
    try:
        with open(path, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as exc:
        log.warning("Could not save breakout state for %s: %s", symbol, exc)


def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Compute ATR (Average True Range) over last `period` days."""
    try:
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        tr_values = []
        for i in range(1, len(df)):
            tr = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
            tr_values.append(tr)
        if not tr_values:
            return 0.0
        atr_series = pd.Series(tr_values)
        return float(atr_series.tail(period).mean())
    except Exception:
        return 0.0


def _compute_position_size(
    entry: float, sl: float, size_multiplier: float
) -> tuple[int, float, float]:
    """
    Compute shares, position_value, and risk_amount.

    Returns:
        (shares, position_value, risk_amount)
    """
    one_r = entry - sl
    if one_r <= 0:
        return 0, 0.0, 0.0

    risk_amount = config.CAPITAL * config.BASE_RISK_PCT * size_multiplier
    raw_shares = risk_amount / one_r
    shares = int(raw_shares)

    position_value = shares * entry
    max_position = config.CAPITAL * config.MAX_SINGLE_STOCK_PCT
    if position_value > max_position:
        shares = int(max_position / entry)
        position_value = shares * entry
        risk_amount = shares * one_r

    return shares, round(position_value, 2), round(risk_amount, 2)


def _detect_type1_breakout(df: pd.DataFrame, base_data: dict) -> dict | None:
    """
    TYPE_1: Price closes above base high with volume >= BREAKOUT_VOLUME_MULT * 20d avg.

    Returns signal dict or None.
    """
    if len(df) < 25:
        return None

    base_high = base_data["base_high"]
    base_low = base_data["base_low"]
    base_range_pct = base_data["range_pct"]

    # Skip if base is too wide (not a VCP setup)
    if base_range_pct > config.MAX_BREAKOUT_RISK_PCT * 4:
        return None

    close = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2])
    volume = float(df["volume"].iloc[-1])
    vol_ma20 = float(df["volume"].tail(21).iloc[:-1].mean())

    # Breakout condition: today's close > base_high AND volume surge
    breakout = (
        close > base_high
        and prev_close <= base_high * 1.005  # wasn't already above (avoid chasing)
        and vol_ma20 > 0
        and volume >= vol_ma20 * config.BREAKOUT_VOLUME_MULT
    )

    if not breakout:
        return None

    # Validate risk %
    risk_pct = (close - base_low) / close if close > 0 else 0
    if risk_pct < config.MIN_BREAKOUT_RISK_PCT or risk_pct > config.MAX_BREAKOUT_RISK_PCT:
        log.debug(
            "TYPE_1 breakout risk %.2f%% out of range [%.0f%%-%.0f%%]",
            risk_pct * 100,
            config.MIN_BREAKOUT_RISK_PCT * 100,
            config.MAX_BREAKOUT_RISK_PCT * 100,
        )
        return None

    entry = close
    sl = base_low
    one_r = entry - sl
    target1 = entry + config.PHASE2_REWARD_RATIO * one_r
    target2 = entry + 3.0 * one_r

    return {
        "entry_type": "TYPE_1",
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "target1": round(target1, 2),
        "target2": round(target2, 2),
        "risk_pct": round(risk_pct, 4),
        "volume_ratio": round(volume / vol_ma20, 2) if vol_ma20 > 0 else 0,
    }


def _detect_type2_breakout(df: pd.DataFrame, base_data: dict) -> dict | None:
    """
    TYPE_2: VCP — base is contracting (tight range + volume dry-up) then breakout candle.

    Uses ATR to define entry just above recent pivot high.
    Returns signal dict or None.
    """
    if len(df) < 30:
        return None

    base_range_pct = base_data["range_pct"]
    contraction_ratio = base_data["contraction_ratio"]

    # Must be a tight, contracting base
    if base_range_pct >= 0.08:
        return None
    if contraction_ratio >= 0.85:
        return None

    close = float(df["close"].iloc[-1])
    prev_close = float(df["close"].iloc[-2])

    # 10-day pivot high as breakout level
    pivot_high = float(df["high"].tail(10).max())
    volume = float(df["volume"].iloc[-1])
    vol_ma20 = float(df["volume"].tail(21).iloc[:-1].mean())

    breakout = (
        close > pivot_high
        and prev_close <= pivot_high * 1.005
        and vol_ma20 > 0
        and volume >= vol_ma20 * config.BREAKOUT_VOLUME_MULT
    )

    if not breakout:
        return None

    atr = _compute_atr(df, 14)
    sl = close - 1.5 * atr if atr > 0 else base_data["base_low"]
    sl = max(sl, base_data["base_low"])  # don't set SL below base_low

    one_r = close - sl
    if one_r <= 0:
        return None

    risk_pct = one_r / close
    if risk_pct < config.MIN_BREAKOUT_RISK_PCT or risk_pct > config.MAX_BREAKOUT_RISK_PCT:
        log.debug(
            "TYPE_2 breakout risk %.2f%% out of range",
            risk_pct * 100,
        )
        return None

    entry = close
    target1 = entry + config.PHASE2_REWARD_RATIO * one_r
    target2 = entry + 3.0 * one_r

    return {
        "entry_type": "TYPE_2",
        "entry": round(entry, 2),
        "sl": round(sl, 2),
        "target1": round(target1, 2),
        "target2": round(target2, 2),
        "risk_pct": round(risk_pct, 4),
        "volume_ratio": round(volume / vol_ma20, 2) if vol_ma20 > 0 else 0,
    }


def run_breakout_scan(
    symbol: str,
    df: pd.DataFrame,
    nifty_df: pd.DataFrame,
    rs55_data: dict,
    stock_meta: dict,
    regime: dict,
    provider,
) -> None:
    """
    Run breakout detection for a single symbol. Sends Telegram alert on confirmed signal.
    Deduplicates: won't re-alert the same breakout date.

    Args:
        symbol: NSE symbol
        df: OHLCV DataFrame (400 days)
        nifty_df: Nifty 50 benchmark DataFrame
        rs55_data: Dict from compute_rs55() — can be empty {}
        stock_meta: Dict from watchlist (grade, score, sector, etc.)
        regime: Dict from get_market_regime()
        provider: DataProvider instance (unused here, reserved for live price lookup)
    """
    if len(df) < 30:
        log.debug("run_breakout_scan: insufficient data for %s (%d rows)", symbol, len(df))
        return

    # Deduplicate: check if we already sent a signal today
    state = _load_state(symbol)
    today_str = pd.Timestamp.now().strftime("%Y-%m-%d")
    if state.get("last_alert_date") == today_str:
        log.debug("Breakout already alerted for %s today, skipping.", symbol)
        return

    # Compute base quality
    try:
        base_data = base_quality_score(df)
    except Exception as exc:
        log.warning("base_quality_score failed for %s: %s", symbol, exc)
        return

    # Attempt TYPE_1 first, then TYPE_2
    signal = _detect_type1_breakout(df, base_data)
    if signal is None:
        signal = _detect_type2_breakout(df, base_data)

    if signal is None:
        return

    # Compute position size
    size_multiplier = float(regime.get("size_multiplier", 1.0))
    shares, position_value, risk_amount = _compute_position_size(
        signal["entry"], signal["sl"], size_multiplier
    )

    if shares <= 0:
        log.warning(
            "run_breakout_scan: %s zero shares computed (entry=%.2f sl=%.2f)",
            symbol, signal["entry"], signal["sl"],
        )
        return

    # RSI for alert message
    try:
        rsi_val = float(
            _rsi(df["close"].astype(float), 14).iloc[-1]
        )
    except Exception:
        rsi_val = 50.0

    # Volume trend slope (last 10 days ratio slope) — reuse scorer logic
    try:
        vol = df["volume"].astype(float)
        vol_ma20 = vol.rolling(20).mean()
        vol_ratio = (vol / vol_ma20).tail(10).fillna(1.0).values
        from scipy.stats import linregress
        vol_slope = float(linregress(np.arange(len(vol_ratio)), vol_ratio).slope)
    except Exception:
        vol_slope = 0.0

    grade = stock_meta.get("grade", "?")
    score = int(stock_meta.get("score", 0))
    sector = stock_meta.get("sector", "Other")
    mom_percentile = float(stock_meta.get("mom_percentile", 0.0))
    base_score_val = int(base_data.get("score", 0))

    # Send alert
    try:
        from notify.notifier import send_breakout_alert
        send_breakout_alert(
            symbol=symbol,
            entry_type=signal["entry_type"],
            grade=grade,
            score=score,
            regime=regime,
            entry=signal["entry"],
            sl=signal["sl"],
            target1=signal["target1"],
            target2=signal["target2"],
            shares=shares,
            position_value=position_value,
            risk_amount=risk_amount,
            rs55_data=rs55_data,
            mom_percentile=mom_percentile,
            base_score=base_score_val,
            base_range_pct=base_data["range_pct"],
            base_length=base_data["base_length"],
            vol_trend_slope=vol_slope,
            rsi=rsi_val,
            sector=sector,
        )
        log.info(
            "BREAKOUT ALERT sent: %s %s entry=%.2f sl=%.2f target1=%.2f shares=%d",
            symbol, signal["entry_type"], signal["entry"], signal["sl"],
            signal["target1"], shares,
        )

        # Persist state so we don't re-alert today
        state["last_alert_date"] = today_str
        state["last_signal"] = signal
        _save_state(symbol, state)

    except Exception as exc:
        log.error("Failed to send breakout alert for %s: %s", symbol, exc)
