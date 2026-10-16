import importlib.util
from pathlib import Path
import time

import numpy as np
import pytest

from backend.core.data_contract import data_contract_metadata


@pytest.fixture
def robot():
    path = Path(__file__).resolve().parents[2] / "deployment/gripper_feedback/robot.py"
    spec = importlib.util.spec_from_file_location("feedback_robot_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def observation():
    state = [0.0] * 14
    state[13] = 12.4
    return {"state": state, "force_right": [0.0] * 6, "dataContract": data_contract_metadata(),
            "gripperFeedback": {"right": {"participating": True, "valid": True,
                                           "source": "jodell_read", "positionMm": 12.4,
                                           "sampleUnixMs": time.time() * 1000, "ageMs": 0}}}


def test_missing_metadata_is_not_accepted_as_measurement(robot):
    data = observation()
    data.pop("gripperFeedback")
    with pytest.raises(robot.Busy, match="feedback"):
        robot.check_gripper_feedback(data, np.asarray(data["state"]))


@pytest.mark.parametrize("changes", [
    {"valid": False}, {"source": "command_target"}, {"positionMm": 19.0},
    {"sampleUnixMs": 1}, {"sampleUnixMs": None},
])
def test_client_rejects_invalid_or_delayed_feedback(robot, changes):
    data = observation()
    data["gripperFeedback"]["right"].update(changes)
    with pytest.raises(robot.Busy) as failure:
        robot.check_gripper_feedback(data, np.asarray(data["state"]))
    assert failure.value.detail["code"] == "POLICY_GRIPPER_FEEDBACK_UNAVAILABLE"


def test_successful_retry_preserves_the_failed_attempt(robot):
    data = observation()
    failure = {"detail": {"code": "POLICY_GRIPPER_FEEDBACK_UNAVAILABLE", "message": "read timeout",
                           "gripperFeedback": {"right": {"valid": False, "reason": "read_failed"}}}}
    class Response:
        def __init__(self, status, body):
            self.status_code, self.body = status, body
        def json(self):
            return self.body
        def raise_for_status(self):
            pass
    class Session:
        def __init__(self):
            self.responses = [Response(503, failure), Response(200, {"data": data})]
        def get(self, _url, **kwargs):
            assert kwargs["params"] == {"controlledSides": ["right"]}
            return self.responses.pop(0)
    io = robot.RobotIO()
    io.http = Session()
    try:
        observed, _state, _force, _elapsed = io.observation()
        attempts = observed["observationAttempts"]
        assert [item["http"] for item in attempts] == [503, 200]
        assert attempts[0]["detail"]["gripperFeedback"]["right"]["reason"] == "read_failed"
    finally:
        io.pool.shutdown()
