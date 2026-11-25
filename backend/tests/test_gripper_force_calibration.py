# 阅读导航 07｜测试与验证
# 职责：回归验证：Modbus 帧与手册样例一致；夹持力标定拟合、反解与 commandForceLimitN 生效条件。
# 先看：test_modbus_frames_match_manual_examples → test_fit_recovers_linear_model_and_reports_quality → test_grip_torque_uses_calibrated_force_limit_when_enabled。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。

"""夹爪 Modbus 帧与夹持力标定的离线回归；帧样例取自钧舵 EPG 手册 A.1 第 7 章。"""

from __future__ import annotations

import random

import pytest

from backend.core.defaults import default_config
from backend.core.gripper_force import (
    CalibrationError,
    effective_grip_torque,
    fit_force_calibration,
    force_n_for_rfc,
    rfc_for_force_n,
    side_calibration,
    summarize_baseline,
)
from backend.core.jodell_modbus import (
    GOBJ_CONTACT_CLOSING,
    GOBJ_MOVING,
    check_crc,
    move_request,
    parse_status_response,
    position_raw_for_gap_mm,
    read_status_request,
)


def test_modbus_frames_match_manual_examples() -> None:
    assert read_status_request(9) == bytes.fromhex("09 04 07 D0 00 03 B1 CE")
    assert move_request(9, position_raw=0xFF, speed_raw=0xFF, force_raw=0xFF) == bytes.fromhex(
        "09 10 03 E8 00 03 06 00 09 FF 00 FF FF 9E 95"
    )
    assert check_crc(bytes.fromhex("09 10 03 E8 00 03 01 30"))


def test_modbus_status_parses_moving_and_clamped_examples() -> None:
    moving = parse_status_response(bytes.fromhex("09 04 06 00 39 89 00 01 00 B0 9A"), 9)
    assert (moving.gOBJ, moving.gSTA, moving.gGTO, moving.gACT) == (GOBJ_MOVING, 3, 1, 1)
    assert (moving.position_raw, moving.current_raw, moving.fault) == (0x89, 0x01, 0)

    clamped = parse_status_response(bytes.fromhex("09 04 06 00 B1 AE 00 FE 00 1B C1"), 9)
    assert clamped.gOBJ == GOBJ_CONTACT_CLOSING
    assert (clamped.position_raw, clamped.current_raw) == (0xAE, 0xFE)


def test_modbus_status_rejects_bad_crc_and_wrong_slave() -> None:
    with pytest.raises(ValueError, match="CRC"):
        parse_status_response(bytes.fromhex("09 04 06 00 B1 AE 00 FE 00 1B C2"), 9)
    with pytest.raises(ValueError, match="header"):
        parse_status_response(bytes.fromhex("09 04 06 00 B1 AE 00 FE 00 1B C1"), 10)


def test_position_raw_matches_driver_conversion() -> None:
    assert position_raw_for_gap_mm(26.0, 26.0) == 0
    assert position_raw_for_gap_mm(1.02, 26.0) == round((26 - 1.02) / 26 * 255)
    assert position_raw_for_gap_mm(-5.0, 26.0) == 255


def _synthetic_points(slope: float = 0.02, intercept: float = 1.5) -> list[dict[str, object]]:
    rng = random.Random(7)
    points: list[dict[str, object]] = []
    for sequence, settings in (("ascending", (40, 80, 120, 160, 200)), ("descending", (200, 160, 120, 80, 40))):
        for rfc in settings:
            for _ in range(2):
                points.append({
                    "rfcRaw": rfc,
                    "forceN": slope * rfc + intercept + rng.uniform(-0.03, 0.03)
                    + (0.05 if sequence == "descending" else 0),
                    "currentRaw": min(254, rfc + rng.randint(-2, 2)),
                    "sequence": sequence,
                })
    return points


def _calibration() -> dict[str, object]:
    baseline = [3, 4, 3, 5, 4, 3, 4, 4, 3, 5, 4, 3]
    return fit_force_calibration(
        _synthetic_points(), baseline, port="COM8", slave_id=10, calibrated_at_ms=1, reference="unit"
    )


