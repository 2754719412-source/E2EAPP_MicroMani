# 阅读导航 07｜测试与验证
# 职责：回归验证：HKVL 端口绑定、方向校准、阈值和柔顺参数校验。
# 先看：hkvl_config → test_hkvl_force_config_payload_matches_hal_flat_contract → test_hkvl_force_config_payload_uses_pnp_bound_runtime_ports → test_hkvl_force_config_payload_rejects_duplicate_pnp_bound_ports。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from backend.core.config import SettingsService
from backend.core.defaults import default_config
from backend.core.force_config import hal_force_config_payload, hkvl_tare_sample_count, validate_force_config
from backend.core.logging import LogService


@pytest.mark.parametrize("source", ["hkvl_serial", "nidaq"])
def test_force_source_selection_survives_settings_reload(tmp_path: Path, source: str) -> None:
    settings = SettingsService(tmp_path, LogService(emit_startup=False))
    config = settings.get_config()
    assert config["force"]["source"] == "hkvl_serial"
    config["force"]["source"] = source
    config["force"]["leftIp"] = "DevBackup/ai0:5"

    settings.save_config(config, emit_log=False)
    restored = SettingsService(tmp_path, LogService(emit_startup=False)).get_config()

    assert restored["force"]["source"] == source
    assert restored["force"]["leftIp"] == "DevBackup/ai0:5"
    assert hal_force_config_payload(restored)["source"] == source


def test_legacy_config_without_force_source_defaults_to_hkvl(tmp_path: Path) -> None:
    config = default_config()
    config["force"].pop("source")
    config["force"]["leftIp"] = "DevBackup/ai0:5"
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")

    restored = SettingsService(tmp_path, LogService(emit_startup=False)).get_config()

    assert restored["force"]["source"] == "hkvl_serial"
    assert restored["force"]["leftIp"] == "DevBackup/ai0:5"


def hkvl_config() -> dict:
    config = default_config()
    config["force"]["source"] = "hkvl_serial"
    return config


@pytest.mark.parametrize("value", [1, 12, 199, 1001, 5000, 200.5, -1, True, None, "nan"])
def test_hkvl_tare_rejects_inadequate_or_unbounded_sample_windows(value: object) -> None:
    config = hkvl_config()
    config["force"]["tareSamples"] = value
    with pytest.raises(ValueError, match="tareSamples"):
        validate_force_config(config)


@pytest.mark.parametrize(("value", "expected"), [(0, 200), (200, 200), (512, 512), (1000, 1000)])
def test_hkvl_tare_default_and_supported_window_sizes(value: int, expected: int) -> None:
    config = hkvl_config()
    config["force"]["tareSamples"] = value
    validate_force_config(config)
    assert hkvl_tare_sample_count(value) == expected


def test_nidaq_keeps_its_independent_tare_sample_range() -> None:
    config = hkvl_config()
    config["force"].update(source="nidaq", tareSamples=12)
    validate_force_config(config)


def test_hkvl_force_config_payload_matches_hal_flat_contract() -> None:
    config = hkvl_config()
    config["force"]["compliance"]["left"].update(
        {
            "mappingConfirmed": True,
            "matrix": [0.0, 1.0, -1.0, 0.0],
            "deadbandN": [0.2, 0.3],
            "gainUmPerNs": [12.0, 13.0],
            "maxStepUm": [4.0, 5.0],
            "maxOffsetUm": [40.0, 50.0],
        }
    )

    payload = hal_force_config_payload(config)

    assert payload["source"] == "hkvl_serial"
    assert payload["protocol"] == "hkvl_active_v1"
    assert payload["leftPort"] == "COM15"
    assert payload["rightPort"] == "COM14"
    assert payload["leftAxisSign"] == [1.0, 1.0, -1.0, -1.0, -1.0, 1.0]
    assert payload["rightAxisSign"] == [1.0, -1.0, 1.0, -1.0, 1.0, -1.0]
    assert payload["baudrate"] == 1_000_000
    assert payload["expectedSampleHz"] == 1000
    assert payload["fxyWarnN"] == 2
    assert payload["fxyStopN"] == 30
    assert payload["fzStopN"] == 30
    assert payload["momentStopNm"] == 1
    assert payload["watchdogMs"] == 50
    assert payload["acknowledgeStableMs"] == 500
    assert payload["leftMappingConfirmed"] is True
    assert payload["leftComplianceMatrix"] == [0.0, 1.0, -1.0, 0.0]
    assert payload["leftComplianceGainUmPerNs"] == [12.0, 13.0]


def test_hkvl_force_config_payload_uses_pnp_bound_runtime_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APPSTATION_HKVL_LEFT_PORT", "COM31")
    monkeypatch.setenv("APPSTATION_HKVL_RIGHT_PORT", "COM32")

    payload = hal_force_config_payload(hkvl_config())

    assert payload["leftPort"] == "COM31"
    assert payload["rightPort"] == "COM32"


