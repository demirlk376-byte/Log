"""rules_v11.py — v0.11 BTC A+ Cost-Survival.

Gates a setup on absolute-R survivability against costs and on TP1_R quality.
Returns PASS / CANCEL with reason tags.
"""
from __future__ import annotations

from typing import Dict

from .structure import Setup


def evaluate(setup: Setup, v10: Dict, cfg) -> Dict:
    t = cfg.v11
    f = v10["features"]
    cs = f["acceptance_close_strength"]
    br = f["body_ratio"]
    wc = v10["weakness_count"]

    tp1_r = setup.tp1_r

    # Hard fail floor.
    if tp1_r < t["tp1_r_hard_floor"]:
        return {"result": "CANCEL", "tags": ["v11_hard_fail_tp1_r", f"tp1_r={tp1_r:.2f}"]}

    base_ok = (
        setup.r_abs_bps >= t["r_abs_bps_min"]
        and setup.r_abs_atr >= t["r_abs_atr_min"]
        and cs >= t["close_strength_min"]
        and br >= t["body_ratio_min"]
    )

    # Normal A+ pass.
    if tp1_r >= t["tp1_r_min"] and base_ok:
        return {"result": "PASS", "tags": ["v11_normal_Aplus"]}

    # Conditional sub-2R pass.
    if t["sub2r_floor"] <= tp1_r < t["tp1_r_min"]:
        sub_ok = (
            setup.r_abs_bps >= t["r_abs_bps_min"]
            and setup.r_abs_atr >= t["r_abs_atr_min"]
            and cs >= t["sub2r_close_strength_min"]
            and br >= t["sub2r_body_ratio_min"]
            and wc <= t["sub2r_weakness_count_max"]
            and setup.entry_edge_dist_band <= t["sub2r_entry_edge_dist_band_max"]
        )
        if sub_ok:
            return {"result": "PASS", "tags": ["v11_conditional_sub2r"]}
        return {"result": "CANCEL", "tags": ["v11_sub2r_fail"]}

    # tp1_r >= 2.0 but base quality failed.
    reasons = []
    if setup.r_abs_bps < t["r_abs_bps_min"]:
        reasons.append("r_abs_bps_low")
    if setup.r_abs_atr < t["r_abs_atr_min"]:
        reasons.append("r_abs_atr_low")
    if cs < t["close_strength_min"]:
        reasons.append("close_strength_low")
    if br < t["body_ratio_min"]:
        reasons.append("body_ratio_low")
    return {"result": "CANCEL", "tags": ["v11_quality_fail"] + reasons}
