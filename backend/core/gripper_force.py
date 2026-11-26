# 阅读导航 03｜后端契约与配置
# 职责：夹持力标定：空载电流基线、rFC→N 拟合、N→rFC 反解，以及按 commandForceLimitN 选择下发的 rFC。
# 先看：fit_force_calibration → rfc_for_force_n → calibration_matches → effective_grip_torque。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。

"""夹爪夹持力标定：空载电流基线、rFC→N 拟合、N→rFC 反解与命令力限制换算。

背景（钧舵 EPG 手册 6.2.5/6.3.5）：rFC 设定电机最大电流，手指超过上限即停止并触发目标检测；
gCU 是电流标幺值，稳定夹持时贴近设定上限，本身没有换算到牛顿的公式。腕部六维力测不到两指间的内力，
因此 rFC→N 必须用夹在两指之间的参考测力计实测拟合。本模块只做离线计算，不访问硬件。

标定结果按硬件侧存放在 config["gripper"]["forceCalibration"][side]，并记录端口和从站号；
换夹爪或改接线后端口/从站不一致即视为未标定。
"""

from __future__ import annotations

import math
import statistics
import time
from collections.abc import Iterable, Mapping
from typing import Any

CALIBRATION_VERSION = 1
CALIBRATION_METHOD = "reference_dynamometer_v1"
RFC_MIN = 1
RFC_MAX = 255
# 空载阈值：max(最大值, 均值 + k·σ) + 余量，避免把正常运动电流抖动误判为接触。
BASELINE_SIGMA_K = 6.0
BASELINE_MARGIN_RAW = 1.0
MIN_DISTINCT_RFC = 3


class CalibrationError(ValueError):
    pass


def _finite(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CalibrationError(f"{name} 不是数值: {value!r}") from exc
    if not math.isfinite(number):
        raise CalibrationError(f"{name} 不是有限数值: {value!r}")
    return number


def _linear_fit(xs: list[float], ys: list[float]) -> tuple[float, float]:
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0.0:
        raise CalibrationError("拟合自变量没有变化")
    slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True)) / sxx
    return slope, mean_y - slope * mean_x


def _residual_summary(xs: list[float], ys: list[float], slope: float, intercept: float) -> dict[str, float]:
    residuals = [y - (slope * x + intercept) for x, y in zip(xs, ys, strict=True)]
    return {
        "rmsResidual": math.sqrt(statistics.fmean(r * r for r in residuals)),
        "maxAbsResidual": max(abs(r) for r in residuals),
    }


def summarize_baseline(current_raw: Iterable[Any]) -> dict[str, float | int]:
    """空载开合（两指分离、无物体）时的 gCU 统计与接触判定阈值。"""
    values = [_finite(value, "baseline gCU") for value in current_raw]
    if len(values) < 10:
        raise CalibrationError(f"空载基线样本不足: {len(values)} < 10")
    mean = statistics.fmean(values)
    std = statistics.pstdev(values)
    threshold = max(max(values), mean + BASELINE_SIGMA_K * std) + BASELINE_MARGIN_RAW
    return {
        "samples": len(values),
        "currentMeanRaw": round(mean, 4),
        "currentStdRaw": round(std, 4),
        "currentMaxRaw": max(values),
        "contactThresholdRaw": round(threshold, 4),
    }


