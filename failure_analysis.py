"""Comprehensive failure analysis of real v0.11.1 results.

Produces 14 diagnostic CSV/TXT files. NO rule changes proposed here —
pure diagnosis: which groups break the system, which survive.
"""
import csv
import collections
import math
import os
from datetime import datetime, timezone

OUT = "reports/"

# ── loaders ────────────────────────────────────────────────────────────────
def load(f): return list(csv.DictReader(open(OUT + f)))

trades   = load("trade_log.csv")
execs    = load("execute_gate_audit.csv")
blocked  = load("blocked_stale_duplicate_log.csv")
dec_log  = load("decision_log.csv")

expired  = [b for b in blocked if b.get("blocked_reason") == "candidate_expired_no_fill"]
filled   = [e for e in execs if e["filled"] == "yes"]
unfilled = [e for e in execs if e["filled"] == "no"]

def ts(s): return datetime.fromisoformat(s)
def flt(x):
    try: return float(x)
    except: return None

# ── match each trade to its source EXECUTE_CANDIDATE ─────────────────────
execs_sorted = sorted(execs, key=lambda e: ts(e["timestamp"]))
def src_exec(fill_time):
    cands = [e for e in execs_sorted if ts(e["timestamp"]) < fill_time]
    return max(cands, key=lambda e: ts(e["timestamp"]), default=None) if cands else None

matched = []  # (trade, exec_row)
for t in trades:
    ft = ts(t["timestamp"])
    e = src_exec(ft)
    matched.append((t, e))

# ── helpers ────────────────────────────────────────────────────────────────
def session(h):
    if 0 <= h < 8:  return "Asia(00-08)"
    if 8 <= h < 13: return "London(08-13)"
    if 13 <= h < 17: return "NY_Open(13-17)"
    if 17 <= h < 22: return "NY_Late(17-22)"
    return "Night(22-24)"

def month(ts_str): return ts_str[:7]

def win(t): return t["exit_reason"] == "TP1"

def summary_row(label, grp):
    rr = [flt(t["result_R"]) for t in grp if flt(t["result_R"]) is not None]
    if not rr: return {"group": label, "trades": 0, "wins": 0, "win_rate": None,
                       "total_R": None, "avg_R": None, "profit_factor": None}
    wins  = [r for r in rr if r > 0]
    losses= [r for r in rr if r < 0]
    gains = sum(wins)
    loss_abs = -sum(losses)
    pf = gains/loss_abs if loss_abs>0 else ("inf" if gains>0 else 0)
    return {"group": label, "trades": len(rr), "wins": len(wins),
            "win_rate": round(len(wins)/len(rr),3),
            "total_R": round(sum(rr),4), "avg_R": round(sum(rr)/len(rr),4),
            "profit_factor": round(pf,4) if isinstance(pf,float) else pf}

def write_csv(name, rows, fields=None):
    if not rows: return
    fields = fields or list(rows[0].keys())
    with open(OUT + name, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k,"") for k in fields})
    print(f"  {name}: {len(rows)} rows")

# ══════════════════════════════════════════════════════════════════════════
print("=== 1. direction ===")
by_dir = collections.defaultdict(list)
for t,_ in matched: by_dir[t["direction"]].append(t)
rows = [summary_row(d, by_dir[d]) for d in sorted(by_dir)]
write_csv("failure_by_direction.csv", rows)

# ══════════════════════════════════════════════════════════════════════════
print("=== 2. month ===")
by_mon = collections.defaultdict(list)
for t,_ in matched: by_mon[month(t["timestamp"])].append(t)
rows = [summary_row(m, by_mon[m]) for m in sorted(by_mon)]
write_csv("failure_by_month.csv", rows)

# ══════════════════════════════════════════════════════════════════════════
print("=== 3. IS / OOS ===")
OOS_MONTHS = {"2025-10","2026-01","2026-02","2026-03","2026-04"}
by_oos = collections.defaultdict(list)
for t,_ in matched:
    by_oos["OOS" if month(t["timestamp"]) in OOS_MONTHS else "IS"].append(t)
