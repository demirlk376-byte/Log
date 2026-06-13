"""Unit tests for v0.11 BTC A+ Cost-Survival."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from btc_replay import rules_v11
from btc_replay.config import load_config
from btc_replay.structure import Range, Setup

CFG = load_config()


def _setup(entry, sl, tp1, atr5=1.0, direction="long"):
    rng = Range(low=min(entry, sl, tp1) - 1, high=max(entry, sl, tp1) + 1,
                lookback=20, last_close=entry)
    return Setup(direction, entry, sl, tp1, atr5, rng, "SW", "EID",
                 {"open": entry, "high": entry + 1, "low": entry - 1, "close": entry + 0.9})


def _v10(close_strength=0.9, body_ratio=0.8, weakness_count=0):
    return {
        "weakness_count": weakness_count,
        "features": {"acceptance_close_strength": close_strength, "body_ratio": body_ratio},
    }


def test_normal_aplus_pass():
    # entry 101, sl 99 -> risk 2 (bps ~198, atr 2.0), tp1 109 -> tp1_r=4
    s = _setup(101.0, 99.0, 109.0, atr5=1.0)
    out = rules_v11.evaluate(s, _v10(), CFG)
    assert out["result"] == "PASS"
    assert "v11_normal_Aplus" in out["tags"]


def test_hard_fail_below_1p8R():
    # tp1_r < 1.8 -> hard fail
    s = _setup(101.0, 99.0, 104.0, atr5=1.0)  # reward 3 / risk 2 = 1.5R
    out = rules_v11.evaluate(s, _v10(), CFG)
    assert out["result"] == "CANCEL"
    assert "v11_hard_fail_tp1_r" in out["tags"]


def test_conditional_sub2r_pass():
    # tp1_r in [1.8, 2.0): reward 3.8 / risk 2 = 1.9R, strong quality, 0 weakness
    s = _setup(101.0, 99.0, 104.8, atr5=1.0)
    out = rules_v11.evaluate(s, _v10(close_strength=0.7, body_ratio=0.4, weakness_count=0), CFG)
    assert out["result"] == "PASS"
    assert "v11_conditional_sub2r" in out["tags"]


def test_conditional_sub2r_fail_on_weakness():
    s = _setup(101.0, 99.0, 104.8, atr5=1.0)  # 1.9R
    out = rules_v11.evaluate(s, _v10(close_strength=0.7, body_ratio=0.4, weakness_count=1), CFG)
    assert out["result"] == "CANCEL"
    assert "v11_sub2r_fail" in out["tags"]


def test_quality_fail_when_close_strength_low():
    s = _setup(101.0, 99.0, 109.0, atr5=1.0)  # tp1_r=4 but weak quality
    out = rules_v11.evaluate(s, _v10(close_strength=0.4, body_ratio=0.2), CFG)
    assert out["result"] == "CANCEL"
    assert "v11_quality_fail" in out["tags"]
