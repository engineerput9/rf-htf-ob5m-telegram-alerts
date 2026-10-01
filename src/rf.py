"""Range Filter (CondIni) — Pine-faithful, aligned with yahoo_backtest/backtest.py."""
from __future__ import annotations

import numpy as np
import pandas as pd

RF_PERIOD = 100
RF_MULT = 3.0
SWING_LOOKBACK = 10
ATR_LEN = 14
ATR_MULT = 1.0
TP_R = 0.6
ATR_FLOOR_SMA = 20
TZ = "Asia/Kolkata"
SESSION_START = (9, 15)
SESSION_END = (15, 30)


def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def atr(df: pd.DataFrame, length: int = ATR_LEN) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()  # Pine RMA/ATR


def smoothrng(src: pd.Series, t: int, m: float) -> pd.Series:
    wper = (t * 2) - 1
    avrng = ema((src - src.shift(1)).abs(), t)
    return ema(avrng, wper) * m


def rngfilt(src: pd.Series, r: pd.Series) -> pd.Series:
    """Trailing range filter (Pine rngfilt)."""
    n = len(src)
    filt = np.empty(n, dtype=float)
    s = src.values.astype(float)
    rv = r.values.astype(float)
    filt[0] = s[0]
    for i in range(1, n):
        prev = filt[i - 1]
        x = s[i]
        ri = rv[i]
        if np.isnan(ri) or np.isnan(x):
            filt[i] = prev if not np.isnan(prev) else x
            continue
        if x > prev:
            filt[i] = prev if (x - ri) < prev else (x - ri)
        else:
            filt[i] = prev if (x + ri) > prev else (x + ri)
    return pd.Series(filt, index=src.index)


def compute_range_filter(
    df: pd.DataFrame, per: int = RF_PERIOD, mult: float = RF_MULT
) -> pd.DataFrame:
    out = df.copy()
    src = out["close"]
    smrng = smoothrng(src, per, mult)
    filt = rngfilt(src, smrng)
    out["filt"] = filt
    out["smrng"] = smrng

    upward = np.zeros(len(out), dtype=float)
    downward = np.zeros(len(out), dtype=float)
    f = filt.values
    for i in range(1, len(out)):
        if f[i] > f[i - 1]:
            upward[i] = upward[i - 1] + 1
            downward[i] = 0
        elif f[i] < f[i - 1]:
            downward[i] = downward[i - 1] + 1
            upward[i] = 0
        else:
            upward[i] = upward[i - 1]
            downward[i] = downward[i - 1]
    out["upward"] = upward
    out["downward"] = downward

    long_cond = (src > filt) & (out["upward"] > 0)
    short_cond = (src < filt) & (out["downward"] > 0)
    out["long_cond"] = long_cond
    out["short_cond"] = short_cond

    cond_ini = np.zeros(len(out), dtype=int)
    lc = long_cond.values
    sc = short_cond.values
    for i in range(len(out)):
        if lc[i]:
            cond_ini[i] = 1
        elif sc[i]:
            cond_ini[i] = -1
        else:
            cond_ini[i] = cond_ini[i - 1] if i > 0 else 0
    out["cond_ini"] = cond_ini
    prev_ini = np.roll(cond_ini, 1)
    prev_ini[0] = 0
    out["long_signal"] = long_cond & (prev_ini == -1)
    out["short_signal"] = short_cond & (prev_ini == 1)
    return out


def add_risk_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["atr"] = atr(out, ATR_LEN)
    out["atr_sma"] = out["atr"].rolling(ATR_FLOOR_SMA).mean()
    out["prev_swing_low"] = out["low"].rolling(SWING_LOOKBACK).min().shift(1)
    out["prev_swing_high"] = out["high"].rolling(SWING_LOOKBACK).max().shift(1)
    return out


def filter_session(df: pd.DataFrame) -> pd.DataFrame:
    """Keep bars within NSE cash session roughly 09:15–15:30 IST."""
    t = df.index
    minutes = t.hour * 60 + t.minute
    start_m = SESSION_START[0] * 60 + SESSION_START[1]
    end_m = SESSION_END[0] * 60 + SESSION_END[1]
    mask = (minutes >= start_m) & (minutes <= end_m)
    return df.loc[mask].copy()


def map_htf_bias(df5: pd.DataFrame) -> pd.Series:
    """15m RF CondIni, last completed 15m bar only (no lookahead)."""
    ohlc = (
        df5[["open", "high", "low", "close", "volume"]]
        .resample("15min", label="left", closed="left")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(subset=["open", "high", "low", "close"])
    )
    rf15 = compute_range_filter(ohlc)
    avail = rf15[["cond_ini"]].copy()
    avail.index = avail.index + pd.Timedelta(minutes=15)
    mapped = avail.reindex(df5.index, method="ffill")
    return mapped["cond_ini"].fillna(0).astype(int)


def suggest_sl_tp(side: str, close: float, atr_v: float, swing_low: float, swing_high: float) -> tuple[float, float, float]:
    """Swing/ATR SL and 0.6R TP. Returns (sl, tp, risk)."""
    if side == "long":
        sl_raw = swing_low
        if np.isnan(sl_raw) or (close - sl_raw) < atr_v * ATR_MULT:
            sl = close - atr_v * ATR_MULT
        else:
            sl = sl_raw
        if sl >= close:
            sl = close - atr_v * ATR_MULT
        risk = close - sl
        tp = close + risk * TP_R
    else:
        sl_raw = swing_high
        if np.isnan(sl_raw) or (sl_raw - close) < atr_v * ATR_MULT:
            sl = close + atr_v * ATR_MULT
        else:
            sl = sl_raw
        if sl <= close:
            sl = close + atr_v * ATR_MULT
        risk = sl - close
        tp = close - risk * TP_R
    return float(sl), float(tp), float(risk)
