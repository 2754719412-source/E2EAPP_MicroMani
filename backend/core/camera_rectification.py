"""用已绑定镜头的 OpenCV 内参生成与标定脚本相同的全尺寸去畸变图像。"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from math import isfinite
from typing import Any

from backend.core.camera_roles import STANDARD_CAMERA_KEYS

_CONFIG_KEYS = {"global": "global", "wrist_left": "wristLeft", "wrist_right": "wristRight"}


@dataclass(frozen=True)
class LensGeometry:
    identity: str
    size: tuple[int, int]
    matrix: tuple[tuple[float, ...], ...]
    distortion: tuple[float, ...]

    def rectify(self, frame: Any) -> Any:
        import cv2

        if frame.shape[:2] != self.size[::-1]:
            raise RuntimeError(f"实际帧分辨率 {frame.shape[1]}x{frame.shape[0]} 与镜头标定 {self.size} 不一致")
        _, map1, map2 = _maps(self)
        return cv2.remap(frame, map1, map2, cv2.INTER_LINEAR)


@lru_cache(maxsize=8)
def _maps(geometry: LensGeometry) -> tuple[Any, Any, Any]:
    import cv2
    import numpy as np

    k = np.asarray(geometry.matrix, dtype=np.float64)
    d = np.asarray(geometry.distortion, dtype=np.float64)
    new_k, _ = cv2.getOptimalNewCameraMatrix(k, d, geometry.size, 0)
    map1, map2 = cv2.initUndistortRectifyMap(k, d, None, new_k, geometry.size, cv2.CV_16SC2)
    return new_k, map1, map2


def lens_geometry(config: dict[str, Any], camera: str) -> LensGeometry | None:
    cameras = config.get("cameras", {})
    if camera not in _CONFIG_KEYS:
        return None
    profiles = cameras.get("lensIntrinsics", {})
    if not isinstance(profiles, dict):
        raise RuntimeError("镜头内参配置格式无效")
    if camera not in profiles:
        return None
    profile = profiles[camera]
    key = _CONFIG_KEYS[camera]
    try:
        if (profile["schema"] != "appstation.camera_calibration.v1" or profile["kind"] != "intrinsics"
                or profile["camera"] != camera or profile["verdict"] != "ok"
                or profile["distortionModel"] != "opencv_k1_k2_p1_p2_k3"):
            raise ValueError
        identity = profile["cameraInfo"]["identity"]
        if not isinstance(identity, str) or not identity.strip() or identity != cameras.get(f"{key}Identity"):
            raise RuntimeError(f"{camera} 镜头标定身份与当前相机绑定不一致")
        width, height = profile["imageSize"]["width"], profile["imageSize"]["height"]
        if type(width) is not int or type(height) is not int or not (0 < width <= 4096 and 0 < height <= 2160):
            raise ValueError
        configured = str(cameras.get(f"{key}Resolution") or cameras.get("previewResolution", "native")).lower().replace(" ", "")
        if configured == "native":
            configured = "640x480"  # 三路相机驱动的原生默认采集尺寸。
        if configured != f"{width}x{height}":
            raise RuntimeError(f"{camera} 采集分辨率 {configured} 与镜头标定 {width}x{height} 不一致")
        matrix = tuple(tuple(float(v) for v in row) for row in profile["cameraMatrix"])
        distortion = tuple(float(v) for v in profile["distCoeffs"])
        if (len(matrix) != 3 or any(len(row) != 3 for row in matrix) or len(distortion) != 5
                or not all(isfinite(v) for row in (*matrix, distortion) for v in row)
                or matrix[0][0] <= 0 or matrix[1][1] <= 0 or matrix[2] != (0, 0, 1)):
            raise ValueError
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise RuntimeError(f"{camera} 镜头内参无效，需要通过验收的 OpenCV 五参数标定") from exc
    return LensGeometry(identity, (width, height), matrix, distortion)


def rectification_metadata(config: dict[str, Any]) -> dict[str, Any]:
    result = {}
    for camera in STANDARD_CAMERA_KEYS:
        geometry = lens_geometry(config, camera)
        if geometry is not None:
            new_k, _, _ = _maps(geometry)
            result[camera] = {
                "imageSpace": "opencv_undistorted_alpha0_v1", "identity": geometry.identity,
                "imageSize": list(geometry.size), "sourceMatrix": [list(row) for row in geometry.matrix],
                "sourceDistCoeffs": list(geometry.distortion), "outputMatrix": new_k.tolist(),
            }
    return result
