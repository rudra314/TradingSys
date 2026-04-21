"""
notifier.py — Telegram alert sender.
Reads TELEGRAM_TOKEN and CHAT_ID from .env via python-dotenv.
Retries 3x with 5s sleep. Logs to logs/signals.log on each alert.
Never crashes the scan on Telegram failure.
"""
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent.parent))
import config

load_dotenv()
log = logging.getLogger(__name__)

_SIGNALS_LOG = Path(__file__).parent.parent / "logs" / "signals.log"


def _get_credentials() -> tuple[str, str]:
    """Return (token, chat_id) from env. Raises ValueError if missing."""
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat_id = os.environ.get("CHAT_ID", "").strip()
    if not token:
        raise ValueError("TELEGRAM_TOKEN not set in environment / .env file")
    if not chat_id:
        raise ValueError("CHAT_ID not set in environment / .env file")
    return token, chat_id


def send_telegram(message: str) -> bool:
    """
    Send plain text message to Telegram. Retry 3x with 5s sleep.
    Returns True on success, False on all failures. Never raises.
    """
    try:
        token, chat_id = _get_credentials()
    except ValueError as exc:
        log.warning("Telegram credentials missing: %s", exc)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    for attempt in range(1, 4):
        try:
            resp = requests.post(url, data=payload, timeout=10)
            if resp.status_code == 200 and resp.json().get("ok"):
                log.debug("Telegram message sent successfully (attempt %d)", attempt)
                return True
            else:
                log.warning(
                    "Telegram API error (attempt %d/%d): status=%d body=%s",
                    attempt, 3, resp.status_code, resp.text[:200],
                )
        except requests.RequestException as exc:
            log.warning("Telegram request failed (attempt %d/3): %s", attempt, exc)

        if attempt < 3:
            time.sleep(5)

    log.error("All 3 Telegram send attempts failed for message: %s", message[:80])
    return False


def _log_signal(
    alert_type: str,
    symbol: str,
    entry: float,
    sl: float,
    target1: float,
    grade: str,
    score: int,
    rs55_pct: float,
) -> None:
    """Append one line to logs/signals.log in standardized format."""
    _SIGNALS_LOG.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = (
        f"{timestamp} | {alert_type} | {symbol} | {entry:.2f} | {sl:.2f} | "
        f"{target1:.2f} | {grade} | {score} | {rs55_pct:.2f}\n"
    )
    try:
        with open(_SIGNALS_LOG, "a") as f:
            f.write(line)
    except Exception as exc:
        log.warning("Could not write to signals.log: %s", exc)


def send_breakout_alert(
    symbol: str,
    entry_type: str,
    grade: str,
    score: int,
    regime: dict,
    entry: float,
    sl: float,
    target1: float,
    target2: float,
    shares: int,
    position_value: float,
    risk_amount: float,
    rs55_data: dict,
    mom_percentile: float,
    base_score: int,
    base_range_pct: float,
    base_length: int,
    vol_trend_slope: float,
    rsi: float,
    sector: str,
    fno_expiry_week: bool = False,
    results_days: int = None,
) -> None:
    """
    Format and send breakout alert.

    Format:
    [BREAKOUT | TYPE_1] SYMBOL
    Grade: A | Score: 84/100 | Regime: State 1 — Full momentum

    Entry: Rs X | SL: Rs Y | Risk: Z%
    Target 1: Rs X  (1:2R — book 30%)
    Target 2: Rs X  (1:3R — trail rest)
    Shares @ 1.5% risk on Rs 10L: N shares
    Position value: Rs X

    RS55: +6.2% | Rising N days
    Momentum: top X% of universe
    Base: N days | Range: X% (tight/moderate/wide) | Vol trend: expanding/flat/shrinking
    RSI: X (rising/flat) | Sector: NAME (RS55 positive/negative)
    """
    risk_pct = ((entry - sl) / entry * 100) if entry > 0 else 0.0
    rs55_pct = rs55_data.get("rs55_pct", 0.0)
    rs55_rising_days = rs55_data.get("rs55_rising_days", 0)

    # Tightness label
    if base_range_pct < 0.06:
        tightness = "tight"
    elif base_range_pct < 0.12:
        tightness = "moderate"
    else:
        tightness = "wide"

    # Volume trend label
    if vol_trend_slope > 0.01:
        vol_label = "expanding"
    elif vol_trend_slope < -0.01:
        vol_label = "shrinking"
    else:
        vol_label = "flat"

    # RSI trend label (use a simple heuristic — if rsi > 55 assume rising, else flat)
    rsi_label = "rising" if rsi >= 55 else "flat"

    # Sector RS55 label
    sector_rs_label = "RS55 positive" if rs55_pct > 0 else "RS55 negative"

    # 1R, 2R, 3R
    one_r = entry - sl
    r2_ratio = (target1 - entry) / one_r if one_r > 0 else 0
    r3_ratio = (target2 - entry) / one_r if one_r > 0 else 0

    # Momentum percentile text (mom_percentile is 0-1 where 0=top)
    top_pct = (1 - mom_percentile) * 100

    lines = [
        f"<b>[BREAKOUT | {entry_type}] {symbol}</b>",
        f"Grade: {grade} | Score: {score}/100 | Regime: State {regime.get('state', '?')} — {regime.get('label', '')}",
        "",
        f"Entry: Rs {entry:.2f} | SL: Rs {sl:.2f} | Risk: {risk_pct:.1f}%",
        f"Target 1: Rs {target1:.2f}  (1:{r2_ratio:.1f}R — book 30%)",
        f"Target 2: Rs {target2:.2f}  (1:{r3_ratio:.1f}R — trail rest)",
        f"Shares @ {config.BASE_RISK_PCT*100:.1f}% risk on Rs {config.CAPITAL/100_000:.0f}L: {shares} shares",
        f"Position value: Rs {position_value:,.0f}",
        "",
        f"RS55: {rs55_pct:+.2f}% | Rising {rs55_rising_days} days",
        f"Momentum: top {top_pct:.0f}% of universe",
        f"Base: {base_length} days | Range: {base_range_pct*100:.1f}% ({tightness}) | Vol trend: {vol_label}",
        f"RSI: {rsi:.1f} ({rsi_label}) | Sector: {sector} ({sector_rs_label})",
    ]

    # Conditional flags
    if fno_expiry_week:
        lines.append("")
        lines.append("⚠ F&amp;O expiry week — size 50%")
    if results_days is not None and results_days > 0:
        lines.append(f"⚠ Results in {results_days} trading days — monitor closely")

    message = "\n".join(lines)
    send_telegram(message)
    _log_signal("BREAKOUT", symbol, entry, sl, target1, grade, score, rs55_pct)


