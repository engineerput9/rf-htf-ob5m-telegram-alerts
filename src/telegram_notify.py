"""Telegram Bot API helpers for signal alerts."""
from __future__ import annotations

import os
import time
from typing import Optional

import requests

TELEGRAM_API = "https://api.telegram.org"


def get_credentials() -> tuple[str, str]:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError(
            "Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID env vars / GitHub secrets."
        )
    return token, chat_id


def format_signal_message(sig: dict) -> str:
    """Build human-readable alert text.

    Expected keys: side, symbol, entry, sl, tp, bar_time_ist, risk
    """
    side = str(sig.get("side", "")).upper()
    emoji = "🟢 LONG" if side == "LONG" else "🔴 SHORT"
    symbol = sig.get("symbol", "?")
    entry = sig.get("entry")
    sl = sig.get("sl")
    tp = sig.get("tp")
    risk = sig.get("risk")
    bar_time = sig.get("bar_time_ist", "")

    def fmt(x) -> str:
        try:
            return f"{float(x):.2f}"
        except Exception:
            return str(x)

    lines = [
        f"{emoji} | {symbol}",
        f"Entry ~{fmt(entry)} | SL {fmt(sl)} | TP 0.6R {fmt(tp)}",
        f"RF+HTF+OB5m | 5m | {bar_time}",
    ]
    if risk is not None:
        try:
            lines.append(f"Risk/share ~{float(risk):.2f}")
        except Exception:
            pass
    lines.append("")
    lines.append(
        "⚠️ DISCLAIMER: Not live trading advice. Educational / discretionary "
        "alerts only. Past patterns do not guarantee future results. You alone "
        "are responsible for any trades."
    )
    return "\n".join(lines)


def send_message(
    text: str,
    token: Optional[str] = None,
    chat_id: Optional[str] = None,
    parse_mode: Optional[str] = None,
    dry_run: bool = False,
) -> bool:
    if dry_run:
        print("[telegram dry-run]\n" + text)
        return True
    if token is None or chat_id is None:
        token, chat_id = get_credentials()
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if parse_mode:
        payload["parse_mode"] = parse_mode
    try:
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code != 200:
            print(f"[telegram] HTTP {r.status_code}: {r.text[:300]}")
            return False
        return True
    except Exception as e:
        print(f"[telegram] send failed: {e}")
        return False


def send_signals(signals: list[dict], dry_run: bool = False, pause_s: float = 0.4) -> int:
    """Send each signal; return count successfully posted."""
    if not signals:
        return 0
    token = chat_id = None
    if not dry_run:
        token, chat_id = get_credentials()
    ok = 0
    for sig in signals:
        msg = format_signal_message(sig)
        if send_message(msg, token=token, chat_id=chat_id, dry_run=dry_run):
            ok += 1
        time.sleep(pause_s)
    return ok
