"""Central configuration.

ALL thresholds live here (acceptance criterion: "All thresholds must be in
config, not hardcoded in many places"). Override any value via a JSON file
passed to `load_config`.

The engine is single-source-of-truth: replay and a future live bot read the
exact same config object, so behaviour is identical.
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Dict, List


# --------------------------------------------------------------------------
# Default configuration. Edit here or override with --config <file.json>.
# --------------------------------------------------------------------------
DEFAULTS: Dict[str, Any] = {
    "symbol": "BTCUSDT",
    "version": "v0_11_1",

    # Which setup families are active. FIRST TEST: only SRR-1.
    # Every other family is explicitly OFF.
    "setups": {
        "enabled": ["SRR-1"],
        "all_families": ["SRR-1", "SRR-2", "RER-1", "RER-2"],
    },

    # Indicators (computed on CLOSED 5M candles only).
    "indicators": {
        "atr_period": 14,
    },

    # 1H / 15M structure.
    "structure": {
        "h1_context_lookback": 20,     # closed 1H candles for bias
        "h1_ema_fast": 8,
        "h1_ema_slow": 21,
        "m15_range_lookback": 20,      # closed 15M candles for range
        "edge_band_frac": 0.20,        # within this frac of range from an edge => "edge zone"
        "min_range_atr": 1.5,          # range must be >= this * ATR5m to be tradeable, else "unclear"
    },

    # 5M sweep / reclaim / entry geometry.
    "geometry": {
        "sweep_lookback_5m": 3,        # sweep must have happened within last N closed 5M candles
        "sl_buffer_atr": 0.10,         # SL placed this many ATR beyond the sweep extreme
        "tp1_target": "opposite_edge", # "opposite_edge" or "mid"
        "weak_retest_atr": 0.10,       # reclaim margin below this * ATR5m => weak_retest
    },

    # Pending EXECUTE_CANDIDATE -> fill management (the "entry must be touched" rule).
    "execution": {
        "candidate_lifetime_5m": 6,    # candidate expires if entry not touched within N closed 5M candles
        "sl_first_on_tie": True,       # if TP and SL in same 1M candle -> SL first (conservative)
    },

    # v0.10.1 Soft Acceptance thresholds.
    "v10_1": {
        "weak_body_ratio": 0.30,
        "weak_close_strength": 0.60,
        "weak_opposite_wick": 0.45,
        "watch_weakness_count": 3,         # >= this => WATCH
        "watch_with_major_warning": 2,     # == this + v0.8 major warning => WATCH
        # strict cancel
        "strict_body_ratio": 0.20,
        "strict_close_strength": 0.50,
        "strict_aligned_close_strength": 0.45,
        "strict_opp_wick": 0.65,
        "strict_opp_wick_body": 0.25,
    },

    # v0.11 BTC A+ Cost-Survival thresholds.
    "v11": {
        # Normal A+ pass
        "r_abs_bps_min": 22.0,
        "r_abs_atr_min": 0.70,
        "close_strength_min": 0.60,
        "body_ratio_min": 0.30,
        "tp1_r_min": 2.0,
        # Conditional sub-2R pass (1.8 <= TP1_R < 2.0)
        "sub2r_floor": 1.8,
        "sub2r_close_strength_min": 0.65,
        "sub2r_body_ratio_min": 0.35,
        "sub2r_weakness_count_max": 0,
        "sub2r_entry_edge_dist_band_max": 0.85,
        # Hard fail
        "tp1_r_hard_floor": 1.8,
    },

    # v0.11.1 No-Stale-Reentry / No Duplicate Promotion.
    "v11_1": {
        "cooldown_bars_5m": 6,
    },

    # Costs. The PRIMARY run uses round-trip 0.08% (= 8 bps) per the task brief.
    # The full cost-stress table (spec) is also produced by reports.py.
    "costs": {
        "primary_roundtrip_bps": 8.0,   # 0.08% round trip
        "stress_scenarios_bps": {
            "maker_maker": 0.0,
            "maker_taker_1p6": 1.6,
            "taker_taker_3p2": 3.2,
            "maker_taker_slip1": 3.6,
            "maker_taker_slip2": 5.6,
            "stress_7p6": 7.6,
        },
    },

    # IS/OOS split. OOS = 2025-10 plus 2026-01..04 per acceptance criteria.
    "windows": {
        "oos_months": ["2025-10", "2026-01", "2026-02", "2026-03", "2026-04"],
    },
}


@dataclass
class Config:
    data: Dict[str, Any] = field(default_factory=lambda: deepcopy(DEFAULTS))

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)

    # convenience dotted access, e.g. cfg.v11["tp1_r_min"]
    def __getattr__(self, name: str) -> Any:  # pragma: no cover - simple passthrough
        try:
            return self.data[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = deepcopy(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: str | None = None) -> Config:
    """Load defaults, optionally deep-merged with a JSON override file."""
    cfg = deepcopy(DEFAULTS)
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            override = json.load(fh)
        cfg = _deep_merge(cfg, override)
    return Config(cfg)
