"""
yahoo_provider.py — Yahoo Finance implementation of DataProvider.

NSE symbols: appends '.NS' suffix automatically.
Nifty 50 benchmark: '^NSEI'.
Parquet cache: data/cache/{symbol}_{YYYY-MM-DD}.parquet — loaded same-day if present.

Fetch strategy:
  get_all_ohlcv  — bulk yf.download() in chunks of 100, single API call per chunk
  get_ohlcv      — single Ticker.history() call with start= date (not period=)
  get_benchmark  — same as get_ohlcv

Both use start= date string (YYYY-MM-DD) instead of period= because yfinance
only accepts fixed period strings like "1y","2y","max" — "400d" is invalid.
"""

import logging
import os
import time
from datetime import date, datetime, timedelta

import pandas as pd
import pytz
import yfinance as yf

from data.data_provider import DataProvider
import config

log = logging.getLogger(__name__)

_IST = pytz.timezone("Asia/Kolkata")
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
_BATCH_SIZE = 100
_BATCH_PAUSE = 3


def _cache_path(symbol: str, today: str) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"{symbol}_{today}.parquet")


def _load_cache(symbol: str) -> pd.DataFrame | None:
    today = date.today().isoformat()
    path = _cache_path(symbol, today)
    if os.path.exists(path):
        try:
            return pd.read_parquet(path)
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


def _start_date(period_days: int) -> str:
    """Calculate start date with 40% buffer for weekends and holidays."""
    buffer = int(period_days * 1.4)
    return (date.today() - timedelta(days=buffer)).strftime("%Y-%m-%d")


def _normalize(raw: pd.DataFrame) -> pd.DataFrame | None:
    """Normalize any yfinance DataFrame to lowercase OHLCV with tz-naive DatetimeIndex."""
    if raw is None or raw.empty:
        return None
    if isinstance(raw.columns, pd.MultiIndex):
        raw = raw.copy()
        raw.columns = raw.columns.get_level_values(0)
    raw.columns = [str(c).lower() for c in raw.columns]
    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(raw.columns):
        return None
    df = raw[["open", "high", "low", "close", "volume"]].copy()
    df.index = pd.to_datetime(df.index)
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    df.sort_index(inplace=True)
    df.dropna(inplace=True)
    return df if not df.empty else None


def _fetch_single(ticker_ns: str, period_days: int) -> pd.DataFrame | None:
    """Fetch one ticker via Ticker.history(start=...). Retries 3x with backoff."""
    start = _start_date(period_days)
    delays = [2, 4, 8]
    for attempt, delay in enumerate(delays, 1):
        try:
            raw = yf.Ticker(ticker_ns).history(start=start, auto_adjust=True, actions=False)
            df = _normalize(raw)
            if df is not None:
                return df
            raise ValueError("empty after normalization")
        except Exception as exc:
            log.warning(f"[{ticker_ns}] attempt {attempt}/3 failed: {exc}")
            if attempt < len(delays):
                time.sleep(delay)
    log.error(f"[{ticker_ns}] all retries exhausted")
    return None


def _fetch_batch(tickers_ns: list[str], period_days: int) -> dict[str, pd.DataFrame]:
    """
    Download a list of tickers in one yf.download() call.
    Handles both MultiIndex column layouts across yfinance versions:
      - (ticker, price_type)  when group_by='ticker' and level-0 contains .NS
      - (price_type, ticker)  older layout where level-1 contains .NS
    """
    start = _start_date(period_days)
    result: dict[str, pd.DataFrame] = {}
    try:
        raw = yf.download(
            tickers=tickers_ns,
            start=start,
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
            timeout=60,
        )
    except Exception as exc:
        log.error(f"yf.download batch failed: {exc}")
        return result
    if raw is None or raw.empty:
        log.warning("yf.download returned empty DataFrame")
        return result
    if isinstance(raw.columns, pd.MultiIndex):
        lvl0 = raw.columns.get_level_values(0).unique().tolist()
        if any(".NS" in str(t) for t in lvl0):
            for sym_ns in tickers_ns:
                try:
                    if sym_ns not in raw.columns.get_level_values(0):
                        continue
                    df = _normalize(raw[sym_ns].copy())
                    if df is not None:
                        result[sym_ns] = df
                except Exception as exc:
                    log.debug(f"Extract {sym_ns}: {exc}")
        else:
            for sym_ns in tickers_ns:
                try:
                    if sym_ns not in raw.columns.get_level_values(1):
                        continue
                    sub = raw.xs(sym_ns, axis=1, level=1)
                    df = _normalize(sub.copy())
                    if df is not None:
                        result[sym_ns] = df
                except Exception as exc:
                    log.debug(f"Extract {sym_ns}: {exc}")
    else:
        if len(tickers_ns) == 1:
            df = _normalize(raw.copy())
            if df is not None:
                result[tickers_ns[0]] = df
    return result


