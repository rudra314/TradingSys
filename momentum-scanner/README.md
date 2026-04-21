# NSE Momentum Scanner

Institutional-grade momentum scanner for the Indian NSE market.

**Features:** RS55 (Vivek Bajaj model) · Pivot-based breakout detection · 4-state regime filter · 3-phase exit engine · Telegram alerts · Yahoo Finance (free) → Zerodha swap-ready

---

## Quick Start

### 1. Install dependencies

```bash
cd momentum-scanner
pip install -r requirements.txt
```

### 2. Set up Telegram alerts (3 minutes)

**Step 1 — Create your bot:**
1. Open Telegram and search for **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g. "My NSE Scanner") and a username (e.g. `my_nse_scanner_bot`)
4. BotFather will give you a token like: `123456789:ABCdefGhIjKlMnOpQrStUvWxYz`

**Step 2 — Get your Chat ID:**
1. Search for **@userinfobot** on Telegram
2. Start it — it replies with your numeric user ID (e.g. `987654321`)

**Step 3 — Create your .env file:**
```bash
cp .env.example .env
# Edit .env and fill in TELEGRAM_TOKEN and CHAT_ID
```

### 3. Verify the installation

```bash
python test_scan.py --live      # Requires internet — verifies RS55 against real data
python test_scan.py --mock      # Works offline — verifies all engine logic
```

### 4. Run the scanner

```bash
python main.py
```

The scheduler will run automatically:
- **Sunday 6:00 PM IST** — full universe scan (~500 stocks), generates weekly watchlist
- **Mon–Fri 9:30 AM IST** — breakout detection on watchlist stocks
- **Mon–Fri 3:00 PM IST** — exit/trailing-SL checks on open positions

---

## How to Read the Watchlist

**`data/watchlist.csv` columns explained:**

| Column | Meaning |
|--------|---------|
| `grade` | A/B/C/EXCLUDE — A is highest conviction |
| `score` | Total score out of 100 |
| `rs55_pct` | RS55 value in % — stock's 55-day return vs Nifty 50 |
| `rs55_just_turned` | True = RS55 just crossed above zero (early signal) |
| `rs55_at_new_high` | True = RS55 at highest level in 55 days |
| `mom_percentile` | Cross-sectional momentum rank (100 = top performer) |
| `base_range_pct` | How tight the base is (< 6% = tight, ideal for entry) |
| `base_low` | Structural stop-loss anchor |

**Grades:**
- **Grade A (≥78 pts):** Full position, all setups
- **Grade B (≥58 pts):** Reduced position (75%), confirmed breakouts only
- **Grade C (≥40 pts):** Half position, high conviction entries only

---

## How to Verify RS55 Values

RS55 is Vivek Bajaj's Relative Strength model — it measures a stock's 55-session performance relative to Nifty 50.

**Cross-checking on StockEdge:**
1. Open StockEdge → Search any stock
2. Go to "Technical" tab → "Relative Strength"
3. Look for RS(55) — should match our output within ±1%

**Cross-checking on TradingView:**
1. Open any NSE chart on TradingView
2. Add indicator: search "RS55" or "Relative Strength 55"
3. Compare the RS value — should match within ±1%

**Formula used (exactly):**
```
RS55 = (stock_close_today / stock_close_55d_ago) / (nifty_close_today / nifty_close_55d_ago) - 1
```

---

## Market Regime States

The scanner automatically adjusts position sizing based on Nifty 50 structure:

| State | Label | Condition | Size | Max Positions |
|-------|-------|-----------|------|---------------|
| 1 | Full Momentum | Price > EMA200 > EMA50 rising, VIX < 16 | 100% | 10 |
| 2 | Selective | Above EMA200 but EMA50 flat, or VIX 16–20 | 75% | 7 |
| 3 | Defensive | Between EMAs, or EMA50 < EMA200, or VIX 20–26 | 40% | 4 |
| 4 | Cash | Below EMA200 and EMA50 < EMA200, or VIX > 26 | 0% | 0 |

---

## Position Sizing

Position size is computed per trade using:
```
Risk per trade = Capital × 1.5% × Regime multiplier × Grade multiplier
Shares = Risk per trade / (Entry price − Stop loss)
```

Caps applied: max 15% of capital per stock, max sector concentration 30%.

---

## Three-Phase Exit System

