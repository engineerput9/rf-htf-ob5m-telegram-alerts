"""wugamlo Order Block detection (periods=5, threshold=0, usewicks=false).

Aligned with yahoo_backtest/ob5m_d_regen.py.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

OB_PERIODS = 5
OB_THRESHOLD = 0.0
OB_USEWICKS = False


def detect_order_blocks(
    df: pd.DataFrame,
    periods: int = OB_PERIODS,
    threshold: float = OB_THRESHOLD,
    usewicks: bool = OB_USEWICKS,
) -> pd.DataFrame:
    """wugamlo OB detection on bar close (Pine-faithful indexing).

    At bar i: OB candle = i-(periods+1); sequence = i-periods .. i-1.
    Bull: red OB + periods green; zone open→low (or high→low if usewicks).
    Bear: green OB + periods red; zone open→high (or low→high if usewicks).
    """
    o = df["open"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    c = df["close"].values.astype(float)
    n = len(df)
    ob_period = periods + 1

    det_bull = np.zeros(n, dtype=bool)
    det_bear = np.zeros(n, dtype=bool)
    z_top = np.full(n, np.nan)
    z_bot = np.full(n, np.nan)
    z_side = np.zeros(n, dtype=int)
    ob_idx = np.full(n, -1, dtype=int)

    for i in range(ob_period, n):
        j = i - ob_period
        if c[j] == 0 or np.isnan(c[j]) or np.isnan(c[i - 1]):
            continue
        absmove = abs(c[j] - c[i - 1]) / c[j] * 100.0
        if absmove < threshold:
            continue

        up = 0
        down = 0
        for k in range(1, periods + 1):
            idx = i - k
            if c[idx] > o[idx]:
                up += 1
            elif c[idx] < o[idx]:
                down += 1

        bullish_ob = c[j] < o[j]
        bearish_ob = c[j] > o[j]

        if bullish_ob and up == periods:
            det_bull[i] = True
            top = h[j] if usewicks else o[j]
            bot = l[j]
            z_top[i], z_bot[i] = max(top, bot), min(top, bot)
            z_side[i] = 1
            ob_idx[i] = j
        elif bearish_ob and down == periods:
            det_bear[i] = True
            top = h[j]
            bot = l[j] if usewicks else o[j]
            z_top[i], z_bot[i] = max(top, bot), min(top, bot)
            z_side[i] = -1
            ob_idx[i] = j

    return pd.DataFrame(
        {
            "ob_det_bull": det_bull,
            "ob_det_bear": det_bear,
            "ob_det_top": z_top,
            "ob_det_bot": z_bot,
            "ob_det_side": z_side,
            "ob_candle_i": ob_idx,
        },
        index=df.index,
    )


def build_active_ob_state(df: pd.DataFrame, dets: pd.DataFrame) -> pd.DataFrame:
    """Track ALL unmitigated bull/bear OBs (not just latest).

    Active at bar i only if detected on a prior bar (j < i) and not mitigated
    by any close after detection through i (bull: close < zone_bot; bear: close > zone_top).
    inside_* true if close[i] sits in ANY active zone of that side.
    """
    n = len(df)
    c = df["close"].values.astype(float)
    det_side = dets["ob_det_side"].values
    det_top = dets["ob_det_top"].values
    det_bot = dets["ob_det_bot"].values

    bull_top = np.full(n, np.nan)
    bull_bot = np.full(n, np.nan)
    bull_det_i = np.full(n, -1, dtype=int)
    bear_top = np.full(n, np.nan)
    bear_bot = np.full(n, np.nan)
    bear_det_i = np.full(n, -1, dtype=int)
    inside_bull = np.zeros(n, dtype=bool)
    inside_bear = np.zeros(n, dtype=bool)

    bulls: list[tuple[float, float, int]] = []
    bears: list[tuple[float, float, int]] = []

    for i in range(n):
        if bulls:
            bulls = [(t, b, d) for (t, b, d) in bulls if not (c[i] < b)]
        if bears:
            bears = [(t, b, d) for (t, b, d) in bears if not (c[i] > t)]

        match_b = None
        for (t, b, d) in reversed(bulls):
            if b <= c[i] <= t:
                match_b = (t, b, d)
                break
        match_s = None
        for (t, b, d) in reversed(bears):
            if b <= c[i] <= t:
                match_s = (t, b, d)
                break

        if match_b is not None:
            t, b, d = match_b
            bull_top[i], bull_bot[i], bull_det_i[i] = t, b, d
            inside_bull[i] = True
        elif bulls:
            t, b, d = bulls[-1]
            bull_top[i], bull_bot[i], bull_det_i[i] = t, b, d

        if match_s is not None:
            t, b, d = match_s
            bear_top[i], bear_bot[i], bear_det_i[i] = t, b, d
            inside_bear[i] = True
        elif bears:
            t, b, d = bears[-1]
            bear_top[i], bear_bot[i], bear_det_i[i] = t, b, d

        if det_side[i] == 1 and not np.isnan(det_top[i]):
            bulls.append((float(det_top[i]), float(det_bot[i]), i))
        elif det_side[i] == -1 and not np.isnan(det_top[i]):
            bears.append((float(det_top[i]), float(det_bot[i]), i))

    bars_since_bull = np.where(bull_det_i >= 0, np.arange(n) - bull_det_i, -1)
    bars_since_bear = np.where(bear_det_i >= 0, np.arange(n) - bear_det_i, -1)

    return pd.DataFrame(
        {
            "bull_ob_top": bull_top,
            "bull_ob_bot": bull_bot,
            "bull_ob_det_i": bull_det_i,
            "bear_ob_top": bear_top,
            "bear_ob_bot": bear_bot,
            "bear_ob_det_i": bear_det_i,
            "inside_bull_ob": inside_bull,
            "inside_bear_ob": inside_bear,
            "bars_since_bull_ob": bars_since_bull,
            "bars_since_bear_ob": bars_since_bear,
        },
        index=df.index,
    )