def fit_force_calibration(
    points: Iterable[Mapping[str, Any]],
    baseline_current_raw: Iterable[Any],
    *,
    port: str,
    slave_id: int,
    calibrated_at_ms: int | None = None,
    reference: str = "",
) -> dict[str, Any]:
    """由测力计稳态点拟合单个夹爪的标定。

    每个点：rfcRaw（设定力原码）、forceN（参考测力计读数）、currentRaw（稳态 gCU），
    可选 sequence="ascending"/"descending" 用于估计升降设定的回差。
    """
    rows: list[tuple[float, float, float, str]] = []
    for index, point in enumerate(points):
        rfc = _finite(point.get("rfcRaw"), f"points[{index}].rfcRaw")
        if not RFC_MIN <= rfc <= RFC_MAX:
            raise CalibrationError(f"points[{index}].rfcRaw 超出 {RFC_MIN}..{RFC_MAX}: {rfc}")
        force_n = _finite(point.get("forceN"), f"points[{index}].forceN")
        if force_n < 0.0:
            raise CalibrationError(f"points[{index}].forceN 为负: {force_n}")
        current = _finite(point.get("currentRaw"), f"points[{index}].currentRaw")
        rows.append((rfc, force_n, current, str(point.get("sequence", ""))))
    distinct = sorted({row[0] for row in rows})
    if len(distinct) < MIN_DISTINCT_RFC:
        raise CalibrationError(f"至少需要 {MIN_DISTINCT_RFC} 个不同的 rFC 设定，当前 {len(distinct)}")
    rfcs = [row[0] for row in rows]
    forces = [row[1] for row in rows]
    currents = [row[2] for row in rows]
    slope, intercept = _linear_fit(rfcs, forces)
    if slope <= 0.0:
        raise CalibrationError(f"rFC→N 斜率非正 ({slope:.6g})，检查测力计读数或夹持是否打滑")
    hold_slope, hold_intercept = _linear_fit(rfcs, currents)

    repeat_spread = 0.0
    hysteresis = 0.0
    for rfc in distinct:
        same = [row for row in rows if row[0] == rfc]
        if len(same) > 1:
            repeat_spread = max(repeat_spread, max(r[1] for r in same) - min(r[1] for r in same))
        ascending = [r[1] for r in same if r[3] == "ascending"]
        descending = [r[1] for r in same if r[3] == "descending"]
        if ascending and descending:
            hysteresis = max(hysteresis, abs(statistics.fmean(ascending) - statistics.fmean(descending)))

    baseline = summarize_baseline(baseline_current_raw)
    force_residual = _residual_summary(rfcs, forces, slope, intercept)
    hold_residual = _residual_summary(rfcs, currents, hold_slope, hold_intercept)
    return {
        "version": CALIBRATION_VERSION,
        "method": CALIBRATION_METHOD,
        "port": str(port),
        "slaveId": int(slave_id),
        "calibratedAtUnixMs": int(calibrated_at_ms if calibrated_at_ms is not None else time.time() * 1000),
        "reference": reference,
        "baseline": baseline,
        "rfcToForceN": {
            "slope": slope,
            "intercept": intercept,
            "rmsResidualN": round(force_residual["rmsResidual"], 6),
            "maxAbsResidualN": round(force_residual["maxAbsResidual"], 6),
            "repeatSpreadN": round(repeat_spread, 6),
            "hysteresisN": round(hysteresis, 6),
            "rfcMin": distinct[0],
            "rfcMax": distinct[-1],
            "forceMinN": round(min(forces), 6),
            "forceMaxN": round(max(forces), 6),
            "points": len(rows),
        },
        "holdCurrentRaw": {
            "slope": hold_slope,
            "intercept": hold_intercept,
            "rmsResidualRaw": round(hold_residual["rmsResidual"], 6),
            "maxAbsResidualRaw": round(hold_residual["maxAbsResidual"], 6),
        },
    }


def force_n_for_rfc(calibration: Mapping[str, Any], rfc_raw: float) -> float:
    fit = calibration["rfcToForceN"]
    return float(fit["slope"]) * float(rfc_raw) + float(fit["intercept"])


def rfc_for_force_n(calibration: Mapping[str, Any], force_n: float) -> dict[str, Any]:
    """反解 N→rFC。向下取整保证不超过目标力；不向上外推到标定范围以外。"""
    fit = calibration["rfcToForceN"]
    slope = float(fit["slope"])
    if slope <= 0.0:
        raise CalibrationError("标定斜率非正")
    target = _finite(force_n, "force_n")
    exact = (target - float(fit["intercept"])) / slope
    rfc_max = int(math.floor(float(fit["rfcMax"])))
    rfc = min(max(int(math.floor(exact)), RFC_MIN), rfc_max, RFC_MAX)
    rfc_min = float(fit["rfcMin"])
    return {
        "rfcRaw": rfc,
        "expectedForceN": force_n_for_rfc(calibration, rfc),
        "clampedHigh": exact > rfc_max,
        "extrapolatedLow": rfc < rfc_min,
    }


