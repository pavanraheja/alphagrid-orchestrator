"""
Flask app — orchestrator entry point.

Endpoints:
    POST /signal           — receive signal from upstream
    POST /close            — close a position
    POST /kill             — emergency: close all + halt
    POST /revive           — clear kill state (manual)
    GET  /status           — full system state
    GET  /api/live-readiness — Lab Framework: which streams cleared all gates
    GET  /api/risk-status   — Lab Framework: current risk state
"""

import logging
import os
from typing import Optional

import yaml
from flask import Flask, jsonify, request

from .risk_guardian import RiskGuardian, Signal
from .promotion import PromotionGate, StreamGates
from .dispatch import Dispatcher, ExecutionRequest
from .adapters import MockAdapter
from .alerts import TelegramAlerter


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s :: %(message)s",
)
log = logging.getLogger("orchestrator")


def load_config(path: str = "config/example_config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def build_app(config_path: Optional[str] = None) -> Flask:
    cfg = load_config(config_path or os.environ.get("ORCH_CONFIG", "config/example_config.yaml"))

    risk = RiskGuardian(cfg.get("risk", {}))
    promo = PromotionGate()
    dispatcher = Dispatcher(MockAdapter())
    alerter = TelegramAlerter(**cfg.get("alerts", {}).get("telegram", {}))

    # register configured streams
    for name, stream_cfg in cfg.get("streams", {}).items():
        promo.register_stream(
            name,
            gates=StreamGates(**stream_cfg.get("gates", {})),
            initial_state=stream_cfg.get("promotion_state", "shadow"),
        )

    # in-memory open-position tracker (production should use a real store)
    open_positions: list[dict] = []

    app = Flask(__name__)

    # -------------------------------------------------------------- /signal
    @app.post("/signal")
    def signal_in():
        data = request.get_json(force=True)
        sig = Signal(
            strategy=data["strategy"],
            asset=data["asset"],
            direction=data["direction"],
            size=float(data.get("size", 0)),
            metadata=data.get("metadata", {}),
        )

        # Promotion: only "live" streams can act on real resources
        if not promo.can_act(sig.strategy):
            return jsonify({
                "status": "shadowed",
                "reason": f"stream {sig.strategy} not promoted to live",
                "promotion_state": promo.state_of(sig.strategy),
            }), 200

        # Risk Guardian
        decision = risk.evaluate(sig, open_positions)
        if not decision.allowed:
            alerter.alert_error("risk_guardian", f"{sig.strategy}/{sig.asset}: {decision.reason}")
            return jsonify({"status": "rejected", "gate": decision.gate, "reason": decision.reason}), 200

        # Dispatch
        req = ExecutionRequest(
            asset=sig.asset,
            direction=sig.direction,
            size=sig.size,
            sl_pct=data.get("sl_pct"),
            tp_pct=data.get("tp_pct"),
            metadata=sig.metadata,
        )
        result = dispatcher.dispatch(req)
        if not result.accepted:
            alerter.alert_error("dispatcher", result.error or "unknown")
            return jsonify({"status": "dispatch_failed", "error": result.error}), 502

        open_positions.append({
            "primary_id": result.primary_id,
            "asset": sig.asset,
            "direction": sig.direction,
            "strategy": sig.strategy,
        })
        alerter.alert_entry(data, result.primary_id)
        return jsonify({"status": "accepted",
                        "primary_id": result.primary_id,
                        "sl_id": result.sl_id,
                        "tp_id": result.tp_id}), 200

    # ---------------------------------------------------------------- /close
    @app.post("/close")
    def close():
        data = request.get_json(force=True)
        primary_id = data["primary_id"]
        pnl_pct = float(data.get("pnl_pct", 0))

        # mark closed
        for i, p in enumerate(open_positions):
            if p["primary_id"] == primary_id:
                strategy = p["strategy"]
                asset = p["asset"]
                open_positions.pop(i)
                risk.record_outcome(strategy, pnl_pct)
                promo.record_trade(strategy, pnl_pct)
                alerter.alert_close(strategy, asset, pnl_pct)
                return jsonify({"status": "closed"}), 200
        return jsonify({"status": "not_found"}), 404

    # ----------------------------------------------------------------- /kill
    @app.post("/kill")
    def kill():
        data = request.get_json(silent=True) or {}
        reason = data.get("reason", "manual")
        risk.kill(reason)
        closed = dispatcher.kill_all()
        alerter.alert_kill_switch(reason)
        return jsonify({"status": "killed", "closed": closed, "reason": reason}), 200

    @app.post("/revive")
    def revive():
        risk.revive()
        return jsonify({"status": "revived"}), 200

    # --------------------------------------------------------------- /status
    @app.get("/status")
    def status():
        return jsonify({
            "risk": risk.status(),
            "open_positions": open_positions,
            "streams": promo.all_streams(),
        })

    # --------------------------------------- /api/live-readiness (Lab Framework)
    @app.get("/api/live-readiness")
    def live_readiness():
        report = {}
        for name, s in promo.all_streams().items():
            report[name] = {
                "promotion_state": s["promotion_state"],
                "ready_for_live": promo.is_ready_for_live(name),
                "metrics": s["metrics"],
                "gates": s["gates"],
            }
        return jsonify(report)

    # ------------------------------------------ /api/risk-status (Lab Framework)
    @app.get("/api/risk-status")
    def risk_status():
        st = risk.status()
        breached = []
        if st["killed"]:
            breached.append("kill_switch")
        if st["account_pnl_pct"] <= -abs(cfg.get("risk", {}).get("max_drawdown_pct", 15)):
            breached.append("drawdown_kill")
        for strategy, loss in st["strategy_loss"].items():
            if loss <= -abs(cfg.get("risk", {}).get("per_strategy_loss_cap_pct", 5)):
                breached.append(f"loss_cap:{strategy}")
        return jsonify({
            "ok": len(breached) == 0,
            "breached": breached,
            "state": st,
        })

    return app


if __name__ == "__main__":
    app = build_app()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8095)))
