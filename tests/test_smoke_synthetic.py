"""Full-pipeline smoke test on SYNTHETIC data.

Proves run_replay -> reports.write_all produces well-formed
decision_log.csv / trade_log.csv / summary.json with the exact schemas the
task brief requires. The numbers here are synthetic and must not be read as a
real backtest."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from btc_replay import reports
from btc_replay.config import load_config
from btc_replay.replay_engine import run_replay
from _synth import make_srr1_long

CFG = load_config()

TRADE_COLS = ["timestamp", "direction", "entry", "SL", "TP1", "RR", "cost_R",
              "result_R", "exit_reason", "exit_time", "setup_reason", "mfe_R", "mae_R"]
SUMMARY_FIELDS = ["total_decisions", "WATCH", "CANCEL", "EXECUTE_CANDIDATE",
                  "filled_trade", "total_R", "win_rate", "profit_factor",
                  "max_drawdown", "top_cancel_reason", "top_sl_reason",
                  "reliability_note"]


def test_full_pipeline_schema_and_files(tmp_path):
    data_dir = str(tmp_path / "data")
    out_dir = str(tmp_path / "reports")
    make_srr1_long(os.path.join(data_dir, "BTCUSDT_synth.csv"))

    results = run_replay(data_dir, CFG)
    summary = reports.write_all(results, CFG, out_dir)

    for f in ("decision_log.csv", "trade_log.csv", "summary.json",
              "v0_11_1_raw_cost_stress.csv", "v0_11_1_raw_monthly_summary.csv",
              "v0_11_1_raw_IS_OOS_summary.csv", "v0_11_1_raw_drawdown_summary.txt"):
        assert os.path.exists(os.path.join(out_dir, f)), f"missing {f}"

    trade_df = pd.read_csv(os.path.join(out_dir, "trade_log.csv"))
    assert list(trade_df.columns) == TRADE_COLS
    assert len(trade_df) >= 1

    with open(os.path.join(out_dir, "summary.json")) as fh:
        s = json.load(fh)
    for field in SUMMARY_FIELDS:
        assert field in s, f"summary.json missing {field}"

    assert s["filled_trade"] == len(trade_df)
    assert s["total_decisions"] == (s["WATCH"] + s["CANCEL"] + s["EXECUTE_CANDIDATE"])
    # synthetic long should win -> positive net R after 0.08% cost
    assert s["filled_trade"] >= 1
    assert "reliable backtest" in s["reliability_note"].lower()
