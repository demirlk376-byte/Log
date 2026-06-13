"""Synthetic 1M data generators for tests ONLY.

These are clearly-labelled synthetic fixtures used to prove the pipeline runs
end-to-end and that invariants hold. They are NOT real market data and must
never be presented as a real backtest result.
"""
from __future__ import annotations

import os
from typing import List, Tuple

import pandas as pd

START = pd.Timestamp("2025-06-01 00:00:00")


def _row(minute: int, o, h, l, c, v=10.0):
    ts = START + pd.Timedelta(minutes=minute)
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}


def make_srr1_long(path: str) -> str:
    """Write a synthetic CSV containing one clean SRR-1 long: range ~[101,109],
    sweep below 101 to 99, strong reclaim, retest fill at 101, rally to TP1=109.
    Returns the CSV path written."""
    rows: List[dict] = []

    # ---- warmup channel: alternate 15-min blocks high(108.7)/low(101.3) ----
    # high blocks make high=109.0, low blocks make low=101.0  -> range [101,109]
    for block in range(0, 260 // 15 + 1):
        base = 108.7 if block % 2 == 0 else 101.3
        for j in range(15):
            minute = block * 15 + j
            if minute >= 260:
                break
            if base > 105:  # high phase: push a high to 109.0
                o, c = base, base
                h, l = 109.0, base - 0.3
            else:           # low phase: push a low to 101.0
                o, c = base, base
                h, l = base + 0.3, 101.0
            rows.append(_row(minute, o, h, l, c))

    # ---- low hold 260..330 (flat at 101.3 -> recent 15M closes = lower edge,
    #      and ATR window stays small) ----
    for minute in range(260, 330):
        rows.append(_row(minute, 101.3, 101.5, 101.0, 101.3))

    # ---- decision 5M candle [330,335): sweep to 99.0 then strong reclaim ----
    decision = [
        (330, 99.2, 99.5, 99.0, 99.4),
        (331, 99.4, 100.0, 99.4, 99.9),
        (332, 99.9, 100.6, 99.9, 100.5),
        (333, 100.5, 101.2, 100.5, 101.1),
        (334, 101.1, 101.9, 101.1, 101.8),
    ]
    for (m, o, h, l, c) in decision:
        rows.append(_row(m, o, h, l, c))

    # ---- retest fill at 101.0 on minute 335 (low dips to 100.9) ----
    rows.append(_row(335, 101.6, 101.7, 100.9, 101.2))

    # ---- rally to TP1 = 109.0 ----
    prev_c = 101.2
    minute = 336
    while prev_c < 109.4:
        c = prev_c + 0.6
        o = prev_c
        h = c + 0.2
        l = prev_c - 0.1
        rows.append(_row(minute, o, h, l, c))
        prev_c = c
        minute += 1

    # ---- trailing flat data ----
    for k in range(10):
        rows.append(_row(minute + k, 109.3, 109.5, 109.1, 109.3))

    df = pd.DataFrame(rows)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_csv(path, index=False)
    return path
