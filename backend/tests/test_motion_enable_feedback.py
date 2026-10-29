from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from backend.services import command_service
from backend.tests.test_hardware_homing import setup_homing


@pytest.mark.parametrize("operation", ["enable_all", "disable_all"])
@pytest.mark.parametrize("error", [
    "DDS topic has invalid source timestamp: AppStation.Hal.MotionState",
    "DDS motion controller sample timestamp is stale or unavailable",
])
def test_axis_enable_change_waits_for_measured_feedback_without_resending(tmp_path, monkeypatch, operation, error):
    client, hal, _ = setup_homing(tmp_path, monkeypatch)
    original = hal.motion_state
    calls = 0

    async def motion_state():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError(error)
        return await original()

    hal.motion_state = motion_state
    response = client.post(f"/api/motion/left/{operation}")
    assert response.status_code == 200, response.text
    assert calls == 2
    hal.command.assert_awaited_once()


@pytest.mark.parametrize("error", [
    "DDS topic has invalid source timestamp: AppStation.Hal.MotionState",
    "DDS control channel isolated",
])
def test_axis_enable_change_rejects_missing_feedback(tmp_path, monkeypatch, error):
    client, hal, _ = setup_homing(tmp_path, monkeypatch)
    hal.motion_state = AsyncMock(side_effect=RuntimeError(error))
    ticks = iter([0., 3.])
    monkeypatch.setattr(command_service, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    response = client.post("/api/motion/left/enable_all")
    assert response.status_code == 503
    assert error in response.text
    hal.command.assert_awaited_once()


def test_axis_enable_does_not_report_success_after_emergency_during_feedback(tmp_path, monkeypatch):
    client, hal, _ = setup_homing(tmp_path, monkeypatch)
    original = hal.motion_state

    async def motion_state():
        client.app.state.commands.safety.interrupt(emergency=True)
        return await original()

    hal.motion_state = motion_state
    assert client.post("/api/motion/left/enable_all").status_code == 503
    hal.command.assert_awaited_once()
