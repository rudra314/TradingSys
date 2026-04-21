"""
scorer.py — Cross-sectional scoring engine.

Scores all gate-passing stocks across 5 components (total 100 pts) and assigns
grades: A (>=78), B (>=58), C (>=40), EXCLUDE (<40).

Components:
    RS55         — 30 pts  (relative strength vs Nifty, 55-day window)
    Momentum     — 25 pts  (cross-sectional 12-1 month momentum percentile)
    Base quality — 20 pts  (VCP tightness / contraction)
    Volume trend — 15 pts  (slope of vol/MA ratio + recent confirmation)
    RSI health   — 10 pts  (level + slope)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

import numpy as np
import pandas as pd
from scipy.stats import linregress

import config
from engine.base_analyzer import base_quality_score
from engine.indicators import rsi as _rsi
from engine.rs55_engine import compute_rs55_score

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal component scorers
# ---------------------------------------------------------------------------

def _score_volume_trend(df: pd.DataFrame) -> tuple[int, float]:
    """
    Volume trend component (0-15 pts).

    Computes the slope of (volume / 20-day rolling mean) over the last 10 days.
    An uptick in relative volume signals accumulation.

    Returns:
        (score, slope) tuple
    """
    try:
        volume = df["volume"].astype(float)
        if len(volume) < 25:
            return 2, 0.0

        vol_ma20 = volume.rolling(20).mean()
        vol_ratio = volume / vol_ma20

        if vol_ratio.tail(10).isna().all():
            return 2, 0.0

        tail10 = vol_ratio.tail(10).ffill().fillna(1.0).values
        x = np.arange(len(tail10))
        try:
            slope = linregress(x, tail10).slope
        except Exception:
            slope = 0.0

        if slope > 0.02:
            base_pts = 12
        elif slope > -0.02:
            base_pts = 8
        else:
            base_pts = 2

        # Confirmation bonus: recent 3-day average vol ratio > 1.0
        recent_mean = vol_ratio.iloc[-3:].mean()
        bonus = 3 if (not pd.isna(recent_mean) and recent_mean > 1.0) else 0

        score = min(15, base_pts + bonus)
        return int(score), float(slope)
    except Exception as exc:
        log.warning("Volume trend scoring failed: %s", exc)
        return 2, 0.0


def _score_rsi(df: pd.DataFrame) -> tuple[int, float]:
    """
    RSI health component (0-10 pts).

    Uses 14-period Wilder RSI.
    Level: 55-70 → 6, 70-78 → 4, 48-55 → 3, else → 0
    Slope: rsi[-1] - rsi[-5] > 3 → 4, > 1 → 2, else → 0

    Returns:
        (score, rsi_current) tuple
    """
    try:
        if len(df) < 20:
            return 0, 50.0

        close = df["close"].astype(float)
        rsi_series = _rsi(close, 14)

        if rsi_series.isna().all():
            return 0, 50.0

        rsi_val = rsi_series.iloc[-1]
        if pd.isna(rsi_val):
            return 0, 50.0

        # Level points
        if 55 <= rsi_val <= 70:
            level_pts = 6
        elif 70 < rsi_val <= 78:
            level_pts = 4
        elif 48 <= rsi_val < 55:
            level_pts = 3
        else:
            level_pts = 0

        # Slope points
        if len(rsi_series.dropna()) >= 5:
            rsi_change = rsi_val - rsi_series.dropna().iloc[-5]
            if rsi_change > 3:
                slope_pts = 4
            elif rsi_change > 1:
                slope_pts = 2
            else:
                slope_pts = 0
        else:
            slope_pts = 0

        return int(level_pts + slope_pts), float(rsi_val)
    except Exception as exc:
        log.warning("RSI scoring failed: %s", exc)
        return 0, 50.0


def _assign_grade(score: float) -> str:
    """Assign letter grade based on total score."""
    if score >= config.GRADE_A_MIN:
        return "A"
    elif score >= config.GRADE_B_MIN:
        return "B"
    elif score >= config.GRADE_C_MIN:
        return "C"
    else:
        return "EXCLUDE"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def score_universe(
    eligible_stocks: dict[str, pd.DataFrame],
    nifty_df: pd.DataFrame,
    rs55_map: dict[str, dict],
) -> pd.DataFrame:
    """
    Score all eligible stocks cross-sectionally. Returns ranked DataFrame.

    Args:
        eligible_stocks: Dict {symbol: ohlcv_df} — stocks that passed all gates.
        nifty_df: Nifty 50 benchmark OHLCV DataFrame.
        rs55_map: Dict {symbol: rs55_data_dict} from compute_rs55() for each stock.

    Returns:
        pd.DataFrame sorted by score descending, columns:
            symbol, grade, score, rs55_score, mom_score, base_score,
            vol_score, rsi_score, rs55_pct, rs55_rising_days, rs55_just_turned,
            rs55_at_new_high, rs55_declining, mom_percentile, base_range_pct,
            base_length, base_low, base_high, vol_trend_slope, rsi, sector
    """
    if not eligible_stocks:
        log.warning("score_universe: no eligible stocks to score")
        return pd.DataFrame()

    # ------------------------------------------------------------------
    # Pass 1 — compute 12-1 month momentum factor for cross-sectional rank
    # ------------------------------------------------------------------
    mom_factors: dict[str, float] = {}
    for sym, df in eligible_stocks.items():
        try:
            close = df["close"].astype(float)
            if len(close) < 252:
                continue
            ret_12m = close.iloc[-1] / close.iloc[-252] - 1
            ret_1m = close.iloc[-1] / close.iloc[-21] - 1
            mom_factors[sym] = ret_12m - ret_1m
        except Exception as exc:
            log.debug("Momentum factor for %s failed: %s", sym, exc)

    # Cross-sectional percentile rank
    if mom_factors:
        mom_series = pd.Series(mom_factors)
        mom_pct_series = mom_series.rank(pct=True)
    else:
        mom_pct_series = pd.Series(dtype=float)

    # ------------------------------------------------------------------
    # Pass 2 — score each stock
    # ------------------------------------------------------------------
    rows: list[dict] = []

    # Sector map import (best-effort)
    try:
        from data.universe import SECTOR_MAP as _sector_map
    except ImportError:
        _sector_map = {}

    for sym, df in eligible_stocks.items():
        try:
            close = df["close"].astype(float)

            # --- Component 1: RS55 (30 pts) ---
            rs55_data = rs55_map.get(sym, {})
            rs55_score = compute_rs55_score(rs55_data) if rs55_data else 0

            # --- Component 2: Cross-sectional momentum (25 pts) ---
            if sym in mom_pct_series.index:
                mom_pct = float(mom_pct_series[sym])
                mom_score = round(mom_pct * 25, 1)
                mom_percentile = round(mom_pct * 100, 1)
            else:
                mom_score = 0.0
                mom_percentile = 0.0

            # --- Component 3: Base quality (20 pts) ---
            base_data = base_quality_score(df)
            base_score = base_data["score"]

            # --- Component 4: Volume trend (15 pts) ---
            vol_score, vol_slope = _score_volume_trend(df)

            # --- Component 5: RSI health (10 pts) ---
            rsi_score, rsi_val = _score_rsi(df)

            # --- Total ---
            total = rs55_score + mom_score + base_score + vol_score + rsi_score
            grade = _assign_grade(total)

            sector = _sector_map.get(sym, "Other")

            rows.append(
                {
                    "symbol": sym,
                    "grade": grade,
                    "score": round(total, 1),
                    "rs55_score": rs55_score,
                    "mom_score": round(mom_score, 1),
                    "base_score": base_score,
                    "vol_score": vol_score,
                    "rsi_score": rsi_score,
                    # RS55 detail fields
                    "rs55_pct": rs55_data.get("rs55_pct", 0.0),
                    "rs55_rising_days": rs55_data.get("rs55_rising_days", 0),
                    "rs55_just_turned": rs55_data.get("rs55_just_turned", False),
                    "rs55_at_new_high": rs55_data.get("rs55_at_new_high", False),
                    "rs55_declining": rs55_data.get("rs55_declining", False),
                    # Momentum detail
                    "mom_percentile": mom_percentile,
                    # Base detail
                    "base_range_pct": base_data["range_pct"],
                    "base_length": base_data["base_length"],
                    "base_low": base_data["base_low"],
                    "base_high": base_data["base_high"],
                    # Vol / RSI detail
                    "vol_trend_slope": round(vol_slope, 5),
                    "rsi": round(rsi_val, 2),
                    # Meta
                    "sector": sector,
                }
            )

        except Exception as exc:
            log.warning("Scoring failed for %s: %s", sym, exc, exc_info=True)
            continue

    if not rows:
        log.warning("score_universe: all stocks failed scoring, returning empty DataFrame")
        return pd.DataFrame()

    result_df = pd.DataFrame(rows)
    result_df = result_df.sort_values("score", ascending=False).reset_index(drop=True)
    return result_df