def test_hkvl_force_config_payload_rejects_duplicate_pnp_bound_ports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APPSTATION_HKVL_LEFT_PORT", "COM31")
    monkeypatch.setenv("APPSTATION_HKVL_RIGHT_PORT", "com31")

    with pytest.raises(ValueError, match="runtime ports must be present and different"):
        hal_force_config_payload(hkvl_config())


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("force", "source"), "serial", "force.source"),
        (("force", "serial", "protocol"), "modbus", "protocol"),
        (("force", "serial", "baudrate"), 115_200, "1 Mbps"),
        (("force", "serial", "rightPort"), "COM15", "different"),
        (("safety", "fxyWarnN"), 30.0, "fxy"),
        (("safety", "fzStopN"), 31.0, "fz"),
        (("safety", "momentStopNm"), 1.1, "moment"),
    ],
)
def test_invalid_hkvl_force_configuration_is_rejected(
    path: tuple[str, ...],
    value: object,
    message: str,
) -> None:
    config = hkvl_config()
    target = config
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ValueError, match=message):
        validate_force_config(config)


def test_compliance_cannot_be_enabled_until_both_mappings_are_confirmed() -> None:
    config = hkvl_config()
    config["force"]["compliance"]["enabled"] = True
    config["force"]["compliance"]["left"]["mappingConfirmed"] = True

    with pytest.raises(ValueError, match="mappingConfirmed"):
        validate_force_config(config)


def test_compliance_arrays_have_fixed_sizes_and_nonnegative_limits() -> None:
    too_short = hkvl_config()
    too_short["force"]["compliance"]["left"]["matrix"] = [1.0, 0.0]
    with pytest.raises(ValueError, match="matrix"):
        validate_force_config(too_short)

    negative = deepcopy(hkvl_config())
    negative["force"]["compliance"]["right"]["maxStepUm"] = [1.0, -1.0]
    with pytest.raises(ValueError, match="maxStepUm"):
        validate_force_config(negative)


def test_hkvl_force_axis_direction_uses_the_dedicated_calibration() -> None:
    config = hkvl_config()
    config["motion"]["kinematics"]["leftSignedPulsePerUnit"] = [1.0] * 6

    assert hal_force_config_payload(config)["leftAxisSign"] == [1.0, 1.0, -1.0, -1.0, -1.0, 1.0]


@pytest.mark.parametrize("value", ([1.0, 0.0, -1.0, 1.0, -1.0, 1.0], [1.0] * 5))
def test_hkvl_force_axis_direction_requires_six_unit_signs(value: list[float]) -> None:
    config = hkvl_config()
    config["force"]["axisSign"]["left"] = value

    with pytest.raises(ValueError, match="force.axisSign.left"):
        validate_force_config(config)


@pytest.mark.parametrize("key", ["replayTrackingLimitUm", "replayTrackingLimitDeg"])
@pytest.mark.parametrize("value", [0, -1, float("nan"), "x", "500", True])
def test_replay_tracking_limits_must_be_positive_numbers(key: str, value: object) -> None:
    config = default_config()
    config["safety"][key] = value
    with pytest.raises(ValueError, match=key):
        validate_force_config(config)


def test_replay_tracking_limits_default_and_can_be_raised() -> None:
    config = default_config()
    assert config["safety"]["replayTrackingLimitUm"] == 500
    assert config["safety"]["replayTrackingLimitDeg"] == 1.0
    config["safety"].update(replayTrackingLimitUm=3000, replayTrackingLimitDeg=5)
    validate_force_config(config)


@pytest.mark.parametrize("legacy,expected", [("500", 500.0), (" 750.5 ", 750.5), (True, 500.0), ("abc", 500.0), (-3, 500.0)])
def test_legacy_replay_tracking_limit_is_migrated_without_resetting_config(tmp_path: Path, legacy: object, expected: float) -> None:
    """旧版允许字符串阈值：读取时只迁移该项，缺少默认字段触发迁移保存时也不能整份重置。"""
    config = default_config()
    config["safety"]["replayTrackingLimitUm"] = legacy
    config["safety"]["replayTrackingLimitDeg"] = "2"
    config["cameras"]["globalIdentity"] = "custom-camera-identity"
    config["motion"].pop("workOriginStrategyVersion", None)  # 需要补齐/迁移的字段，迫使读取后落盘
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")
    logs = LogService(emit_startup=False)

    restored = SettingsService(tmp_path, logs).get_config()

    assert restored["safety"]["replayTrackingLimitUm"] == expected
    assert restored["safety"]["replayTrackingLimitDeg"] == 2.0
    assert restored["cameras"]["globalIdentity"] == "custom-camera-identity"
    assert not any("default config restored" in entry.msg for entry in logs.list_entries())
    assert any("replayTrackingLimitUm" in entry.msg for entry in logs.list_entries())
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert saved["safety"]["replayTrackingLimitUm"] == expected
    validate_force_config(restored)


def test_legacy_boolean_replay_threshold_is_written_back_even_when_equal_in_python(tmp_path: Path) -> None:
    """True == 1.0 在 Python 中相等；迁移记录必须驱动写回，磁盘上不能残留 true。"""
    config = SettingsService(tmp_path, LogService(emit_startup=False)).get_config()
    config["safety"]["replayTrackingLimitDeg"] = True
    (tmp_path / "config.json").write_text(json.dumps(config), encoding="utf-8")

    restored = SettingsService(tmp_path, LogService(emit_startup=False)).get_config()

    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert restored["safety"]["replayTrackingLimitDeg"] == 1.0
    assert saved["safety"]["replayTrackingLimitDeg"] is not True
    assert saved["safety"]["replayTrackingLimitDeg"] == 1.0