class YahooDataProvider(DataProvider):
    """Yahoo Finance data provider. Default for paper trading and backtesting."""

    _BENCHMARK = "^NSEI"

    def get_ohlcv(self, symbol: str, period_days: int = 400) -> pd.DataFrame:
        cached = _load_cache(symbol)
        if cached is not None:
            return cached
        df = _fetch_single(f"{symbol}.NS", period_days)
        if df is None:
            raise RuntimeError(f"Could not fetch data for {symbol}")
        _save_cache(symbol, df)
        return df

    def get_universe(self) -> list[str]:
        from data.universe import UNIVERSE
        return UNIVERSE

    def get_benchmark(self, period_days: int = 400) -> pd.DataFrame:
        cached = _load_cache("NIFTY50_BENCH")
        if cached is not None:
            return cached
        df = _fetch_single(self._BENCHMARK, period_days)
        if df is None:
            raise RuntimeError("Could not fetch Nifty 50 benchmark (^NSEI)")
        _save_cache("NIFTY50_BENCH", df)
        return df

    def get_all_ohlcv(self, symbols: list[str], period_days: int = 400) -> dict[str, pd.DataFrame]:
        """
        Batch-fetch OHLCV for up to ~500 symbols.
        1. Load all same-day cached symbols instantly.
        2. Batch-download uncached symbols via yf.download() in chunks of 100.
        3. Retry individually only if <= 20 symbols still missing.
        """
        result: dict[str, pd.DataFrame] = {}
        total = len(symbols)

        uncached: list[str] = []
        for sym in symbols:
            cached = _load_cache(sym)
            if cached is not None:
                if len(cached) >= 260:
                    result[sym] = cached
                else:
                    log.warning(f"Cached {sym} has only {len(cached)} rows — skipping")
            else:
                uncached.append(sym)

        if not uncached:
            log.info(f"All {total} symbols loaded from cache")
            return result

        log.info(f"Cache: {len(result)}/{total}. Downloading {len(uncached)} symbols in chunks of {_BATCH_SIZE}...")

        ns_map = {f"{s}.NS": s for s in uncached}
        ns_list = list(ns_map.keys())
        total_chunks = (len(ns_list) + _BATCH_SIZE - 1) // _BATCH_SIZE

        for chunk_idx in range(0, len(ns_list), _BATCH_SIZE):
            chunk_ns = ns_list[chunk_idx: chunk_idx + _BATCH_SIZE]
            chunk_num = chunk_idx // _BATCH_SIZE + 1
            log.info(f"Downloading chunk {chunk_num}/{total_chunks} ({len(chunk_ns)} symbols)...")

            batch = _fetch_batch(chunk_ns, period_days)
            for sym_ns, df in batch.items():
                sym = ns_map.get(sym_ns, sym_ns.replace(".NS", ""))
                if len(df) >= 260:
                    _save_cache(sym, df)
                    result[sym] = df
                else:
                    log.warning(f"{sym}: only {len(df)} rows — skipping")

            log.info(f"Chunk {chunk_num} done: {len(batch)}/{len(chunk_ns)} fetched. Total so far: {len(result)}/{total}")
            if chunk_idx + _BATCH_SIZE < len(ns_list):
                time.sleep(_BATCH_PAUSE)

        still_missing = [s for s in uncached if s not in result]
        if 0 < len(still_missing) <= 20:
            log.info(f"Retrying {len(still_missing)} individually: {still_missing}")
            for sym in still_missing:
                df = _fetch_single(f"{sym}.NS", period_days)
                if df is not None and len(df) >= 260:
                    _save_cache(sym, df)
                    result[sym] = df
                time.sleep(1)
        elif len(still_missing) > 20:
            log.warning(f"{len(still_missing)} symbols missing after batch — Yahoo may be rate-limiting. Re-run to use cache.")

        log.info(f"Fetch complete: {len(result)}/{total} symbols loaded")
        return result

    def is_market_open(self) -> bool:
        now_ist = datetime.now(_IST)
        if now_ist.weekday() >= 5:
            return False
        open_t  = now_ist.replace(hour=9,  minute=15, second=0, microsecond=0)
        close_t = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
        return open_t <= now_ist <= close_t
