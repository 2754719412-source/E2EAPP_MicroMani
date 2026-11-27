# 阅读导航 03｜后端契约与配置
# 职责：校验 HKVL 串口、六轴方向、安全阈值与柔顺参数，并转换为 HAL 的扁平配置。
# 先看：validate_force_config → hal_force_config_payload。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。

from __future__ import annotations

import math
import os
from typing import Any

HKVL_TARE_DEFAULT_SAMPLES = 200
HKVL_TARE_MAX_SAMPLES = 1000


def hkvl_tare_sample_count(value: object) -> int:
    samples = _number(value, "force.tareSamples")
    if isinstance(value, bool) or not samples.is_integer() or (
        samples != 0 and not HKVL_TARE_DEFAULT_SAMPLES <= samples <= HKVL_TARE_MAX_SAMPLES
    ):
        raise ValueError("HKVL force.tareSamples must be 0 (default 200) or an integer from 200 to 1000")
    return int(samples) if samples else HKVL_TARE_DEFAULT_SAMPLES


def _mapping(value: object, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _number(value: object, name: str) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(result):
        raise ValueError(f"{name} must be a finite number")
    return result


def _number_array(value: object, name: str, size: int, *, nonnegative: bool) -> list[float]:
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f"{name} must contain exactly {size} numbers")
    result = [_number(item, f"{name}[{index}]") for index, item in enumerate(value)]
    if nonnegative and any(item < 0 for item in result):
        raise ValueError(f"{name} values must be nonnegative")
    return result


def _force_axis_signs(config: dict[str, Any]) -> dict[str, list[float]]:
    force = _mapping(config.get("force"), "force")
    axis_sign = _mapping(force.get("axisSign"), "force.axisSign")
    result: dict[str, list[float]] = {}
    for side in ("left", "right"):
        values = _number_array(
            axis_sign.get(side),
            f"force.axisSign.{side}",
            6,
            nonnegative=False,
        )
        if any(value not in {-1.0, 1.0} for value in values):
            raise ValueError(f"force.axisSign.{side} values must be either -1 or 1")
        result[side] = values
    return result


def _compliance_axis_signs(config: dict[str, Any], side: str) -> list[Any] | None:
    # HAL 导纳只用方向换算后的 Fx、Fz，二者符号翻转等同反转导纳方向；其他轴不影响。
    force = config.get("force")
    axis_sign = force.get("axisSign") if isinstance(force, dict) else None
    signs = axis_sign.get(side) if isinstance(axis_sign, dict) else None
    return [signs[0], signs[2]] if isinstance(signs, list) and len(signs) == 6 else None


REPLAY_TRACKING_LIMIT_DEFAULTS = {"replayTrackingLimitUm": 500.0, "replayTrackingLimitDeg": 1.0}


def replay_tracking_limit_values(safety: object) -> tuple[float, float]:
    """回放跟踪偏差阈值（μm, degree）；保存、预检与启动共用，拒绝布尔、字符串与非正数。"""
    section = safety if isinstance(safety, dict) else {}
    values = []
    for key, default in REPLAY_TRACKING_LIMIT_DEFAULTS.items():
        value = section.get(key, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"safety.{key} must be a positive number")
        values.append(float(value))
    return values[0], values[1]


def migrate_replay_tracking_limits(safety: object) -> list[str]:
    """旧版曾允许把回放阈值存成字符串：数字字符串转为数值，其他非法值恢复默认；返回迁移说明。"""
    if not isinstance(safety, dict):
        return []
    notes = []
    for key, default in REPLAY_TRACKING_LIMIT_DEFAULTS.items():
        if key not in safety:
            continue
        value = safety[key]
        try:
            replay_tracking_limit_values({key: value})
            continue
        except ValueError:
            pass
        migrated = default
        if isinstance(value, str):
            try:
                parsed = float(value.strip())
            except ValueError:
                parsed = math.nan
            if math.isfinite(parsed) and parsed > 0:
                migrated = parsed
        safety[key] = migrated
        notes.append(f"safety.{key} 旧值 {value!r} 已迁移为 {migrated:g}")
    return notes


