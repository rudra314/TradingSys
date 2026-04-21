"""
regime.py — Market regime classifier.

Classifies Nifty 50 into 4 states using EMA50/EMA200 structure and optional VIX.
State determines position sizing (size_multiplier) and maximum concurrent positions
(max_positions). All downstream position sizing reads from the returned dict.

States:
    1  Full momentum   mult=1.00  max=10  (price>EMA200, price>EMA50, EMA50 rising, low VIX)
    2  Selective        mult=0.75  max=7   (above EMA200 but EMA50 not rising or moderate VIX)
    3  Defensive        mult=0.40  max=4   (price between EMAs or EMA50<EMA200 or elevated VIX)
    4  Cash             mult=0.00  max=0   (price<EMA200 and EMA50<EMA200 or high VIX)
"""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from engine.indicators import ema as _ema

log = logging.getLogger(__name__)

# State descriptors — states are 1-4
_STATES: dict[int, dict] = {
    1: {
        "label": "Full Momentum",
        "size_multiplier": 1.0,
        "max_positions": 10,
        "description": (
            "Price above both EMAs, EMA50 sloping up, VIX benign. "
            "Deploy full risk budget."
        ),
    },
    2: {
        "label": "Selective",
        "size_multiplier": 0.75,
        "max_positions": 7,
        "description": (
            "Price above EMA200 but EMA50 not rising or moderate VIX. "
            "Reduce size, favour high-grade setups only."
        ),
    },
    3: {
        "label": "Defensive",
        "size_multiplier": 0.40,
        "max_positions": 4,
        "description": (
            "Price between EMAs or EMA50 below EMA200 or elevated VIX. "
            "Minimum exposure, existing winners only."
        ),
    },
    4: {
        "label": "Cash",
        "size_multiplier": 0.0,
        "max_positions": 0,
        "description": (
            "Price below EMA200 and EMA50 below EMA200, or VIX extreme. "
            "No new trades. Move to cash."
        ),
    },
}


def get_market_regime(nifty_df: pd.DataFrame, vix: float = None) -> dict:
    """
    Classify market into 4 states based on Nifty 50 EMA structure.

    Evaluation order: 1 → 2 → 3 → 4 (first match wins).

    Args:
        nifty_df: Nifty 50 OHLCV DataFrame with DatetimeIndex and 'close' column.
                  Must contain at least 210 rows for reliable EMA200 calculation.
        vix: India VIX value (float, optional). When provided, adjusts state boundaries:
             VIX < 16  → favours State 1
             16 ≤ VIX ≤ 20 → may force State 2
             20 < VIX ≤ 26 → may force State 3
             VIX > 26  → forces State 4

    Returns:
        dict with keys:
            state           int 1-4
            label           str
            size_multiplier float  (multiply BASE_RISK_PCT by this)
            max_positions   int
            description     str
    """
    try:
        if len(nifty_df) < 15:
            log.warning(
                "get_market_regime: insufficient data (%d rows), defaulting to State 3",
                len(nifty_df),
            )
            return _build_result(3)

        close = nifty_df["close"].astype(float)
        price = float(close.iloc[-1])

        # EMA50 and EMA200 via ta library (consistent with gates.py)
        ema50_series = _ema(close, 50)
        ema200_series = _ema(close, 200)

        ema50_val = float(ema50_series.iloc[-1])
        ema200_val = float(ema200_series.iloc[-1])

        # EMA50 slope: today's EMA50 > EMA50 ten periods ago
        lookback_idx = -10 if len(ema50_series) >= 10 else 0
        ema50_10ago_val = float(ema50_series.iloc[lookback_idx])
        ema50_slope: bool = ema50_val > ema50_10ago_val

        log.debug(
            "Regime inputs: price=%.2f ema50=%.2f ema200=%.2f ema50_slope=%s vix=%s",
            price, ema50_val, ema200_val, ema50_slope, vix,
        )

        # VIX override — forced State 4
        if vix is not None and vix > 26:
            log.info("Regime: forced State 4 — VIX=%.1f > 26", vix)
            return _build_result(4)

        # State 1: Full momentum
        # price > EMA200 AND price > EMA50 AND EMA50 rising AND (no VIX or VIX < 16)
        state1_vix_ok = vix is None or vix < 16
        if price > ema200_val and price > ema50_val and ema50_slope and state1_vix_ok:
            return _build_result(1)

        # State 2: Selective
        # price > EMA200 AND (EMA50 not rising OR VIX 16-20)
        if price > ema200_val:
            state2_trigger = (not ema50_slope) or (vix is not None and 16 <= vix <= 20)
            if state2_trigger:
                return _build_result(2)
            # price > EMA200, EMA50 rising, but VIX moderate — still State 2
            if vix is not None and 16 <= vix <= 20:
                return _build_result(2)
            # price > EMA200, EMA50 rising, VIX fine but something else -> State 2
            # (catches the case where price > EMA200 but State 1 condition not fully met)
            return _build_result(2)

        # State 3: Defensive
        # price between EMA50 and EMA200, OR EMA50 < EMA200, OR VIX 20-26
        state3_vix = vix is not None and 20 < vix <= 26
        price_between_emas = min(ema50_val, ema200_val) <= price <= max(ema50_val, ema200_val)
        ema50_below_ema200 = ema50_val < ema200_val
        if price_between_emas or ema50_below_ema200 or state3_vix:
            return _build_result(3)

        # State 4: Cash — final fallback
        return _build_result(4)

    except Exception as exc:
        log.error("get_market_regime exception: %s — defaulting to State 3", exc, exc_info=True)
        return _build_result(3)


def _build_result(state: int) -> dict:
    """Build the full result dict for a given state integer."""
    s = _STATES[state]
    return {
        "state": state,
        "label": s["label"],
        "size_multiplier": s["size_multiplier"],
        "max_positions": s["max_positions"],
        "description": s["description"],
    }
