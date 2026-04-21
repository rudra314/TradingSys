"""
indicators.py — Pure pandas/numpy implementations of EMA, RSI, ATR.

Drop-in replacements for the ta library — no compiled dependencies required.
"""
import pandas as pd
import numpy as np


def ema(series: pd.Series, window: int) -> pd.Series:
    """
    Exponential Moving Average using Wilder smoothing (adjust=False).

    Equivalent to ta.trend.EMAIndicator(close, window).ema_indicator().

    Args:
        series: Price series (close or any numeric series).
        window: Lookback period (e.g. 50, 200).

    Returns:
        pd.Series of EMA values, same index as input.
    """
    return series.ewm(span=window, adjust=False, min_periods=window).mean()


def rsi(series: pd.Series, window: int = 14) -> pd.Series:
    """
    RSI with Wilder smoothing — matches StockEdge / TradingView RSI exactly.

    Equivalent to ta.momentum.RSIIndicator(close, window).rsi().

    Args:
        series: Close price series.
        window: Lookback period (default 14).

    Returns:
        pd.Series of RSI values [0, 100]. NaN for first `window` periods.
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)
    # Wilder smoothing = EWM with com = window - 1
    avg_gain = gain.ewm(com=window - 1, adjust=False, min_periods=window).mean()
    avg_loss = loss.ewm(com=window - 1, adjust=False, min_periods=window).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100.0 - (100.0 / (1.0 + rs))


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """
    Average True Range using Wilder smoothing.

    Equivalent to ta.volatility.AverageTrueRange(high, low, close, window).average_true_range().

    Args:
        high: High price series.
        low:  Low price series.
        close: Close price series.
        window: Lookback period (default 14).

    Returns:
        pd.Series of ATR values.
    """
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(com=window - 1, adjust=False, min_periods=window).mean()
