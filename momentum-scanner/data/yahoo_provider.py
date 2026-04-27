"""
yahoo_provider.py — Yahoo Finance implementation via yfinance + curl_cffi.

Why curl_cffi?
  Yahoo Finance uses TLS fingerprinting to block automated requests from cloud
  IPs (GitHub Actions, AWS, etc.).  curl_cffi makes requests look like a real
  Chrome browser — it is yfinance's own recommended fix for this issue.
  When curl_cffi is installed, yfinance uses it automatically.

Fetch strategy for get_all_ohlcv (500 NSE symbols):
  1. Load same-day parquet cache (instant, no network).
  2. For uncached symbols batch via yf.download() in chunks of 50.
     Each chunk = one HTTP request instead of 50 individual ones.
  3. Individual Ticker.history() retry for any symbols still missing
     (handles the rare stock that yf.download ignores silently).
"""

import logging
import os
import time
from datetime import date, datetime, timedelta

import pandas as pd
import pytz
import yfinance as yf

from data.data_provider import DataProvider

log = logging.getLogger(__name__)

_IST       = pytz.timezone("Asia/Kolkata")
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
_BATCH     = 50
_PAUSE     = 2
_MIN_ROWS  = 260


def _today() -> str:
    return date.today().isoformat()


def _cache_path(key: str) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"{key}_{_today()}.parquet")


def _load_cache(key: str):
    p = _cache_path(key)
    if os.path.exists(p):
        try:
            return pd.read_parquet(p)
        except Exception:
            pass
    return None


def _save_cache(key: str, df: pd.DataFrame) -> None:
    try:
        df.to_parquet(_cache_path(key), engine="pyarrow")
    except Exception as exc:
        log.warning("Cache write failed [%s]: %s", key, exc)


def _start(period_days: int) -> str:
    """Start date string with 40% buffer for holidays and weekends."""
    return (date.today() - timedelta(days=int(period_days * 1.4))).strftime("%Y-%m-%d")


def _clean(df: pd.DataFrame):
    """Return a tz-naive lowercase OHLCV DataFrame, or None if unusable."""
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df = df.droplevel(1, axis=1) if df.columns.nlevels == 2 else df
        df = df.copy()
    df.columns = [str(c).lower() for c in df.columns]
    need = {"open", "high", "low", "close", "volume"}
    if not need.issubset(df.columns):
        return None
    df = df[["open", "high", "low", "close", "volume"]].copy()
    df.index = pd.to_datetime(df.index)
    if getattr(df.index, "tz", None) is not None:
        df.index = df.index.tz_localize(None)
    df.sort_index(inplace=True)
    df.dropna(inplace=True)
    return df if len(df) > 0 else None


def _fetch_one(ticker_ns: str, period_days: int):
    """Download one symbol via Ticker.history(). Retries 3x with backoff."""
    start = _start(period_days)
    for i in range(1, 4):
        try:
            raw = yf.Ticker(ticker_ns).history(start=start, auto_adjust=True, actions=False)
            df = _clean(raw)
            if df is not None:
                return df
            raise ValueError("empty after clean")
        except Exception as exc:
            log.warning("[%s] attempt %d/3: %s", ticker_ns, i, exc)
            if i < 3:
                time.sleep(2 ** i)
    log.error("[%s] all retries exhausted", ticker_ns)
    return None


def _fetch_batch(tickers_ns: list, period_days: int) -> dict:
    """
    Download a chunk of tickers with a single yf.download() call.
    Handles both MultiIndex layouts that yfinance returns depending on version.
    """
    start = _start(period_days)
    out: dict = {}
    try:
        raw = yf.download(
            tickers=tickers_ns,
            start=start,
            auto_adjust=True,
            progress=False,
            group_by="ticker",
            threads=True,
            timeout=30,
        )
    except Exception as exc:
        log.error("yf.download chunk failed: %s", exc)
        return out

    if raw is None or raw.empty:
        log.warning("yf.download returned empty for chunk of %d symbols", len(tickers_ns))
        return out

    if not isinstance(raw.columns, pd.MultiIndex):
        if len(tickers_ns) == 1:
            df = _clean(raw)
            if df is not None:
                out[tickers_ns[0]] = df
        return out

    lvl0 = raw.columns.get_level_values(0).unique().tolist()
    ticker_in_lvl0 = any(".NS" in str(v) or "^" in str(v) for v in lvl0)

    for sym_ns in tickers_ns:
        try:
            sub = raw[sym_ns] if ticker_in_lvl0 else raw.xs(sym_ns, axis=1, level=1)
            df = _clean(sub.copy())
            if df is not None:
                out[sym_ns] = df
        except KeyError:
            pass
        except Exception as exc:
            log.debug("Extract %s: %s", sym_ns, exc)

    return out


