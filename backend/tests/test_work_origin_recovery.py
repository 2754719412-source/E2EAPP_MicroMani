from copy import deepcopy
import asyncio
from unittest.mock import AsyncMock

import pytest

from backend.core.data_contract import data_contract_metadata
from backend.tests.test_hardware_homing import setup_homing


def test_work_origin_return_rejects_controller_restart_before_dispatch(tmp_path, monkeypatch):
    client, hal, state = setup_homing(tmp_path, monkeypatch)
    before = deepcopy(client.app.state.settings.get_config()["motion"])
    hal.instance["id"] = "after-power-cycle"
    state["pulses"] = [0.] * 12

    async def command(name, payload):
        if name == "motion.home_origin_side":
            state["pulses"][6:] = payload["pulse"]
        return {"response": {"ok": True}}

    hal.command.side_effect = command
    response = client.post("/api/motion/right/return_origin")

    assert response.status_code == 503, response.text
    assert "工作原点未在当前控制器会话恢复" in response.text
    hal.command.assert_not_awaited()
    assert client.app.state.settings.get_config()["motion"] == before


def calibrated_xy(tmp_path, monkeypatch):
    client, hal, state = setup_homing(tmp_path, monkeypatch)
    response = client.post("/api/motion/left/origin/capture", json={"confirmLargeDrift": True})
    assert response.status_code == 200, response.text
    state["pulses"][:2] = [1000., 2000.]
    hal.command.return_value = {"response": {
        "homeCompleted": True, "limitReferenceAxes": [True, True, False, False, False, False]}}
    response = client.post("/api/motion/left/positive_limit_reference", json={"axes": ["X", "Y"]})
    assert response.status_code == 200, response.text
    return client, hal, state


def test_power_cycle_recovers_xy_from_fixed_offsets_and_returns_only_restored_axes(tmp_path, monkeypatch):
    client, hal, state = calibrated_xy(tmp_path, monkeypatch)
    before = deepcopy(client.app.state.settings.get_config()["motion"])
    offset = before["workOriginOffset"]["leftPulseDelta"][:2]
    hal.instance["id"] = "after-power-cycle"
    state["pulses"] = [0.] * 12
    new_reference = [4100., 6100.]

    async def command(name, payload):
        if name == "motion.home_side":
            state["pulses"][:2] = new_reference
            return {"response": {"homeCompleted": True, "limitReferenceAxes": [True, True, False, False, False, False]}}
        assert name == "motion.home_origin_side"
        assert payload["expectedInstanceId"] == "after-power-cycle"
        for i, selected in enumerate(payload["enabledAxes"]):
            if selected:
                state["pulses"][i] = payload["pulse"][i]
        return {"response": {"ok": True}}

    hal.command.side_effect = command
    response = client.post("/api/motion/left/positive_limit_reference", json={"axes": ["X", "Y"]})
    assert response.status_code == 200, response.text
    after = client.app.state.settings.get_config()["motion"]
    expected = [new_reference[i] + offset[i] for i in range(2)]
    assert after["origin"]["leftPulse"][:2] == expected
    assert after["origin"]["leftPulse"][2:] == before["origin"]["leftPulse"][2:]
    assert after["origin"]["rightPulse"] == before["origin"]["rightPulse"]
    assert after["workOriginOffset"] == before["workOriginOffset"]
    assert after["origin"]["leftAxisInstanceId"][:2] == ["after-power-cycle"] * 2
    hal.command.reset_mock()
    assert client.post("/api/motion/left/return_origin").status_code == 503
    hal.command.assert_not_awaited()
    response = client.post("/api/motion/left/return_origin", json={"axes": ["X", "Y"]})
    assert response.status_code == 200, response.text
    assert state["pulses"] == expected + [0.] * 10
    assert not client.app.state.recorder.status()["resetReady"]


def test_same_instance_limit_measurement_keeps_work_position(tmp_path, monkeypatch):
    client, hal, state = calibrated_xy(tmp_path, monkeypatch)
    before = deepcopy(client.app.state.settings.get_config()["motion"])
    state["pulses"][:2] = [1003., 2004.]
    response = client.post("/api/motion/left/positive_limit_reference", json={"axes": ["X", "Y"]})
    assert response.status_code == 200, response.text
    after = client.app.state.settings.get_config()["motion"]
    assert after["origin"] == before["origin"]
    assert after["workOriginOffset"]["leftPulseDelta"][:2] == [100. - 1003., 101. - 2004.]


