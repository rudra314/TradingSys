"""
rs55_engine.py — RS55 relative strength computation and scoring.

RS55 measures a stock's 55-day return relative to the Nifty 50 benchmark.
A positive RS55 means the stock outperformed Nifty over the past 55 sessions.
"""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np

log = logging.getLogger(__name__)


def compute_rs55(df: pd.DataFrame, nifty_df: pd.DataFrame) -> dict:
    """
    Compute RS55 and all derived signals.
    RS55 = (stock_55d_return / nifty_55d_return) - 1
    Align stock and Nifty on common trading dates via inner join before computing.

    Returns dict:
        rs55: float, rs55_pct: float, rs55_yesterday: float, rs55_2d_ago: float,
        rs55_rising_days: int, rs55_just_turned: bool, rs55_at_new_high: bool,
        rs55_declining: bool, rs55_series: pd.Series
    """
    # Align on common trading dates
    aligned = df[["close"]].join(
        nifty_df[["close"]].rename(columns={"close": "nifty"}), how="inner"
    )

    if len(aligned) < 57:
        raise ValueError(
            f"compute_rs55: need at least 57 aligned rows, got {len(aligned)}"
        )

    # Build full daily RS55 series (rolling, every index i from 55..len)
    rs55_values: list[float] = []
    rs55_index: list = []
    for i in range(55, len(aligned)):
        s_perf = aligned["close"].iloc[i] / aligned["close"].iloc[i - 55]
        n_perf = aligned["nifty"].iloc[i] / aligned["nifty"].iloc[i - 55]
        if n_perf == 0:
            rs55_values.append(float("nan"))
        else:
            rs55_values.append((s_perf / n_perf) - 1)
        rs55_index.append(aligned.index[i])

    rs55_series = pd.Series(rs55_values, index=rs55_index, name="rs55")

    # Today (index -1 of aligned = index -1 of rs55_series)
    n = len(aligned)
    def _rs55_at(i_neg: int) -> float:
        """Compute RS55 at position i_neg (negative index from end of aligned)."""
        idx = n + i_neg  # absolute index
        s_perf = aligned["close"].iloc[idx] / aligned["close"].iloc[idx - 55]
        n_perf = aligned["nifty"].iloc[idx] / aligned["nifty"].iloc[idx - 55]
        if n_perf == 0:
            return float("nan")
        return (s_perf / n_perf) - 1

    rs55_today = _rs55_at(-1)
    rs55_yesterday = _rs55_at(-2)
    rs55_2d_ago = _rs55_at(-3)

    # rs55_rising_days: count consecutive days RS55 increased (check up to 5 days back)
    rs55_rising_days = 0
    if len(rs55_series) >= 6:
        recent = rs55_series.dropna().tail(6).values
        # Walk backwards from most recent pair
        for j in range(len(recent) - 1, 0, -1):
            if recent[j] > recent[j - 1]:
                rs55_rising_days += 1
            else:
                break

    # Derived signals
    rs55_just_turned: bool = bool(
        (not pd.isna(rs55_today))
        and (not pd.isna(rs55_yesterday))
        and (rs55_today > 0)
        and (rs55_yesterday <= 0)
    )

    # At new high: current RS55 >= 99.9% of max over last 55 values in series
    rs55_at_new_high = False
    if len(rs55_series) >= 55:
        recent_max = rs55_series.iloc[-55:].dropna().max()
        if not pd.isna(recent_max) and not pd.isna(rs55_today):
            rs55_at_new_high = bool(rs55_today >= recent_max * 0.999)

    rs55_declining: bool = bool(
        (not pd.isna(rs55_today))
        and (not pd.isna(rs55_yesterday))
        and (rs55_today < rs55_yesterday)
    )

    rs55_pct = rs55_today * 100 if not pd.isna(rs55_today) else 0.0

    return {
        "rs55": float(rs55_today) if not pd.isna(rs55_today) else 0.0,
        "rs55_pct": float(rs55_pct),
        "rs55_yesterday": float(rs55_yesterday) if not pd.isna(rs55_yesterday) else 0.0,
        "rs55_2d_ago": float(rs55_2d_ago) if not pd.isna(rs55_2d_ago) else 0.0,
        "rs55_rising_days": int(rs55_rising_days),
        "rs55_just_turned": rs55_just_turned,
        "rs55_at_new_high": rs55_at_new_high,
        "rs55_declining": rs55_declining,
        "rs55_series": rs55_series,
    }


def compute_rs55_score(rs55_data: dict) -> int:
    """
    RS55 component score 0-30 for scorer.py.
    Level pts (0-15): pct>5→15, pct>2→12, pct>0.5→8, pct>0→4, else→0
    Momentum pts (0-15): declining→0, flat(diff<0.001)→4, rising>=3→15, ==2→12, ==1→8, else→4
    Returns level_pts + momentum_pts (max 30)
    """
    rs55_pct: float = rs55_data.get("rs55_pct", 0.0)
    rs55_today: float = rs55_data.get("rs55", 0.0)
    rs55_yesterday: float = rs55_data.get("rs55_yesterday", 0.0)
    rs55_rising_days: int = rs55_data.get("rs55_rising_days", 0)
    rs55_declining: bool = rs55_data.get("rs55_declining", False)

    # Level points (0-15)
    if rs55_pct > 5:
        level_pts = 15
    elif rs55_pct > 2:
        level_pts = 12
    elif rs55_pct > 0.5:
        level_pts = 8
    elif rs55_pct > 0:
        level_pts = 4
    else:
        level_pts = 0

    # Momentum points (0-15)
    diff = abs(rs55_today - rs55_yesterday)
    if rs55_declining:
        momentum_pts = 0
    elif diff < 0.001:
        momentum_pts = 4  # flat
    elif rs55_rising_days >= 3:
        momentum_pts = 15
    elif rs55_rising_days == 2:
        momentum_pts = 12
    elif rs55_rising_days == 1:
        momentum_pts = 8
    else:
        momentum_pts = 4

    return int(level_pts + momentum_pts)