class YahooDataProvider(DataProvider):

    _BENCH = "^NSEI"

    def _preflight(self) -> bool:
        """Test that Yahoo Finance is reachable before scanning 500 symbols."""
        try:
            raw = yf.Ticker("RELIANCE.NS").history(period="5d", actions=False)
            if raw is not None and not raw.empty:
                log.info("Pre-flight OK: RELIANCE.NS returned %d rows", len(raw))
                return True
            log.error("Pre-flight FAIL: RELIANCE.NS returned empty DataFrame")
            return False
        except Exception as exc:
            log.error("Pre-flight FAIL: %s", exc)
            return False

    def get_ohlcv(self, symbol: str, period_days: int = 400) -> pd.DataFrame:
        cached = _load_cache(symbol)
        if cached is not None:
            return cached
        # Index symbols (^NSEBANK, ^CNXIT …) must not get the .NS suffix
        ticker = symbol if symbol.startswith("^") else f"{symbol}.NS"
        df = _fetch_one(ticker, period_days)
        if df is None:
            raise RuntimeError(f"Could not fetch data for {symbol}")
        _save_cache(symbol, df)
        return df

    def get_universe(self) -> list:
        from data.universe import UNIVERSE
        return UNIVERSE

    def get_benchmark(self, period_days: int = 400) -> pd.DataFrame:
        cached = _load_cache("__NIFTY__")
        if cached is not None:
            return cached
        df = _fetch_one(self._BENCH, period_days)
        if df is None:
            raise RuntimeError("Could not fetch Nifty 50 benchmark (^NSEI)")
        _save_cache("__NIFTY__", df)
        return df

    def get_all_ohlcv(self, symbols: list, period_days: int = 400) -> dict:
        result: dict = {}
        total = len(symbols)

        uncached = []
        for sym in symbols:
            c = _load_cache(sym)
            if c is not None and len(c) >= _MIN_ROWS:
                result[sym] = c
            else:
                uncached.append(sym)

        log.info("Cache: %d/%d. Need to fetch: %d", len(result), total, len(uncached))
        if not uncached:
            return result

        if not self._preflight():
            log.error(
                "Pre-flight failed — Yahoo Finance is not reachable. "
                "Ensure curl_cffi>=0.6.2 is installed. "
                "Returning %d cached symbols only.", len(result)
            )
            return result

        ns = {f"{s}.NS": s for s in uncached}
        ns_list = list(ns)
        n_chunks = (len(ns_list) + _BATCH - 1) // _BATCH

        for i in range(0, len(ns_list), _BATCH):
            chunk_ns = ns_list[i: i + _BATCH]
            chunk_no = i // _BATCH + 1
            log.info("Batch %d/%d: downloading %d symbols...", chunk_no, n_chunks, len(chunk_ns))

            batch = _fetch_batch(chunk_ns, period_days)
            for sym_ns, df in batch.items():
                sym = ns.get(sym_ns, sym_ns.replace(".NS", ""))
                if len(df) >= _MIN_ROWS:
                    _save_cache(sym, df)
                    result[sym] = df
                else:
                    log.warning("%s: only %d rows — dropping", sym, len(df))

            log.info("Batch %d done: %d/%d. Total: %d/%d",
                     chunk_no, len(batch), len(chunk_ns), len(result), total)
            if i + _BATCH < len(ns_list):
                time.sleep(_PAUSE)

        missing = [s for s in uncached if s not in result]
        if missing:
            log.info("Individual retry for %d stragglers...", len(missing))
            for sym in missing:
                df = _fetch_one(f"{sym}.NS", period_days)
                if df is not None and len(df) >= _MIN_ROWS:
                    _save_cache(sym, df)
                    result[sym] = df
                time.sleep(0.5)

        log.info("Fetch complete: %d/%d symbols", len(result), total)
        return result

    def is_market_open(self) -> bool:
        now = datetime.now(_IST)
        if now.weekday() >= 5:
            return False
        o = now.replace(hour=9,  minute=15, second=0, microsecond=0)
        c = now.replace(hour=15, minute=30, second=0, microsecond=0)
        return o <= now <= c