def test_legacy_offsets_are_retained_but_not_used_as_calibration(tmp_path, monkeypatch):
    client, hal, state = calibrated_xy(tmp_path, monkeypatch)
    settings = client.app.state.settings
    config = settings.get_config()
    config["motion"]["workOriginOffset"].pop("leftAxisReferenceKind")
    settings.save_config(config, emit_log=False, work_origin_update=True)
    before = deepcopy(settings.get_config()["motion"])
    hal.instance["id"] = "after-power-cycle"
    state["pulses"][:2] = [500., 600.]
    assert client.post("/api/motion/left/positive_limit_reference", json={"axes": ["X", "Y"]}).status_code == 200
    after = settings.get_config()["motion"]
    assert after["origin"]["leftPulse"] == before["origin"]["leftPulse"]
    assert after["workOriginOffset"] == before["workOriginOffset"]
    hal.command.reset_mock()
    assert client.post("/api/motion/left/return_origin", json={"axes": ["X", "Y"]}).status_code == 503
    hal.command.assert_not_awaited()


def test_capture_after_restart_does_not_calibrate_against_old_reference(tmp_path, monkeypatch):
    client, hal, state = calibrated_xy(tmp_path, monkeypatch)
    hal.instance["id"] = "after-power-cycle"
    state["pulses"][:6] = [300.] * 6
    assert client.post("/api/motion/left/origin/capture").status_code == 200
    captured = client.app.state.settings.get_config()["motion"]
    assert captured["origin"]["leftAxisInstanceId"] == ["after-power-cycle"] * 6
    assert captured["workOriginOffset"]["leftAxisReferenceKind"] == [""] * 6
    state["pulses"][:2] = [1100., 2100.]
    assert client.post("/api/motion/left/positive_limit_reference", json={"axes": ["X", "Y"]}).status_code == 200
    after = client.app.state.settings.get_config()["motion"]
    assert after["origin"]["leftPulse"] == [300.] * 6
    assert after["workOriginOffset"]["leftPulseDelta"][:2] == [-800., -1800.]
    assert after["workOriginOffset"]["leftAxisReferenceKind"][:2] == ["positive_limit"] * 2


def test_failed_recovery_retains_calibration_but_cannot_return(tmp_path, monkeypatch):
    client, hal, _ = calibrated_xy(tmp_path, monkeypatch)
    before = deepcopy(client.app.state.settings.get_config()["motion"])
    hal.instance["id"] = "after-power-cycle"
    hal.command.side_effect = RuntimeError("limit signal missing")
    assert client.post("/api/motion/left/positive_limit_reference", json={"axes": ["X", "Y"]}).status_code == 503
    after = client.app.state.settings.get_config()["motion"]
    assert after["origin"] == before["origin"]
    assert after["workOriginOffset"] == before["workOriginOffset"]
    hal.command.reset_mock()
    assert client.post("/api/motion/left/return_origin", json={"axes": ["X", "Y"]}).status_code == 503
    hal.command.assert_not_awaited()


def test_settings_cannot_forge_origin_instance_or_calibration(tmp_path, monkeypatch):
    client, hal, _ = calibrated_xy(tmp_path, monkeypatch)
    settings = client.app.state.settings
    hal.instance["id"] = "after-power-cycle"
    config = settings.get_config()
    config["motion"]["origin"]["leftAxisInstanceId"] = [hal.instance["id"]] * 6
    config["motion"]["workOriginOffset"]["leftAxisReferenceKind"] = ["positive_limit"] * 6
    saved = settings.save_config(config, emit_log=False)
    assert saved["motion"]["origin"]["leftAxisInstanceId"] == ["test-hal-instance"] * 6
    assert saved["motion"]["workOriginOffset"]["leftAxisReferenceKind"][2:] == ["origin"] * 4
    config["motion"]["origin"]["leftPulse"][0] += 1
    saved = settings.save_config(config, emit_log=False)
    assert saved["motion"]["origin"]["leftAxisInstanceId"][0] == ""
    assert saved["motion"]["workOriginOffset"]["leftAxisReferenceKind"][0] == ""


