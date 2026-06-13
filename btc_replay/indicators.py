"""indicators.py — pure functions over CLOSED candle lists.

All inputs are sequences of candle dicts/objects with keys
open/high/low/close. Nothing here looks at the future: callers pass only
candles that have already closed at decision time.
"""
from __future__ import annotations

from typing import Sequence

Candle = dict  # expects keys: open, high, low, close (floats)


def true_range(prev_close: float, high: float, low: float) -> float:
    return max(high - low, abs(high - prev_close), abs(low - prev_close))


def atr(candles: Sequence[Candle], period: int) -> float:
    """Wilder-style ATR over the last `period` closed candles. 0.0 if too few."""
    if len(candles) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        trs.append(true_range(candles[i - 1]["close"], candles[i]["high"], candles[i]["low"]))
    window = trs[-period:]
    return sum(window) / len(window)


def body_ratio(c: Candle) -> float:
    rng = c["high"] - c["low"]
    if rng <= 0:
        return 0.0
    return abs(c["close"] - c["open"]) / rng


def close_strength(c: Candle, direction: str) -> float:
    """How decisively the candle closed in the trade direction.

    long  -> close near high  => (close-low)/range
    short -> close near low    => (high-close)/range
    """
    rng = c["high"] - c["low"]
    if rng <= 0:
        return 0.0
    if direction == "long":
        return (c["close"] - c["low"]) / rng
    return (c["high"] - c["close"]) / rng


def opposite_wick_ratio(c: Candle, direction: str) -> float:
    """Wick on the side that argues AGAINST the trade.

    long  -> upper wick ratio (rejection from above)
    short -> lower wick ratio
    """
    rng = c["high"] - c["low"]
    if rng <= 0:
        return 0.0
    body_top = max(c["open"], c["close"])
    body_bot = min(c["open"], c["close"])
    if direction == "long":
        return (c["high"] - body_top) / rng
    return (body_bot - c["low"]) / rng


def body_aligned(c: Candle, direction: str) -> bool:
    if direction == "long":
        return c["close"] > c["open"]
    return c["close"] < c["open"]
