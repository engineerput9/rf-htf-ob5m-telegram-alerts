"""Live RF+HTF+OB5m scanner — Yahoo 5m F&O, Telegram on NEW CondIni flips.

Signal rule (no lookahead):
  NEW RF CondIni flip on the latest *completed* 5m bar that also passes:
    LONG  if HTF CondIni == +1 AND close inside active bull OB
    SHORT if HTF CondIni == -1 AND close inside active bear OB
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import yfinance as yf

from . import ob as obmod
from . import rf as rfmod
from . import telegram_notify as tg

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYMBOLS = ROOT / "symbols_fno.txt"
DEFAULT_STATE = ROOT / "state" / "last_signals.json"
IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc

# Yahoo rate-limit / resilience
FETCH_SLEEP_S = 0.35
FETCH_TIMEOUT_RETRIES = 2
YF_PERIOD = "60d"
YF_INTERVAL = "5m"
MIN_BARS = rfmod.RF_PERIOD + 50


def load_symbols(path: Path) -> list[str]:
    syms: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        syms.append(line)
    return syms


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"signals": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if "signals" not in data:
            data = {"signals": data if isinstance(data, dict) else {}}
        return data
    except Exception:
        return {"signals": {}}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def fetch_5m(symbol: str) -> Optional[pd.DataFrame]:
    last_err = None
    for attempt in range(FETCH_TIMEOUT_RETRIES + 1):
        try:
            t = yf.Ticker(symbol)
            df = t.history(period=YF_PERIOD, interval=YF_INTERVAL, auto_adjust=True)
            if df is None or df.empty:
                return None
            df = df.rename(
                columns={
                    "Open": "open",
                    "High": "high",
                    "Low": "low",
                    "Close": "close",
                    "Volume": "volume",
                }
            )
            df = df[["open", "high", "low", "close", "volume"]].copy()
            if df.index.tz is None:
                df.index = df.index.tz_localize(rfmod.TZ)
            else:
                df.index = df.index.tz_convert(rfmod.TZ)
            df = df[~df.index.duplicated(keep="last")].sort_index()
            return rfmod.filter_session(df)
        except Exception as e:
            last_err = e
            time.sleep(1.0 * (attempt + 1))
    print(f"[fetch] {symbol} failed: {last_err}")
    return None


def drop_incomplete_bar(df: pd.DataFrame, now_ist: Optional[datetime] = None) -> pd.DataFrame:
    """Exclude the forming 5m bar so we only evaluate completed bars (no lookahead)."""
    if df.empty:
        return df
    now = now_ist or datetime.now(IST)
    last_ts = df.index[-1]
    # Bar labeled T covers [T, T+5m). Completed when now >= T+5m.
    bar_end = last_ts + pd.Timedelta(minutes=5)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    else:
        now = now.astimezone(IST)
    if now < bar_end.to_pydatetime():
        return df.iloc[:-1].copy()
    return df


def analyze_symbol(symbol: str, df: pd.DataFrame) -> Optional[dict]:
    """Return a signal dict if the latest completed bar has a NEW RF flip + HTF+OB filter."""
    if df is None or len(df) < MIN_BARS:
        return None
    df = drop_incomplete_bar(df)
    if len(df) < MIN_BARS:
        return None

    data = rfmod.compute_range_filter(df)
    data = rfmod.add_risk_indicators(data)
    htf = rfmod.map_htf_bias(df)
    data["htf_bias"] = htf

    dets = obmod.detect_order_blocks(df)
    active = obmod.build_active_ob_state(df, dets)
    for col in active.columns:
        data[col] = active[col]

    i = len(data) - 1
    row = data.iloc[i]
    ts = data.index[i]

    long_sig = bool(row["long_signal"]) and int(row["htf_bias"]) == 1 and bool(row["inside_bull_ob"])
    short_sig = bool(row["short_signal"]) and int(row["htf_bias"]) == -1 and bool(row["inside_bear_ob"])
    if not long_sig and not short_sig:
        return None

    side = "long" if long_sig else "short"
    close = float(row["close"])
    atr_v = float(row["atr"])
    if np.isnan(atr_v) or atr_v <= 0:
        return None
    swing_low = float(row["prev_swing_low"]) if not np.isnan(row["prev_swing_low"]) else np.nan
    swing_high = float(row["prev_swing_high"]) if not np.isnan(row["prev_swing_high"]) else np.nan
    sl, tp, risk = rfmod.suggest_sl_tp(side, close, atr_v, swing_low, swing_high)
    if risk <= 0 or np.isnan(sl) or np.isnan(tp):
        return None

    bar_time_ist = ts.astimezone(IST).strftime("%Y-%m-%d %H:%M IST")
    key = f"{symbol}|{side}|{ts.isoformat()}"
    return {
        "key": key,
        "symbol": symbol,
        "side": side,
        "entry": round(close, 4),
        "sl": round(sl, 4),
        "tp": round(tp, 4),
        "risk": round(risk, 4),
        "atr": round(atr_v, 4),
        "htf_bias": int(row["htf_bias"]),
        "bar_time": ts.isoformat(),
        "bar_time_ist": bar_time_ist,
    }


def signal_key(sig: dict) -> str:
    return sig.get("key") or f"{sig['symbol']}|{sig['side']}|{sig['bar_time']}"


def scan(
    symbols: list[str],
    state: dict[str, Any],
    dry_run: bool = False,
) -> tuple[list[dict], dict[str, Any]]:
    known = state.setdefault("signals", {})
    new_signals: list[dict] = []
    scanned = 0
    failed = 0

    for sym in symbols:
        scanned += 1
        try:
            df = fetch_5m(sym)
            time.sleep(FETCH_SLEEP_S)
            if df is None or df.empty:
                failed += 1
                print(f"[skip] {sym}: no data")
                continue
            sig = analyze_symbol(sym, df)
            if sig is None:
                continue
            sk = signal_key(sig)
            if sk in known:
                print(f"[dup] {sk}")
                continue
            print(f"[NEW] {sk} entry={sig['entry']} sl={sig['sl']} tp={sig['tp']}")
            new_signals.append(sig)
            known[sk] = {
                "symbol": sig["symbol"],
                "side": sig["side"],
                "bar_time": sig["bar_time"],
                "entry": sig["entry"],
                "seen_at": datetime.now(UTC).isoformat(),
            }
        except Exception as e:
            failed += 1
            print(f"[error] {sym}: {e}")
            continue

    # Prune very old keys (keep last 500)
    if len(known) > 500:
        items = sorted(known.items(), key=lambda kv: kv[1].get("seen_at", ""), reverse=True)
        state["signals"] = dict(items[:500])

    state["last_run"] = datetime.now(UTC).isoformat()
    state["last_scanned"] = scanned
    state["last_failed"] = failed
    state["last_new"] = len(new_signals)

    if new_signals:
        sent = tg.send_signals(new_signals, dry_run=dry_run)
        print(f"[telegram] sent {sent}/{len(new_signals)}")
    else:
        print("[scan] no new signals")

    print(f"[scan] symbols={scanned} failed={failed} new={len(new_signals)}")
    return new_signals, state


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="RF+HTF+OB5m Telegram scanner")
    p.add_argument("--symbols", type=Path, default=DEFAULT_SYMBOLS)
    p.add_argument("--state", type=Path, default=DEFAULT_STATE)
    p.add_argument("--dry-run", action="store_true", help="Print messages; do not call Telegram")
    p.add_argument("--limit", type=int, default=0, help="Scan only first N symbols (debug)")
    args = p.parse_args(argv)

    symbols = load_symbols(args.symbols)
    if args.limit and args.limit > 0:
        symbols = symbols[: args.limit]
    if not symbols:
        print("No symbols loaded", file=sys.stderr)
        return 2

    state = load_state(args.state)
    _, state = scan(symbols, state, dry_run=args.dry_run)
    save_state(args.state, state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
