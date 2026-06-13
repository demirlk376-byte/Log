"""signal_engine.py — SINGLE SOURCE OF TRUTH.

`evaluate_at_5m_close` is called identically by the replay engine and (later)
by the live/paper alarm bot. It takes only CLOSED candle history plus engine
state and returns a decision dict. It never touches the future.

Decision chain:
  1. 1H context
  2. 15M range/edge  (middle -> CANCEL, unclear -> WATCH/CANCEL)
  3. 5M sweep + reclaim -> Setup (entry/SL/TP1)
  4. v0.10.1 Soft Acceptance
  5. v0.11 BTC A+ Cost-Survival
  6. v0.11.1 No-Stale-Reentry / No Duplicate Promotion
  -> WATCH | CANCEL | EXECUTE_CANDIDATE  (+ reason_tags)
"""
from __future__ import annotations

from typing import Dict, List, Sequence

from . import indicators as ind
from . import rules_v10_1, rules_v11, rules_v11_1, structure
from .rules_v11_1 import EngineState, setup_identity

Candle = dict


def _empty_decision(ts, decision, tags, **extra) -> Dict:
    base = {
        "timestamp": ts,
        "decision": decision,
        "setup_family": "SRR-1",
        "direction": None,
        "h1_context": None,
        "m15_zone": None,
        "edge_id": None,
        "sweep_id": None,
        "entry": None, "SL": None, "TP1": None,
        "R_abs": None, "R_abs_bps": None, "R_abs_ATR": None, "TP1_R": None,
        "body_ratio": None, "acceptance_close_strength": None,
        "opposite_wick_ratio": None, "entry_edge_dist_band": None,
        "acceptance_weakness_count": None,
        "v10_1_result": None, "v11_result": None, "v11_1_result": None,
        "duplicate_state": None, "cooldown_state": None,
        "setup_id": None,
        "reason_tags": ",".join(tags),
    }
    base.update(extra)
    return base


def evaluate_at_5m_close(
    ts,
    m5: Sequence[Candle],
    m15: Sequence[Candle],
    h1: Sequence[Candle],
    state: EngineState,
    cfg,
) -> Dict:
    """Evaluate one 5M close. Returns a decision dict + (if EXECUTE_CANDIDATE)
    a `setup` object the replay layer uses to manage the pending entry."""
    if "SRR-1" not in cfg.setups["enabled"]:
        return _empty_decision(ts, "CANCEL", ["srr1_disabled"])

    cd = "active" if state.cooldown_active() else "clear"

    atr5 = ind.atr(list(m5), cfg.indicators["atr_period"])
    ctx = structure.h1_context(h1, cfg)
    rng = structure.m15_range(m15, cfg)
    edge = structure.classify_edge(rng, atr5, cfg)

    common = {"h1_context": ctx, "m15_zone": edge, "cooldown_state": cd}

    if rng is None:
        return _empty_decision(ts, "WATCH", ["m15_range_insufficient"], **common)
    if edge == "middle":
        return _empty_decision(ts, "CANCEL", ["range_middle"], **common)
    if edge == "unclear":
        return _empty_decision(ts, "WATCH", ["edge_unclear"], **common)

    setup = structure.detect_srr1(list(m5), rng, edge, atr5, cfg)
    if setup is None:
        return _empty_decision(ts, "WATCH", ["no_sweep_reclaim"], **common,
                               edge_id=(rng.edge_id_low if edge == "lower_edge" else rng.edge_id_high))

    # Geometry / quality features now available.
    geo = {
        "direction": setup.direction,
        "edge_id": setup.edge_id,
        "sweep_id": setup.sweep_id,
        "entry": setup.entry, "SL": setup.sl, "TP1": setup.tp1,
        "R_abs": setup.r_abs, "R_abs_bps": setup.r_abs_bps,
        "R_abs_ATR": setup.r_abs_atr, "TP1_R": setup.tp1_r,
        "entry_edge_dist_band": setup.entry_edge_dist_band,
        "setup_id": setup_identity(state.symbol, setup),
    }

    # --- v0.10.1 Soft Acceptance ---
    v10 = rules_v10_1.evaluate(setup, cfg)
    feats = v10["features"]
    geo.update({
        "body_ratio": feats["body_ratio"],
        "acceptance_close_strength": feats["acceptance_close_strength"],
        "opposite_wick_ratio": feats["opposite_wick_ratio"],
        "acceptance_weakness_count": v10["weakness_count"],
        "v10_1_result": v10["result"],
    })
    if v10["result"] == "CANCEL":
        return _empty_decision(ts, "CANCEL", v10["tags"], **common, **geo, setup=setup)
    if v10["result"] == "WATCH":
        return _empty_decision(ts, "WATCH", v10["tags"], **common, **geo, setup=setup)

    # --- v0.11 BTC A+ Cost-Survival ---
    v11 = rules_v11.evaluate(setup, v10, cfg)
    geo["v11_result"] = v11["result"]
    if v11["result"] == "CANCEL":
        return _empty_decision(ts, "CANCEL", v10["tags"] + v11["tags"], **common, **geo, setup=setup)

    # --- v0.11.1 No-Stale-Reentry / No Duplicate Promotion ---
    v111 = rules_v11_1.evaluate(setup, state, cfg)
    geo["v11_1_result"] = v111["result"]
    geo["duplicate_state"] = "duplicate" if "duplicate_promotion_candidate" in v111["tags"] else "fresh"
    if v111["blocked"]:
        return _empty_decision(ts, "WATCH", v10["tags"] + v11["tags"] + v111["tags"],
                               **common, **geo, setup=setup)

    # Clean promotion.
    return _empty_decision(ts, "EXECUTE_CANDIDATE",
                           v10["tags"] + v11["tags"] + v111["tags"],
                           **common, **geo, setup=setup)