rows = [summary_row(k, by_oos[k]) for k in ["IS","OOS"]]
write_csv("failure_IS_OOS.csv", rows)

# ══════════════════════════════════════════════════════════════════════════
print("=== 4. hour & session ===")
by_hour = collections.defaultdict(list)
by_sess = collections.defaultdict(list)
for t,_ in matched:
    h = ts(t["timestamp"]).hour
    by_hour[h].append(t)
    by_sess[session(h)].append(t)
rows_h = [summary_row(str(h).zfill(2), by_hour[h]) for h in sorted(by_hour)]
write_csv("failure_by_hour.csv", rows_h)
rows_s = [summary_row(s, by_sess[s]) for s in sorted(by_sess)]
write_csv("failure_by_session.csv", rows_s)

# ══════════════════════════════════════════════════════════════════════════
def bin_metric(metric_key, bins, label, from_exec=True):
    """Bin trades by a quality metric from source exec row."""
    by_bin = collections.defaultdict(list)
    for t, e in matched:
        if e is None: continue
        val = flt(e[metric_key]) if from_exec else flt(t.get(metric_key,""))
        if val is None: continue
        b = None
        for lo, hi, name in bins:
            if lo <= val < hi:
                b = name; break
        if b is None:
            lo, hi, name = bins[-1]
            if val >= lo: b = name
        if b: by_bin[b].append(t)
    rows = [summary_row(b, by_bin[b]) for b in [n for _,_,n in bins] if b in by_bin]
    write_csv(f"failure_by_{label}_bin.csv", rows)

print("=== 5. TP1_R bins ===")
bin_metric("TP1_R", [
    (1.8,2.5,"1.8-2.5"), (2.5,4.0,"2.5-4.0"),
    (4.0,6.0,"4.0-6.0"), (6.0,10.0,"6.0-10.0"), (10.0,999,"10+")
], "TP1_R")

print("=== 6. R_abs_bps bins ===")
bin_metric("R_abs_bps", [
    (22,35,"22-35"), (35,50,"35-50"), (50,75,"50-75"), (75,999,"75+")
], "R_abs_bps")

print("=== 7. R_abs_ATR bins ===")
bin_metric("R_abs_ATR", [
    (0.7,1.0,"0.7-1.0"), (1.0,1.5,"1.0-1.5"),
    (1.5,2.5,"1.5-2.5"), (2.5,999,"2.5+")
], "R_abs_ATR")

print("=== 8. body_ratio bins ===")
bin_metric("body_ratio", [
    (0.30,0.40,"0.30-0.40"), (0.40,0.55,"0.40-0.55"),
    (0.55,0.70,"0.55-0.70"), (0.70,1.01,"0.70+")
], "body_ratio")

print("=== 9. close_strength bins ===")
bin_metric("acceptance_close_strength", [
    (0.60,0.70,"0.60-0.70"), (0.70,0.80,"0.70-0.80"),
    (0.80,0.90,"0.80-0.90"), (0.90,1.01,"0.90+")
], "close_strength")

print("=== 10. entry_edge_dist_band bins ===")
# entry_edge_dist_band lives in decision_log, not execute_gate_audit;
# build a lookup from decision timestamp -> value
dec_by_ts = {d["timestamp"]: d for d in dec_log}
by_bin_eed = collections.defaultdict(list)
for t, e in matched:
    if e is None: continue
    src_dec = dec_by_ts.get(e["timestamp"])
    if src_dec is None: continue
    val = flt(src_dec.get("entry_edge_dist_band",""))
    if val is None: continue
    bins_eed = [(0.0,0.01,"0.00-0.01"),(0.01,0.05,"0.01-0.05"),
                (0.05,0.15,"0.05-0.15"),(0.15,1.0,"0.15+")]
    b = None
    for lo, hi, name in bins_eed:
        if lo <= val < hi: b = name; break
    if b is None and val >= 0.15: b = "0.15+"
    if b: by_bin_eed[b].append(t)
