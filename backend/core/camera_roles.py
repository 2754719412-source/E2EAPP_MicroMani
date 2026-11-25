"""采集软件的相机角色与显微通道格式。"""
from typing import Any

STANDARD_CAMERA_KEYS = ("global", "wrist_left", "wrist_right")
CAMERA_KEYS = (*STANDARD_CAMERA_KEYS, "microscope")
MICROSCOPE_SIZE = (3840, 2160)
MICROSCOPE_FPS = 60


def active_camera_keys(config: dict[str, Any]) -> tuple[str, ...]:
    if config.get("cameras", {}).get("microscopeEnabled"):
        return CAMERA_KEYS
    return STANDARD_CAMERA_KEYS


def microscope_mode_matches(width: float | None, height: float | None, fps: float | None) -> bool:
    # 兼容 60000/1001 的标称帧率；设备须确认采集格式。
    return (width, height) == MICROSCOPE_SIZE and fps is not None and abs(fps - MICROSCOPE_FPS) < 0.5