@pytest.mark.parametrize("axes", [[], ["X", "X"], ["unknown"]])
def test_invalid_partial_return_never_dispatches(tmp_path, monkeypatch, axes):
    client, hal, _ = setup_homing(tmp_path, monkeypatch)
    assert client.post("/api/motion/right/return_origin", json={"axes": axes}).status_code == 422
    hal.command.assert_not_awaited()


@pytest.mark.parametrize("entry", ["teleop", "recording", "replay", "policy"])
def test_stale_origin_cannot_enter_automatic_motion(tmp_path, monkeypatch, entry):
    client, hal, state = calibrated_xy(tmp_path, monkeypatch)
    hal.instance["id"] = "after-power-cycle"
    hal.command.reset_mock()
    app = client.app
    app.state.commands.safety.readiness_check = None
    config = app.state.settings.get_config()
    if entry == "policy":
        monkeypatch.setattr("backend.app.PolicyGripperObservation.read", AsyncMock(return_value=([0., 0.], {})))
        response = client.post("/api/policy/action", json={
            "action": [0.] * 14, "dryRun": False, "controlledSides": ["right"],
            "dataContract": data_contract_metadata(),
        })
        assert response.status_code == 503, response.text
        assert "工作原点未在当前控制器会话恢复" in response.text
    else:
        if entry == "teleop":
            call = app.state.services.teleop_mapper._return_to_work_origin_before_start(config, "left")
        elif entry == "recording":
            call = app.state.commands.validate_record_origin({"left"})
        else:
            replay = app.state.replay
            replay._participation = {"version": "appstation.participation.v1", "arms": ["right"], "grippers": []}
            call = replay._send([0.] * 14, config, replay.safety.capture())
        with pytest.raises(RuntimeError, match="工作原点未在当前控制器会话恢复"):
            asyncio.run(call)
    hal.command.assert_not_awaited()


def test_reference_kind_must_match_before_restoring_offset(tmp_path, monkeypatch):
    client, hal, state = calibrated_xy(tmp_path, monkeypatch)
    config = client.app.state.settings.get_config()
    config["motion"]["workOriginOffset"]["leftAxisReferenceKind"][2] = "positive_limit"
    client.app.state.settings.save_config(config, emit_log=False, work_origin_update=True)
    before = deepcopy(client.app.state.settings.get_config()["motion"])
    hal.instance["id"] = "after-power-cycle"
    hal.command.return_value = {"response": {"homeCompleted": True}}
    state["pulses"][2] = 9000.
    assert client.post("/api/motion/left/home", json={"axes": ["Z"]}).status_code == 200
    after = client.app.state.settings.get_config()["motion"]
    assert after["origin"]["leftPulse"][2] == before["origin"]["leftPulse"][2]
    assert after["origin"]["leftAxisInstanceId"][2] == ""
    assert after["workOriginOffset"] == before["workOriginOffset"]


def test_capture_cannot_save_across_instance_change(tmp_path, monkeypatch):
    client, hal, _ = setup_homing(tmp_path, monkeypatch)
    before = deepcopy(client.app.state.settings.get_config()["motion"])
    original_health = hal.health
    calls = 0

    async def health():
        nonlocal calls
        calls += 1
        if calls == 2:
            hal.instance["id"] = "restarted-during-capture"
        return await original_health()

    hal.health = health
    response = client.post("/api/motion/right/origin/capture")
    assert response.status_code == 503
    assert client.app.state.settings.get_config()["motion"] == before


def test_old_hal_cannot_silently_ignore_instance_check(tmp_path, monkeypatch):
    client, hal, _ = setup_homing(tmp_path, monkeypatch)
    original_health = hal.health

    async def health():
        result = await original_health()
        result.capabilities = []
        return result

    hal.health = health
    response = client.post("/api/motion/right/return_origin")
    assert response.status_code == 503
    assert "HAL 尚不支持工作原点实例校验" in response.text
    hal.command.assert_not_awaited()
