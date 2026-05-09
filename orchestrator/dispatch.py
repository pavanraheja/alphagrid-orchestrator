"""
Dispatcher — two-stage entry; routes to an ExecutionAdapter.

The two-stage pattern (place primary, then place protective orders separately)
exists because retry-safe single-call entry has bug classes that two-stage
doesn't. Specifically: a transient timeout on a combined call can lead to
double-fills if the retry races the original. Splitting the calls and tracking
each independently eliminates that.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class ExecutionRequest:
    asset: str
    direction: str
    size: float
    sl_pct: Optional[float] = None
    tp_pct: Optional[float] = None
    metadata: Optional[dict] = None


@dataclass
class ExecutionResult:
    accepted: bool
    primary_id: Optional[str] = None
    sl_id: Optional[str] = None
    tp_id: Optional[str] = None
    error: Optional[str] = None


class ExecutionAdapter(ABC):
    """
    Abstract execution surface. Production adapters (Binance, webhooks, etc.)
    live elsewhere; the orchestrator only knows about this interface.
    """

    @abstractmethod
    def place_primary(self, req: ExecutionRequest) -> str:
        """Return primary order id. Idempotent on retry via metadata.idempotency_key."""

    @abstractmethod
    def place_sl(self, primary_id: str, sl_pct: float) -> str:
        """Place stop-loss order keyed off the primary."""

    @abstractmethod
    def place_tp(self, primary_id: str, tp_pct: float) -> str:
        """Place take-profit order keyed off the primary."""

    @abstractmethod
    def cancel(self, order_id: str) -> bool: ...

    @abstractmethod
    def close_all(self) -> int:
        """Emergency-close all open positions. Returns count closed."""


class Dispatcher:
    """
    Two-stage entry routing to an injected ExecutionAdapter.

    Stage 1: place primary order.
    Stage 2: place SL and TP orders (independently, can be retried).
    If stage 2 fails, primary is cancelled to avoid orphan positions.
    """

    def __init__(self, adapter: ExecutionAdapter):
        self._adapter = adapter

    def dispatch(self, req: ExecutionRequest) -> ExecutionResult:
        try:
            primary_id = self._adapter.place_primary(req)
        except Exception as e:
            return ExecutionResult(False, error=f"primary failed: {e}")

        sl_id = tp_id = None
        try:
            if req.sl_pct is not None:
                sl_id = self._adapter.place_sl(primary_id, req.sl_pct)
            if req.tp_pct is not None:
                tp_id = self._adapter.place_tp(primary_id, req.tp_pct)
        except Exception as e:
            # Stage 2 failed — cancel primary to avoid orphan.
            self._adapter.cancel(primary_id)
            return ExecutionResult(False, primary_id=primary_id,
                                   error=f"stage-2 failed, primary cancelled: {e}")

        return ExecutionResult(True, primary_id=primary_id, sl_id=sl_id, tp_id=tp_id)

    def kill_all(self) -> int:
        """Emergency: close everything immediately."""
        return self._adapter.close_all()
