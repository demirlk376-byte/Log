"""rules_v11_1.py — v0.11.1 No-Stale-Reentry / No Duplicate Promotion.

Stateful guard. The engine keeps a small `EngineState` of recent setup
identities, an active-setup lock and cooldowns. A setup that would re-promote
the same edge+sweep, fire during cooldown, while another setup is active, or
duplicate a prior promotion is demoted to WATCH (never silently dropped).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Set

from .structure import Setup


def setup_identity(symbol: str, setup: Setup) -> str:
    return f"{symbol}|{setup.direction}|{setup.edge_id}|{setup.sweep_id}"


@dataclass
class EngineState:
    symbol: str = "BTCUSDT"
    bar_index_5m: int = 0                      # increments each closed 5M candle
    active_setup_id: Optional[str] = None      # set while a candidate/trade is live
    cooldown_until_bar: int = -1               # cooldown active while bar_index_5m < this
    promoted_ids: Set[str] = field(default_factory=set)
    prior_watch_ids: Set[str] = field(default_factory=set)
    last_promoted_bar: Dict[str, int] = field(default_factory=dict)

    def cooldown_active(self) -> bool:
        return self.bar_index_5m < self.cooldown_until_bar

    def start_cooldown(self, bars: int) -> None:
        self.cooldown_until_bar = self.bar_index_5m + bars


def evaluate(setup: Setup, state: EngineState, cfg) -> Dict:
    sid = setup_identity(state.symbol, setup)
    tags = []
    block = False

    if state.active_setup_id is not None:
        block = True
        tags.append("active_setup_exists")

    if state.cooldown_active():
        block = True
        tags.append("cooldown_active")

    same_edge_same_sweep = sid in state.promoted_ids
    if same_edge_same_sweep:
        block = True
        tags.append("same_edge_same_sweep_reentry")

    if sid in state.prior_watch_ids:
        block = True
        tags.append("late_reentry_after_prior_watch")

    if same_edge_same_sweep:
        tags.append("duplicate_promotion_candidate")

    return {
        "result": "WATCH" if block else "PASS",
        "blocked": block,
        "setup_id": sid,
        "tags": tags if tags else ["v11_1_clear"],
    }
