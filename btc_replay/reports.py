"""reports.py — turn replay results into the required CSV/JSON artifacts.

PRIMARY (task brief) outputs:
  * decision_log.csv
  * trade_log.csv
  * summary.json   (only written when a trade log exists)

SPEC outputs (additional):
  * v0_11_1_raw_EXECUTE_log.csv
  * v0_11_1_raw_WATCH_CANCEL_log.csv
  * v0_11_1_raw_blocked_stale_duplicate_log.csv
  * v0_11_1_raw_monthly_summary.csv
  * v0_11_1_raw_IS_OOS_summary.csv
  * v0_11_1_raw_cost_stress.csv
  * v0_11_1_raw_drawdown_summary.txt
"""
from __future__ import annotations

import json
import os
from collections import Counter
from typing import Dict, List

import pandas as pd


def _month(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m")


def _max_drawdown_R(result_R: List[float]) -> float:
    """Max peak-to-trough drawdown of the cumulative-R equity curve (in R)."""
    peak = 0.0
    cum = 0.0
    mdd = 0.0
    for r in result_R:
        cum += r
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return mdd  # <= 0


def _max_consecutive_sl(exit_reasons: List[str]) -> int:
    best = cur = 0
    for r in exit_reasons:
        if r == "SL":
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _profit_factor(result_R: List[float]) -> float:
    gains = sum(r for r in result_R if r > 0)
    losses = -sum(r for r in result_R if r < 0)
    if losses == 0:
        return float("inf") if gains > 0 else 0.0
    return gains / losses


def build_summary(results: Dict, cfg) -> Dict:
    decisions = results["decisions"]
    trades = results["trades"]

    total_decisions = len(decisions)
    counts = Counter(d["decision"] for d in decisions)

    result_R = [t["result_R"] for t in trades]
    exit_reasons = [t["exit_reason"] for t in trades]
    wins = [r for r in result_R if r > 0]

    cancel_tags: Counter = Counter()
    for d in decisions:
        if d["decision"] == "CANCEL":
            for tag in str(d["reason_tags"]).split(","):
                cancel_tags[tag] += 1

    sl_tags: Counter = Counter()
    for t in trades:
        if t["exit_reason"] == "SL":
            for tag in str(t["setup_reason"]).split(","):
                sl_tags[tag] += 1

    has_trades = len(trades) > 0
    if has_trades:
        reliability = (
            "reliable backtest: trade_log üretildi, summary gerçek trade'lerden hesaplandı."
        )
    else:
        reliability = (
            "reliable backtest yapılamadı — hiç dolmuş trade yok (0 filled_trade). "
            "summary metrikleri trade'e dayanmıyor; total_decisions/WATCH/CANCEL hariç R metrikleri anlamsız."
        )

    summary = {
        "total_decisions": total_decisions,
        "WATCH": counts.get("WATCH", 0),
        "CANCEL": counts.get("CANCEL", 0),
        "EXECUTE_CANDIDATE": counts.get("EXECUTE_CANDIDATE", 0),
        "filled_trade": len(trades),
        "total_R": round(sum(result_R), 4),
        "win_rate": round(len(wins) / len(trades), 4) if has_trades else None,
        "profit_factor": (round(_profit_factor(result_R), 4)
                          if has_trades and _profit_factor(result_R) != float("inf")
                          else ("inf" if has_trades else None)),
        "max_drawdown": round(_max_drawdown_R(result_R), 4) if has_trades else None,
        "top_cancel_reason": cancel_tags.most_common(1)[0][0] if cancel_tags else None,
        "top_sl_reason": sl_tags.most_common(1)[0][0] if sl_tags else None,
        "max_consecutive_SL": _max_consecutive_sl(exit_reasons),
        "data_span": results.get("data_span"),
        "continuity": results.get("continuity"),
        "reliability_note": reliability,
    }
    return summary


def cost_stress(trades: List[dict], cfg) -> pd.DataFrame:
    """Re-price each trade's gross R under each cost scenario."""
    rows = []
    scenarios = cfg.costs["stress_scenarios_bps"]
    scenarios = {**scenarios, "primary_0p08pct": cfg.costs["primary_roundtrip_bps"]}
    for name, bps in scenarios.items():
        frac = bps / 10000.0
        net = []
        for t in trades:
            # recover gross R from net + original cost
            gross = t["result_R"] + t["cost_R"]
            entry = t["entry"]
            r_abs = abs(entry - t["SL"])
            cost_R = (frac * entry) / r_abs if r_abs > 0 else 0.0
            net.append(gross - cost_R)
        rows.append({
            "scenario": name,
            "roundtrip_bps": bps,
            "trades": len(net),
            "total_R": round(sum(net), 4),
            "win_rate": round(sum(1 for r in net if r > 0) / len(net), 4) if net else None,
            "profit_factor": round(_profit_factor(net), 4) if net and _profit_factor(net) != float("inf") else None,
        })
    return pd.DataFrame(rows)


def monthly_summary(trades: List[dict]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(columns=["month", "trades", "total_R", "win_rate", "max_consecutive_SL"])
    df = pd.DataFrame(trades)
    df["month"] = df["timestamp"].map(_month)
    rows = []
    for m, g in df.groupby("month"):
        rr = g["result_R"].tolist()
        rows.append({
            "month": m,
            "trades": len(g),
            "total_R": round(sum(rr), 4),
            "win_rate": round(sum(1 for r in rr if r > 0) / len(rr), 4),
            "max_consecutive_SL": _max_consecutive_sl(g["exit_reason"].tolist()),
        })
    return pd.DataFrame(rows).sort_values("month")


def is_oos_summary(trades: List[dict], cfg) -> pd.DataFrame:
    oos_months = set(cfg.windows["oos_months"])
    rows = {"IS": [], "OOS": []}
    for t in trades:
        bucket = "OOS" if _month(t["timestamp"]) in oos_months else "IS"
        rows[bucket].append(t["result_R"])
    out = []
    for bucket, rr in rows.items():
        out.append({
            "window": bucket,
            "trades": len(rr),
            "total_R": round(sum(rr), 4),
            "win_rate": round(sum(1 for r in rr if r > 0) / len(rr), 4) if rr else None,
            "profit_factor": round(_profit_factor(rr), 4) if rr and _profit_factor(rr) != float("inf") else None,
        })
    return pd.DataFrame(out)


def write_all(results: Dict, cfg, out_dir: str) -> Dict:
    os.makedirs(out_dir, exist_ok=True)
    decisions = results["decisions"]
    trades = results["trades"]
    blocked = results["blocked"]

    dec_df = pd.DataFrame(decisions)
    dec_df.to_csv(os.path.join(out_dir, "decision_log.csv"), index=False)

    trade_cols = ["timestamp", "direction", "entry", "SL", "TP1", "RR", "cost_R",
                  "result_R", "exit_reason", "exit_time", "setup_reason", "mfe_R", "mae_R"]
    trade_df = pd.DataFrame(trades, columns=trade_cols)
    trade_df.to_csv(os.path.join(out_dir, "trade_log.csv"), index=False)

    summary = build_summary(results, cfg)
    # Guard from the task brief: do not present a trade-derived summary that
    # was fabricated. summary.json is always written, but its reliability_note
    # states plainly whether any trade actually filled.
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)

    # ---- spec-aligned extra artifacts ----
    if not dec_df.empty:
        ex = dec_df[dec_df["decision"] == "EXECUTE_CANDIDATE"]
        wc = dec_df[dec_df["decision"].isin(["WATCH", "CANCEL"])]
    else:
        ex = wc = dec_df
    ex.to_csv(os.path.join(out_dir, "v0_11_1_raw_EXECUTE_log.csv"), index=False)
    wc.to_csv(os.path.join(out_dir, "v0_11_1_raw_WATCH_CANCEL_log.csv"), index=False)
    pd.DataFrame(blocked).to_csv(
        os.path.join(out_dir, "v0_11_1_raw_blocked_stale_duplicate_log.csv"), index=False)

    monthly_summary(trades).to_csv(
        os.path.join(out_dir, "v0_11_1_raw_monthly_summary.csv"), index=False)
    is_oos_summary(trades, cfg).to_csv(
        os.path.join(out_dir, "v0_11_1_raw_IS_OOS_summary.csv"), index=False)
    cost_stress(trades, cfg).to_csv(
        os.path.join(out_dir, "v0_11_1_raw_cost_stress.csv"), index=False)

    dd_path = os.path.join(out_dir, "v0_11_1_raw_drawdown_summary.txt")
    with open(dd_path, "w", encoding="utf-8") as fh:
        rr = [t["result_R"] for t in trades]
        fh.write("BTC v0.11.1 RAW REPLAY — drawdown / risk summary\n")
        fh.write(f"filled_trades        : {len(trades)}\n")
        fh.write(f"total_R (net 0.08%)  : {round(sum(rr),4)}\n")
        fh.write(f"max_drawdown_R       : {round(_max_drawdown_R(rr),4) if rr else 'n/a'}\n")
        fh.write(f"max_consecutive_SL   : {_max_consecutive_sl([t['exit_reason'] for t in trades])}\n")
        fh.write(f"reliability_note     : {summary['reliability_note']}\n")

    return summary
