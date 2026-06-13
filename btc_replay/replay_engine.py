"""replay_engine.py — drives the single signal engine over 1M data.

Single forward pass over 1M candles. At each 5M close the engine decides;
EXECUTE_CANDIDATE creates a PENDING entry that is only counted as a trade once
price actually touches the entry (the retest). TP/SL are resolved strictly on
1M candles AFTER the decision, with SL-first on same-candle ties.

No-lookahead invariants enforced here:
  * decisions use only candles whose close_time <= the decision close_time,
  * pending fills / exits use only 1M candles whose close_time > decision time,
  * if entry never trades within the candidate lifetime, it is NOT a trade.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from . import data_loader, signal_engine
from .config import Config
from .rules_v11_1 import EngineState


def _to_candles(df: pd.DataFrame) -> List[dict]:
    return df[["open_time", "close_time", "open", "high", "low", "close", "volume"]].to_dict("records")


class Pending:
    def __init__(self, decision: Dict, setup, expiry_time):
        self.d = decision
        self.s = setup
        self.expiry_time = expiry_time
        self.filled = False
        self.fill_time = None
        self.mfe_R = 0.0
        self.mae_R = 0.0


def bar_outcome(direction: str, sl: float, tp1: float, low: float, high: float,
                sl_first: bool = True) -> Optional[str]:
    """Resolve a single 1M bar against SL/TP1. Returns 'SL', 'TP1' or None.

    Conservative tie rule: if both SL and TP1 are touched inside the same 1M
    candle, SL wins (the no-lookahead acceptance requirement).
    """
    if direction == "long":
        hit_sl = low <= sl
        hit_tp = high >= tp1
    else:
        hit_sl = high >= sl
        hit_tp = low <= tp1
    if hit_sl and (sl_first or not hit_tp):
        return "SL"
    if hit_tp:
        return "TP1"
    return None


def _update_excursion(p: Pending, low: float, high: float) -> None:
    s = p.s
    if s.r_abs <= 0:
        return
    if s.direction == "long":
        fav = (high - s.entry) / s.r_abs
        adv = (s.entry - low) / s.r_abs
    else:
        fav = (s.entry - low) / s.r_abs
        adv = (high - s.entry) / s.r_abs
    p.mfe_R = max(p.mfe_R, fav)
    p.mae_R = max(p.mae_R, adv)


def run_replay(data_dir: str, cfg: Config) -> Dict:
    symbol = cfg["symbol"]
    df1 = data_loader.load_1m(data_dir, symbol)
    continuity = data_loader.validate_continuity(df1)

    df5 = data_loader.resample(df1, "5min")
    df15 = data_loader.resample(df1, "15min")
    dfh1 = data_loader.resample(df1, "1h")
    # closed & complete only
    df5 = df5[df5["full"]].reset_index(drop=True)
    df15 = df15[df15["full"]].reset_index(drop=True)
    dfh1 = dfh1[dfh1["full"]].reset_index(drop=True)

    c5 = _to_candles(df5)
    c15 = _to_candles(df15)
    ch1 = _to_candles(dfh1)
    boundary_5m = set(df5["close_time"].tolist())

    state = EngineState(symbol=symbol)
    decisions: List[dict] = []
    trades: List[dict] = []
    blocked: List[dict] = []

    pending: Optional[Pending] = None
    i5 = i15 = ih1 = 0  # pointers: number of TF candles closed so far

    cost_frac = cfg.costs["primary_roundtrip_bps"] / 10000.0
    cooldown_bars = cfg.v11_1["cooldown_bars_5m"]
    lifetime = cfg.execution["candidate_lifetime_5m"]
    sl_first = cfg.execution["sl_first_on_tie"]

    # Bounded windows handed to the engine each 5M close. The engine only ever
    # looks back a fixed number of candles; passing tails keeps the replay O(n)
    # (full-history slices would make it O(n^2)).
    w5 = cfg.indicators["atr_period"] + cfg.geometry["sweep_lookback_5m"] + 5
    w15 = cfg.structure["m15_range_lookback"] + 2
    wh1 = cfg.structure["h1_context_lookback"] + 2

    closes_time = (df1["timestamp"] + pd.Timedelta("1min")).tolist()
    highs = df1["high"].tolist()
    lows = df1["low"].tolist()

    def close_trade(p: Pending, exit_reason: str, exit_time, gross_R: float) -> None:
        nonlocal pending
        s = p.s
        cost_R = (cost_frac * s.entry) / s.r_abs if s.r_abs > 0 else 0.0
        result_R = gross_R - cost_R
        trades.append({
            "timestamp": p.fill_time,
            "direction": s.direction,
            "entry": round(s.entry, 2),
            "SL": round(s.sl, 2),
            "TP1": round(s.tp1, 2),
            "RR": round(s.tp1_r, 4),
            "cost_R": round(cost_R, 4),
            "result_R": round(result_R, 4),
            "exit_reason": exit_reason,
            "exit_time": exit_time,
            "setup_reason": p.d["reason_tags"],
            "mfe_R": round(p.mfe_R, 4),
            "mae_R": round(p.mae_R, 4),
        })
        state.active_setup_id = None
        state.start_cooldown(cooldown_bars)
        pending = None

    for k in range(len(df1)):
        ct = closes_time[k]
        hi = highs[k]
        lo = lows[k]

        # ---- step 1: progress any pending/open order on THIS 1M candle ----
        if pending is not None:
            s = pending.s
            if not pending.filled:
                # expire candidate if entry never touched within lifetime
                if ct > pending.expiry_time:
                    blocked.append({**pending.d, "blocked_reason": "candidate_expired_no_fill",
                                    "expiry_time": pending.expiry_time})
                    state.active_setup_id = None
                    state.start_cooldown(cooldown_bars)
                    pending = None
                else:
                    touched = lo <= s.entry <= hi
                    if touched:
                        pending.filled = True
                        pending.fill_time = ct
                        _update_excursion(pending, lo, hi)
                        # same-candle resolution after fill (SL-first on tie)
                        outcome = bar_outcome(s.direction, s.sl, s.tp1, lo, hi, sl_first)
                        if outcome == "SL":
                            close_trade(pending, "SL", ct, -1.0)
                        elif outcome == "TP1":
                            close_trade(pending, "TP1", ct, s.tp1_r)
            elif pending is not None and pending.filled:
                _update_excursion(pending, lo, hi)
                outcome = bar_outcome(s.direction, s.sl, s.tp1, lo, hi, sl_first)
                if outcome == "SL":
                    close_trade(pending, "SL", ct, -1.0)
                elif outcome == "TP1":
                    close_trade(pending, "TP1", ct, s.tp1_r)

        # ---- step 2: decision at 5M close ----
        if ct in boundary_5m:
            # advance closed-candle pointers to everything closed at or before ct
            while i5 < len(c5) and c5[i5]["close_time"] <= ct:
                i5 += 1
            while i15 < len(c15) and c15[i15]["close_time"] <= ct:
                i15 += 1
            while ih1 < len(ch1) and ch1[ih1]["close_time"] <= ct:
                ih1 += 1

            state.bar_index_5m += 1
            d = signal_engine.evaluate_at_5m_close(
                ct,
                c5[max(0, i5 - w5):i5],
                c15[max(0, i15 - w15):i15],
                ch1[max(0, ih1 - wh1):ih1],
                state, cfg,
            )
            setup = d.pop("setup", None)
            decisions.append(d)

            tags = d["reason_tags"]
            if d["decision"] == "WATCH" and d.get("setup_id"):
                state.prior_watch_ids.add(d["setup_id"])
                if any(t in tags for t in (
                    "same_edge_same_sweep_reentry", "active_setup_exists",
                    "cooldown_active", "late_reentry_after_prior_watch",
                    "duplicate_promotion_candidate")):
                    blocked.append({**d, "blocked_reason": "stale_or_duplicate"})

            if d["decision"] == "EXECUTE_CANDIDATE" and setup is not None and pending is None:
                state.active_setup_id = d["setup_id"]
                state.promoted_ids.add(d["setup_id"])
                expiry = ct + pd.Timedelta(minutes=5 * lifetime)
                pending = Pending(d, setup, expiry)

    return {
        "continuity": continuity,
        "decisions": decisions,
        "trades": trades,
        "blocked": blocked,
        "data_span": {"start": continuity["start"], "end": continuity["end"]},
    }