def calibration_matches(calibration: Any, gripper: Mapping[str, Any], side: str) -> bool:
    """标定只对记录时的端口/从站有效，换线或换夹爪后不得沿用。"""
    if not isinstance(calibration, Mapping) or calibration.get("version") != CALIBRATION_VERSION:
        return False
    try:
        slope = float(calibration["rfcToForceN"]["slope"])
    except (KeyError, TypeError, ValueError):
        return False
    return (
        slope > 0.0
        and str(calibration.get("port", "")).upper() == str(gripper.get(f"{side}Port", "")).upper()
        and int(calibration.get("slaveId", -1)) == int(gripper.get(f"{side}SlaveId", -2))
    )


def side_calibration(config: Mapping[str, Any], side: str) -> dict[str, Any] | None:
    gripper = config.get("gripper", {})
    if not isinstance(gripper, Mapping):
        return None
    store = gripper.get("forceCalibration", {})
    calibration = store.get(side) if isinstance(store, Mapping) else None
    if not isinstance(calibration, Mapping) or not calibration_matches(calibration, gripper, side):
        return None
    return dict(calibration)


def effective_grip_torque(config: Mapping[str, Any]) -> dict[str, Any]:
    """返回实际下发的夹持力原码 rFC。

    默认沿用 teleop.gripperTeleop.gripTorque。只有显式开启 applyCommandForceLimit 且所有已启用夹爪
    都有匹配标定时，才按 commandForceLimitN 反解；HAL 只有一个 gripTorque，取各侧较小值，
    保证任一侧都不超过限制。条件不满足时返回原设定并给出原因，不静默放大夹持力。
    """
    gripper = config.get("gripper", {}) if isinstance(config.get("gripper"), Mapping) else {}
    teleop = config.get("teleop", {}) if isinstance(config.get("teleop"), Mapping) else {}
    gripper_teleop = teleop.get("gripperTeleop", {}) if isinstance(teleop.get("gripperTeleop"), Mapping) else {}
    configured = min(max(int(gripper_teleop.get("gripTorque", 1)), RFC_MIN), RFC_MAX)
    store = gripper.get("forceCalibration", {})
    if not isinstance(store, Mapping) or not bool(store.get("applyCommandForceLimit", False)):
        return {"rfcRaw": configured, "source": "gripTorque", "reason": "applyCommandForceLimit disabled"}
    sides = [side for side in ("left", "right") if bool(gripper.get(f"{side}Enabled", False))]
    if not sides:
        return {"rfcRaw": configured, "source": "gripTorque", "reason": "no gripper enabled"}
    limit_n = gripper.get("commandForceLimitN")
    try:
        limit = _finite(limit_n, "commandForceLimitN")
    except CalibrationError as exc:
        return {"rfcRaw": configured, "source": "gripTorque", "reason": str(exc)}
    calibrations: dict[str, dict[str, Any]] = {}
    for side in sides:
        calibration = side_calibration(config, side)
        if calibration is None:
            return {"rfcRaw": configured, "source": "gripTorque", "reason": f"{side} gripper not calibrated"}
        calibrations[side] = calibration
    rfc = min(int(rfc_for_force_n(calibration, limit)["rfcRaw"]) for calibration in calibrations.values())
    return {
        "rfcRaw": rfc,
        "source": "commandForceLimitN",
        "commandForceLimitN": limit,
        "expectedForceN": {side: force_n_for_rfc(cal, rfc) for side, cal in calibrations.items()},
        "reason": "",
    }