def send_exit_alert(
    symbol: str, alert_type: str, message: str, position: dict
) -> None:
    """Format and send exit/warning alert. Log to signals.log."""
    entry = float(position.get("entry", 0))
    sl = float(position.get("sl", 0))
    grade = str(position.get("grade", "?"))
    score = int(position.get("score", 0))
    rs55_pct = float(position.get("rs55_pct", 0.0))

    text = (
        f"<b>[{alert_type}] {symbol}</b>\n"
        f"{message}\n"
        f"Entry: Rs {entry:.2f} | SL: Rs {sl:.2f} | Grade: {grade}"
    )
    send_telegram(text)
    _log_signal(alert_type, symbol, entry, sl, 0.0, grade, score, rs55_pct)


def send_weekly_summary(
    top_stocks: list[dict],
    regime: dict,
    total_scanned: int,
    total_eligible: int,
    blackout_count: int = 0,
) -> None:
    """
    Format and send weekly watchlist summary.

    Format:
    WEEKLY WATCHLIST — {date}
    Market Regime: State N — LABEL | Size: X%

    Scanned: X | Passed gates: Y | Top setups: Z
    Top 10 Momentum Stocks: (numbered list with grade, score, RS55, base summary)
    """
    today_str = datetime.now().strftime("%d %b %Y")
    size_pct = int(regime.get("size_multiplier", 1.0) * 100)
    state = regime.get("state", "?")
    label = regime.get("label", "")

    lines = [
        f"<b>WEEKLY WATCHLIST — {today_str}</b>",
        f"Market Regime: State {state} — {label} | Size: {size_pct}%",
        "",
        f"Scanned: {total_scanned} | Passed gates: {total_eligible} | Top setups: {len(top_stocks)}",
    ]

    if blackout_count > 0:
        lines.append(f"Skipped (results blackout): {blackout_count}")

    top10 = top_stocks[:10]
    if top10:
        lines.append("")
        lines.append("<b>Top 10 Momentum Stocks:</b>")
        for i, stock in enumerate(top10, 1):
            sym = stock.get("symbol", "?")
            grade = stock.get("grade", "?")
            sc = stock.get("score", 0)
            rs55_pct = stock.get("rs55_pct", 0.0)
            base_len = stock.get("base_length", stock.get("base_score", 0))
            base_range = stock.get("base_range_pct", 0.0)
            tightness = "tight" if base_range < 0.06 else "moderate" if base_range < 0.12 else "wide"
            rs55_dir = "rising" if not stock.get("rs55_declining", False) else "declining"
            lines.append(
                f"{i}. <b>{sym}</b>  Grade: {grade}  Score: {sc:.0f}/100  "
                f"RS55: {rs55_pct:+.2f}% ({rs55_dir})  "
                f"Base: {base_len}d ({tightness})"
            )
    else:
        lines.append("\nNo stocks passed gates this week.")

    send_telegram("\n".join(lines))


def send_regime_alert(regime: dict) -> None:
    """Send CASH MODE ACTIVE alert when regime state == 4."""
    state = regime.get("state", 4)
    label = regime.get("label", "")
    message = (
        f"<b>[CASH MODE ACTIVE]</b>\n"
        f"Market Regime: State {state} — {label}\n\n"
        f"No new positions. Hold cash until regime improves.\n"
        f"Monitor existing positions with tight stops."
    )
    send_telegram(message)
