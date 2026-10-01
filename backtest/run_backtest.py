#!/usr/bin/env python3
"""RF+HTF+OB5m backtest (TP=0.6R) on Yahoo 5m F&O symbols.

Aligned with yahoo_backtest/ob5m_d_regen.py variant D:
  long  if RF CondIni flip long  AND HTF=+1 AND close inside active bull OB
  short if RF CondIni flip short AND HTF=-1 AND close inside active bear OB
SL = swing / ATR floor; TP = 0.6R. One trade per day. Force flat 15:15 IST.

Usage (from repo root):
  python -m backtest.run_backtest
  python -m backtest.run_backtest --symbols symbols_fno.txt --limit 10
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# Allow `python -m backtest.run_backtest` from repo root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src import ob as obmod  # noqa: E402
from src import rf as rfmod  # noqa: E402
from src.scanner import fetch_5m, load_symbols  # noqa: E402

DEFAULT_SYMBOLS = ROOT / "symbols_fno.txt"
OUT_DIR = ROOT / "output"
LOCAL_DATA_DIR = Path("/workspace/yahoo_backtest/data/fno208")
STOCK_SLIP_PCT = 0.0005
COMMISSION_PCT = 0.0003
FORCE_FLAT_HHMM = (15, 15)
TP_R = rfmod.TP_R
QTY = 1.0


def local_path_for_symbol(symbol: str, data_dir: Path) -> Path:
    """Map Yahoo NSE symbols to fno208 filenames (e.g. M&M.NS -> M&M_NS_5m.csv)."""
    stem = symbol[:-3] if symbol.endswith(".NS") else symbol
    return data_dir / f"{stem}_NS_5m.csv"


def load_local_5m(path: Path) -> pd.DataFrame:
    """Load an existing fno208 CSV and normalize it like the Yahoo loader."""
    df = pd.read_csv(path, parse_dates=["datetime"])
    required = ["datetime", "open", "high", "low", "close", "volume"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    df = df[required].copy().set_index("datetime")
    if df.index.tz is None:
        df.index = df.index.tz_localize(rfmod.TZ)
    else:
        df.index = df.index.tz_convert(rfmod.TZ)
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return rfmod.filter_session(df)


@dataclass
class Trade:
    symbol: str
    entry_time: str
    exit_time: str
    side: str
    entry: float
    exit: float
    sl: float
    tp: float
    risk: float
    pnl_points: float
    pnl_r: float
    exit_reason: str
    bars_held: int
    atr_at_entry: float
    day: str
    htf_bias: int
    zone_top: float
    zone_bot: float


def run_symbol_backtest(symbol: str, df: pd.DataFrame) -> list[Trade]:
    if df is None or len(df) < rfmod.RF_PERIOD + 50:
        return []

    data = rfmod.compute_range_filter(df)
    data = rfmod.add_risk_indicators(data)
    htf = rfmod.map_htf_bias(df)
    data["htf_bias"] = htf

    dets = obmod.detect_order_blocks(df)
    active = obmod.build_active_ob_state(df, dets)
    for col in active.columns:
        data[col] = active[col]

    data["long_ok"] = (data["htf_bias"] == 1) & data["inside_bull_ob"]
    data["short_ok"] = (data["htf_bias"] == -1) & data["inside_bear_ob"]

    trades: list[Trade] = []
    position = None
    traded_days: set[str] = set()
    idx = data.index
    warm = max(rfmod.RF_PERIOD + 5, rfmod.ATR_LEN + rfmod.ATR_FLOOR_SMA, rfmod.SWING_LOOKBACK + 2)

    for i in range(len(data)):
        row = data.iloc[i]
        ts = idx[i]
        day = str(ts.date())
        hhmm = (ts.hour, ts.minute)

        if position is not None:
            exit_price = None
            reason = None
            side = position["side"]
            sl = position["sl"]
            tp = position["tp"]
            if side == "long":
                hit_sl = row["low"] <= sl
                hit_tp = row["high"] >= tp
                if hit_sl and hit_tp:
                    exit_price, reason = sl, "sl"
                elif hit_sl:
                    exit_price, reason = sl, "sl"
                elif hit_tp:
                    exit_price, reason = tp, "tp_0.6R"
            else:
                hit_sl = row["high"] >= sl
                hit_tp = row["low"] <= tp
                if hit_sl and hit_tp:
                    exit_price, reason = sl, "sl"
                elif hit_sl:
                    exit_price, reason = sl, "sl"
                elif hit_tp:
                    exit_price, reason = tp, "tp_0.6R"
            if exit_price is None and hhmm >= FORCE_FLAT_HHMM:
                exit_price = float(row["close"])
                reason = "eod_flat"
            if exit_price is not None:
                entry = position["entry"]
                slip = exit_price * STOCK_SLIP_PCT
                if side == "long":
                    fill = exit_price - slip
                    raw = (fill - entry) * QTY
                else:
                    fill = exit_price + slip
                    raw = (entry - fill) * QTY
                commission = entry * COMMISSION_PCT * QTY + abs(fill) * COMMISSION_PCT * QTY
                pnl = raw - commission
                risk = position["risk"]
                trades.append(
                    Trade(
                        symbol=symbol,
                        entry_time=str(position["entry_time"]),
                        exit_time=str(ts),
                        side=side,
                        entry=round(entry, 4),
                        exit=round(fill, 4),
                        sl=round(sl, 4),
                        tp=round(position["tp"], 4),
                        risk=round(risk, 4),
                        pnl_points=round(pnl, 4),
                        pnl_r=round(pnl / risk if risk > 0 else 0.0, 4),
                        exit_reason=reason,
                        bars_held=i - position["entry_i"],
                        atr_at_entry=round(position["atr"], 4),
                        day=position["day"],
                        htf_bias=int(position["htf_bias"]),
                        zone_top=round(position["zone_top"], 4),
                        zone_bot=round(position["zone_bot"], 4),
                    )
                )
                position = None
                continue

        if position is not None:
            continue
        if i < warm:
            continue
        if day in traded_days:
            continue
        if hhmm >= FORCE_FLAT_HHMM:
            continue

        long_sig = bool(row["long_signal"]) and bool(row["long_ok"])
        short_sig = bool(row["short_signal"]) and bool(row["short_ok"])
        if not long_sig and not short_sig:
            continue

        atr_v = float(row["atr"])
        if np.isnan(atr_v) or atr_v <= 0:
            continue

        side = "long" if long_sig else "short"
        raw_entry = float(row["close"])

        if side == "long":
            entry = raw_entry + raw_entry * STOCK_SLIP_PCT
            sl_raw = float(row["prev_swing_low"])
            if np.isnan(sl_raw):
                continue
            if (raw_entry - sl_raw) < atr_v * rfmod.ATR_MULT:
                sl = raw_entry - atr_v * rfmod.ATR_MULT
            else:
                sl = sl_raw
            if sl >= entry:
                sl = entry - atr_v * rfmod.ATR_MULT
            risk = entry - sl
            if risk <= 0:
                continue
            tp = entry + risk * TP_R
            zone_top = float(row.get("bull_ob_top", np.nan))
            zone_bot = float(row.get("bull_ob_bot", np.nan))
        else:
            entry = raw_entry - raw_entry * STOCK_SLIP_PCT
            sl_raw = float(row["prev_swing_high"])
            if np.isnan(sl_raw):
                continue
            if (sl_raw - raw_entry) < atr_v * rfmod.ATR_MULT:
                sl = raw_entry + atr_v * rfmod.ATR_MULT
            else:
                sl = sl_raw
            if sl <= entry:
                sl = entry + atr_v * rfmod.ATR_MULT
            risk = sl - entry
            if risk <= 0:
                continue
            tp = entry - risk * TP_R
            zone_top = float(row.get("bear_ob_top", np.nan))
            zone_bot = float(row.get("bear_ob_bot", np.nan))

        position = {
            "side": side,
            "entry": entry,
            "sl": sl,
            "tp": tp,
            "risk": risk,
            "entry_time": ts,
            "entry_i": i,
            "atr": atr_v,
            "day": day,
            "htf_bias": int(row["htf_bias"]),
            "zone_top": zone_top if not np.isnan(zone_top) else 0.0,
            "zone_bot": zone_bot if not np.isnan(zone_bot) else 0.0,
        }
        traded_days.add(day)

    # Force close leftover
    if position is not None:
        row = data.iloc[-1]
        ts = idx[-1]
        side = position["side"]
        entry = position["entry"]
        _px = float(row["close"])
        slip = _px * STOCK_SLIP_PCT
        fill = _px - slip if side == "long" else _px + slip
        commission = entry * COMMISSION_PCT * QTY + abs(fill) * COMMISSION_PCT * QTY
        raw = (fill - entry) * QTY if side == "long" else (entry - fill) * QTY
        pnl = raw - commission
        risk = position["risk"]
        trades.append(
            Trade(
                symbol=symbol,
                entry_time=str(position["entry_time"]),
                exit_time=str(ts),
                side=side,
                entry=round(entry, 4),
                exit=round(fill, 4),
                sl=round(position["sl"], 4),
                tp=round(position["tp"], 4),
                risk=round(risk, 4),
                pnl_points=round(pnl, 4),
                pnl_r=round(pnl / risk if risk > 0 else 0.0, 4),
                exit_reason="eod_flat",
                bars_held=len(data) - 1 - position["entry_i"],
                atr_at_entry=round(position["atr"], 4),
                day=position["day"],
                htf_bias=int(position["htf_bias"]),
                zone_top=round(position["zone_top"], 4),
                zone_bot=round(position["zone_bot"], 4),
            )
        )
    return trades


def summarize(trades: list[Trade]) -> dict:
    if not trades:
        return {
            "n_trades": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "expectancy_r": 0.0,
            "net_pnl": 0.0,
            "avg_r": 0.0,
            "n_long": 0,
            "n_short": 0,
        }
    pnls = np.array([t.pnl_points for t in trades], dtype=float)
    rs = np.array([t.pnl_r for t in trades], dtype=float)
    wins = pnls[pnls > 0]
    losses = pnls[pnls <= 0]
    gross_win = float(wins.sum()) if len(wins) else 0.0
    gross_loss = float((-losses).sum()) if len(losses) else 0.0
    pf = (gross_win / gross_loss) if gross_loss > 0 else (float("inf") if gross_win > 0 else 0.0)
    return {
        "n_trades": len(trades),
        "win_rate": float((pnls > 0).mean()),
        "profit_factor": None if pf == float("inf") else round(pf, 4),
        "expectancy_r": round(float(rs.mean()), 4),
        "net_pnl": round(float(pnls.sum()), 4),
        "avg_r": round(float(rs.mean()), 4),
        "n_long": sum(1 for t in trades if t.side == "long"),
        "n_short": sum(1 for t in trades if t.side == "short"),
        "n_symbols": len({t.symbol for t in trades}),
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="RF+HTF+OB5m backtest TP=0.6R")
    p.add_argument("--symbols", type=Path, default=DEFAULT_SYMBOLS)
    p.add_argument("--out-dir", type=Path, default=OUT_DIR)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--sleep", type=float, default=0.35, help="Pause between Yahoo fetches")
    p.add_argument(
        "--data-dir", type=Path,
        default=LOCAL_DATA_DIR if LOCAL_DATA_DIR.exists() else None,
        help="Prefer local fno208 CSVs from this directory; fall back to Yahoo when absent",
    )
    args = p.parse_args(argv)

    symbols = load_symbols(args.symbols)
    if args.limit and args.limit > 0:
        symbols = symbols[: args.limit]
    if not symbols:
        print("No symbols", file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    all_trades: list[Trade] = []
    per_sym: list[dict] = []
    counts = {"local": 0, "yahoo": 0, "skipped": 0, "errors": 0, "with_data": 0}

    for i, sym in enumerate(symbols, 1):
        print(f"[{i}/{len(symbols)}] {sym} ...", flush=True)
        try:
            local_path = (local_path_for_symbol(sym, args.data_dir)
                          if args.data_dir is not None else None)
            if local_path is not None and local_path.exists():
                df = load_local_5m(local_path)
                source = "local"
                counts["local"] += 1
            else:
                df = fetch_5m(sym)
                time.sleep(args.sleep)
                source = "yahoo"
                counts["yahoo"] += 1
            if df is None or df.empty:
                print(f"  no data ({source})")
                counts["skipped"] += 1
                per_sym.append({"symbol": sym, "n_trades": 0, "status": "skipped_no_data", "data_source": source})
                continue
            if len(df) < rfmod.RF_PERIOD + 50:
                print(f"  skipped: only {len(df)} bars ({source})")
                counts["skipped"] += 1
                per_sym.append({"symbol": sym, "n_trades": 0, "status": "skipped_too_short", "bars": len(df), "data_source": source})
                continue
            counts["with_data"] += 1
            tr = run_symbol_backtest(sym, df)
            all_trades.extend(tr)
            s = summarize(tr)
            s["symbol"] = sym
            s["status"] = "ok"
            s["bars"] = len(df)
            s["data_source"] = source
            per_sym.append(s)
            print(f"  trades={s['n_trades']} WR={s['win_rate']:.1%} ExpR={s['expectancy_r']} net={s['net_pnl']} ({source})")
        except Exception as e:
            print(f"  error: {e}")
            counts["errors"] += 1
            counts["skipped"] += 1
            per_sym.append({"symbol": sym, "n_trades": 0, "status": "error", "error": str(e)})

    agg = summarize(all_trades)
    agg.update({
        "symbols_scanned": len(symbols),
        "symbols_with_data": counts["with_data"],
        "symbols_skipped": counts["skipped"],
        "symbols_errors": counts["errors"],
        "symbols_local": counts["local"],
        "symbols_yahoo": counts["yahoo"],
    })
    trades_path = args.out_dir / "rf_htf_ob5m_trades.csv"
    summary_path = args.out_dir / "rf_htf_ob5m_summary.json"
    per_path = args.out_dir / "rf_htf_ob5m_per_symbol.csv"

    if all_trades:
        pd.DataFrame([asdict(t) for t in all_trades]).to_csv(trades_path, index=False)
    else:
        pd.DataFrame(columns=list(Trade.__dataclass_fields__.keys())).to_csv(
            trades_path, index=False
        )
    summary_path.write_text(json.dumps(agg, indent=2), encoding="utf-8")
    pd.DataFrame(per_sym).to_csv(per_path, index=False)

    print("\n=== AGGREGATE ===")
    print(json.dumps(agg, indent=2))
    print(f"\nWrote {trades_path}")
    print(f"Wrote {summary_path}")
    print(f"Wrote {per_path}")
    print(
        "\nDISCLAIMER: Research / educational only. Not trading advice. "
        "Yahoo data and costs are approximate."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