def test_fit_recovers_linear_model_and_reports_quality() -> None:
    calibration = _calibration()
    fit = calibration["rfcToForceN"]
    assert fit["slope"] == pytest.approx(0.02, abs=1e-3)
    assert fit["intercept"] == pytest.approx(1.525, abs=0.05)
    assert fit["rmsResidualN"] < 0.06
    assert fit["hysteresisN"] == pytest.approx(0.05, abs=0.04)
    assert (fit["rfcMin"], fit["rfcMax"], fit["points"]) == (40, 200, 20)
    assert calibration["holdCurrentRaw"]["slope"] == pytest.approx(1.0, abs=0.05)
    assert calibration["baseline"]["contactThresholdRaw"] > calibration["baseline"]["currentMaxRaw"]


def test_inverse_floors_and_never_extrapolates_above_range() -> None:
    calibration = _calibration()
    result = rfc_for_force_n(calibration, 3.5)
    assert force_n_for_rfc(calibration, result["rfcRaw"]) <= 3.5
    assert force_n_for_rfc(calibration, result["rfcRaw"] + 1) > 3.5
    high = rfc_for_force_n(calibration, 50.0)
    assert high["rfcRaw"] == 200 and high["clampedHigh"]
    low = rfc_for_force_n(calibration, 0.0)
    assert low["rfcRaw"] == 1 and low["extrapolatedLow"]


@pytest.mark.parametrize(
    ("points", "message"),
    [
        ([{"rfcRaw": 50, "forceN": 1, "currentRaw": 50}, {"rfcRaw": 60, "forceN": 2, "currentRaw": 60}], "至少需要"),
        ([{"rfcRaw": r, "forceN": 10 - r / 50, "currentRaw": r} for r in (50, 100, 150)], "斜率非正"),
        ([{"rfcRaw": 300, "forceN": 1, "currentRaw": 1}], "超出"),
        ([{"rfcRaw": 50, "forceN": "nan", "currentRaw": 1}], "有限"),
    ],
)
def test_fit_rejects_unusable_points(points: list[dict[str, object]], message: str) -> None:
    with pytest.raises(CalibrationError, match=message):
        fit_force_calibration(points, [1] * 20, port="COM8", slave_id=10)


def test_baseline_requires_enough_samples() -> None:
    with pytest.raises(CalibrationError, match="样本不足"):
        summarize_baseline([1, 2, 3])


def _config_with_calibration(apply: bool) -> dict[str, object]:
    config = default_config()
    config["gripper"]["leftEnabled"] = True
    config["gripper"]["commandForceLimitN"] = 3.5
    config["gripper"]["forceCalibration"] = {"applyCommandForceLimit": apply, "left": _calibration(), "right": None}
    config["teleop"]["gripperTeleop"]["gripTorque"] = 7
    return config


def test_grip_torque_defaults_to_configured_raw_value() -> None:
    assert effective_grip_torque(default_config())["rfcRaw"] == 1
    result = effective_grip_torque(_config_with_calibration(apply=False))
    assert result == {"rfcRaw": 7, "source": "gripTorque", "reason": "applyCommandForceLimit disabled"}


def test_grip_torque_uses_calibrated_force_limit_when_enabled() -> None:
    config = _config_with_calibration(apply=True)
    result = effective_grip_torque(config)
    assert result["source"] == "commandForceLimitN"
    assert result["rfcRaw"] == rfc_for_force_n(config["gripper"]["forceCalibration"]["left"], 3.5)["rfcRaw"]
    assert result["expectedForceN"]["left"] <= 3.5


def test_grip_torque_falls_back_when_any_enabled_side_is_uncalibrated_or_rewired() -> None:
    config = _config_with_calibration(apply=True)
    config["gripper"]["rightEnabled"] = True
    assert effective_grip_torque(config) == {
        "rfcRaw": 7, "source": "gripTorque", "reason": "right gripper not calibrated"
    }
    rewired = _config_with_calibration(apply=True)
    rewired["gripper"]["leftPort"] = "COM3"
    assert side_calibration(rewired, "left") is None
    assert effective_grip_torque(rewired)["source"] == "gripTorque"


def test_hal_payloads_send_effective_grip_torque() -> None:
    from backend.services.gripper_backend import native_gripper_payload

    config = _config_with_calibration(apply=True)
    expected = effective_grip_torque(config)["rfcRaw"]
    assert native_gripper_payload(config, "left", 10.0)["gripTorque"] == expected
