"""
Risk Guardian — drawdown-kill, loss caps, conflict + duplicate guards, kill switch.

Every signal that wants to act passes through `evaluate(...)`. If any gate fails,
the signal is rejected with a structured reason. State is persisted to JSON
after every change so the process can recover from a crash.
"""

import json
import os
import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Signal:
    strategy: str
    asset: str
    direction: str  # "long" | "short"
    size: float
    metadata: dict


@dataclass
class GuardDecision:
    allowed: bool
    reason: Optional[str] = None
    gate: Optional[str] = None  # which gate fired


class RiskGuardian:
    """
    Stateful guardian for autonomous decision systems.

    Gates checked, in order:
      1. Kill switch (manual / auto-tripped)
      2. Drawdown-kill (account-level circuit breaker)
      3. Per-strategy loss cap
      4. Conflict gate (same asset, opposite direction)
      5. Duplicate gate (same asset + direction + strategy)
    """

    def __init__(self, config: dict, state_path: str = "state/risk_state.json"):
        self._cfg = config
        self._state_path = state_path
        self._lock = threading.Lock()
        self._state = self._load_state()

    # -- public API -----------------------------------------------------------

    def evaluate(self, signal: Signal, open_positions: list) -> GuardDecision:
        with self._lock:
            if self._state["killed"]:
                return GuardDecision(False, self._state.get("kill_reason", "killed"), "kill_switch")

            if self._is_drawdown_killed():
                return GuardDecision(False, "account drawdown breached", "drawdown_kill")

            if self._is_strategy_loss_capped(signal.strategy):
                return GuardDecision(False, f"strategy {signal.strategy} loss cap breached", "loss_cap")

            if self._cfg.get("conflict_gate", True):
                conflict = self._has_conflict(signal, open_positions)
                if conflict:
                    return GuardDecision(False, f"conflict with open {conflict}", "conflict_gate")

            if self._cfg.get("duplicate_gate", True):
                duplicate = self._has_duplicate(signal, open_positions)
                if duplicate:
                    return GuardDecision(False, f"duplicate of open {duplicate}", "duplicate_gate")

            return GuardDecision(True)

    def record_outcome(self, strategy: str, pnl_pct: float):
        """Record realised P&L. Triggers loss-cap auto-pause if breached."""
        with self._lock:
            sl = self._state["strategy_loss"].get(strategy, 0.0) + min(pnl_pct, 0)
            self._state["strategy_loss"][strategy] = sl
            self._state["account_pnl_pct"] += pnl_pct
            self._save_state()

    def kill(self, reason: str = "manual"):
        with self._lock:
            self._state["killed"] = True
            self._state["kill_reason"] = reason
            self._state["killed_at"] = datetime.now(timezone.utc).isoformat()
            self._save_state()

    def revive(self):
        with self._lock:
            self._state["killed"] = False
            self._state["kill_reason"] = None
            self._save_state()

    def status(self) -> dict:
        with self._lock:
            return dict(self._state)

    # -- gate logic -----------------------------------------------------------

    def _is_drawdown_killed(self) -> bool:
        cap = self._cfg.get("max_drawdown_pct", 15)
        if self._state["account_pnl_pct"] <= -abs(cap):
            self._state["killed"] = True
            self._state["kill_reason"] = "drawdown-kill auto-tripped"
            self._save_state()
            return True
        return False

    def _is_strategy_loss_capped(self, strategy: str) -> bool:
        cap = self._cfg.get("per_strategy_loss_cap_pct", 5)
        return self._state["strategy_loss"].get(strategy, 0.0) <= -abs(cap)

    def _has_conflict(self, signal: Signal, open_positions: list) -> Optional[str]:
        for p in open_positions:
            if p["asset"] == signal.asset and p["direction"] != signal.direction:
                return f"{p['strategy']} {p['direction']} {p['asset']}"
        return None

    def _has_duplicate(self, signal: Signal, open_positions: list) -> Optional[str]:
        for p in open_positions:
            if (p["asset"] == signal.asset
                    and p["direction"] == signal.direction
                    and p["strategy"] == signal.strategy):
                return f"{p['strategy']} {p['direction']} {p['asset']}"
        return None

    # -- persistence ----------------------------------------------------------

    def _load_state(self) -> dict:
        if os.path.exists(self._state_path):
            with open(self._state_path) as f:
                return json.load(f)
        return {
            "killed": False,
            "kill_reason": None,
            "killed_at": None,
            "account_pnl_pct": 0.0,
            "strategy_loss": {},
        }

    def _save_state(self):
        os.makedirs(os.path.dirname(self._state_path) or ".", exist_ok=True)
        with open(self._state_path, "w") as f:
            json.dump(self._state, f, indent=2, default=str)
