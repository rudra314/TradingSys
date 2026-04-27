"""
gates.py — Hard gate layer. 5 binary disqualifiers.
Gates and scores are completely separate. Fail any gate = score 0, excluded.
Gates do NOT contribute to score.
"""
import logging
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import config
from engine.indicators import ema as _ema

log = logging.getLogger(__name__)


def _gate_1_trend(df: pd.DataFrame) -> tuple[bool, str]:
    """Gate 1: close > EMA50, close > EMA200, EMA50 sloping up."""
    try:
        if len(df) < 210:
            return False, "Gate1_Trend: insufficient data (need 210+ rows)"

        close = df["close"]
        ema50_series = _ema(close, 50)
        ema200_series = _ema(close, 200)

        price = close.iloc[-1]
        ema50_val = ema50_series.iloc[-1]
        ema200_val = ema200_series.iloc[-1]
        ema50_prev = ema50_series.iloc[-10]

        if pd.isna(ema50_val) or pd.isna(ema200_val) or pd.isna(ema50_prev):
            return False, "Gate1_Trend: EMA values are NaN"

        if price <= ema200_val:
            return False, f"Gate1_Trend: price {price:.2f} <= EMA200 {ema200_val:.2f}"
        if price <= ema50_val:
            return False, f"Gate1_Trend: price {price:.2f} <= EMA50 {ema50_val:.2f}"
        if ema50_val <= ema50_prev:
            return False, f"Gate1_Trend: EMA50 not sloping up ({ema50_val:.2f} <= {ema50_prev:.2f})"

        return True, ""
    except Exception as exc:
        log.warning("Gate1_Trend exception: %s", exc)
        return False, f"Gate1_Trend: exception {exc}"


def _gate_2_liquidity(df: pd.DataFrame) -> tuple[bool, str]:
    """Gate 2: median daily turnover (close * volume) over 20 days > MIN_MEDIAN_TURNOVER."""
    try:
        if len(df) < 20:
            return False, "Gate2_Liquidity: insufficient data (need 20+ rows)"

        turnover = df["close"] * df["volume"]
        median_turnover = turnover.tail(20).median()

        if median_turnover <= config.MIN_MEDIAN_TURNOVER:
            return (
                False,
                f"Gate2_Liquidity: median turnover {median_turnover:,.0f} <= {config.MIN_MEDIAN_TURNOVER:,.0f}",
            )
        return True, ""
    except Exception as exc:
        log.warning("Gate2_Liquidity exception: %s", exc)
        return False, f"Gate2_Liquidity: exception {exc}"


def _gate_3_rs55(df: pd.DataFrame, nifty_df: pd.DataFrame) -> tuple[bool, str]:
    """Gate 3: RS55 = (stock_55d_return / nifty_55d_return) - 1 must be > 0."""
    try:
        stock_close = df[["close"]].copy()
        nifty_close = nifty_df[["close"]].rename(columns={"close": "nifty"}).copy()

        aligned = stock_close.join(nifty_close, how="inner")
        if len(aligned) < 56:
            return False, f"Gate3_RS55: only {len(aligned)} aligned rows (need 56+)"

        stock_perf = aligned["close"].iloc[-1] / aligned["close"].iloc[-55]
        nifty_perf = aligned["nifty"].iloc[-1] / aligned["nifty"].iloc[-55]

        if nifty_perf == 0:
            return False, "Gate3_RS55: nifty_perf is zero"

        rs55 = (stock_perf / nifty_perf) - 1

        if rs55 <= config.MIN_RS55:
            return False, f"Gate3_RS55: RS55 {rs55:.4f} <= {config.MIN_RS55}"
        return True, ""
    except Exception as exc:
        log.warning("Gate3_RS55 exception: %s", exc)
        return False, f"Gate3_RS55: exception {exc}"


def _gate_4_sector_rs(symbol: str, sector_rs55_map: dict) -> tuple[bool, str]:
    """Gate 4: sector RS55 > 0. Pass if sector is 'Other' or not mapped."""
    try:
        from data.universe import SECTOR_MAP

        sector = SECTOR_MAP.get(symbol, "Other")
        if sector == "Other":
            return True, ""

        if sector not in sector_rs55_map:
            log.debug("Gate4_SectorRS: sector '%s' not in rs55_map, passing", sector)
            return True, ""

        sector_rs = sector_rs55_map[sector]
        if sector_rs <= 0:
            return False, f"Gate4_SectorRS: sector '{sector}' RS55={sector_rs:.4f} <= 0"
        return True, ""
    except ImportError:
        log.debug("Gate4_SectorRS: data.universe.SECTOR_MAP not found, passing gate")
        return True, ""
    except Exception as exc:
        log.warning("Gate4_SectorRS exception: %s", exc)
        return True, ""  # Pass on unexpected errors


