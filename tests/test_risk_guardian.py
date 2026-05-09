"""Critical-path tests for RiskGuardian."""

import os
import tempfile

import pytest

from orchestrator.risk_guardian import RiskGuardian, Signal


@pytest.fixture
def guardian(tmp_path):
    state = tmp_path / "risk_state.json"
    cfg = {
        "max_drawdown_pct": 15,
        "per_strategy_loss_cap_pct": 5,
        "conflict_gate": True,
        "duplicate_gate": True,
    }
    return RiskGuardian(cfg, state_path=str(state))


def _sig(strategy="alpha", asset="BTC", direction="long", size=1.0):
    return Signal(strategy, asset, direction, size, {})


def test_clean_signal_allowed(guardian):
    d = guardian.evaluate(_sig(), open_positions=[])
    assert d.allowed
    assert d.gate is None


def test_kill_switch_blocks_everything(guardian):
    guardian.kill("test")
    d = guardian.evaluate(_sig(), open_positions=[])
    assert not d.allowed
    assert d.gate == "kill_switch"


def test_drawdown_kill_auto_trips(guardian):
    guardian.record_outcome("alpha", -16)  # past 15% threshold
    d = guardian.evaluate(_sig(), open_positions=[])
    assert not d.allowed
    assert d.gate == "drawdown_kill"


def test_per_strategy_loss_cap(guardian):
    guardian.record_outcome("alpha", -2)
    guardian.record_outcome("alpha", -4)  # cumulative -6 > 5% cap
    d = guardian.evaluate(_sig(strategy="alpha"), open_positions=[])
    assert not d.allowed
    assert d.gate == "loss_cap"

    # other strategies unaffected
    d2 = guardian.evaluate(_sig(strategy="beta"), open_positions=[])
    assert d2.allowed


def test_conflict_gate_blocks_opposite_direction(guardian):
    open_pos = [{"asset": "BTC", "direction": "long", "strategy": "beta", "primary_id": "x"}]
    d = guardian.evaluate(_sig(strategy="alpha", asset="BTC", direction="short"),
                          open_positions=open_pos)
    assert not d.allowed
    assert d.gate == "conflict_gate"


def test_duplicate_gate_blocks_same_strategy_reentry(guardian):
    open_pos = [{"asset": "BTC", "direction": "long", "strategy": "alpha", "primary_id": "x"}]
    d = guardian.evaluate(_sig(strategy="alpha", asset="BTC", direction="long"),
                          open_positions=open_pos)
    assert not d.allowed
    assert d.gate == "duplicate_gate"


def test_state_persists_across_instances(tmp_path):
    state = tmp_path / "risk_state.json"
    cfg = {"max_drawdown_pct": 15, "per_strategy_loss_cap_pct": 5}
    g1 = RiskGuardian(cfg, state_path=str(state))
    g1.kill("first instance")

    g2 = RiskGuardian(cfg, state_path=str(state))
    d = g2.evaluate(_sig(), open_positions=[])
    assert not d.allowed
    assert d.gate == "kill_switch"


def test_revive_clears_kill_state(guardian):
    guardian.kill("test")
    guardian.revive()
    d = guardian.evaluate(_sig(), open_positions=[])
    assert d.allowed
