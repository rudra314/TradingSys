"""
base_analyzer.py — VCP / base quality scoring.

Evaluates the tightness and contraction of a stock's recent price base.
Supports 15, 20, and 30-day windows; selects the tightest (lowest range_pct).
Max score: 20 points.
"""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

log = logging.getLogger(__name__)


def _score_window(window: pd.DataFrame, df_full: pd.DataFrame) -> dict:
    """
    Score a single base window. Returns scoring dict for that window.

    Args:
        window: Tail slice of the OHLCV DataFrame for this window length
        df_full: Full OHLCV DataFrame (for 52-week high computation)
    """
    window_high = window["high"].max()
    window_low = window["low"].min()
    window_close_mean = window["close"].mean()

    if window_close_mean == 0:
        return {
            "range_pct": float("inf"),
            "contraction_ratio": float("inf"),
            "range_pts": 0,
            "contraction_pts": 0,
            "position_bonus": 0,
            "base_high": window_high,
            "base_low": window_low,
        }

    range_pct = (window_high - window_low) / window_close_mean

    # Split window: recent = last 5 days, prior = remaining
    if len(window) <= 5:
        recent = window.copy()
        prior = window.copy()
    else:
        recent = window.tail(5)
        prior = window.iloc[: len(window) - 5]

    def _adr(w: pd.DataFrame) -> float:
        """Average daily range as fraction of close."""
        if len(w) == 0 or w["close"].eq(0).any():
            return float("nan")
        return ((w["high"] - w["low"]) / w["close"]).mean()

    recent_adr = _adr(recent)
    prior_adr = _adr(prior)

    if pd.isna(prior_adr) or prior_adr == 0:
        contraction_ratio = 1.0  # neutral if can't compute
    elif pd.isna(recent_adr):
        contraction_ratio = 1.0
    else:
        contraction_ratio = recent_adr / prior_adr

    # 52-week high (last 252 trading days)
    high_52wk = df_full["high"].tail(252).max()

    # Range pts
    if range_pct < 0.06:
        range_pts = 12
    elif range_pct < 0.10:
        range_pts = 9
    elif range_pct < 0.15:
        range_pts = 5
    elif range_pct < 0.20:
        range_pts = 2
    else:
        range_pts = 0

    # Contraction pts
    if contraction_ratio < 0.6:
        contraction_pts = 5
    elif contraction_ratio < 0.8:
        contraction_pts = 3
    elif contraction_ratio < 1.0:
        contraction_pts = 1
    else:
        contraction_pts = 0

    # Position bonus: base_high within 15% of 52-week high
    position_bonus = 0
    if not pd.isna(high_52wk) and high_52wk > 0:
        if window_high >= high_52wk * 0.85:
            position_bonus = 3

    return {
        "range_pct": range_pct,
        "contraction_ratio": contraction_ratio,
        "range_pts": range_pts,
        "contraction_pts": contraction_pts,
        "position_bonus": position_bonus,
        "base_high": window_high,
        "base_low": window_low,
    }


def base_quality_score(df: pd.DataFrame) -> dict:
    """
    Compute VCP/base quality score (0-20 points).
    Tests windows of 15, 20, 30 days. Selects tightest.

    Args:
        df: Full OHLCV DataFrame with columns [open, high, low, close, volume]

    Returns:
        dict: score(int), base_length(int), base_high(float), base_low(float),
              range_pct(float), contraction_ratio(float)
    """
    windows = [15, 20, 30]
    best: dict | None = None
    best_range_pct = float("inf")
    best_length = 15

    for w_len in windows:
        if len(df) < w_len:
            log.debug("base_quality_score: insufficient data for %d-day window (%d rows)", w_len, len(df))
            continue

        window = df.tail(w_len).copy()
        result = _score_window(window, df)

        if result["range_pct"] < best_range_pct:
            best_range_pct = result["range_pct"]
            best = result
            best_length = w_len

    if best is None:
        # Fallback: use whatever data exists
        window = df.tail(min(15, len(df))).copy()
        best = _score_window(window, df)
        best_length = len(window)

    total = best["range_pts"] + best["contraction_pts"] + best["position_bonus"]
    score = min(20, total)

    return {
        "score": int(score),
        "base_length": int(best_length),
        "base_high": float(best["base_high"]),
        "base_low": float(best["base_low"]),
        "range_pct": float(best["range_pct"]),
        "contraction_ratio": float(best["contraction_ratio"]),
    }
