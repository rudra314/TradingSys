"""
backtester.py — Event-driven backtest engine for NSE momentum scanner.

Usage:
    python engine/backtester.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]

Outputs in backtest_results/:
    trades.csv        — one row per closed trade
    summary.json      — aggregate statistics
    equity_curve.csv  — daily portfolio value vs Nifty

Design:
- Lookahead-safe: get_data_as_of(df, date) clips data to simulation date
- Weekly scan on last Friday of each week → watchlist for following Mon-Fri
- Breakout detection: pending on day 1, confirmed entry at next day open
- Trade phases: 1 (SL), 2 (1.5R partial + SL→entry), 3 (trailing stop)
- Transaction cost: 0.5% on both entry and exit trade values
"""
import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from data.yahoo_provider import YahooDataProvider
from engine.base_analyzer import base_quality_score
from engine.breakout import _detect_type1_breakout, _detect_type2_breakout
from engine.gates import apply_all_gates
from engine.indicators import ema as _ema, atr as _atr
from engine.regime import get_market_regime
from engine.rs55_engine import compute_rs55
from engine.scorer import score_universe
from engine.sizer import compute_position_size

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
TRANSACTION_COST_PCT = 0.005       # 0.5% applied to both entry and exit values
DEFAULT_SIM_START    = "2023-01-01"
DEFAULT_SIM_END      = "2024-10-31"
TOP_N_WATCHLIST      = 20
SWING_TIME_EXIT      = 10          # sessions without 1R → full exit
POSITIONAL_TIME_EXIT = 30          # sessions without 1.5R → exit half
OUTPUT_DIR = Path(__file__).parent.parent / "backtest_results"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_data_as_of(df: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Return df sliced to rows with index <= as_of."""
    return df.loc[df.index <= as_of]


def _atr14(df: pd.DataFrame) -> float:
    """Latest ATR(14) as scalar, or 0.0 if insufficient data."""
    if len(df) < 15:
        return 0.0
    series = _atr(df["high"], df["low"], df["close"], 14)
    val = series.iloc[-1]
    return float(val) if not pd.isna(val) else 0.0


def _trading_days_in_range(
    nifty_df: pd.DataFrame,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> list:
    mask = (nifty_df.index >= start) & (nifty_df.index <= end)
    return list(nifty_df.index[mask])


def _week_scan_dates(trading_days: list) -> list[tuple]:
    """
    Return [(scan_date, week_first_day), ...] pairs.
    scan_date = last trading day of prior week (Friday close → used as Sunday scan proxy).
    week_first_day = first trading day of the week that will use this watchlist.
    """
    if not trading_days:
        return []
    weeks: list[list] = []
    current: list = [trading_days[0]]
    for d in trading_days[1:]:
        prev = current[-1]
        same_week = (
            d.isocalendar()[1] == prev.isocalendar()[1]
            and d.year == prev.year
        )
        if same_week:
            current.append(d)
        else:
            weeks.append(current)
            current = [d]
    if current:
        weeks.append(current)

    result = []
    for i in range(1, len(weeks)):
        scan_date = weeks[i - 1][-1]       # last trading day of prior week
        week_first = weeks[i][0]           # Monday (or first trading day) of current week
        result.append((scan_date, week_first))
    return result


# ---------------------------------------------------------------------------
# Trade dataclass
# ---------------------------------------------------------------------------

@dataclass
class Trade:
    symbol:        str
    entry_date:    pd.Timestamp
    entry_price:   float
    sl_initial:    float
    sl_current:    float
    target1:       float    # 1.5R
    target2:       float    # 3R
    initial_shares: int
    active_shares: int
    entry_type:    str      # TYPE_1 or TYPE_2
    grade:         str
    score:         float
    sector:        str
    regime_state:  int
    phase:         int = 1  # 1, 2, 3
    hold_sessions: int = 0  # trading sessions held (for time-exit logic)
    max_price:     float = 0.0
    phase2_done:   bool = False
    # Accumulate P&L across partial exits
    gross_pnl:     float = 0.0
    net_pnl:       float = 0.0
    # Set on close
    exit_date:     Optional[pd.Timestamp] = None
    exit_price:    Optional[float] = None
    exit_reason:   Optional[str] = None
    r_multiple:    float = 0.0

    @property
    def initial_risk(self) -> float:
        return self.entry_price - self.sl_initial


# ---------------------------------------------------------------------------
# Sector RS55 map (backtest version uses pre-loaded data)
# ---------------------------------------------------------------------------

def _sector_rs55_backtest(
    sector_data: dict,
    nifty_as_of: pd.DataFrame,
) -> dict:
    nifty_close = nifty_as_of[["close"]].rename(columns={"close": "nifty"})
    result = {}
    for sector_name, sector_df in sector_data.items():
        try:
            if sector_df is None or len(sector_df) < 56:
                continue
            aligned = sector_df[["close"]].join(nifty_close, how="inner")
            if len(aligned) < 56:
                continue
            s_perf = aligned["close"].iloc[-1] / aligned["close"].iloc[-55]
            n_perf = aligned["nifty"].iloc[-1] / aligned["nifty"].iloc[-55]
            if n_perf == 0:
                continue
            result[sector_name] = float((s_perf / n_perf) - 1)
        except Exception:
            pass
    return result


# ---------------------------------------------------------------------------
# Backtest engine
# ---------------------------------------------------------------------------

class BacktestEngine:

    def __init__(self, sim_start: str = DEFAULT_SIM_START, sim_end: str = DEFAULT_SIM_END):
        self.sim_start = pd.Timestamp(sim_start)
        self.sim_end   = pd.Timestamp(sim_end)
        self.provider  = YahooDataProvider()

        # Full historical data (loaded once)
        self.all_data:    dict[str, pd.DataFrame] = {}
        self.nifty_full:  pd.DataFrame = pd.DataFrame()
        self.sector_full: dict[str, pd.DataFrame] = {}

        # Simulation state
        self.open_trades:   list[Trade] = []
        self.closed_trades: list[Trade] = []
        self.capital = float(config.CAPITAL)
        self.cash    = self.capital
        self.equity_curve: list[dict] = []

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_data(self) -> None:
        log.info("Loading Nifty 50 benchmark...")
        self.nifty_full = self.provider.get_benchmark(period_days=1200)
        log.info("Nifty: %d rows (%s → %s)",
                 len(self.nifty_full),
                 self.nifty_full.index[0].date(),
                 self.nifty_full.index[-1].date())

        log.info("Loading sector index data...")
        for sector_name, sym in config.SECTOR_INDICES.items():
            try:
                df = self.provider.get_ohlcv(sym, period_days=1200)
                self.sector_full[sector_name] = df
                log.info("  %s: %d rows", sector_name, len(df))
            except Exception as exc:
                log.warning("  %s (%s) failed: %s", sector_name, sym, exc)

        log.info("Loading universe stock data...")
        from data.universe import UNIVERSE
        self.all_data = self.provider.get_all_ohlcv(UNIVERSE, period_days=1200)
        log.info("Loaded %d/%d symbols", len(self.all_data), len(UNIVERSE))

    # ------------------------------------------------------------------
    # Weekly scan
    # ------------------------------------------------------------------

    def _weekly_scan(self, scan_date: pd.Timestamp) -> tuple[list, dict]:
        """
        Run full pipeline as of scan_date.
        Returns (watchlist, regime) where watchlist is list of dicts.
        """
        nifty_as_of = get_data_as_of(self.nifty_full, scan_date)
        if len(nifty_as_of) < 210:
            return [], {"state": 3, "size_multiplier": 0.4, "max_positions": 4}

        regime = get_market_regime(nifty_as_of)
        if regime["state"] == 4:
            log.info("Cash regime on %s — skipping scan", scan_date.date())
            return [], regime

        # Sector RS55 map
        sector_clipped = {
            s: get_data_as_of(df, scan_date)
            for s, df in self.sector_full.items()
        }
        sector_rs55_map = _sector_rs55_backtest(sector_clipped, nifty_as_of)

        # Gate pass + RS55 computation
        eligible:  dict[str, pd.DataFrame] = {}
        rs55_map:  dict[str, dict] = {}

        for sym, full_df in self.all_data.items():
            df = get_data_as_of(full_df, scan_date)
            if len(df) < 210:
                continue
            passed, _ = apply_all_gates(sym, df, nifty_as_of, sector_rs55_map)
            if not passed:
                continue
            try:
                rs55_data = compute_rs55(df, nifty_as_of)
                eligible[sym] = df
                rs55_map[sym] = rs55_data
            except Exception:
                pass

        log.debug("%d stocks passed gates on %s", len(eligible), scan_date.date())
        if not eligible:
            return [], regime

        scored_df = score_universe(eligible, nifty_as_of, rs55_map)
        if scored_df.empty:
            return [], regime

        scored_df = scored_df[scored_df["grade"] != "EXCLUDE"].head(TOP_N_WATCHLIST)

        watchlist = []
        for _, row in scored_df.iterrows():
            watchlist.append({
                "symbol":    row["symbol"],
                "grade":     row["grade"],
                "score":     float(row["score"]),
                "sector":    row["sector"],
                "base_high": float(row["base_high"]),
                "base_low":  float(row["base_low"]),
            })

        log.info("Watchlist %s: %d stocks, regime=%s",
                 scan_date.date(), len(watchlist), regime["label"])
        return watchlist, regime

    # ------------------------------------------------------------------
    # Breakout detection
    # ------------------------------------------------------------------

    def _check_breakout(self, sym: str, meta: dict, sim_date: pd.Timestamp) -> Optional[dict]:
        if sym not in self.all_data:
            return None
        df = get_data_as_of(self.all_data[sym], sim_date)
        if len(df) < 30:
            return None
        try:
            base_data = base_quality_score(df)
            signal = _detect_type1_breakout(df, base_data)
            if signal is None:
                signal = _detect_type2_breakout(df, base_data)
            return signal
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Position / risk checks
    # ------------------------------------------------------------------

    def _can_open(self, regime: dict, sector: str) -> bool:
        if regime.get("size_multiplier", 0.0) == 0.0:
            return False
        if len(self.open_trades) >= regime.get("max_positions", 10):
            return False
        sector_value = sum(
            t.active_shares * t.entry_price
            for t in self.open_trades
            if t.sector == sector
        )
        if sector_value >= self.capital * config.MAX_SECTOR_PCT:
            return False
        total_open_risk = sum(
            t.active_shares * t.initial_risk
            for t in self.open_trades
        )
        if total_open_risk >= self.capital * config.MAX_TOTAL_OPEN_RISK:
            return False
        return True

    # ------------------------------------------------------------------
    # Trade entry
    # ------------------------------------------------------------------

    def _enter(
        self,
        sym: str,
        entry_price: float,
        signal: dict,
        meta: dict,
        entry_date: pd.Timestamp,
        regime: dict,
    ) -> Optional[Trade]:
        df = get_data_as_of(self.all_data[sym], entry_date)
        atr_val = _atr14(df)

        # SL: wider (lower) of base_low*0.99 and entry-1.5*ATR
        sl_base = meta["base_low"] * 0.99
        sl_atr  = (entry_price - 1.5 * atr_val) if atr_val > 0 else sl_base
        sl = min(sl_base, sl_atr)   # min = lower price = wider stop

        if sl >= entry_price:
            return None
        risk_pct = (entry_price - sl) / entry_price
        if risk_pct < config.MIN_BREAKOUT_RISK_PCT or risk_pct > config.MAX_BREAKOUT_RISK_PCT:
            return None

        sizing = compute_position_size(
            entry=entry_price, sl=sl,
            grade=meta["grade"], regime=regime,
            capital=self.capital,
        )
        shares = sizing["shares"]
        if shares <= 0:
            return None

        position_value = shares * entry_price
        entry_cost     = position_value * TRANSACTION_COST_PCT
        if position_value + entry_cost > self.cash:
            shares = int(self.cash / (entry_price * (1 + TRANSACTION_COST_PCT)))
            if shares <= 0:
                return None
            position_value = shares * entry_price
            entry_cost     = position_value * TRANSACTION_COST_PCT

        one_r   = entry_price - sl
        target1 = entry_price + config.PHASE2_REWARD_RATIO * one_r
        target2 = entry_price + 3.0 * one_r

        self.cash -= position_value + entry_cost

        trade = Trade(
            symbol=sym,
            entry_date=entry_date,
            entry_price=entry_price,
            sl_initial=sl,
            sl_current=sl,
            target1=target1,
            target2=target2,
            initial_shares=shares,
            active_shares=shares,
            entry_type=signal["entry_type"],
            grade=meta["grade"],
            score=meta["score"],
            sector=meta["sector"],
            regime_state=regime["state"],
            max_price=entry_price,
        )
        self.open_trades.append(trade)
        log.info("ENTER %s %s @ %.2f sl=%.2f shares=%d grade=%s",
                 sym, signal["entry_type"], entry_price, sl, shares, meta["grade"])
        return trade

    # ------------------------------------------------------------------
    # Trade close helpers
    # ------------------------------------------------------------------

    def _close_full(
        self,
        trade: Trade,
        exit_price: float,
        exit_date: pd.Timestamp,
        reason: str,
    ) -> None:
        shares = trade.active_shares
        gross   = (exit_price - trade.entry_price) * shares
        cost    = exit_price * shares * TRANSACTION_COST_PCT
        net     = gross - cost

        trade.gross_pnl  += gross
        trade.net_pnl    += net
        trade.exit_date   = exit_date
        trade.exit_price  = exit_price
        trade.exit_reason = reason
        trade.hold_sessions = trade.hold_sessions   # already tracked

        if trade.initial_risk > 0 and trade.initial_shares > 0:
            trade.r_multiple = trade.net_pnl / (trade.initial_risk * trade.initial_shares)

        self.cash += exit_price * shares - cost
        trade.active_shares = 0

        self.open_trades.remove(trade)
        self.closed_trades.append(trade)
        log.info("EXIT %s [%s] @ %.2f R=%.2f hold=%d sessions",
                 trade.symbol, reason, exit_price, trade.r_multiple, trade.hold_sessions)

    def _close_partial(
        self,
        trade: Trade,
        exit_price: float,
        shares: int,
    ) -> None:
        gross = (exit_price - trade.entry_price) * shares
        cost  = exit_price * shares * TRANSACTION_COST_PCT
        net   = gross - cost
        trade.gross_pnl  += gross
        trade.net_pnl    += net
        trade.active_shares -= shares
        self.cash += exit_price * shares - cost

    # ------------------------------------------------------------------
    # Daily trade update
    # ------------------------------------------------------------------

    def _update_trades(self, sim_date: pd.Timestamp) -> None:
        for trade in list(self.open_trades):
            sym = trade.symbol
            if sym not in self.all_data:
                continue

            df = get_data_as_of(self.all_data[sym], sim_date)
            if df.empty:
                continue

            # Only act if we have today's bar
            last_date = df.index[-1]
            if last_date != sim_date:
                continue

            bar   = df.iloc[-1]
            high  = float(bar["high"])
            low   = float(bar["low"])
            close = float(bar["close"])

            trade.hold_sessions += 1
            trade.max_price = max(trade.max_price, high)

            # Phase 2: book partial at 1.5R, move SL to entry
            if trade.phase == 1 and high >= trade.target1 and not trade.phase2_done:
                book = max(1, int(trade.active_shares * config.PHASE2_BOOK_PCT))
                self._close_partial(trade, trade.target1, book)
                trade.sl_current = trade.entry_price
                trade.phase      = 2
                trade.phase2_done = True
                log.debug("PHASE2 %s: booked %d @ %.2f, SL→entry", sym, book, trade.target1)

            # Phase 3: trailing stop activated at 2R (target2 = entry + 3R, but activate at 2R)
            if trade.phase == 2 and high >= trade.entry_price + 2 * trade.initial_risk:
                trade.phase = 3

            # Phase 3: update trailing stop
            if trade.phase == 3 and len(df) >= 21:
                ema21      = float(_ema(df["close"], 21).iloc[-1])
                two_wk_low = float(df["low"].tail(10).min())
                new_trail  = max(ema21, two_wk_low)
                if new_trail > trade.sl_current:
                    trade.sl_current = new_trail

            # SL hit check (use low of day)
            if low <= trade.sl_current:
                exit_px = min(trade.sl_current, low)  # assume filled at SL or worse
                self._close_full(trade, exit_px, sim_date, "SL")
                continue

            # Time exits
            if trade.hold_sessions >= SWING_TIME_EXIT and trade.phase == 1:
                if trade.max_price < trade.entry_price + trade.initial_risk:
                    self._close_full(trade, close, sim_date, "TimeExit_10")
                    continue

            if trade.hold_sessions == POSITIONAL_TIME_EXIT and trade.phase < 2:
                if trade.max_price < trade.target1:
                    half = max(1, trade.active_shares // 2)
                    self._close_partial(trade, close, half)
                    log.debug("TIME_30d partial %s: exited %d shares", sym, half)

    # ------------------------------------------------------------------
    # Portfolio mark-to-market
    # ------------------------------------------------------------------

    def _portfolio_value(self, sim_date: pd.Timestamp) -> float:
        mtm = 0.0
        for trade in self.open_trades:
            sym = trade.symbol
            if sym not in self.all_data:
                continue
            df = get_data_as_of(self.all_data[sym], sim_date)
            if not df.empty:
                mtm += trade.active_shares * float(df["close"].iloc[-1])
        return self.cash + mtm

    # ------------------------------------------------------------------
    # Main simulation loop
    # ------------------------------------------------------------------

    def simulate(self) -> None:
        trading_days = _trading_days_in_range(self.nifty_full, self.sim_start, self.sim_end)
        log.info("Simulation: %d trading days %s → %s",
                 len(trading_days), self.sim_start.date(), self.sim_end.date())

        # Pre-compute weekly scans (slow — runs gates+scoring per week)
        week_pairs = _week_scan_dates(trading_days)
        week_data: dict[pd.Timestamp, tuple] = {}
        log.info("Running %d weekly scans...", len(week_pairs))
        for scan_date, week_first in week_pairs:
            wl, regime = self._weekly_scan(scan_date)
            week_data[week_first] = (wl, regime)
        log.info("Weekly scans complete.")

        current_watchlist: list[dict] = []
        current_regime: dict = {"state": 3, "size_multiplier": 0.4, "max_positions": 4}
        pending: dict[str, dict] = {}   # symbol → {signal, meta, date}

        for sim_date in trading_days:
            # Load new watchlist if new week starts
            if sim_date in week_data:
                current_watchlist, current_regime = week_data[sim_date]

            # 1. Update open trades (SL, phases, time exits)
            self._update_trades(sim_date)

            # 2. Confirm pending breakouts: enter at today's open
            to_confirm = list(pending.items())
            for sym, pend in to_confirm:
                if sym not in self.all_data:
                    del pending[sym]
                    continue
                df = get_data_as_of(self.all_data[sym], sim_date)
                if df.empty or df.index[-1] != sim_date:
                    del pending[sym]
                    continue
                entry_price = float(df["open"].iloc[-1])
                already_open = any(t.symbol == sym for t in self.open_trades)
                if not already_open and self._can_open(current_regime, pend["meta"]["sector"]):
                    self._enter(sym, entry_price, pend["signal"], pend["meta"],
                                sim_date, current_regime)
                del pending[sym]

            # 3. Check watchlist for new breakout signals (mark PENDING)
            for item in current_watchlist:
                sym = item["symbol"]
                if sym in pending:
                    continue
                if any(t.symbol == sym for t in self.open_trades):
                    continue
                signal = self._check_breakout(sym, item, sim_date)
                if signal is not None:
                    pending[sym] = {"signal": signal, "meta": item, "date": sim_date}
                    log.debug("PENDING %s %s on %s", sym, signal["entry_type"], sim_date.date())

            # 4. Record equity
            nifty_close = float(get_data_as_of(self.nifty_full, sim_date)["close"].iloc[-1])
            self.equity_curve.append({
                "date":            sim_date.date().isoformat(),
                "portfolio_value": round(self._portfolio_value(sim_date), 2),
                "nifty_close":     round(nifty_close, 2),
            })

        # Close all remaining open trades at end of simulation
        if trading_days:
            final = trading_days[-1]
            for trade in list(self.open_trades):
                sym = trade.symbol
                if sym in self.all_data:
                    df = get_data_as_of(self.all_data[sym], final)
                    if not df.empty:
                        self._close_full(trade, float(df["close"].iloc[-1]), final, "SimEnd")

        log.info("Simulation complete: %d closed trades", len(self.closed_trades))

    # ------------------------------------------------------------------
    # Output generation
    # ------------------------------------------------------------------

    def _compute_summary(self) -> dict:
        trades = self.closed_trades
        if not trades:
            return {"error": "no_trades", "total_trades": 0}

        r_multiples = [t.r_multiple for t in trades]
        winners     = [r for r in r_multiples if r > 0]
        losers      = [r for r in r_multiples if r <= 0]
        win_rate    = len(winners) / len(trades)
        avg_r       = sum(r_multiples) / len(r_multiples)

        # Max drawdown from equity curve
        max_dd = 0.0
        peak   = 0.0
        for e in self.equity_curve:
            v    = e["portfolio_value"]
            peak = max(peak, v)
            dd   = (peak - v) / peak if peak > 0 else 0.0
            max_dd = max(max_dd, dd)

        gross_wins  = sum(winners)
        gross_loss  = abs(sum(losers))
        profit_factor = (gross_wins / gross_loss) if gross_loss > 0 else float("inf")

        # Daily Sharpe
        if len(self.equity_curve) > 1:
            vals = [e["portfolio_value"] for e in self.equity_curve]
            rets = [(vals[i] - vals[i-1]) / vals[i-1] for i in range(1, len(vals))]
            mu   = sum(rets) / len(rets)
            var  = sum((r - mu) ** 2 for r in rets) / len(rets)
            std  = var ** 0.5
            sharpe = (mu / std * (252 ** 0.5)) if std > 0 else 0.0
        else:
            sharpe = 0.0

        # Max consecutive losses
        max_consec = cur = 0
        for r in r_multiples:
            if r <= 0:
                cur += 1
                max_consec = max(max_consec, cur)
            else:
                cur = 0

        # Annual return vs Nifty
        final_val   = self.equity_curve[-1]["portfolio_value"] if self.equity_curve else self.capital
        total_ret   = (final_val - self.capital) / self.capital
        years       = (self.sim_end - self.sim_start).days / 365.25
        annual_ret  = (1 + total_ret) ** (1 / years) - 1 if years > 0 else 0.0
        nifty_start = self.equity_curve[0]["nifty_close"]  if self.equity_curve else 1
        nifty_end   = self.equity_curve[-1]["nifty_close"] if self.equity_curve else 1
        nifty_ret   = (nifty_end - nifty_start) / nifty_start if nifty_start else 0.0
        nifty_ann   = (1 + nifty_ret) ** (1 / years) - 1 if years > 0 else 0.0

        by_regime, by_grade, exit_reasons = {}, {}, {}
        for t in trades:
            k = str(t.regime_state)
            by_regime[k]      = by_regime.get(k, 0) + 1
            by_grade[t.grade] = by_grade.get(t.grade, 0) + 1
            r = t.exit_reason or "unknown"
            exit_reasons[r]   = exit_reasons.get(r, 0) + 1

        avg_hold = (
            sum((t.exit_date - t.entry_date).days for t in trades if t.exit_date)
            / len(trades)
        )

        return {
            "total_trades":            len(trades),
            "win_rate":                round(win_rate, 4),
            "avg_r_multiple":          round(avg_r, 4),
            "max_drawdown_pct":        round(max_dd * 100, 2),
            "profit_factor":           round(profit_factor, 4) if profit_factor != float("inf") else "inf",
            "sharpe_ratio":            round(sharpe, 4),
            "max_consecutive_losses":  max_consec,
            "annual_return_pct":       round(annual_ret * 100, 2),
            "nifty_return_pct":        round(nifty_ret * 100, 2),
            "alpha_pct":               round((annual_ret - nifty_ann) * 100, 2),
            "final_portfolio_value":   round(final_val, 2),
            "trades_by_regime":        by_regime,
            "trades_by_grade":         by_grade,
            "exit_reason_breakdown":   exit_reasons,
            "avg_hold_days":           round(avg_hold, 1),
        }

    def save_outputs(self) -> None:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

        # trades.csv
        rows = []
        for t in self.closed_trades:
            rows.append({
                "symbol":         t.symbol,
                "entry_date":     t.entry_date.date().isoformat(),
                "exit_date":      t.exit_date.date().isoformat() if t.exit_date else "",
                "entry_type":     t.entry_type,
                "grade":          t.grade,
                "score":          round(t.score, 1),
                "sector":         t.sector,
                "regime_state":   t.regime_state,
                "entry_price":    round(t.entry_price, 2),
                "exit_price":     round(t.exit_price, 2) if t.exit_price else "",
                "sl_initial":     round(t.sl_initial, 2),
                "initial_shares": t.initial_shares,
                "hold_sessions":  t.hold_sessions,
                "hold_days":      (t.exit_date - t.entry_date).days if t.exit_date else 0,
                "exit_reason":    t.exit_reason or "",
                "gross_pnl":      round(t.gross_pnl, 2),
                "net_pnl":        round(t.net_pnl, 2),
                "r_multiple":     round(t.r_multiple, 4),
            })
        pd.DataFrame(rows).to_csv(OUTPUT_DIR / "trades.csv", index=False)
        log.info("Saved %s", OUTPUT_DIR / "trades.csv")

        # summary.json
        summary = self._compute_summary()
        with open(OUTPUT_DIR / "summary.json", "w") as f:
            json.dump(summary, f, indent=2)
        log.info("Saved %s", OUTPUT_DIR / "summary.json")

        # equity_curve.csv
        eq_df = pd.DataFrame(self.equity_curve)
        if not eq_df.empty:
            start_nifty = eq_df["nifty_close"].iloc[0]
            eq_df["nifty_value"] = eq_df["nifty_close"] / start_nifty * self.capital
            eq_df[["date", "portfolio_value", "nifty_value"]].to_csv(
                OUTPUT_DIR / "equity_curve.csv", index=False
            )
        log.info("Saved %s", OUTPUT_DIR / "equity_curve.csv")

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def run(self) -> None:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        )
        log.info("=== NSE Momentum Backtest ===")
        log.info("Period: %s → %s", self.sim_start.date(), self.sim_end.date())
        self._load_data()
        self.simulate()
        self.save_outputs()

        summary = self._compute_summary()
        print("\n=== Backtest Summary ===")
        for k, v in summary.items():
            if isinstance(v, dict):
                print(f"  {k}:")
                for kk, vv in v.items():
                    print(f"    {kk}: {vv}")
            else:
                print(f"  {k}: {v}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="NSE Momentum Backtest Engine")
    parser.add_argument("--start", default=DEFAULT_SIM_START, help="Sim start YYYY-MM-DD")
    parser.add_argument("--end",   default=DEFAULT_SIM_END,   help="Sim end YYYY-MM-DD")
    args = parser.parse_args()

    BacktestEngine(sim_start=args.start, sim_end=args.end).run()
