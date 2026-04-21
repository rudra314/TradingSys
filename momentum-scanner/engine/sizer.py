"""
sizer.py — Position sizing with risk-based calculation and hard caps.

Sizing hierarchy (all caps must pass):
    1. Risk-based shares: risk_amount / risk_per_share
    2. Single-stock cap: position_value <= CAPITAL * MAX_SINGLE_STOCK_PCT
    3. Grade multiplier: A=1.0, B=0.75, C=0.5
    4. Regime multiplier: from get_market_regime() size_multiplier

All values sourced from config.py. No hardcoded numbers.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

import config

log = logging.getLogger(__name__)

# Grade multipliers — grade determines fraction of risk budget to deploy
_GRADE_MULTIPLIERS: dict[str, float] = {
    "A": 1.0,
    "B": 0.75,
    "C": 0.5,
}


def compute_position_size(
    entry: float,
    sl: float,
    grade: str,
    regime: dict,
    capital: float = None,
) -> dict:
    """
    Compute shares, position_value, and risk_amount with all hard caps applied.

    Sizing formula:
        risk_amount   = capital × BASE_RISK_PCT × regime_mult × grade_mult
        shares        = floor(risk_amount / risk_per_share)
        position_cap  = capital × MAX_SINGLE_STOCK_PCT

    If position_value > position_cap, shares are reduced to fit within cap.
    Returns zero shares if entry <= sl (invalid stop) or grade unknown.

    Args:
        entry:   Planned entry price in Rs.
        sl:      Stop-loss price in Rs. Must be strictly below entry.
        grade:   Trade grade — 'A', 'B', or 'C'. Unknown grade → 0 shares.
        regime:  Dict returned by get_market_regime(). Must contain
                 'size_multiplier' key.
        capital: Override capital in Rs. Defaults to config.CAPITAL.

    Returns:
        dict with keys:
            shares          int    — number of whole shares to buy
            position_value  float  — shares × entry
            risk_amount     float  — shares × risk_per_share (actual risk after rounding)
            grade_mult      float  — multiplier applied for this grade
            regime_mult     float  — multiplier applied for current regime
            risk_pct        float  — actual risk_amount / capital (fraction, not %)
    """
    if capital is None:
        capital = float(config.CAPITAL)

    # Validate inputs
    risk_per_share = entry - sl
    if risk_per_share <= 0:
        log.warning(
            "compute_position_size: invalid stop — entry %.4f <= sl %.4f. Returning 0 shares.",
            entry, sl,
        )
        return _zero_result(grade, regime)

    grade_mult = _GRADE_MULTIPLIERS.get(grade, 0.0)
    if grade_mult == 0.0:
        log.warning(
            "compute_position_size: unknown grade '%s'. Returning 0 shares.", grade
        )
        return _zero_result(grade, regime)

    regime_mult = float(regime.get("size_multiplier", 0.0))
    if regime_mult == 0.0:
        log.debug("compute_position_size: regime size_multiplier=0 (cash regime). Returning 0 shares.")
        return _zero_result(grade, regime)

    # Target risk amount for this trade
    target_risk = capital * config.BASE_RISK_PCT * regime_mult * grade_mult

    # Initial share count from risk
    shares = int(target_risk / risk_per_share)
    position_value = shares * entry

    # Hard cap: single stock cannot exceed MAX_SINGLE_STOCK_PCT of capital
    max_position_value = capital * config.MAX_SINGLE_STOCK_PCT
    if position_value > max_position_value and entry > 0:
        shares = int(max_position_value / entry)
        position_value = shares * entry
        log.debug(
            "compute_position_size: %s capped at %.0f (%.0f%% capital limit). "
            "Shares reduced from %d to %d.",
            grade,
            max_position_value,
            config.MAX_SINGLE_STOCK_PCT * 100,
            int(target_risk / risk_per_share),
            shares,
        )

    # Recompute actual risk after rounding
    actual_risk = shares * risk_per_share
    risk_pct = actual_risk / capital if capital > 0 else 0.0

    log.debug(
        "Size: entry=%.2f sl=%.2f grade=%s regime_mult=%.2f grade_mult=%.2f "
        "shares=%d pos_value=%.0f actual_risk=%.0f risk_pct=%.3f%%",
        entry, sl, grade, regime_mult, grade_mult,
        shares, position_value, actual_risk, risk_pct * 100,
    )

    return {
        "shares": int(shares),
        "position_value": float(position_value),
        "risk_amount": float(actual_risk),
        "grade_mult": float(grade_mult),
        "regime_mult": float(regime_mult),
        "risk_pct": float(risk_pct),
    }


def _zero_result(grade: str, regime: dict) -> dict:
    """Return a zero-position result dict."""
    return {
        "shares": 0,
        "position_value": 0.0,
        "risk_amount": 0.0,
        "grade_mult": float(_GRADE_MULTIPLIERS.get(grade, 0.0)),
        "regime_mult": float(regime.get("size_multiplier", 0.0)),
        "risk_pct": 0.0,
    }