rows_eed = [summary_row(b, by_bin_eed[b])
            for b in ["0.00-0.01","0.01-0.05","0.05-0.15","0.15+"] if b in by_bin_eed]
write_csv("failure_by_entry_edge_dist_bin.csv", rows_eed)

# ══════════════════════════════════════════════════════════════════════════
print("=== 11. fill delay (decision -> fill, in 1M bars) ===")
delay_rows = []
for t, e in matched:
    if e is None: continue
    dec_ts  = ts(e["timestamp"])
    fill_ts = ts(t["timestamp"])
    delta_min = int((fill_ts - dec_ts).total_seconds() / 60)
    delta_5m  = delta_min // 5
    delay_rows.append({
        "decision_time": e["timestamp"],
        "fill_time":     t["timestamp"],
        "direction":     t["direction"],
        "delta_1m_bars": delta_min,
        "delta_5m_bars": delta_5m,
        "exit_reason":   t["exit_reason"],
        "result_R":      t["result_R"],
    })
write_csv("fill_delay_analysis.csv", delay_rows)

# summary by delay bucket
delay_buckets = collections.defaultdict(list)
for r in delay_rows:
    d = r["delta_1m_bars"]
    if d <= 1:   bk = "0-1min"
    elif d <= 5: bk = "2-5min"
    elif d <= 15:bk = "6-15min"
    elif d <= 30:bk = "16-30min"
    else:        bk = ">30min"
    delay_buckets[bk].append({"result_R": r["result_R"],
                               "exit_reason": r["exit_reason"]})

print("  fill delay bucket summary:")
for bk in ["0-1min","2-5min","6-15min","16-30min",">30min"]:
    grp = delay_buckets.get(bk,[])
    if grp:
        rr = [flt(x["result_R"]) for x in grp]
        wins = sum(1 for r in rr if r and r>0)
        print(f"    {bk}: n={len(grp)} wins={wins} totalR={round(sum(r for r in rr if r),4)}")

