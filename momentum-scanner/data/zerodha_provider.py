"""
zerodha_provider.py — Zerodha Kite API stub.

All methods raise NotImplementedError with step-by-step setup instructions.
Implement this file when ready to go live. config.py needs one-line change only.

Setup checklist:
  1. pip install kiteconnect
  2. Set KITE_API_KEY and KITE_API_SECRET in .env
  3. Implement the 5 abstract methods below using kite.historical_data()
  4. Change DATA_PROVIDER = 'zerodha' in config.py
"""

import pandas as pd
from data.data_provider import DataProvider

_SETUP_MSG = (
    "Zerodha provider not yet configured.\n"
    "  1. Set KITE_API_KEY and KITE_API_SECRET in .env\n"
    "  2. Implement get_ohlcv() using kite.historical_data()\n"
    "  3. Change DATA_PROVIDER = 'zerodha' in config.py"
)


class ZerodhaDataProvider(DataProvider):
    """Zerodha Kite API provider — implement before going live."""

    def get_ohlcv(self, symbol: str, period_days: int = 400) -> pd.DataFrame:
        """Fetch OHLCV via kite.historical_data(). Not yet implemented."""
        raise NotImplementedError(_SETUP_MSG)

    def get_universe(self) -> list[str]:
        """Return NSE universe symbols. Not yet implemented."""
        raise NotImplementedError(_SETUP_MSG)

    def get_benchmark(self, period_days: int = 400) -> pd.DataFrame:
        """Fetch Nifty 50 via Kite API. Not yet implemented."""
        raise NotImplementedError(_SETUP_MSG)

    def get_all_ohlcv(
        self, symbols: list[str], period_days: int = 400
    ) -> dict[str, pd.DataFrame]:
        """Batch fetch via Kite API. Not yet implemented."""
        raise NotImplementedError(_SETUP_MSG)

    def is_market_open(self) -> bool:
        """Check market hours via Kite API. Not yet implemented."""
        raise NotImplementedError(_SETUP_MSG)
