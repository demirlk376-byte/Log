"""Gate audit for the REAL v0.11.1 chain run.

Proves the decision chain actually executed, in order:
    v0.10.1 Soft Acceptance -> v0.11 BTC A+ Cost-Survival
    -> v0.11.1 No-Stale-Reentry / No Duplicate Promotion
by replaying the per-decision gate results recorded in decision_log.csv.

Writes the requested audit CSVs into reports/.
"""
import csv
import collections
from datetime import datetime

R = "reports/"
dec = list(csv.DictReader(open(R + "decision_log.csv")))
trades = list(csv.DictReader(open(R + "trade_log.csv")))
blocked = list(csv.DictReader(open(R + "blocked_stale_duplicate_log.csv")))

DEC_COLS = dec[0].keys()


def w(name, rows, cols=None):
    cols = cols or DEC_COLS
    with open(R + name, "w", newline="") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(cols))
        wr.writeheader()
        for r in rows:
            wr.writerow({k: r.get(k, "") for k in cols})
    print(f"  wrote {name}: {len(rows)} rows")


# A decision "formed a setup" iff detect_srr1 returned one (setup_id present).
formed = [r for r in dec if r["setup_id"]]
total_dec = len(dec)

# ---- funnel ----
v10 = collections.Counter(r["v10_1_result"] for r in formed)               # PASS/WATCH/CANCEL
after_v10 = [r for r in formed if r["v10_1_result"] == "PASS"]
v11 = collections.Counter(r["v11_result"] for r in after_v10)              # PASS/CANCEL
after_v11 = [r for r in after_v10 if r["v11_result"] == "PASS"]
v111 = collections.Counter(r["v11_1_result"] for r in after_v11)           # PASS/WATCH
execs = [r for r in dec if r["decision"] == "EXECUTE_CANDIDATE"]

expired_ts = {b["timestamp"] for b in blocked if b.get("blocked_reason") == "candidate_expired_no_fill"}
filled_execs = [e for e in execs if e["timestamp"] not in expired_ts]

# map each trade -> source EXECUTE (most recent EXECUTE strictly before fill)
for e in execs:
    e["_ts"] = datetime.fromisoformat(e["timestamp"])
execs_sorted = sorted(execs, key=lambda e: e["_ts"])
exec_result = {}
for t in trades:
    ft = datetime.fromisoformat(t["timestamp"])
    src = max((e for e in execs_sorted if e["_ts"] < ft), key=lambda e: e["_ts"], default=None)
    if src:
        exec_result[src["timestamp"]] = (t["exit_reason"], t["result_R"])

print("\n==== v0.11.1 CHAIN FUNNEL (real data) ====")
print(f"total 5M decisions           : {total_dec}")
print(f"  -> setups formed (SRR-1)   : {len(formed)}")
print(f"[v0.10.1 Soft Acceptance]    PASS={v10['PASS']}  WATCH={v10['WATCH']}  CANCEL={v10['CANCEL']}")
print(f"[v0.11 A+ Cost-Survival]     in={len(after_v10)}  PASS={v11['PASS']}  CANCEL={v11['CANCEL']}")
print(f"[v0.11.1 Stale/Duplicate]    in={len(after_v11)}  clear(PASS)={v111['PASS']}  BLOCKED(WATCH)={v111['WATCH']}")
print(f"=> EXECUTE_CANDIDATE         : {len(execs)}")
print(f"   of which filled (retest)  : {len(filled_execs)}")
print(f"   expired no-fill           : {len(expired_ts)}")
print(f"   filled trades in log      : {len(trades)}")

# ---- audit CSVs ----
print("\n==== writing audit files ====")
# gate_breakdown.csv
gb = [
    {"stage": "setups_formed_SRR1", "input": total_dec, "pass": len(formed), "blocked": "", "note": "5M closes with a sweep+reclaim setup"},
    {"stage": "v0_10_1_soft_acceptance", "input": len(formed), "pass": v10["PASS"], "blocked": v10["WATCH"] + v10["CANCEL"], "note": f"WATCH={v10['WATCH']} CANCEL={v10['CANCEL']}"},
    {"stage": "v0_11_aplus_cost_survival", "input": len(after_v10), "pass": v11["PASS"], "blocked": v11["CANCEL"], "note": "CANCEL on hard-fail/quality/sub2r"},
    {"stage": "v0_11_1_stale_duplicate", "input": len(after_v11), "pass": v111["PASS"], "blocked": v111["WATCH"], "note": "blocked -> WATCH (cooldown/active/dup/prior-watch)"},
    {"stage": "EXECUTE_CANDIDATE", "input": len(after_v11), "pass": len(execs), "blocked": "", "note": "clean promotions"},
    {"stage": "retest_fill", "input": len(execs), "pass": len(filled_execs), "blocked": len(expired_ts), "note": "entry must actually trade; else expire"},
]
with open(R + "gate_breakdown.csv", "w", newline="") as fh:
    wr = csv.DictWriter(fh, fieldnames=["stage", "input", "pass", "blocked", "note"])
    wr.writeheader(); wr.writerows(gb)
print(f"  wrote gate_breakdown.csv: {len(gb)} rows")

# execute_gate_audit.csv (one row per EXECUTE_CANDIDATE + fill outcome)
audit_cols = ["timestamp", "direction", "edge_id", "sweep_id", "entry", "SL", "TP1",
              "R_abs_bps", "R_abs_ATR", "TP1_R", "body_ratio", "acceptance_close_strength",
              "acceptance_weakness_count", "v10_1_result", "v11_result", "v11_1_result",
              "duplicate_state", "cooldown_state", "reason_tags", "filled", "exit_reason", "result_R"]
arows = []
for e in execs_sorted:
    er = exec_result.get(e["timestamp"])
    row = {k: e.get(k, "") for k in audit_cols if k in e}
    row["filled"] = "yes" if e["timestamp"] not in expired_ts else "no"
    row["exit_reason"] = er[0] if er else ""
    row["result_R"] = er[1] if er else ""
    arows.append(row)
with open(R + "execute_gate_audit.csv", "w", newline="") as fh:
    wr = csv.DictWriter(fh, fieldnames=audit_cols)
    wr.writeheader(); wr.writerows(arows)
print(f"  wrote execute_gate_audit.csv: {len(arows)} rows")

# blocked-by-gate files
w("blocked_by_v10_1.csv", [r for r in formed if r["v10_1_result"] in ("WATCH", "CANCEL")])
w("blocked_by_v11_aplus.csv", [r for r in after_v10 if r["v11_result"] == "CANCEL"])
w("blocked_by_v11_1_stale_duplicate.csv", [r for r in after_v11 if r["v11_1_result"] == "WATCH"])
