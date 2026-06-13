"""No-lookahead invariants: SL-first ties, closed-candle resampling, and the
'entry must be touched' / 'fill is strictly after decision' guarantees."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from btc_replay import data_loader
from btc_replay.config import load_config
from btc_replay.replay_engine import bar_outcome, run_replay
from _synth import make_srr1_long

CFG = load_config()


def test_sl_first_on_same_candle_tie_long():
    # both SL and TP touched in one candle -> SL wins
    assert bar_outcome("long", sl=99.0, tp1=109.0, low=98.0, high=110.0, sl_first=True) == "SL"


def test_tp_only_long():
    assert bar_outcome("long", sl=99.0, tp1=109.0, low=101.0, high=110.0) == "TP1"


def test_sl_only_long():
    assert bar_outcome("long", sl=99.0, tp1=109.0, low=98.0, high=102.0) == "SL"


def test_none_when_neither():
    assert bar_outcome("long", sl=99.0, tp1=109.0, low=100.5, high=102.0) is None


def test_sl_first_short():
    assert bar_outcome("short", sl=110.0, tp1=101.0, low=100.0, high=111.0, sl_first=True) == "SL"


def test_resample_only_closed_full_bars():
    # 7 one-minute bars -> exactly one full 5M bar; the partial second bar dropped
    rows = []
    base = pd.Timestamp("2025-01-01 00:00:00")
    for i in range(7):
        rows.append({"timestamp": base + pd.Timedelta(minutes=i),
                     "open": 100, "high": 101, "low": 99, "close": 100, "volume": 1})
    df = pd.DataFrame(rows)
    out = data_loader.resample(df, "5min")
    full = out[out["full"]]
    assert len(full) == 1
    assert full.iloc[0]["n"] == 5


def test_fill_strictly_after_decision_and_exit_after_fill(tmp_path):
    csv = make_srr1_long(str(tmp_path / "data" / "BTCUSDT_synth.csv"))
    results = run_replay(str(tmp_path / "data"), CFG)
    trades = results["trades"]
    assert len(trades) >= 1, "synthetic SRR-1 long should produce at least one filled trade"
    decisions = results["decisions"]
    exec_times = [pd.Timestamp(d["timestamp"]) for d in decisions
                  if d["decision"] == "EXECUTE_CANDIDATE"]
    assert exec_times, "expected an EXECUTE_CANDIDATE"
    first_exec = min(exec_times)
    t = trades[0]
    assert pd.Timestamp(t["timestamp"]) > first_exec, "fill must be strictly after the decision"
    assert pd.Timestamp(t["exit_time"]) >= pd.Timestamp(t["timestamp"]), "exit must be at/after fill"
    assert t["exit_reason"] in ("TP1", "SL")
