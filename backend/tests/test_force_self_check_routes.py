from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from backend.app import create_app
from backend.services.control_watchdog import ControlLeaseUnavailable


def test_hkvl_self_check_route_requires_confirmation_and_preserves_hal_result(tmp_path, monkeypatch):
    monkeypatch.setenv("APPSTATION_HAL_MODE", "test")
    app = create_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=False)
    calls = []
    calibration = {"state": "ready", "progress": 100, "reason": "", "completedAtUnixMs": 42}

    async def command(name, payload):
        calls.append((name, payload))
        return {"response": {"ok": True, "calibration": calibration}}

    monkeypatch.setattr(app.state.commands, "_real_hardware_mode", lambda config: True)
    monkeypatch.setattr(app.state.hal, "command", command)
    monkeypatch.setattr(app.state.control_watchdog, "require_ack_ready", lambda: None)
    app.state.commands.safety.interrupt(emergency=True)

    assert client.post("/api/sensors/tare").status_code == 503
    assert client.post("/api/sensors/tare", json={"unloadedConfirmed": "true"}).status_code == 503
    assert client.post("/api/force/left/tare", json={"unloadedConfirmed": True}).status_code == 503
    assert calls == []

    response = client.post("/api/sensors/tare", json={"unloadedConfirmed": True})
    assert response.status_code == 200
    assert response.json()["data"]["hal"]["response"]["calibration"] == calibration
    assert calls[0][0] == "force.tare"
    assert calls[0][1]["side"] == "all"
    assert calls[0][1]["unloadedConfirmed"] is True
    assert app.state.commands.safety.latched

    def expired():
        raise ControlLeaseUnavailable("fresh control lease required")

    monkeypatch.setattr(app.state.control_watchdog, "require_ack_ready", expired)
    response = client.post("/api/sensors/tare", json={"unloadedConfirmed": True})
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "CONTROL_LEASE_UNAVAILABLE"
    assert len(calls) == 1


@pytest.mark.parametrize("source", ["teleop", "replay", "policy"])
def test_tare_rejects_active_motion_sources_without_reaching_hal(tmp_path, monkeypatch, source):
    monkeypatch.setenv("APPSTATION_HAL_MODE", "test")
    app = create_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=False)
    calls = []

    async def command(name, payload):
        calls.append(name)
        return {"response": {"ok": True}}

    monkeypatch.setattr(app.state.hal, "command", command)
    monkeypatch.setattr(app.state.commands, "_real_hardware_mode", lambda _config: True)
    monkeypatch.setattr(app.state.control_watchdog, "require_ack_ready", lambda: None)
    if source == "teleop":
        monkeypatch.setattr(app.state.teleop_mapper, "control_active", lambda: True)
    elif source == "replay":
        monkeypatch.setattr(type(app.state.replay), "active", property(lambda _self: True))
    else:
        monkeypatch.setattr(app.state.policy, "dispatch_active", lambda: True)

    response = client.post("/api/sensors/tare", json={"unloadedConfirmed": True})

    assert response.status_code == 503
    # 回放同时持有原点变更锁，会先被录制/回放互斥拒绝；两条路径都不能到达 HAL。
    if source != "replay":
        assert "stop teleoperation, dataset replay and automatic execution" in response.text
    assert calls == []


@pytest.mark.parametrize("record_state", ["_recording", "_session_starting", "_session_active"])
def test_tare_cannot_change_an_active_episode_calibration(tmp_path, monkeypatch, record_state):
    monkeypatch.setenv("APPSTATION_HAL_MODE", "test")
    app = create_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=False)
    calls = []

    async def command(name, payload):
        calls.append(name)
        return {"response": {"ok": True}}

    monkeypatch.setattr(app.state.hal, "command", command)
    monkeypatch.setattr(app.state.commands, "_real_hardware_mode", lambda _config: True)
    monkeypatch.setattr(app.state.control_watchdog, "require_ack_ready", lambda: None)
    monkeypatch.setattr(app.state.recorder, record_state, True)

    response = client.post("/api/sensors/tare", json={"unloadedConfirmed": True})

    assert response.status_code == 503
    assert "finish the recording session" in response.text
    assert calls == []
