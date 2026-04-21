"""
yahoo_provider.py — Yahoo Finance implementation of DataProvider.

NSE symbols: appends '.NS' suffix automatically.
Nifty 50 benchmark: '^NSEI'.
Parquet cache: data/cache/{symbol}_{YYYY-MM-DD}.parquet — loaded same-day if present.
Retry: 3 attempts with exponential backoff (2s, 4s, 8s).
Rate-limit guard: 0.5s sleep between symbols in batch fetch.
"""

import logging
import os
import time
from datetime import date, datetime

import pandas as pd
import pytz
import yfinance as yf

from data.data_provider import DataProvider
import config

log = logging.getLogger(__name__)

_IST = pytz.timezone("Asia/Kolkata")
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")


def _cache_path(symbol: str, today: str) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"{symbol}_{today}.parquet")


def _load_cache(symbol: str) -> pd.DataFrame | None:
    """Return cached DataFrame if a same-day file exists, else None."""
    today = date.today().isoformat()
    path = _cache_path(symbol, today)
    if os.path.exists(path):
        try:
            df = pd.read_parquet(path)
            log.debug(f"Cache hit: {symbol}")
            return df
        except Exception as exc:
            log.warning(f"Cache read failed for {symbol}: {exc}")
    return None


def _save_cache(symbol: str, df: pd.DataFrame) -> None:
    today = date.today().isoformat()
    path = _cache_path(symbol, today)
    try:
        df.to_parquet(path, engine="pyarrow")
    except Exception as exc:
        log.warning(f"Cache write failed for {symbol}: {exc}")


def _fetch_with_retry(ticker_symbol: str, period_days: int) -> pd.DataFrame | None:
    """
    Download OHLCV from Yahoo Finance with 3-attempt exponential backoff.
    Uses Ticker.history() which is stable across all modern yfinance versions.
    """
    delays = [2, 4, 8]
    for attempt, delay in enumerate(delays, 1):
        try:
            ticker = yf.Ticker(ticker_symbol)
            raw = ticker.history(period=f"{period_days}d", auto_adjust=True, actions=False)

            if raw is None or raw.empty:
                raise ValueError("Empty response")

            # Normalize column names to lowercase
            raw.columns = [c.lower() for c in raw.columns]

            # Keep only OHLCV, drop dividends/stock splits if present
            for col in ["dividends", "stock splits", "capital gains"]:
                if col in raw.columns:
                    raw = raw.drop(columns=[col])

            df = raw[["open", "high", "low", "close", "volume"]].copy()

            # Strip timezone from index so parquet round-trips cleanly
            df.index = pd.to_datetime(df.index)
            if df.index.tz is not None:
                df.index = df.index.tz_localize(None)

            df.sort_index(inplace=True)
            df.dropna(inplace=True)
            return df

        except Exception as exc:
            log.warning(f"Attempt {attempt}/3 failed for {ticker_symbol}: {exc}")
            if attempt < len(delays):
                time.sleep(delay)

    log.error(f"All retries exhausted for {ticker_symbol}")
    return None


class YahooDataProvider(DataProvider):
    """Yahoo Finance data provider. Default for paper trading and testing."""

    _BENCHMARK = "^NSEI"

    def get_ohlcv(self, symbol: str, period_days: int = 400) -> pd.DataFrame:
        """
        Fetch OHLCV for one NSE symbol, using same-day parquet cache.

        Args:
            symbol: Plain NSE symbol (e.g. 'RELIANCE').
            period_days: Calendar days of history (400 recommended).

        Returns:
            DataFrame [open, high, low, close, volume] with DatetimeIndex.

        Example:
            df = provider.get_ohlcv('RELIANCE', 400)
        """
        cached = _load_cache(symbol)
        if cached is not None:
            return cached

        ticker = f"{symbol}.NS"
        df = _fetch_with_retry(ticker, period_days)
        if df is None:
            raise RuntimeError(f"Could not fetch data for {symbol}")

        _save_cache(symbol, df)
        return df

    def get_universe(self) -> list[str]:
        """
        Return deduplicated NSE universe (~500 symbols).

        Returns:
            List of plain NSE symbols from data/universe.py UNIVERSE list.
        """
        from data.universe import UNIVERSE
        return UNIVERSE

    def get_benchmark(self, period_days: int = 400) -> pd.DataFrame:
        """
        Fetch Nifty 50 (^NSEI) OHLCV data.

        Args:
            period_days: Calendar days of history.

        Returns:
            Same format as get_ohlcv().
        """
        cached = _load_cache("NIFTY50_BENCH")
        if cached is not None:
            return cached

        df = _fetch_with_retry(self._BENCHMARK, period_days)
        if df is None:
            raise RuntimeError("Could not fetch Nifty 50 benchmark data")

        _save_cache("NIFTY50_BENCH", df)
        return df

    def get_all_ohlcv(
        self, symbols: list[str], period_days: int = 400
    ) -> dict[str, pd.DataFrame]:
        """
        Batch-fetch OHLCV for a list of symbols.

        Loads from same-day cache where available (makes re-runs instant).
        Sleeps 0.5s between live fetches to respect Yahoo rate limits.
        Skips symbols with insufficient history (< 260 days) or fetch errors.

        Args:
            symbols: List of plain NSE symbols.
            period_days: Calendar days of history.

        Returns:
            Dict {symbol: DataFrame}. Failed symbols absent from dict.
        """
        result: dict[str, pd.DataFrame] = {}
        total = len(symbols)

        for i, sym in enumerate(symbols, 1):
            try:
                cached = _load_cache(sym)
                if cached is not None:
                    if len(cached) >= 260:
                        result[sym] = cached
                    else:
                        log.warning(f"Insufficient history for {sym}: {len(cached)} days")
                    continue

                ticker = f"{sym}.NS"
                df = _fetch_with_retry(ticker, period_days)

                if df is None:
                    log.warning(f"Skipping {sym}: fetch failed")
                    continue

                if len(df) < 260:
                    log.warning(f"Insufficient history for {sym}: {len(df)} days")
                    continue

                _save_cache(sym, df)
                result[sym] = df
                log.debug(f"[{i}/{total}] Fetched {sym}: {len(df)} days")
                time.sleep(0.5)

            except Exception as exc:
                log.error(f"Error fetching {sym}: {exc}")
                continue

        log.info(f"Batch fetch complete: {len(result)}/{total} symbols loaded")
        return result

    def is_market_open(self) -> bool:
        """
        Return True if NSE market is currently open (09:15–15:30 IST, Mon–Fri).

        Returns:
            bool: True during market hours on weekdays.
        """
        now_ist = datetime.now(_IST)
        if now_ist.weekday() >= 5:  # Saturday=5, Sunday=6
            return False
        market_open  = now_ist.replace(hour=9,  minute=15, second=0, microsecond=0)
        market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
        return market_open <= now_ist <= market_close
