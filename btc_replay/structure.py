"""structure.py — 1H context, 15M range/edge, 5M sweep/reclaim, and geometry.

SRR-1 thesis (Sweep -> Reclaim -> Retest):
  * 15M price sits at a range EDGE.
  * On 5M, price SWEEPS just beyond the edge then RECLAIMS back inside (close
    re-crosses the edge).
  * Entry is a limit at the reclaimed edge (the RETEST). The trade only counts
    as opened if price actually returns to touch it (handled in replay).
  * SL beyond the sweep extreme; TP1 at the opposite edge (or range mid).

Everything uses CLOSED candles only.
"""
from __future__ import annotations

from typing import List, Optional, Sequence

from . import indicators as ind

Candle = dict


# --------------------------------------------------------------------------
# 1H context
# --------------------------------------------------------------------------
def _ema(values: Sequence[float], period: int) -> Optional[float]:
    if len(values) < period:
        return None
    k = 2.0 / (period + 1)
    e = values[0]
    for v in values[1:]:
        e = v * k + e * (1 - k)
    return e


def h1_context(h1: Sequence[Candle], cfg) -> str:
    look = cfg.structure["h1_context_lookback"]
    if len(h1) < look:
        return "unclear"
    closes = [c["close"] for c in h1[-look:]]
    fast = _ema(closes, cfg.structure["h1_ema_fast"])
    slow = _ema(closes, cfg.structure["h1_ema_slow"])
    if fast is None or slow is None:
        return "unclear"
    if fast > slow:
        return "bullish"
    if fast < slow:
        return "bearish"
    return "neutral"


# --------------------------------------------------------------------------
# 15M range / edge
# --------------------------------------------------------------------------
class Range:
    def __init__(self, low: float, high: float, lookback: int, last_close: float):
        self.low = low
        self.high = high
        self.size = high - low
        self.mid = (high + low) / 2.0
        self.lookback = lookback
        self.last_close = last_close

    @property
    def edge_id_low(self) -> str:
        return f"L:{round(self.low, 1)}@{self.lookback}"

    @property
    def edge_id_high(self) -> str:
        return f"H:{round(self.high, 1)}@{self.lookback}"


def m15_range(m15: Sequence[Candle], cfg) -> Optional[Range]:
    look = cfg.structure["m15_range_lookback"]
    if len(m15) < look:
        return None
    window = m15[-look:]
    low = min(c["low"] for c in window)
    high = max(c["high"] for c in window)
    return Range(low, high, look, window[-1]["close"])


def classify_edge(rng: Range, atr5: float, cfg) -> str:
    """lower_edge / upper_edge / middle / unclear (from last closed 15M close)."""
    if rng is None or rng.size <= 0:
        return "unclear"
    if atr5 > 0 and rng.size < cfg.structure["min_range_atr"] * atr5:
        return "unclear"
    band = cfg.structure["edge_band_frac"] * rng.size
    if rng.last_close <= rng.low + band:
        return "lower_edge"
    if rng.last_close >= rng.high - band:
        return "upper_edge"
    return "middle"


# --------------------------------------------------------------------------
# 5M sweep + reclaim
# --------------------------------------------------------------------------
class Setup:
    """A concrete SRR-1 entry proposal computed at a 5M close (no lookahead)."""

    def __init__(self, direction, entry, sl, tp1, atr5, rng, sweep_id,
                 edge_id, accept_candle):
        self.family = "SRR-1"
        self.direction = direction            # 'long' | 'short'
        self.entry = entry
        self.sl = sl
        self.tp1 = tp1
        self.atr5 = atr5
        self.rng = rng
        self.sweep_id = sweep_id
        self.edge_id = edge_id
        self.accept_candle = accept_candle    # the reclaim/acceptance 5M candle

        self.r_abs = abs(entry - sl)
        self.r_abs_bps = (self.r_abs / entry) * 10000.0 if entry else 0.0
        self.r_abs_atr = (self.r_abs / atr5) if atr5 > 0 else 0.0
        reward = abs(tp1 - entry)
        self.tp1_r = (reward / self.r_abs) if self.r_abs > 0 else 0.0

        # distance of entry from its edge, normalized by range size
        edge = rng.low if direction == "long" else rng.high
        self.entry_edge_dist_band = abs(entry - edge) / rng.size if rng.size > 0 else 1.0


def detect_srr1(m5: Sequence[Candle], rng: Range, edge_class: str, atr5: float,
                cfg) -> Optional[Setup]:
    """Detect a Sweep->Reclaim at the active edge on the just-closed 5M candle.

    Returns a Setup (entry/SL/TP1 fully specified) or None.
    """
    if rng is None or atr5 <= 0:
        return None
    look = cfg.geometry["sweep_lookback_5m"]
    if len(m5) < look:
        return None
    window = m5[-look:]
    accept = window[-1]            # the just-closed decision candle = reclaim/acceptance
    buf = cfg.geometry["sl_buffer_atr"] * atr5
    target = cfg.geometry["tp1_target"]

    if edge_class == "lower_edge":
        # sweep below range low somewhere in window, reclaim (close back above low)
        swept = any(c["low"] < rng.low for c in window)
        reclaimed = accept["close"] > rng.low
        if not (swept and reclaimed):
            return None
        sweep_low = min(c["low"] for c in window if c["low"] < rng.low)
        entry = rng.low
        sl = sweep_low - buf
        if sl >= entry:
            return None
        tp1 = rng.high if target == "opposite_edge" else rng.mid
        if tp1 <= entry:
            return None
        sweep_id = f"SWL:{round(sweep_low,1)}"
        return Setup("long", entry, sl, tp1, atr5, rng, sweep_id, rng.edge_id_low, accept)

    if edge_class == "upper_edge":
        swept = any(c["high"] > rng.high for c in window)
        reclaimed = accept["close"] < rng.high
        if not (swept and reclaimed):
            return None
        sweep_high = max(c["high"] for c in window if c["high"] > rng.high)
        entry = rng.high
        sl = sweep_high + buf
        if sl <= entry:
            return None
        tp1 = rng.low if target == "opposite_edge" else rng.mid
        if tp1 >= entry:
            return None
        sweep_id = f"SWH:{round(sweep_high,1)}"
        return Setup("short", entry, sl, tp1, atr5, rng, sweep_id, rng.edge_id_high, accept)

    return None


def weak_retest(setup: Setup, cfg) -> bool:
    """True if the reclaim only barely cleared the edge (thin acceptance)."""
    margin = abs(setup.accept_candle["close"] - setup.entry)
    return margin < cfg.geometry["weak_retest_atr"] * setup.atr5
