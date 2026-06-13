"""Diagnostic-only analysis of the REAL replay output.

Reads reports/decision_log.csv + reports/trade_log.csv and explains WHERE the
negative R comes from. This is cause-analysis (acceptance criterion #9): it does
NOT change any threshold and does NOT search for a positive configuration. The
'what-if TP' section is a measurement of realized MFE, not a tuned result.
"""
import csv
import collections
from datetime import datetime

DEC = "reports/decision_log.csv"
TR = "reports/trade_log.csv"


def parse_ts(s):
    return datetime.fromisoformat(s)


def load():
    decisions = list(csv.DictReader(open(DEC)))
    trades = list(csv.DictReader(open(TR)))
    execs = [d for d in decisions if d["decision"] == "EXECUTE_CANDIDATE"]
    for e in execs:
        e["_ts"] = parse_ts(e["timestamp"])
    execs.sort(key=lambda e: e["_ts"])
    return execs, trades


def match_trade_to_exec(trades, execs):
    """Each fill originates from the most recent EXECUTE_CANDIDATE strictly
    before the fill time (one active setup at a time guarantees uniqueness)."""
    out = []
    for t in trades:
        ft = parse_ts(t["timestamp"])
        cand = [e for e in execs if e["_ts"] < ft]
        src = max(cand, key=lambda e: e["_ts"]) if cand else None
        out.append((t, src))
    return out


def main():
    execs, trades = load()
    matched = match_trade_to_exec(trades, execs)
    n = len(trades)
    print(f"trades={n}  candidates(EXECUTE)={len(execs)}  fill_rate={n/len(execs):.1%}")

    # ---- 1. exit breakdown ----
    ex = collections.Counter(t["exit_reason"] for t in trades)
    print("\n[1] exit_reason:", dict(ex))

    # ---- 2. by direction ----
    print("\n[2] direction win/total  netR")
    byd = collections.defaultdict(lambda: [0, 0, 0.0])
    for t in trades:
        d = byd[t["direction"]]
        d[1] += 1
        d[2] += float(t["result_R"])
        if t["exit_reason"] == "TP1":
            d[0] += 1
    for k, v in byd.items():
        print(f"   {k:5s}: {v[0]}/{v[1]} wins  netR={v[2]:+.2f}")

    # ---- 3. with vs against 1H context ----
    print("\n[3] trade vs 1H context (long+bullish / short+bearish = WITH trend)")
    bucket = collections.defaultdict(lambda: [0, 0, 0.0])
    for t, src in matched:
        if not src:
            continue
        ctx = src["h1_context"]
        d = t["direction"]
        if (d == "long" and ctx == "bullish") or (d == "short" and ctx == "bearish"):
            rel = "WITH_trend"
        elif ctx in ("bullish", "bearish"):
            rel = "COUNTER_trend"
        else:
            rel = f"ctx_{ctx}"
        b = bucket[rel]
        b[1] += 1
        b[2] += float(t["result_R"])
        if t["exit_reason"] == "TP1":
            b[0] += 1
    for k, v in sorted(bucket.items()):
        print(f"   {k:14s}: {v[0]}/{v[1]} wins  netR={v[2]:+.2f}")

    # ---- 4. how fast do SLs hit (fake-reclaim test) ----
    print("\n[4] SL speed: minutes from fill to SL exit")
    fast = collections.Counter()
    for t in trades:
        if t["exit_reason"] != "SL":
            continue
        mins = (parse_ts(t["exit_time"]) - parse_ts(t["timestamp"])).total_seconds() / 60
        if mins <= 2:
            fast["<=2min"] += 1
        elif mins <= 15:
            fast["<=15min"] += 1
        elif mins <= 60:
            fast["<=60min"] += 1
        else:
            fast[">60min"] += 1
    print("   ", dict(fast))

    # ---- 5. MFE of losers: did price go our way before stopping? ----
    print("\n[5] losers' MFE_R (max favorable before SL) — tests 'TP=opposite edge too far'")
    losers = [t for t in trades if t["exit_reason"] == "SL"]
    for thr in (0.5, 1.0, 1.5, 2.0, 3.0):
        c = sum(1 for t in losers if float(t["mfe_R"]) >= thr)
        print(f"   losers reaching >= {thr}R favorable before SL: {c}/{len(losers)}")

    # ---- 6. RR (TP1_R) of trades ----
    rr = [float(t["RR"]) for t in trades]
    rr.sort()
    print(f"\n[6] realized RR (TP1_R): min={rr[0]:.2f} median={rr[len(rr)//2]:.2f} max={rr[-1]:.2f}")

    # ---- 7. WHAT-IF fixed TP (diagnostic measurement, NOT a tuned result) ----
    # win iff realized MFE_R >= target; cost ~ mean realized cost_R.
    mean_cost = sum(float(t["cost_R"]) for t in trades) / n
    print(f"\n[7] WHAT-IF fixed TP target (uses realized MFE; mean cost_R={mean_cost:.3f})")
    print("    target |  wins | win_rate |   netR (incl cost)")
    for tgt in (1.0, 1.5, 2.0, 2.5, 3.0):
        wins = sum(1 for t in trades if float(t["mfe_R"]) >= tgt)
        losses = n - wins
        netR = wins * (tgt - mean_cost) + losses * (-1.0 - mean_cost)
        print(f"    {tgt:4.1f}R  |  {wins:3d}  |  {wins/n:6.1%}  |  {netR:+.2f}")
    print("    (current opposite-edge TP -> 7 wins / 12.7% / -22.20R)")


if __name__ == "__main__":
    main()
