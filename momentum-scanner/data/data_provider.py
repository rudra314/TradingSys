"""
data_provider.py — Abstract base class for all data providers.

Swap Yahoo for Zerodha by changing DATA_PROVIDER in config.py only.
ALL data access in the system goes through get_provider() factory function.
"""

from abc import ABC, abstractmethod
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


class DataProvider(ABC):
    """
    Abstract interface all data providers must implement.
    Five methods, identical signatures — guaranteed swap compatibility.
    """

    @abstractmethod
    def get_ohlcv(self, symbol: str, period_days: int = 400) -> pd.DataFrame:
        """
        Fetch OHLCV data for one symbol.

        Args:
            symbol: Exchange symbol without suffix (e.g. 'RELIANCE')
            period_days: History in calendar days. 400 covers EMA200 + RS55 + 12M momentum.

        Returns:
            DataFrame with columns [open, high, low, close, volume],
            DatetimeIndex of trading days, sorted ascending.
        """
        pass

    @abstractmethod
    def get_universe(self) -> list[str]:
        """
        Return full list of NSE symbols to scan (~500 stocks).

        Returns:
            List of plain NSE symbols without exchange suffix.
        """
        pass

    @abstractmethod
    def get_benchmark(self, period_days: int = 400) -> pd.DataFrame:
        """
        Fetch Nifty 50 index OHLCV.

        Args:
            period_days: Same as get_ohlcv.

        Returns:
            Same format as get_ohlcv().
        """
        pass

    @abstractmethod
    def get_all_ohlcv(
        self, symbols: list[str], period_days: int = 400
    ) -> dict[str, pd.DataFrame]:
        """
        Batch fetch OHLCV for multiple symbols with caching and retry.

        Args:
            symbols: List of NSE symbols (plain, no suffix).
            period_days: History window.

        Returns:
            Dict mapping symbol → DataFrame. Failed symbols are skipped (logged).
        """
        pass

    @abstractmethod
    def is_market_open(self) -> bool:
        """
        Return True if NSE market is currently open (9:15–15:30 IST, weekdays).
        """
        pass


def get_provider() -> DataProvider:
    """
    Factory function — the ONLY way to obtain a data provider.

    Change config.DATA_PROVIDER to switch between 'yahoo' and 'zerodha'.
    No other file needs modification on provider swap.

    Returns:
        Concrete DataProvider instance per config.DATA_PROVIDER.

    Raises:
        ValueError: If DATA_PROVIDER value is not recognised.
    """
    if config.DATA_PROVIDER == "yahoo":
        from data.yahoo_provider import YahooDataProvider
        return YahooDataProvider()
    elif config.DATA_PROVIDER == "zerodha":
        from data.zerodha_provider import ZerodhaDataProvider
        return ZerodhaDataProvider()
    else:
        raise ValueError(
            f"Unknown DATA_PROVIDER: '{config.DATA_PROVIDER}'. "
            "Valid options: 'yahoo', 'zerodha'."
        )