# safety 中随 force.configure 下发到 HAL 的力安全参数；其余 safety 键（如回放跟踪阈值）只在后端使用。
FORCE_SAFETY_KEYS = frozenset({
    "fxyWarnN", "fxyStopN", "fzWarnN", "fzStopN", "momentWarnNm", "momentStopNm", "watchdogMs",
})


def without_force_settings(config: dict[str, Any]) -> dict[str, Any]:
    """去掉 force 及其 HAL 力安全参数，用于判断一次修改是否只涉及力配置。"""
    trimmed = {key: value for key, value in config.items() if key != "force"}
    safety = config.get("safety")
    if isinstance(safety, dict):
        trimmed["safety"] = {key: value for key, value in safety.items() if key not in FORCE_SAFETY_KEYS}
    return trimmed


def invalidate_changed_force_mappings(
    current: dict[str, Any], candidate: dict[str, Any], *, confirm_side: str | None = None,
) -> None:
    previous_force = current.get("force")
    previous_compliance = previous_force.get("compliance") if isinstance(previous_force, dict) else None
    compliance = _mapping(_mapping(candidate.get("force"), "force").get("compliance"), "force.compliance")
    for side in ("left", "right"):
        previous = previous_compliance.get(side) if isinstance(previous_compliance, dict) else None
        updated = _mapping(compliance.get(side), f"force.compliance.{side}")
        changed = (not isinstance(previous, dict) or previous.get("matrix") != updated.get("matrix")
                   or _compliance_axis_signs(current, side) != _compliance_axis_signs(candidate, side))
        if changed and side == confirm_side:
            raise ValueError("请先保存新矩阵或 Fx/Fz 方向，再确认该侧映射")
        # 重试完整设置或重复应用旧快照，不能替操作者确认刚失效的矩阵。
        unconfirmed = (side != confirm_side and isinstance(previous, dict)
                       and previous.get("mappingConfirmed") is not True and updated.get("mappingConfirmed"))
        if changed or unconfirmed:
            updated["mappingConfirmed"] = False
            compliance["enabled"] = False


def validate_force_config(config: dict[str, Any]) -> None:
    force = _mapping(config.get("force"), "force")
    safety = _mapping(config.get("safety"), "safety")
    source = str(force.get("source", "hkvl_serial")).lower()
    if source not in {"nidaq", "hkvl_serial"}:
        raise ValueError("force.source must be nidaq or hkvl_serial")

    serial = _mapping(force.get("serial"), "force.serial")
    if source == "hkvl_serial":
        hkvl_tare_sample_count(force.get("tareSamples", 0))
        if str(serial.get("protocol", "")) != "hkvl_active_v1":
            raise ValueError("HKVL force protocol must be hkvl_active_v1")
        left_port = str(serial.get("leftPort", "")).strip().upper()
        right_port = str(serial.get("rightPort", "")).strip().upper()
        if not left_port or not right_port or left_port == right_port:
            raise ValueError("HKVL left and right serial ports must be present and different")
        if int(serial.get("baudrate", 0)) != 1_000_000:
            raise ValueError("HKVL serial baudrate must be fixed at 1 Mbps")
        if int(serial.get("expectedSampleHz", 0)) != 1000:
            raise ValueError("HKVL expected sample rate must be 1000 Hz")
        _force_axis_signs(config)

    thresholds = (
        ("fxy", "fxyWarnN", "fxyStopN", 30.0),
        ("fz", "fzWarnN", "fzStopN", 30.0),
        ("moment", "momentWarnNm", "momentStopNm", 1.0),
    )
    for label, warn_key, stop_key, upper_bound in thresholds:
        warn = _number(safety.get(warn_key), f"safety.{warn_key}")
        stop = _number(safety.get(stop_key), f"safety.{stop_key}")
        if not 0 < warn < stop <= upper_bound:
            raise ValueError(
                f"{label} thresholds must satisfy 0 < {warn_key} < {stop_key} <= {upper_bound:g}"
            )
    if _number(safety.get("watchdogMs"), "safety.watchdogMs") <= 0:
        raise ValueError("safety.watchdogMs must be positive")
    replay_tracking_limit_values(safety)

    compliance = _mapping(force.get("compliance"), "force.compliance")
    enabled = bool(compliance.get("enabled", False))
    if enabled and source != "hkvl_serial":
        raise ValueError("force.compliance requires force.source=hkvl_serial")
    for side in ("left", "right"):
        side_config = _mapping(compliance.get(side), f"force.compliance.{side}")
        _number_array(
            side_config.get("matrix"),
            f"force.compliance.{side}.matrix",
            4,
            nonnegative=False,
        )
        for key in ("deadbandN", "gainUmPerNs", "maxStepUm", "maxOffsetUm"):
            _number_array(
                side_config.get(key),
                f"force.compliance.{side}.{key}",
                2,
                nonnegative=True,
            )
        if enabled and not bool(side_config.get("mappingConfirmed", False)):
            raise ValueError(
                f"force.compliance.{side}.mappingConfirmed must be true before enabling compliance"
            )