def _gate_5_results_blackout(symbol: str, calendar: dict) -> tuple[bool, str]:
    """Gate 5: results blackout window. Skip if calendar is None."""
    if calendar is None:
        return True, ""
    try:
        from datetime import date
        from notify.results_calendar import is_in_blackout

        in_blackout = is_in_blackout(symbol, date.today(), calendar)
        if in_blackout:
            return False, f"Gate5_ResultsBlackout: {symbol} in {config.RESULTS_BLACKOUT_DAYS}d blackout"
        return True, ""
    except ImportError:
        log.debug("Gate5_ResultsBlackout: results_calendar module not found, passing gate")
        return True, ""
    except Exception as exc:
        log.warning("Gate5_ResultsBlackout exception for %s: %s", symbol, exc)
        return True, ""  # Always pass on exception


def apply_all_gates(
    symbol: str,
    df: pd.DataFrame,
    nifty_df: pd.DataFrame,
    sector_rs55_map: dict,
    calendar: dict = None,
) -> tuple[bool, list[str]]:
    """
    Apply all 5 hard gates. Returns (passed, failed_reasons).
    Call before any scoring. If passed=False, skip scoring entirely.

    Args:
        symbol: NSE symbol string
        df: Stock OHLCV DataFrame
        nifty_df: Nifty 50 benchmark OHLCV DataFrame
        sector_rs55_map: Dict {sector_name: rs55_float} pre-computed
        calendar: Results calendar dict from results_calendar.py (None = skip Gate 5)

    Returns:
        (True, []) if all gates pass, (False, [reason, ...]) if any fail
    """
    failed_reasons: list[str] = []

    gate_checks = [
        _gate_1_trend(df),
        _gate_2_liquidity(df),
        _gate_3_rs55(df, nifty_df),
        _gate_4_sector_rs(symbol, sector_rs55_map),
        _gate_5_results_blackout(symbol, calendar),
    ]

    for passed, reason in gate_checks:
        if not passed:
            failed_reasons.append(reason)

    if failed_reasons:
        log.debug("%s failed gates: %s", symbol, failed_reasons)
        return False, failed_reasons

    return True, []


def compute_sector_rs55_map(provider, nifty_df: pd.DataFrame) -> dict[str, float]:
    """
    Build {sector_name: rs55_value} dict for Gate 4.
    Primary: fetch sector index OHLCV and compute its RS55 vs Nifty.
    Fallback: if sector index fetch fails, use median RS55 of constituent stocks (pass 0.0).

    Args:
        provider: DataProvider instance with get_ohlcv() method
        nifty_df: Nifty 50 benchmark DataFrame

    Returns:
        Dict mapping sector name to RS55 float value
    """
    sector_rs55: dict[str, float] = {}
    nifty_close = nifty_df[["close"]].rename(columns={"close": "nifty"})

    for sector_name, index_symbol in config.SECTOR_INDICES.items():
        try:
            sector_df = provider.get_ohlcv(index_symbol, period_days=400)
            if sector_df is None or len(sector_df) < 56:
                raise ValueError(f"Insufficient data for {index_symbol}: {len(sector_df) if sector_df is not None else 0} rows")

            sector_close = sector_df[["close"]].copy()
            aligned = sector_close.join(nifty_close, how="inner")
            if len(aligned) < 56:
                raise ValueError(f"Only {len(aligned)} aligned rows for {index_symbol}")

            sector_perf = aligned["close"].iloc[-1] / aligned["close"].iloc[-55]
            nifty_perf = aligned["nifty"].iloc[-1] / aligned["nifty"].iloc[-55]

            if nifty_perf == 0:
                raise ValueError("Nifty perf is zero")

            rs55 = (sector_perf / nifty_perf) - 1
            sector_rs55[sector_name] = rs55
            log.debug("Sector %s RS55 = %.4f (via index %s)", sector_name, rs55, index_symbol)

        except Exception as exc:
            log.warning(
                "Sector %s index fetch failed (%s) — sector omitted from map, Gate 4 will pass",
                sector_name, exc,
            )
            # Intentionally NOT added to map: Gate 4 passes missing sectors (line ~105)

    return sector_rs55
