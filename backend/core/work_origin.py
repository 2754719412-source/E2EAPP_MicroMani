"""工作坐标只在已确认的控制器计数基准内有效；参考偏移则可跨重启保存。"""
from __future__ import annotations

import os
from typing import Any

AXES = ("X", "Y", "Z", "Roll", "Pitch", "Yaw")
INSTANCE_GUARD_CAPABILITY = "work_origin_instance_guard_v1"


class PreviousOriginInstance(RuntimeError):
    def __init__(self, message: str, previous: str, current: str):
        super().__init__(message)
        self.previous = previous
        self.current = current


def axis_instance_ids(root: dict[str, Any], key: str) -> list[str]:
    raw = root.get(key)
    return [value if isinstance(value, str) else "" for value in raw] if isinstance(raw, list) and len(raw) == 6 else [""] * 6


def offset_reference_kinds(offset: dict[str, Any], side: str) -> list[str]:
    return [value if value in {"origin", "positive_limit"} else ""
            for value in axis_instance_ids(offset, f"{side}AxisReferenceKind")]


async def require_current_work_origin(config, hal, sides, enabled_axes=None) -> str:
    sides = tuple(sides)
    if not sides:
        return ""
    mode = os.environ.get("APPSTATION_HAL_MODE") or config.get("hal", {}).get("mode", "real")
    if str(mode).lower() != "real":
        return "test-hal-instance"
    health = await hal.health()
    if not health.connected or not health.ltdmc_ok or not health.instance_id:
        raise RuntimeError("控制器身份不可用，不能使用保存的工作原点")
    if INSTANCE_GUARD_CAPABILITY not in (health.capabilities or []):
        raise RuntimeError("HAL 尚不支持工作原点实例校验，请同步部署 HAL 与夹爪 worker")
    origin = config.get("motion", {}).get("origin", {})
    axes = enabled_axes if enabled_axes is not None else [True] * 6
    for side in sides:
        ids = axis_instance_ids(origin, f"{side}AxisInstanceId")
        stale = [axis for i, axis in enumerate(AXES) if axes[i] and ids[i] != health.instance_id]
        if not origin.get(f"{side}Valid", origin.get("valid", False)) or stale:
            message = f"{side} 工作原点未在当前控制器会话恢复：{', '.join(stale) or '未记录'}；请先重新定位参考点或在已核实位置记录原点"
            sources = {ids[i] for i in range(6) if axes[i]}
            if stale and origin.get(f"{side}Valid") and len(sources) == 1 and "" not in sources:
                raise PreviousOriginInstance(message, sources.pop(), health.instance_id)
            raise RuntimeError(message)
    return health.instance_id
