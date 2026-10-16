import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.data_contract import data_contract_metadata
from backend.core.logging import now_ms


@pytest.fixture
def feedback_app(tmp_path, monkeypatch):
    monkeypatch.setenv("APPSTATION_HAL_MODE", "test")
    monkeypatch.setenv("APPSTATION_DISABLE_CAMERA_PROBE", "1")
    app = create_app(tmp_path)
    config = app.state.settings.get_config()
    config["gripper"].update(leftEnabled=True, rightEnabled=False, targetLeftMm=19.0)
    app.state.settings.save_config(config)
    app.state.telemetry.gripper_positions = [19.0, 13.0]
    native = {
        "gripperFeedbackSampling": True,
        "gripperFeedbackParticipating": [True, False],
        "grippers": {"left": {
            "positionSource": "jodell_read", "positionOk": True, "positionMm": 12.4,
            "positionSampleTs": now_ms(), "lastReadAttemptTs": now_ms(),
            "lastReadDurationMs": 20, "lastReadMessage": "measured", "readAttempts": 1,
            "readSuccesses": 1, "readSkippedBusy": 0,
        }},
    }
    calls = []

    async def command(name, payload=None):
        calls.append((name, payload))
        assert name in {"teleop.native.status", "gripper.feedback.configure"}
        return {"response": deepcopy(native)}

    app.state.hal.command = command
    app.state.hal.motion_state = AsyncMock(return_value={"positions": [0.0] * 12})
    monkeypatch.setenv("APPSTATION_HAL_MODE", "real")
    return app, native, calls


def test_policy_reads_raw_feedback_without_browser_or_mapper(feedback_app):
    app, native, calls = feedback_app
    response = TestClient(app).get("/api/policy/observation", params={"controlledSides": "right"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["state"][13] == 12.4
    assert data["state"][6] == 0.0
    assert data["gripperFeedback"]["right"]["source"] == "jodell_read"
    assert data["gripperFeedback"]["right"]["sampleUnixMs"] == native["grippers"]["left"]["positionSampleTs"]
    assert data["gripperFeedback"]["left"]["participating"] is False
    configure = next(payload for name, payload in calls if name == "gripper.feedback.configure")
    assert configure["leftGripperParticipating"] is True
    assert configure["rightGripperParticipating"] is False
    assert app.state.teleop_mapper.status()["nativeStatus"] == {}


@pytest.mark.parametrize("changes", [
    {"positionMm": None}, {"positionMm": -1}, {"positionMm": float("nan")},
    {"positionMm": 27}, {"positionMm": True}, {"positionOk": False},
    {"positionSource": "command_target"}, {"positionSampleTs": 0},
    {"positionSampleTs": "stale"}, {"positionSampleTs": "future"},
])
def test_invalid_feedback_never_uses_positive_target_cache(feedback_app, changes):
    app, native, _calls = feedback_app
    if changes.get("positionSampleTs") == "stale":
        changes = {"positionSampleTs": now_ms() - 500}
    elif changes.get("positionSampleTs") == "future":
        changes = {"positionSampleTs": now_ms() + 1000}
    native["grippers"]["left"].update(changes)
    response = TestClient(app).get("/api/policy/observation", params={"controlledSides": "right"})
    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "POLICY_GRIPPER_FEEDBACK_UNAVAILABLE"
    assert detail["gripperFeedback"]["right"]["valid"] is False
    assert detail["gripperFeedback"]["right"]["reason"]
    assert "state" not in detail


def test_action_rejects_invalid_feedback_before_any_motion(feedback_app):
    app, native, calls = feedback_app
    native["grippers"]["left"]["positionOk"] = False
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/policy/action")
    with pytest.raises(HTTPException) as failure:
        asyncio.run(endpoint({"action": [0.0] * 14, "dataContract": data_contract_metadata(),
                             "controlledSides": ["right"], "dryRun": False}))
    assert failure.value.status_code == 503
    assert failure.value.detail["code"] == "POLICY_GRIPPER_FEEDBACK_UNAVAILABLE"
    assert all(name == "teleop.native.status" for name, _ in calls)


def test_repeated_valid_observations_do_not_reconfigure_sampler(feedback_app):
    app, _native, calls = feedback_app
    client = TestClient(app)
    for _ in range(3):
        assert client.get("/api/policy/observation", params={"controlledSides": "right"}).status_code == 200
    assert sum(name == "gripper.feedback.configure" for name, _ in calls) == 1


def test_sample_time_must_not_go_backwards_but_same_position_can_be_fresh(feedback_app, monkeypatch):
    app, native, _calls = feedback_app
    monkeypatch.setattr("backend.services.policy_gripper_observation.now_ms", lambda: 10_000)
    detail = native["grippers"]["left"]
    client = TestClient(app)
    detail["positionSampleTs"] = 9900
    assert client.get("/api/policy/observation?controlledSides=right").status_code == 200
    detail["positionSampleTs"] = 9950
    response = client.get("/api/policy/observation?controlledSides=right")
    assert response.status_code == 200
    assert response.json()["data"]["gripperFeedback"]["right"]["sampleUnixMs"] == 9950
    detail["positionSampleTs"] = 9920
    response = client.get("/api/policy/observation?controlledSides=right")
    assert response.status_code == 503
    assert response.json()["detail"]["gripperFeedback"]["right"]["reason"] == "sample_time_regressed"