def hal_force_config_payload(config: dict[str, Any]) -> dict[str, Any]:
    validate_force_config(config)
    force = _mapping(config["force"], "force")
    serial = _mapping(force["serial"], "force.serial")
    safety = _mapping(config["safety"], "safety")
    compliance = _mapping(force["compliance"], "force.compliance")
    axis_signs = _force_axis_signs(config)
    source = str(force["source"]).lower()
    left_port = str(serial["leftPort"])
    right_port = str(serial["rightPort"])
    if source == "hkvl_serial":
        # 启动脚本按设备 PnP 身份解析的实际 COM 口通过环境变量覆盖配置值，避免 USB 重枚举后左右错接。
        left_port = os.getenv("APPSTATION_HKVL_LEFT_PORT", left_port).strip().upper()
        right_port = os.getenv("APPSTATION_HKVL_RIGHT_PORT", right_port).strip().upper()
        if not left_port or not right_port or left_port == right_port:
            raise ValueError("HKVL runtime ports must be present and different")
    payload: dict[str, Any] = {
        "source": source,
        "protocol": str(serial["protocol"]),
        "leftPort": left_port,
        "rightPort": right_port,
        "leftAxisSign": axis_signs["left"],
        "rightAxisSign": axis_signs["right"],
        "baudrate": int(serial["baudrate"]),
        "expectedSampleHz": int(serial["expectedSampleHz"]),
        "lowpassEnabled": bool(force.get("lowpassEnabled", True)),
        "lowpassCutoffHz": _number(force.get("lowpassCutoffHz", 10), "force.lowpassCutoffHz"),
        "fxyWarnN": _number(safety["fxyWarnN"], "safety.fxyWarnN"),
        "fxyStopN": _number(safety["fxyStopN"], "safety.fxyStopN"),
        "fzWarnN": _number(safety["fzWarnN"], "safety.fzWarnN"),
        "fzStopN": _number(safety["fzStopN"], "safety.fzStopN"),
        "momentWarnNm": _number(safety["momentWarnNm"], "safety.momentWarnNm"),
        "momentStopNm": _number(safety["momentStopNm"], "safety.momentStopNm"),
        "watchdogMs": _number(safety["watchdogMs"], "safety.watchdogMs"),
        "acknowledgeStableMs": 500,
        "complianceEnabled": bool(compliance.get("enabled", False)),
    }
    for side in ("left", "right"):
        side_config = _mapping(compliance[side], f"force.compliance.{side}")
        prefix = side
        payload[f"{prefix}MappingConfirmed"] = bool(side_config.get("mappingConfirmed", False))
        payload[f"{prefix}ComplianceMatrix"] = _number_array(
            side_config["matrix"],
            f"force.compliance.{side}.matrix",
            4,
            nonnegative=False,
        )
        for config_key, payload_suffix in (
            ("deadbandN", "DeadbandN"),
            ("gainUmPerNs", "GainUmPerNs"),
            ("maxStepUm", "MaxStepUm"),
            ("maxOffsetUm", "MaxOffsetUm"),
        ):
            payload[f"{prefix}Compliance{payload_suffix}"] = _number_array(
                side_config[config_key],
                f"force.compliance.{side}.{config_key}",
                2,
                nonnegative=True,
            )
    return payload
