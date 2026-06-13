"""rules_v10_1.py — v0.10.1 Soft Acceptance.

Computes acceptance "weakness" features from the reclaim candle and decides
PASS / WATCH / CANCEL. Returns a dict with weakness_count, the individual
features and reason tags.
"""
from __future__ import annotations

from typing import Dict

from . import indicators as ind
from .structure import Setup, weak_retest


def evaluate(setup: Setup, cfg, v08_major_warning: bool = False) -> Dict:
    c = setup.accept_candle
    d = setup.direction
    t = cfg.v10_1

    feats = {
        "body_ratio": ind.body_ratio(c),
        "acceptance_close_strength": ind.close_strength(c, d),
        "acceptance_body_aligned": ind.body_aligned(c, d),
        "opposite_wick_ratio": ind.opposite_wick_ratio(c, d),
        "weak_retest": weak_retest(setup, cfg),
    }

    weaknesses = []
    if feats["body_ratio"] < t["weak_body_ratio"]:
        weaknesses.append("weak_body_ratio")
    if feats["acceptance_close_strength"] < t["weak_close_strength"]:
        weaknesses.append("weak_close_strength")
    if not feats["acceptance_body_aligned"]:
        weaknesses.append("body_not_aligned")
    if feats["opposite_wick_ratio"] > t["weak_opposite_wick"]:
        weaknesses.append("opposite_wick_high")
    if feats["weak_retest"]:
        weaknesses.append("weak_retest")
    weakness_count = len(weaknesses)

    # strict cancels
    strict = (
        (feats["body_ratio"] < t["strict_body_ratio"]
         and feats["acceptance_close_strength"] < t["strict_close_strength"])
        or (not feats["acceptance_body_aligned"]
            and feats["acceptance_close_strength"] < t["strict_aligned_close_strength"])
        or (feats["opposite_wick_ratio"] > t["strict_opp_wick"]
            and feats["body_ratio"] < t["strict_opp_wick_body"])
    )

    if strict:
        result = "CANCEL"
        tags = ["v10_1_strict_cancel"] + weaknesses
    elif weakness_count >= t["watch_weakness_count"]:
        result = "WATCH"
        tags = ["v10_1_watch_weak3"] + weaknesses
    elif weakness_count == t["watch_with_major_warning"] and v08_major_warning:
        result = "WATCH"
        tags = ["v10_1_watch_weak2_major"] + weaknesses
    else:
        result = "PASS"
        tags = ["v10_1_pass"] + weaknesses

    return {
        "result": result,
        "weakness_count": weakness_count,
        "weaknesses": weaknesses,
        "features": feats,
        "tags": tags,
    }
