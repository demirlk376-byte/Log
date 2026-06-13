"""Unit tests for v0.10.1 Soft Acceptance."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from btc_replay import rules_v10_1
from btc_replay.config import load_config
from btc_replay.structure import Range, Setup

CFG = load_config()


def _setup(accept, direction="long", entry=101.0, sl=99.0, tp1=109.0, atr5=1.0):
    rng = Range(low=101.0, high=109.0, lookback=20, last_close=101.3)
    return Setup(direction, entry, sl, tp1, atr5, rng, "SW", "EID", accept)


def test_clean_setup_passes():
    accept = {"open": 99.2, "high": 101.9, "low": 99.0, "close": 101.8}
    out = rules_v10_1.evaluate(_setup(accept), CFG)
    assert out["result"] == "PASS"
    assert out["weakness_count"] == 0


def test_three_weaknesses_without_strict_is_watch():
    # weak_close (0.5), body-not-aligned, weak_retest -> 3 weaknesses,
    # but body_ratio=0.30 and close_strength=0.5 avoid every strict-cancel rule.
    accept = {"open": 101.2, "high": 102.0, "low": 98.0, "close": 100.0}
    out = rules_v10_1.evaluate(_setup(accept, entry=100.05), CFG)
    assert out["weakness_count"] >= 3
    assert out["result"] == "WATCH"


def test_strict_cancel_doji_no_body():
    # tiny body (<0.20) AND weak close strength (<0.50) -> strict cancel rule (a)
    accept = {"open": 99.4, "high": 101.0, "low": 99.0, "close": 99.3}
    out = rules_v10_1.evaluate(_setup(accept), CFG)
    assert out["result"] == "CANCEL"
    assert "v10_1_strict_cancel" in out["tags"]


def test_short_direction_close_strength():
    # for short, strong close = close near low
    accept = {"open": 108.9, "high": 109.0, "low": 107.0, "close": 107.1}
    out = rules_v10_1.evaluate(
        _setup(accept, direction="short", entry=109.0, sl=110.0, tp1=101.0), CFG)
    assert out["features"]["acceptance_close_strength"] > 0.9
    assert out["result"] == "PASS"
