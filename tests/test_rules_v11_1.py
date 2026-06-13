"""Unit tests for v0.11.1 No-Stale-Reentry / No Duplicate Promotion."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from btc_replay import rules_v11_1
from btc_replay.config import load_config
from btc_replay.rules_v11_1 import EngineState, setup_identity
from btc_replay.structure import Range, Setup

CFG = load_config()


def _setup():
    rng = Range(low=101.0, high=109.0, lookback=20, last_close=101.3)
    return Setup("long", 101.0, 99.0, 109.0, 1.0, rng, "SW1", "EID1",
                 {"open": 99.2, "high": 101.9, "low": 99.0, "close": 101.8})


def test_clear_when_fresh():
    s = _setup()
    state = EngineState(symbol="BTCUSDT")
    out = rules_v11_1.evaluate(s, state, CFG)
    assert out["result"] == "PASS"
    assert not out["blocked"]


def test_active_setup_blocks():
    s = _setup()
    state = EngineState(symbol="BTCUSDT", active_setup_id="something")
    out = rules_v11_1.evaluate(s, state, CFG)
    assert out["blocked"]
    assert "active_setup_exists" in out["tags"]


def test_cooldown_blocks():
    s = _setup()
    state = EngineState(symbol="BTCUSDT")
    state.bar_index_5m = 3
    state.start_cooldown(CFG.v11_1["cooldown_bars_5m"])  # until bar 9
    out = rules_v11_1.evaluate(s, state, CFG)
    assert out["blocked"]
    assert "cooldown_active" in out["tags"]


def test_same_edge_same_sweep_reentry_is_duplicate():
    s = _setup()
    state = EngineState(symbol="BTCUSDT")
    state.promoted_ids.add(setup_identity("BTCUSDT", s))
    out = rules_v11_1.evaluate(s, state, CFG)
    assert out["blocked"]
    assert "same_edge_same_sweep_reentry" in out["tags"]
    assert "duplicate_promotion_candidate" in out["tags"]


def test_late_reentry_after_prior_watch():
    s = _setup()
    state = EngineState(symbol="BTCUSDT")
    state.prior_watch_ids.add(setup_identity("BTCUSDT", s))
    out = rules_v11_1.evaluate(s, state, CFG)
    assert out["blocked"]
    assert "late_reentry_after_prior_watch" in out["tags"]
