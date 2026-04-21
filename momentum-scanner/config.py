# config.py — single source of truth. No hardcoded values anywhere else.

DATA_PROVIDER = "yahoo"       # Change to "zerodha" when ready to go live

CAPITAL = 1_000_000           # Rs 10,00,000

BASE_RISK_PCT = 0.015         # 1.5% of capital risked per trade

# Position limits
MAX_SINGLE_STOCK_PCT = 0.15   # 15% of capital max per stock
MAX_SECTOR_PCT = 0.30         # 30% of capital max per sector
MAX_SMALLCAP_PCT = 0.20       # 20% of capital in Nifty Smallcap250
MAX_TOTAL_OPEN_RISK = 0.10    # 10% of capital total open risk at any time

# Gate thresholds
MIN_MEDIAN_TURNOVER = 10_000_000   # Rs 1 Crore median daily turnover
MIN_RS55 = 0.0                     # RS55 must be > 0 (stock outperforming Nifty)
RESULTS_BLACKOUT_DAYS = 10         # Skip stocks with results in next N trading days

# Scoring thresholds
GRADE_A_MIN = 78
GRADE_B_MIN = 58
GRADE_C_MIN = 40

# Breakout detection
MIN_BREAKOUT_RISK_PCT = 0.02  # SL must be at least 2% from entry (slippage buffer)
MAX_BREAKOUT_RISK_PCT = 0.07  # SL must be within 7% of entry (max acceptable risk)
BREAKOUT_VOLUME_MULT = 1.5    # Volume must be 1.5x 20-day average on breakout day

# Exit engine
PHASE2_REWARD_RATIO = 1.5     # Lock profits at 1.5R (book 30%, move SL to breakeven)
PHASE2_BOOK_PCT = 0.30        # Book 30% of position at Phase 2 trigger

# Scheduler times (IST)
WEEKLY_SCAN_DAY = "sunday"
WEEKLY_SCAN_TIME = "18:00"
MORNING_CHECK_TIME = "09:30"
AFTERNOON_CHECK_TIME = "15:00"

# NSE sector index symbols (Yahoo Finance)
SECTOR_INDICES = {
    "Banking":  "^NSEBANK",
    "IT":       "^CNXIT",
    "Auto":     "^CNXAUTO",
    "Pharma":   "^CNXPHARMA",
    "FMCG":     "^CNXFMCG",
    "Metals":   "^CNXMETAL",
    "Energy":   "^CNXENERGY",
    "Infra":    "^CNXINFRA",
    "Realty":   "^CNXREALTY",
}