**Phase 1 (capital protection):** Stop loss at structural base low, enforced immediately.

**Phase 2 (lock profits at 1.5R):** Book 30% of position. Move SL to breakeven. Trade becomes risk-free.

**Phase 3 (trail the winner):** Trail SL using EMA21 or 2-week low, whichever is higher. Ratchet only upward. Exit remaining position when price crosses trailing SL.

**Early warning signals** (reduce before SL is hit):
- RS55 turns negative → reduce 50%
- Volume exhaustion at new high → tighten SL
- Key reversal candle (high volume distribution) → exit 50%

---

## Switching to Zerodha (3 steps)

When ready to go live with real NSE data:

1. **Implement `data/zerodha_provider.py`** — fill in the 5 methods using `kite.historical_data()`. A template with clear instructions is already in the file.

2. **Add credentials to `.env`:**
   ```
   KITE_API_KEY=your_api_key
   KITE_API_SECRET=your_api_secret
   ```

3. **Change one line in `config.py`:**
   ```python
   DATA_PROVIDER = "zerodha"   # was "yahoo"
   ```

No other file changes needed. The swap is isolated to these three steps.

---

## Paper Trading Guide

**Before going live, paper trade for at least 8–12 weeks:**

| Week | What to track |
|------|--------------|
| 1–2 | Do breakout alerts fire at the right time? Cross-check 3 alerts manually on charts |
| 3–4 | Are RS55 values matching StockEdge? (should be within 1%) |
| 5–6 | Does regime state match your read of the market? |
| 7–8 | Track paper P&L: how many Grade A setups hit Phase 2 (1.5R)? |
| 9–12 | Simulate full position sizing — would your simulated capital have stayed within limits? |

**Green light checklist before deploying real capital:**
- [ ] At least 15 alerts fired and manually verified on charts
- [ ] At least 2 full exit cycles completed (entry → Phase 2 → Phase 3)
- [ ] RS55 values verified against StockEdge on 5+ stocks
- [ ] Regime state has matched your manual read at least 90% of the time
- [ ] Telegram delivery is reliable (no missed alerts)

---

## Folder Structure

```
momentum-scanner/
├── config.py              — all settings (one place)
├── main.py                — scheduler
├── test_scan.py           — verification script
├── requirements.txt
├── .env.example           — copy to .env and fill credentials
│
├── data/
│   ├── data_provider.py   — abstract interface
│   ├── yahoo_provider.py  — default (free, for testing)
│   ├── zerodha_provider.py — fill in to go live
│   ├── universe.py        — ~500 NSE symbols + sector map
│   └── cache/             — OHLCV parquet cache (auto-managed)
│
├── engine/
│   ├── gates.py           — 5 binary disqualifiers
│   ├── rs55_engine.py     — Vivek Bajaj RS55 model
│   ├── scorer.py          — 100-point cross-sectional scorer
│   ├── base_analyzer.py   — VCP/base quality scoring
│   ├── breakout.py        — pivot detection + state machine
│   ├── regime.py          — 4-state market classifier
│   ├── exit_engine.py     — 3-phase exit monitoring
│   ├── sizer.py           — position sizing
│   └── indicators.py      — pure pandas EMA/RSI/ATR (no ta dependency)
│
├── notify/
│   ├── notifier.py        — Telegram alert sender
│   └── results_calendar.py — NSE results blackout checker
│
└── logs/
    ├── scanner.log        — operational log
    └── signals.log        — all alerts fired (trade journal)
```

---

## Troubleshooting

**"No eligible stocks" after scan:**
The market may be in State 3/4. Check `logs/scanner.log` for gate failure reasons.

**Telegram alerts not arriving:**
1. Confirm `TELEGRAM_TOKEN` and `CHAT_ID` in `.env` are correct
2. Send a test: `python -c "from notify.notifier import send_telegram; send_telegram('test')"`
3. Check `logs/scanner.log` for Telegram errors

**Yahoo Finance rate limits (HTTP 429):**
The provider sleeps 0.5s between calls and caches same-day data as parquet. Re-running on the same day uses cache (instant). If you still hit limits, increase the sleep in `yahoo_provider.py`.

**RS55 values don't match StockEdge:**
Ensure the data has 60+ trading days. RS55 requires 55 aligned sessions between stock and Nifty. Check `logs/scanner.log` for "insufficient history" warnings.
