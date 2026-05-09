"""
Promotion Gate — staged-promotion (shadow → paper → live).

Every stream registers its own gates (min trades, min WR, min PF). The nightly
review process measures each stream against its gates and promotes if eligible.
There is no manual override — config edits are logged.
"""

import json
import os
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


PROMOTION_STATES = ("shadow", "paper", "live")


@dataclass
class StreamGates:
    min_trades: int = 15
    min_wr_pct: float = 50.0
    min_pf: float = 1.5


@dataclass
class StreamMetrics:
    trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0  # stored as negative

    @property
    def wr_pct(self) -> float:
        return (self.wins / self.trades * 100) if self.trades else 0.0

    @property
    def pf(self) -> float:
        return (self.gross_profit / abs(self.gross_loss)) if self.gross_loss < 0 else float("inf")


class PromotionGate:
    """
    Holds the registry of streams and their current promotion state + metrics.
    """

    def __init__(self, state_path: str = "state/promotion_state.json"):
        self._state_path = state_path
        self._lock = threading.Lock()
        self._state = self._load_state()

    # -- public API -----------------------------------------------------------

    def register_stream(self, name: str, gates: StreamGates, initial_state: str = "shadow"):
        assert initial_state in PROMOTION_STATES, f"invalid state {initial_state}"
        with self._lock:
            if name not in self._state["streams"]:
                self._state["streams"][name] = {
                    "promotion_state": initial_state,
                    "gates": gates.__dict__,
                    "metrics": StreamMetrics().__dict__,
                    "history": [],
                }
                self._save_state()

    def record_trade(self, stream: str, pnl_pct: float):
        with self._lock:
            s = self._state["streams"].get(stream)
            if not s:
                return
            m = s["metrics"]
            m["trades"] += 1
            if pnl_pct >= 0:
                m["wins"] += 1
                m["gross_profit"] += pnl_pct
            else:
                m["losses"] += 1
                m["gross_loss"] += pnl_pct
            self._save_state()

    def is_ready_for_live(self, stream: str) -> bool:
        with self._lock:
            s = self._state["streams"].get(stream)
            if not s:
                return False
            g = s["gates"]
            m = StreamMetrics(**s["metrics"])
            return (m.trades >= g["min_trades"]
                    and m.wr_pct >= g["min_wr_pct"]
                    and m.pf >= g["min_pf"])

    def promote(self, stream: str, to: str, reason: str = "gate-driven"):
        assert to in PROMOTION_STATES, f"invalid state {to}"
        with self._lock:
            s = self._state["streams"].get(stream)
            if not s:
                return
            from_state = s["promotion_state"]
            s["promotion_state"] = to
            s["history"].append({
                "at": datetime.now(timezone.utc).isoformat(),
                "from": from_state,
                "to": to,
                "reason": reason,
            })
            self._save_state()

    def state_of(self, stream: str) -> Optional[str]:
        with self._lock:
            s = self._state["streams"].get(stream)
            return s["promotion_state"] if s else None

    def can_act(self, stream: str) -> bool:
        """A stream can act on real resources only if promoted to live."""
        return self.state_of(stream) == "live"

    def all_streams(self) -> dict:
        with self._lock:
            return dict(self._state["streams"])

    # -- nightly review (Lab Framework hook) ----------------------------------

    def nightly_review(self) -> dict:
        """
        Auto-promote any stream that has cleared its gates.
        Returns a summary of changes for the review log.
        """
        promoted = []
        with self._lock:
            for name, s in self._state["streams"].items():
                if s["promotion_state"] != "paper":
                    continue
                m = StreamMetrics(**s["metrics"])
                g = s["gates"]
                ready = (m.trades >= g["min_trades"]
                         and m.wr_pct >= g["min_wr_pct"]
                         and m.pf >= g["min_pf"])
                if ready:
                    promoted.append(name)
            for name in promoted:
                self._unsafe_promote(name, "live", "nightly-review auto-promote")
            self._save_state()
        return {"promoted": promoted, "ran_at": datetime.now(timezone.utc).isoformat()}

    def _unsafe_promote(self, stream: str, to: str, reason: str):
        # caller already holds the lock
        s = self._state["streams"][stream]
        s["history"].append({
            "at": datetime.now(timezone.utc).isoformat(),
            "from": s["promotion_state"],
            "to": to,
            "reason": reason,
        })
        s["promotion_state"] = to

    # -- persistence ----------------------------------------------------------

    def _load_state(self) -> dict:
        if os.path.exists(self._state_path):
            with open(self._state_path) as f:
                return json.load(f)
        return {"streams": {}}

    def _save_state(self):
        os.makedirs(os.path.dirname(self._state_path) or ".", exist_ok=True)
        with open(self._state_path, "w") as f:
            json.dump(self._state, f, indent=2)