# ══════════════════════════════════════════════════════════════════════════
print("=== 12. filled vs expired comparison ===")
def exec_profile(rows_list, label):
    out = {"group": label, "count": len(rows_list)}
    for col in ["R_abs_bps","R_abs_ATR","TP1_R","body_ratio",
                "acceptance_close_strength"]:
        vals = [flt(r[col]) for r in rows_list if flt(r[col]) is not None]
        out[f"{col}_mean"] = round(sum(vals)/len(vals),4) if vals else None
        out[f"{col}_median"] = round(sorted(vals)[len(vals)//2],4) if vals else None
    return out

# expired candidates: from blocked log
expired_exec_rows = []
expired_ts_set = {b["timestamp"] for b in expired}
for e in execs:
    if e["timestamp"] in expired_ts_set:
        expired_exec_rows.append(e)

cmp_rows = [exec_profile(filled, "filled_55"),
            exec_profile(expired_exec_rows, "expired_no_fill_49")]
all_keys = list(cmp_rows[0].keys())
write_csv("filled_vs_expired_comparison.csv", cmp_rows, all_keys)

# ══════════════════════════════════════════════════════════════════════════
print("=== 13. SL cluster analysis ===")
sl_rows = []
for t, e in matched:
    if t["exit_reason"] != "SL": continue
    row = {
        "fill_time":       t["timestamp"],
        "direction":       t["direction"],
        "entry":           t["entry"],
        "result_R":        t["result_R"],
        "mfe_R":           t["mfe_R"],
        "mae_R":           t["mae_R"],
        "RR":              t["RR"],
        "exit_time":       t["exit_time"],
        "TP1_R":           e["TP1_R"] if e else "",
        "R_abs_bps":       e["R_abs_bps"] if e else "",
        "R_abs_ATR":       e["R_abs_ATR"] if e else "",
        "body_ratio":      e["body_ratio"] if e else "",
        "close_strength":  e["acceptance_close_strength"] if e else "",
        "h1_context":      "",  # filled below from decision_log
        "m15_zone":        "",
    }
    sl_rows.append(row)

# attach h1_context / m15_zone from decision_log (closest prior decision)
dec_sorted = sorted(dec_log, key=lambda d: d["timestamp"])
for row in sl_rows:
    ft = row["fill_time"]
    prior = [d for d in dec_sorted if d["timestamp"] < ft and d["decision"]=="EXECUTE_CANDIDATE"]
    if prior:
        src = max(prior, key=lambda d: d["timestamp"])
        row["h1_context"] = src.get("h1_context","")
        row["m15_zone"]   = src.get("m15_zone","")

write_csv("SL_cluster_analysis.csv", sl_rows)
print("  SL h1_context breakdown:",
      collections.Counter(r["h1_context"] for r in sl_rows))
print("  SL direction:",
      collections.Counter(r["direction"] for r in sl_rows))
mfe_vals = [flt(r["mfe_R"]) for r in sl_rows if flt(r["mfe_R"]) is not None]
print(f"  SL mfe_R: mean={round(sum(mfe_vals)/len(mfe_vals),3)} "
      f"max={round(max(mfe_vals),3)} "
      f"reached_1R={sum(1 for v in mfe_vals if v>=1.0)}/{len(mfe_vals)}")

# ══════════════════════════════════════════════════════════════════════════
print("=== 14. TP1 winner profile ===")
tp_rows = []
for t, e in matched:
    if t["exit_reason"] != "TP1": continue
    row = {
        "fill_time":      t["timestamp"],
        "direction":      t["direction"],
        "result_R":       t["result_R"],
        "mfe_R":          t["mfe_R"],
        "mae_R":          t["mae_R"],
        "RR":             t["RR"],
        "exit_time":      t["exit_time"],
        "TP1_R":          e["TP1_R"] if e else "",
        "R_abs_bps":      e["R_abs_bps"] if e else "",
        "R_abs_ATR":      e["R_abs_ATR"] if e else "",
        "body_ratio":     e["body_ratio"] if e else "",
        "close_strength": e["acceptance_close_strength"] if e else "",
        "h1_context": "", "m15_zone": "",
    }
    for d in dec_sorted:
        if d["timestamp"] < t["timestamp"] and d["decision"]=="EXECUTE_CANDIDATE":
            latest = d
    if 'latest' in dir():
        row["h1_context"] = latest.get("h1_context","")
        row["m15_zone"]   = latest.get("m15_zone","")
    tp_rows.append(row)

write_csv("TP1_winner_profile.csv", tp_rows)
print("  TP1 direction:", collections.Counter(r["direction"] for r in tp_rows))
print("  TP1 h1_context:", collections.Counter(r["h1_context"] for r in tp_rows))

# ══════════════════════════════════════════════════════════════════════════
print("=== 15. max consecutive SL period regime ===")
sl_streak = []
cur_streak = []
best_streak = []
for t,_ in matched:
    if t["exit_reason"] == "SL":
        cur_streak.append(t)
        if len(cur_streak) > len(best_streak):
            best_streak = cur_streak[:]
    else:
        cur_streak = []
print(f"  max consecutive SL streak: {len(best_streak)}")
if best_streak:
    print(f"  streak period: {best_streak[0]['timestamp']} -> {best_streak[-1]['exit_time']}")
    streak_dir = collections.Counter(t["direction"] for t in best_streak)
    print(f"  direction: {dict(streak_dir)}")
    # look up h1_context for each SL in streak
    streak_ctx = []
    for t in best_streak:
        ft = t["timestamp"]
        prior = [d for d in dec_sorted if d["timestamp"]<ft and d["decision"]=="EXECUTE_CANDIDATE"]
        if prior:
            src = max(prior, key=lambda d: d["timestamp"])
            streak_ctx.append(src.get("h1_context",""))
    print(f"  h1_context during streak: {collections.Counter(streak_ctx)}")

# ══════════════════════════════════════════════════════════════════════════
print("=== writing failure_analysis_summary.txt ===")

# collect all bin summaries for the text report
def read_csv_rows(name):
    try: return list(csv.DictReader(open(OUT + name)))
    except: return []

def fmt_rows(rows):
    lines = []
    for r in rows:
        parts = [f"{k}={v}" for k,v in r.items()]
        lines.append("  " + " | ".join(parts))
    return "\n".join(lines)

with open(OUT + "failure_analysis_summary.txt", "w") as fh:
    def w(s=""): fh.write(s + "\n")
    w("BTC v0.11.1 SRR-1 FAILURE ANALYSIS — real data, no rule changes proposed")
    w(f"run date: 2026-06-13  data: 2025-05 to 2026-04 (missing 2026-02)")
    w()
    w("── FUNNEL ─────────────────────────────────────────────────────────────")
    w("total 5M decisions    : 97056")
    w("setups formed (SRR-1) : 3758")
    w("after v0.10.1         : 2591 PASS | 263 WATCH | 904 CANCEL")
    w("after v0.11 A+        :  116 PASS | 2475 CANCEL  (hardest gate)")
    w("after v0.11.1         :  104 EXECUTE_CANDIDATE | 12 BLOCKED")
    w("retest fill           :   55 filled | 49 expired-no-fill")
    w("filled_trade          :   55  (7 TP1 | 48 SL)")
    w("net R (0.08% cost)    : -22.20")
    w()
    w("── 1. DIRECTION ────────────────────────────────────────────────────────")
    w(fmt_rows(read_csv_rows("failure_by_direction.csv")))
    w()
    w("── 2. MONTHLY ──────────────────────────────────────────────────────────")
    w(fmt_rows(read_csv_rows("failure_by_month.csv")))
    w()
    w("── 3. IS / OOS ─────────────────────────────────────────────────────────")
    w(fmt_rows(read_csv_rows("failure_IS_OOS.csv")))
    w()
    w("── 4. SESSION (fill time UTC) ──────────────────────────────────────────")
    w(fmt_rows(read_csv_rows("failure_by_session.csv")))
    w()
    w("── 5. TP1_R BINS ───────────────────────────────────────────────────────")
    w(fmt_rows(read_csv_rows("failure_by_TP1_R_bin.csv")))
    w()
    w("── 6. R_abs_bps BINS ───────────────────────────────────────────────────")
    w(fmt_rows(read_csv_rows("failure_by_R_abs_bps_bin.csv")))
    w()
    w("── 7. R_abs_ATR BINS ───────────────────────────────────────────────────")
    w(fmt_rows(read_csv_rows("failure_by_R_abs_ATR_bin.csv")))
    w()
    w("── 8. BODY_RATIO BINS ──────────────────────────────────────────────────")
    w(fmt_rows(read_csv_rows("failure_by_body_ratio_bin.csv")))
    w()
    w("── 9. CLOSE_STRENGTH BINS ──────────────────────────────────────────────")
    w(fmt_rows(read_csv_rows("failure_by_close_strength_bin.csv")))
    w()
    w("── 10. ENTRY_EDGE_DIST BINS ────────────────────────────────────────────")
    w(fmt_rows(read_csv_rows("failure_by_entry_edge_dist_bin.csv")))
    w()
    w("── 11. FILL DELAY (decision -> fill) ───────────────────────────────────")
    w(fmt_rows(read_csv_rows("fill_delay_analysis.csv")[:0]))  # header only shown inline
    delay_rows_all = read_csv_rows("fill_delay_analysis.csv")
    bucket_cnt = collections.Counter(
        "0-1min" if int(r["delta_1m_bars"])<=1
        else "2-5min" if int(r["delta_1m_bars"])<=5
        else "6-15min" if int(r["delta_1m_bars"])<=15
        else "16-30min" if int(r["delta_1m_bars"])<=30
        else ">30min"
        for r in delay_rows_all
    )
    for bk in ["0-1min","2-5min","6-15min","16-30min",">30min"]:
        w(f"  {bk}: {bucket_cnt.get(bk,0)} trades")
    w()
    w("── 12. FILLED vs EXPIRED QUALITY COMPARISON ────────────────────────────")
    w(fmt_rows(read_csv_rows("filled_vs_expired_comparison.csv")))
    w()
    w("── 13. SL CLUSTER KEY STATS ────────────────────────────────────────────")
    sl_data = read_csv_rows("SL_cluster_analysis.csv")
    sl_dir  = collections.Counter(r["direction"] for r in sl_data)
    sl_ctx  = collections.Counter(r["h1_context"] for r in sl_data)
    mfe_sl  = [flt(r["mfe_R"]) for r in sl_data if flt(r["mfe_R"]) is not None]
    w(f"  n=48  direction={dict(sl_dir)}  h1_context={dict(sl_ctx)}")
    w(f"  mfe_R: mean={round(sum(mfe_sl)/len(mfe_sl),3)}  max={round(max(mfe_sl),3)}")
    w(f"  reached >=0.5R before SL: {sum(1 for v in mfe_sl if v>=0.5)}/48")
    w(f"  reached >=1.0R before SL: {sum(1 for v in mfe_sl if v>=1.0)}/48")
    w(f"  reached >=2.0R before SL: {sum(1 for v in mfe_sl if v>=2.0)}/48")
    w()
    w("── 14. TP1 WINNER PROFILE ──────────────────────────────────────────────")
    tp_data = read_csv_rows("TP1_winner_profile.csv")
    tp_dir  = collections.Counter(r["direction"] for r in tp_data)
    tp_ctx  = collections.Counter(r["h1_context"] for r in tp_data)
    tp_rr   = [flt(r["RR"]) for r in tp_data if flt(r["RR"]) is not None]
    tp_mfe  = [flt(r["mfe_R"]) for r in tp_data if flt(r["mfe_R"]) is not None]
    w(f"  n=7  direction={dict(tp_dir)}  h1_context={dict(tp_ctx)}")
    w(f"  RR range: {round(min(tp_rr),2)} - {round(max(tp_rr),2)}  mean={round(sum(tp_rr)/len(tp_rr),2)}")
    w(f"  mfe_R mean={round(sum(tp_mfe)/len(tp_mfe),3) if tp_mfe else 'n/a'}")
    w()
    w("── 15. MAX CONSECUTIVE SL PERIOD ───────────────────────────────────────")
    w(f"  max streak: {len(best_streak)}")
    if best_streak:
        w(f"  period: {best_streak[0]['timestamp']} -> {best_streak[-1]['exit_time']}")
        w(f"  direction: {dict(collections.Counter(t['direction'] for t in best_streak))}")
        w(f"  h1_context during streak: {collections.Counter(streak_ctx)}")
    w()
    w("── 16. LONG STRUCTURAL LOSS — IS IT REGIME-DEPENDENT? ─────────────────")
    # check: is the long loss evenly distributed or concentrated in a few months?
    long_by_month = collections.defaultdict(list)
    short_by_month = collections.defaultdict(list)
    for t,_ in matched:
        m = month(t["timestamp"])
        rr = flt(t["result_R"])
        if rr is None: continue
        if t["direction"] == "long":  long_by_month[m].append(rr)
        else: short_by_month[m].append(rr)
    w("  long R by month:")
    for m in sorted(long_by_month):
        rr = long_by_month[m]
        w(f"    {m}: n={len(rr)} totalR={round(sum(rr),3)} wins={sum(1 for r in rr if r>0)}")
    w("  short R by month:")
    for m in sorted(short_by_month):
        rr = short_by_month[m]
        w(f"    {m}: n={len(rr)} totalR={round(sum(rr),3)} wins={sum(1 for r in rr if r>0)}")
    w()
    w("── KEY FINDING ─────────────────────────────────────────────────────────")
    w("  No rule changes proposed. Raw findings for review only.")

print("  failure_analysis_summary.txt written")
print("\nAll 14+ outputs written to reports/")
