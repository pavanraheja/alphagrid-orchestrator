"""
Execution adapters.

`MockAdapter` is the reference implementation included in this repo. It logs
every call and assigns synthetic order ids so you can run the full orchestrator
end-to-end without touching real money.

Production adapters (Binance futures, webhook bridges, on-chain wallets, etc.)
are out of scope for this repo — they couple to credentials and venue-specific
mechanics that should not live in a public template.
"""

import itertools
import logging
from .dispatch import ExecutionAdapter, ExecutionRequest


log = logging.getLogger("orchestrator.adapters")


class MockAdapter(ExecutionAdapter):
    """In-memory, deterministic adapter. Use for tests and local demos."""

    def __init__(self):
        self._counter = itertools.count(1)
        self._open: dict[str, ExecutionRequest] = {}
        self._history: list[dict] = []

    def place_primary(self, req: ExecutionRequest) -> str:
        oid = f"mock-primary-{next(self._counter)}"
        self._open[oid] = req
        self._log({"type": "primary", "id": oid, "req": req.__dict__})
        return oid

    def place_sl(self, primary_id: str, sl_pct: float) -> str:
        oid = f"mock-sl-{next(self._counter)}"
        self._log({"type": "sl", "id": oid, "primary": primary_id, "sl_pct": sl_pct})
        return oid

    def place_tp(self, primary_id: str, tp_pct: float) -> str:
        oid = f"mock-tp-{next(self._counter)}"
        self._log({"type": "tp", "id": oid, "primary": primary_id, "tp_pct": tp_pct})
        return oid

    def cancel(self, order_id: str) -> bool:
        if order_id in self._open:
            del self._open[order_id]
        self._log({"type": "cancel", "id": order_id})
        return True

    def close_all(self) -> int:
        n = len(self._open)
        for oid in list(self._open):
            del self._open[oid]
        self._log({"type": "close_all", "count": n})
        return n

    # -- introspection (test helpers) -----------------------------------------

    @property
    def open_count(self) -> int:
        return len(self._open)

    @property
    def history(self) -> list[dict]:
        return list(self._history)

    def _log(self, evt: dict):
        log.info("MockAdapter %s", evt)
        self._history.append(evt)
