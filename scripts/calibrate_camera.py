# 阅读导航 08｜启动、部署与工具
# 职责：张正友平面标定法求三路相机内参，记录定型参考位姿，并用同一标定板复核相机安装是否移动；只读相机画面。
# 先看：BoardSpec → detect_corners → calibrate_images → solve_pose → compare_with_reference → main。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。

"""相机标定工具（张正友法，棋盘格标定板）。

子命令：
  capture    从后端快照接口或直连相机采集标定板图像
  calibrate  由图像求内参与畸变，输出 intrinsics.json
  pose       标定板放在固定参考位置时，记录参考位姿和参考图（定型存档）
  check      标定板放回参考位置，复核相机是否被移动

操作步骤见 docs/camera-calibration.md。本工具不连接运动控制和夹爪。
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import cv2
import numpy as np

SCHEMA = "appstation.camera_calibration.v1"
CAMERA_ROLES = ("global", "wrist_left", "wrist_right")
CAMERA_CONFIG_KEYS = {"global": "global", "wrist_left": "wristLeft", "wrist_right": "wristRight"}
DEFAULT_BASE_URL = "http://127.0.0.1:18082"
DEFAULT_ROOT = Path.home() / ".appstation" / "camera_calibration"
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp")

# 验收阈值：640x480 普通镜头的经验值，超出时给出“需复核”，不阻止写出结果。
MAX_RMS_PX = 0.5
MAX_VIEW_ERROR_PX = 1.0
MIN_VIEWS = 10
RECOMMENDED_VIEWS = 20
COVERAGE_GRID = 4
MIN_COVERAGE = 0.75
MIN_TILT_DEG = 15.0
MIN_TILTED_VIEWS = 3
MAX_FOCAL_REL_STD = 0.01
# 自动采集：标定板静止一段时间且相对上一张移动足够远才保存，避免模糊和重复视角。
AUTO_STILL_PX = 1.0
AUTO_STILL_S = 0.4
AUTO_MIN_MOVE_RATIO = 0.05


class CalibrationError(RuntimeError):
    """标定输入或结果不满足要求。"""


@dataclass(frozen=True)
class BoardSpec:
    cols: int  # 每行内角点数（不是方格数）
    rows: int  # 每列内角点数
    square_mm: float

    @property
    def pattern_size(self) -> tuple[int, int]:
        return (self.cols, self.rows)

    def object_points(self) -> np.ndarray:
        """标定板坐标系下的角点，单位 mm，按 OpenCV 检测顺序逐行排列。"""
        grid = np.zeros((self.rows * self.cols, 3), np.float32)
        grid[:, :2] = np.mgrid[0 : self.cols, 0 : self.rows].T.reshape(-1, 2) * self.square_mm
        return grid

    def as_dict(self) -> dict[str, Any]:
        return {"type": "chessboard", "innerCorners": [self.cols, self.rows], "squareMm": self.square_mm}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BoardSpec:
        cols, rows = data["innerCorners"]
        return cls(int(cols), int(rows), float(data["squareMm"]))


def parse_board(text: str) -> tuple[int, int]:
    parts = text.lower().replace("×", "x").split("x")
    try:
        cols, rows = (int(part) for part in parts)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"标定板规格应写成 列x行 的内角点数，例如 9x6：{text!r}") from exc
    if cols < 3 or rows < 3:
        raise argparse.ArgumentTypeError("内角点数每边至少 3")
    return cols, rows


def parse_size(text: str) -> tuple[int, int]:
    width, height = (int(part) for part in text.lower().split("x"))
    return width, height


def board_notes(board: BoardSpec) -> list[str]:
    if (board.cols + board.rows) % 2 == 0:
        return [
            "标定板内角点列数+行数为偶数，旋转 180° 后图案相同，参考位姿的原点角可能翻转；"
            "推荐 9x6 这类一奇一偶的规格"
        ]
    return []


def read_image(path: Path, flags: int = cv2.IMREAD_COLOR) -> np.ndarray:
    # 经 numpy 读写，避免 OpenCV 在 Windows 上不支持中文路径。
    image = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), flags)
    if image is None:
        raise CalibrationError(f"无法读取图像 {path}")
    return image


def write_image(path: Path, image: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ok, buffer = cv2.imencode(path.suffix or ".png", image)
    if not ok:
        raise CalibrationError(f"无法编码图像 {path}")
    path.write_bytes(buffer.tobytes())


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def now_text() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _patch_mean(gray: np.ndarray, point: np.ndarray, radius: int = 2) -> float | None:
    x, y = int(round(float(point[0]))), int(round(float(point[1])))
    height, width = gray.shape[:2]
    if not (radius <= x < width - radius and radius <= y < height - radius):
        return None
    return float(gray[y - radius : y + radius + 1, x - radius : x + radius + 1].mean())


def canonical_ordering(gray: np.ndarray, corners: np.ndarray, board: BoardSpec) -> np.ndarray:
    """固定原点角：0 号角点外侧对角方格为黑色。

    检测器可能从棋盘任一端开始编号；对一奇一偶的标定板，两端外侧方格颜色相反，据此把顺序统一，
    使参考位姿的标定板坐标系每次都落在同一个物理角上。对称标定板无法区分，保持检测器顺序。
    """
    if (board.cols + board.rows) % 2 == 0:
        return corners
    grid = corners.reshape(board.rows, board.cols, 2)
    first = grid[0, 0] - 0.5 * (grid[0, 1] - grid[0, 0]) - 0.5 * (grid[1, 0] - grid[0, 0])
    last = grid[-1, -1] + 0.5 * (grid[-1, -1] - grid[-1, -2]) + 0.5 * (grid[-1, -1] - grid[-2, -1])
    first_value, last_value = _patch_mean(gray, first), _patch_mean(gray, last)
    if first_value is None or last_value is None or first_value <= last_value:
        return corners
    return corners[::-1].copy()


def detect_corners(image: np.ndarray, board: BoardSpec, *, fast: bool = False) -> np.ndarray | None:
    """返回 (N,1,2) 亚像素角点；fast 仅用于预览，保存和计算一律用精确检测。"""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    classic_flags = cv2.CALIB_CB_ADAPTIVE_THRESH | cv2.CALIB_CB_NORMALIZE_IMAGE
    if fast:
        found, corners = cv2.findChessboardCorners(gray, board.pattern_size, classic_flags | cv2.CALIB_CB_FAST_CHECK)
        return corners.reshape(-1, 1, 2).astype(np.float32) if found else None
    sb_flags = cv2.CALIB_CB_NORMALIZE_IMAGE | cv2.CALIB_CB_EXHAUSTIVE | cv2.CALIB_CB_ACCURACY
    found, corners = cv2.findChessboardCornersSB(gray, board.pattern_size, sb_flags)
    if found:
        return canonical_ordering(gray, corners.reshape(-1, 1, 2).astype(np.float32), board)
    found, corners = cv2.findChessboardCorners(gray, board.pattern_size, classic_flags)
    if not found:
        return None
    corners = corners.reshape(-1, 1, 2).astype(np.float32)
    grid = corners.reshape(board.rows, board.cols, 2)
    spacing = min(
        float(np.linalg.norm(np.diff(grid, axis=1), axis=-1).min()),
        float(np.linalg.norm(np.diff(grid, axis=0), axis=-1).min()),
    )
    # 亚像素窗口不能跨过相邻角点，否则会被拉偏。
    half = int(max(2, min(11, spacing * 0.4)))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-3)
    cv2.cornerSubPix(gray, corners, (half, half), (-1, -1), criteria)
    return canonical_ordering(gray, corners, board)


def view_tilt_deg(rvec: np.ndarray) -> float:
    """标定板法线与光轴的夹角；张正友法要求视角之间有足够的朝向差异。"""
    rotation, _ = cv2.Rodrigues(rvec)
    return math.degrees(math.acos(min(1.0, abs(float(rotation[2, 2])))))


def coverage_summary(point_sets: list[np.ndarray], size: tuple[int, int]) -> dict[str, Any]:
    width, height = size
    points = np.concatenate([item.reshape(-1, 2) for item in point_sets])
    cells_x = np.clip((points[:, 0] / width * COVERAGE_GRID).astype(int), 0, COVERAGE_GRID - 1)
    cells_y = np.clip((points[:, 1] / height * COVERAGE_GRID).astype(int), 0, COVERAGE_GRID - 1)
    hit = np.zeros((COVERAGE_GRID, COVERAGE_GRID), bool)
    hit[cells_y, cells_x] = True
    margin_x, margin_y = 0.1 * width, 0.1 * height
    return {
        "grid": COVERAGE_GRID,
        "fraction": round(float(hit.mean()), 3),
        "cells": hit.astype(int).tolist(),
        "reachesEdges": {
            "left": bool((points[:, 0] < margin_x).any()),
            "right": bool((points[:, 0] > width - margin_x).any()),
            "top": bool((points[:, 1] < margin_y).any()),
            "bottom": bool((points[:, 1] > height - margin_y).any()),
        },
    }


def _run_calibration(
    views: list[tuple[str, np.ndarray]], board: BoardSpec, size: tuple[int, int], flags: int
) -> tuple[float, np.ndarray, np.ndarray, list[np.ndarray], list[np.ndarray], np.ndarray, np.ndarray]:
    object_points = [board.object_points() for _ in views]
    image_points = [corners for _, corners in views]
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 200, 1e-12)
    rms, matrix, dist, rvecs, tvecs, std_intrinsics, _std_extrinsics, per_view = cv2.calibrateCameraExtended(
        object_points, image_points, size, None, None, flags=flags, criteria=criteria
    )
    return (
        float(rms), matrix, dist.reshape(-1), list(rvecs), list(tvecs),
        std_intrinsics.reshape(-1), per_view.reshape(-1),
    )


def calibrate_images(
    paths: list[Path],
    board: BoardSpec,
    *,
    fix_k3: bool = True,
    max_view_error_px: float = MAX_VIEW_ERROR_PX,
    min_views: int = MIN_VIEWS,
) -> dict[str, Any]:
    """张正友法：检测角点 → calibrateCamera → 剔除误差过大的单张后重算一次 → 质量评估。"""
    size: tuple[int, int] | None = None
    views: list[tuple[str, np.ndarray]] = []
    undetected: list[str] = []
    for path in sorted(paths):
        gray = read_image(path, cv2.IMREAD_GRAYSCALE)
        current = (int(gray.shape[1]), int(gray.shape[0]))
        if size is None:
            size = current
        elif current != size:
            raise CalibrationError(f"{path.name} 尺寸 {current} 与其他图像 {size} 不同；内参只对同一分辨率有效")
        corners = detect_corners(gray, board)
        if corners is None:
            undetected.append(path.name)
        else:
            views.append((path.name, corners))
    if size is None:
        raise CalibrationError("没有找到标定图像")
    if len(views) < min_views:
        raise CalibrationError(f"只检测到 {len(views)} 张完整标定板图像，至少需要 {min_views} 张")

    flags = cv2.CALIB_FIX_K3 if fix_k3 else 0
    rms, matrix, dist, rvecs, _tvecs, std, per_view = _run_calibration(views, board, size, flags)
    rejected = [
        {"image": name, "errorPx": round(float(error), 4)}
        for (name, _), error in zip(views, per_view, strict=True)
        if error > max_view_error_px
    ]
    if rejected:
        kept = [view for view, error in zip(views, per_view, strict=True) if error <= max_view_error_px]
        if len(kept) < min_views:
            raise CalibrationError(
                f"剔除单张误差 > {max_view_error_px} px 的 {len(rejected)} 张后只剩 {len(kept)} 张，请重新采集"
            )
        views = kept
        rms, matrix, dist, rvecs, _tvecs, std, per_view = _run_calibration(views, board, size, flags)

    tilts = [view_tilt_deg(rvec) for rvec in rvecs]
    coverage = coverage_summary([corners for _, corners in views], size)
    fx, fy, cx, cy = float(matrix[0, 0]), float(matrix[1, 1]), float(matrix[0, 2]), float(matrix[1, 2])
    std_names = ("fx", "fy", "cx", "cy", "k1", "k2", "p1", "p2", "k3")
    std_dev = {name: round(float(value), 6) for name, value in zip(std_names, std, strict=False)}

    warnings: list[str] = []
    if rms > MAX_RMS_PX:
        warnings.append(f"总体重投影误差 {rms:.3f} px 偏大（建议 ≤ {MAX_RMS_PX}）；检查模糊、反光和标定板平整度")
    if coverage["fraction"] < MIN_COVERAGE:
        warnings.append(f"角点只覆盖画面 {coverage['fraction']:.0%} 的区域；补拍标定板位于画面四角和边缘的图像")
    tilted = sum(tilt >= MIN_TILT_DEG for tilt in tilts)
    if tilted < MIN_TILTED_VIEWS:
        warnings.append(
            f"倾斜 ≥ {MIN_TILT_DEG:.0f}° 的视角只有 {tilted} 张；补拍绕水平和竖直轴各倾斜 20°–45° 的图像，"
            "全部正对时焦距无法确定"
        )
    if std_dev["fx"] / fx > MAX_FOCAL_REL_STD or std_dev["fy"] / fy > MAX_FOCAL_REL_STD:
        warnings.append("焦距估计不确定度超过 1%；增加倾斜视角和图像数量")
    notes = board_notes(board)
    if len(views) < RECOMMENDED_VIEWS:
        notes.append(f"有效图像 {len(views)} 张，建议至少 {RECOMMENDED_VIEWS} 张")

    return {
        "imageSize": {"width": size[0], "height": size[1]},
        "distortionModel": "opencv_k1_k2_p1_p2_k3",
        "fixK3": fix_k3,
        "cameraMatrix": matrix.tolist(),
        "distCoeffs": [float(value) for value in dist[:5]],
        "fx": fx,
        "fy": fy,
        "cx": cx,
        "cy": cy,
        "stdDev": std_dev,
        "rmsPx": round(rms, 4),
        "views": [
            {"image": name, "errorPx": round(float(error), 4), "tiltDeg": round(tilt, 2)}
            for (name, _), error, tilt in zip(views, per_view, tilts, strict=True)
        ],
        "rejected": rejected,
        "undetected": undetected,
        "coverage": coverage,
        "tiltDeg": {"min": round(min(tilts), 2), "max": round(max(tilts), 2), "tiltedViews": int(tilted)},
        "verdict": "ok" if not warnings else "review",
        "warnings": warnings,
        "notes": notes,
    }


def align_ordering(corners: np.ndarray, reference: np.ndarray) -> np.ndarray:
    """检测器可能从另一端开始编号；按与参考角点更接近的顺序对齐。"""
    flipped = corners[::-1].copy()
    direct = float(np.linalg.norm(corners - reference, axis=-1).mean())
    reverse = float(np.linalg.norm(flipped - reference, axis=-1).mean())
    return corners if direct <= reverse else flipped


def median_corners(detections: list[np.ndarray]) -> tuple[np.ndarray, float]:
    """多帧角点逐点取中位数，并返回最大的逐点标准差（px）作为稳定性指标。"""
    aligned = np.stack([align_ordering(item, detections[0]) for item in detections])
    spread = float(np.linalg.norm(aligned.std(axis=0), axis=-1).max()) if len(detections) > 1 else 0.0
    return np.median(aligned, axis=0).astype(np.float32), spread


def solve_pose(corners: np.ndarray, board: BoardSpec, matrix: np.ndarray, dist: np.ndarray) -> dict[str, Any]:
    """求标定板坐标系到相机坐标系的位姿 X_cam = R·X_board + t（mm）。"""
    object_points = board.object_points()
    ok, rvec, tvec = cv2.solvePnP(object_points, corners, matrix, dist, flags=cv2.SOLVEPNP_ITERATIVE)
    if not ok:
        raise CalibrationError("solvePnP 求解失败")
    projected, _ = cv2.projectPoints(object_points, rvec, tvec, matrix, dist)
    error = float(np.sqrt(np.mean(np.sum((projected - corners) ** 2, axis=-1))))
    rotation, _ = cv2.Rodrigues(rvec)
    center = (-rotation.T @ tvec).reshape(-1)
    return {
        "rvec": [float(value) for value in rvec.reshape(-1)],
        "tvecMm": [float(value) for value in tvec.reshape(-1)],
        "rotationMatrix": rotation.tolist(),
        "cameraCenterInBoardMm": [float(value) for value in center],
        "distanceMm": float(np.linalg.norm(tvec)),
        "tiltDeg": view_tilt_deg(rvec),
        "reprojectionErrorPx": error,
    }


def pose_delta(current: dict[str, Any], reference: dict[str, Any]) -> dict[str, float]:
    r_now = np.asarray(current["rotationMatrix"])
    r_ref = np.asarray(reference["rotationMatrix"])
    relative = r_now @ r_ref.T
    angle = math.degrees(math.acos(max(-1.0, min(1.0, (float(np.trace(relative)) - 1.0) / 2.0))))
    shift = float(np.linalg.norm(np.asarray(current["tvecMm"]) - np.asarray(reference["tvecMm"])))
    return {"translationMm": shift, "rotationDeg": angle}


def compare_with_reference(corners: np.ndarray, reference: np.ndarray) -> dict[str, Any]:
    aligned = align_ordering(corners, reference)
    delta = (aligned - reference).reshape(-1, 2)
    shift = np.linalg.norm(delta, axis=-1)
    return {
        "meanShiftPx": float(shift.mean()),
        "maxShiftPx": float(shift.max()),
        "meanVectorPx": [float(value) for value in delta.mean(axis=0)],
        "corners": aligned,
    }


class ApiSource:
    """经后端快照接口取图：与录制使用同一身份绑定、分辨率和曝光设置，后端无需停止。"""

    def __init__(self, base_url: str, camera: str, timeout_s: float = 3.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.url = f"{self.base_url}/api/cameras/{camera}/snapshot"
        self.timeout_s = timeout_s
        # 访问本机后端，不经过系统代理。
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _get(self, url: str) -> bytes:
        try:
            with self.opener.open(url, timeout=self.timeout_s) as response:
                return bytes(response.read())
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            raise CalibrationError(f"{url} 返回 {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise CalibrationError(f"无法连接后端 {url}: {exc.reason}；确认服务已启动，或改用 --source device") from exc

    def read(self) -> np.ndarray:
        image = cv2.imdecode(np.frombuffer(self._get(self.url), np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise CalibrationError("快照不是有效图像")
        return image

    def camera_info(self, camera: str) -> dict[str, Any]:
        try:
            config = json.loads(self._get(f"{self.base_url}/api/settings"))
        except (CalibrationError, ValueError):
            return {}
        cameras = config.get("cameras", {}) if isinstance(config, dict) else {}
        key = CAMERA_CONFIG_KEYS[camera]
        tuning = cameras.get("tuning", {}) if isinstance(cameras.get("tuning"), dict) else {}
        return {
            "identity": cameras.get(f"{key}Identity"),
            "descriptor": cameras.get(key),
            "resolution": cameras.get(f"{key}Resolution"),
            "fps": cameras.get("fps"),
            "tuning": tuning.get(camera),
        }

    def close(self) -> None:
        pass


class DeviceSource:
    """直接打开相机；后端运行时相机通常被占用，需先停止服务。"""

    def __init__(self, index: int, size: tuple[int, int], fps: float = 30.0) -> None:
        backend = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY
        self.capture = cv2.VideoCapture(index, backend)
        if not self.capture.isOpened():
            raise CalibrationError(f"无法打开相机序号 {index}；后端运行时相机可能被占用，可改用 --source api")
        # 与采集服务一致：YUYV 原始格式和录制分辨率。
        self.capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"YUYV"))
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, size[0])
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, size[1])
        self.capture.set(cv2.CAP_PROP_FPS, fps)

    def read(self) -> np.ndarray:
        ok, frame = self.capture.read()
        if not ok or frame is None:
            raise CalibrationError("读取相机帧失败")
        return frame

    def close(self) -> None:
        self.capture.release()


class SourceExhausted(CalibrationError):
    """离线图像已读完。"""


class FileSource:
    """离线图像：pose/check 循环读取；capture 按顺序读完即结束。"""

    def __init__(self, paths: list[Path], cycle: bool = True) -> None:
        if not paths:
            raise CalibrationError("--source file 需要用 --image 指定图像")
        self.paths = paths
        self.cycle = cycle
        self.index = 0

    def read(self) -> np.ndarray:
        if not self.cycle and self.index >= len(self.paths):
            raise SourceExhausted("图像已读完")
        image = read_image(self.paths[self.index % len(self.paths)])
        self.index += 1
        return image

    def close(self) -> None:
        pass


FrameSource = ApiSource | DeviceSource | FileSource


def make_source(args: argparse.Namespace, *, cycle: bool = True) -> FrameSource:
    if args.source == "api":
        return ApiSource(args.base_url, args.camera)
    if args.source == "device":
        if args.index is None:
            raise CalibrationError("--source device 需要 --index 指定相机序号")
        return DeviceSource(args.index, args.size)
    return FileSource([Path(item) for item in (args.image or [])], cycle=cycle)


def source_info(args: argparse.Namespace, source: FrameSource) -> dict[str, Any]:
    if isinstance(source, ApiSource):
        return {"source": "api", "baseUrl": source.base_url, **source.camera_info(args.camera)}
    if isinstance(source, DeviceSource):
        return {"source": "device", "deviceIndex": args.index, "requestedSize": list(args.size)}
    return {"source": "file", "images": [str(item) for item in (args.image or [])]}


def collect_detections(
    source: FrameSource, board: BoardSpec, frames: int, timeout_s: float = 20.0
) -> tuple[list[np.ndarray], np.ndarray]:
    detections: list[np.ndarray] = []
    last_frame: np.ndarray | None = None
    deadline = time.monotonic() + timeout_s
    while len(detections) < frames and time.monotonic() < deadline:
        frame = source.read()
        corners = detect_corners(frame, board)
        if corners is not None:
            detections.append(corners)
            last_frame = frame
        if not isinstance(source, FileSource):
            time.sleep(0.1)
    if last_frame is None:
        raise CalibrationError(f"{timeout_s:.0f} 秒内未检测到完整标定板")
    return detections, last_frame


def camera_dir(args: argparse.Namespace) -> Path:
    return Path(args.root).expanduser() / args.camera


def _draw_capture_overlay(
    frame: np.ndarray, board: BoardSpec, corners: np.ndarray | None, saved: list[np.ndarray], auto: bool
) -> np.ndarray:
    display = frame.copy()
    height, width = display.shape[:2]
    hit = np.zeros((COVERAGE_GRID, COVERAGE_GRID), bool)
    for item in saved:
        for x, y in item.reshape(-1, 2):
            hit[min(int(y / height * COVERAGE_GRID), COVERAGE_GRID - 1),
                min(int(x / width * COVERAGE_GRID), COVERAGE_GRID - 1)] = True
            cv2.circle(display, (int(x), int(y)), 1, (0, 200, 0), -1)
    for row in range(COVERAGE_GRID):
        for col in range(COVERAGE_GRID):
            top_left = (col * width // COVERAGE_GRID, row * height // COVERAGE_GRID)
            bottom_right = ((col + 1) * width // COVERAGE_GRID - 1, (row + 1) * height // COVERAGE_GRID - 1)
            cv2.rectangle(display, top_left, bottom_right, (0, 200, 0) if hit[row, col] else (0, 0, 200), 1)
    if corners is not None:
        cv2.drawChessboardCorners(display, board.pattern_size, corners, True)
    found = "OK" if corners is not None else "--"
    status = f"saved {len(saved)}  coverage {hit.mean():.0%}  auto {'ON' if auto else 'off'}  board {found}"
    cv2.putText(display, status, (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1, cv2.LINE_AA)
    cv2.putText(display, "SPACE save | A auto | Q quit", (8, height - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                (0, 255, 255), 1, cv2.LINE_AA)
    return display


def cmd_capture(args: argparse.Namespace) -> int:
    board = BoardSpec(args.board[0], args.board[1], args.square_mm)
    folder = camera_dir(args)
    meta_path = folder / "capture.json"
    meta = read_json(meta_path) if meta_path.exists() else {}
    if meta and meta.get("board") != board.as_dict():
        raise CalibrationError(f"{meta_path} 已记录另一种标定板 {meta.get('board')}；换板请使用新的 --root 目录")
    for note in board_notes(board):
        print(f"提示：{note}")
    preview = not args.no_preview
    auto = args.auto or not preview
    target = args.count or (0 if preview else 25)
    source = make_source(args, cycle=False)
    window = f"calibrate {args.camera}"
    if preview:
        try:
            cv2.namedWindow(window, cv2.WINDOW_AUTOSIZE)
        except cv2.error as exc:
            source.close()
            raise CalibrationError("当前 OpenCV 不带图形界面；可加 --no-preview 自动采集") from exc
    meta = {
        "schema": SCHEMA,
        "kind": "capture",
        "camera": args.camera,
        "board": board.as_dict(),
        "cameraInfo": source_info(args, source),
        "createdAt": meta.get("createdAt", now_text()),
        "images": meta.get("images", []),
    }
    saved = [np.asarray(item["corners"], np.float32) for item in meta["images"] if item.get("corners")]
    session_count = 0
    previous: np.ndarray | None = None
    still_since = time.monotonic()
    last_saved: np.ndarray | None = saved[-1] if saved else None
    if preview:
        print("采集中：拿稳标定板后按空格保存（A 切换自动保存，Q 退出）")
    else:
        print(f"自动采集 {target} 张，Ctrl+C 结束")
    try:
        while True:
            try:
                frame = source.read()
            except SourceExhausted:
                break
            corners = detect_corners(frame, board, fast=True)
            now = time.monotonic()
            if corners is None or previous is None or float(
                np.linalg.norm(align_ordering(corners, previous) - previous, axis=-1).mean()
            ) > AUTO_STILL_PX:
                still_since = now
            previous = corners
            key = cv2.waitKey(1) & 0xFF if preview else -1
            if key in (ord("q"), 27):
                break
            if key == ord("a"):
                auto = not auto
            want_save = key in (ord(" "), ord("s"))
            if auto and corners is not None and now - still_since >= AUTO_STILL_S:
                moved = last_saved is None or float(
                    np.linalg.norm(align_ordering(corners, last_saved) - last_saved, axis=-1).mean()
                ) > AUTO_MIN_MOVE_RATIO * frame.shape[1]
                want_save = want_save or moved
            if want_save:
                accurate = detect_corners(frame, board)
                if accurate is None:
                    print("未检测到完整标定板，未保存")
                else:
                    name = f"{args.camera}_{datetime.now():%Y%m%d_%H%M%S_%f}.png"
                    write_image(folder / "images" / name, frame)
                    meta["images"].append({"file": name, "savedAt": now_text(),
                                           "corners": accurate.reshape(-1, 2).round(3).tolist()})
                    write_json(meta_path, meta)
                    saved.append(accurate)
                    last_saved = accurate
                    session_count += 1
                    print(f"已保存 {name}（本次 {session_count} 张，累计 {len(meta['images'])} 张）")
                    if target and session_count >= target:
                        break
            if preview:
                cv2.imshow(window, _draw_capture_overlay(frame, board, corners, saved, auto))
            else:
                time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    finally:
        source.close()
        if preview:
            cv2.destroyAllWindows()
    print(f"图像目录：{folder / 'images'}")
    return 0


def cmd_calibrate(args: argparse.Namespace) -> int:
    folder = camera_dir(args)
    image_dir = Path(args.images).expanduser() if args.images else folder / "images"
    paths = [path for path in sorted(image_dir.glob("*")) if path.suffix.lower() in IMAGE_SUFFIXES]
    capture_meta_path = folder / "capture.json"
    capture_meta = read_json(capture_meta_path) if capture_meta_path.exists() else {}
    if args.board and args.square_mm:
        board = BoardSpec(args.board[0], args.board[1], args.square_mm)
    elif capture_meta.get("board"):
        board = BoardSpec.from_dict(capture_meta["board"])
    else:
        raise CalibrationError("请用 --board 和 --square-mm 指定标定板规格")
    result = calibrate_images(
        paths, board, fix_k3=not args.free_k3, max_view_error_px=args.max_view_error, min_views=args.min_views
    )
    payload = {
        "schema": SCHEMA,
        "kind": "intrinsics",
        "camera": args.camera,
        "createdAt": now_text(),
        "method": "zhang_planar_chessboard",
        "opencvVersion": cv2.__version__,
        "imageDir": str(image_dir),
        "cameraInfo": capture_meta.get("cameraInfo", {}),
        "board": board.as_dict(),
        **result,
    }
    out = folder / "intrinsics.json"
    if out.exists():
        out.replace(folder / f"intrinsics.{datetime.now():%Y%m%d_%H%M%S}.bak.json")
    write_json(out, payload)
    # 去畸变对照图：直线（标定板边、台面边缘）在右图中应当是直的。
    sample = read_image(image_dir / result["views"][0]["image"])
    matrix = np.asarray(result["cameraMatrix"])
    dist = np.asarray(result["distCoeffs"])
    size = (result["imageSize"]["width"], result["imageSize"]["height"])
    new_matrix, _ = cv2.getOptimalNewCameraMatrix(matrix, dist, size, 0)
    undistorted = cv2.undistort(sample, matrix, dist, None, new_matrix)
    write_image(folder / "undistort_check.png", np.hstack([sample, undistorted]))

    print(f"相机 {args.camera}：有效 {len(result['views'])} 张，剔除 {len(result['rejected'])} 张，"
          f"未检出 {len(result['undetected'])} 张")
    print(f"重投影误差 RMS = {result['rmsPx']:.4f} px；fx={result['fx']:.2f} fy={result['fy']:.2f} "
          f"cx={result['cx']:.2f} cy={result['cy']:.2f}")
    print(f"畸变 k1,k2,p1,p2,k3 = {', '.join(f'{v:.5f}' for v in result['distCoeffs'])}")
    print(f"画面覆盖 {result['coverage']['fraction']:.0%}；倾斜角 {result['tiltDeg']['min']:.1f}°–"
          f"{result['tiltDeg']['max']:.1f}°")
    for note in result["notes"]:
        print(f"提示：{note}")
    for warning in result["warnings"]:
        print(f"需复核：{warning}")
    print(f"结论：{'通过' if result['verdict'] == 'ok' else '需复核'}；结果写入 {out}")
    return 0


def _load_intrinsics(path: Path) -> tuple[dict[str, Any], np.ndarray, np.ndarray, tuple[int, int]]:
    if not path.exists():
        raise CalibrationError(f"找不到内参文件 {path}，请先运行 calibrate")
    data = read_json(path)
    size = (int(data["imageSize"]["width"]), int(data["imageSize"]["height"]))
    return data, np.asarray(data["cameraMatrix"], np.float64), np.asarray(data["distCoeffs"], np.float64), size


def _check_frame_size(frame: np.ndarray, size: tuple[int, int]) -> None:
    actual = (int(frame.shape[1]), int(frame.shape[0]))
    if actual != size:
        raise CalibrationError(f"当前画面 {actual} 与标定分辨率 {size} 不同；内参不能跨分辨率使用")


def cmd_pose(args: argparse.Namespace) -> int:
    folder = camera_dir(args)
    out = folder / "reference_pose.json"
    if out.exists() and not args.force:
        raise CalibrationError(f"{out} 已存在；定型参考不应被覆盖，确需重做请加 --force（旧文件会备份）")
    intrinsics_path = Path(args.intrinsics).expanduser() if args.intrinsics else folder / "intrinsics.json"
    intrinsics, matrix, dist, size = _load_intrinsics(intrinsics_path)
    if args.board and args.square_mm:
        board = BoardSpec(args.board[0], args.board[1], args.square_mm)
    else:
        board = BoardSpec.from_dict(intrinsics["board"])
    for note in board_notes(board):
        print(f"提示：{note}")
    source = make_source(args)
    try:
        info = source_info(args, source)
        detections, frame = collect_detections(source, board, args.frames)
    finally:
        source.close()
    _check_frame_size(frame, size)
    corners, spread = median_corners(detections)
    pose = solve_pose(corners, board, matrix, dist)
    per_frame = [solve_pose(align_ordering(item, corners), board, matrix, dist)["tvecMm"] for item in detections]
    translation_spread = float(np.linalg.norm(np.asarray(per_frame).std(axis=0))) if len(per_frame) > 1 else 0.0
    if out.exists():
        out.replace(folder / f"reference_pose.{datetime.now():%Y%m%d_%H%M%S}.bak.json")
    write_image(folder / "reference.png", frame)
    axes = frame.copy()
    cv2.drawChessboardCorners(axes, board.pattern_size, corners, True)
    cv2.drawFrameAxes(axes, matrix, dist, np.asarray(pose["rvec"]), np.asarray(pose["tvecMm"]),
                      board.square_mm * 3, 2)
    write_image(folder / "reference_axes.png", axes)
    write_json(out, {
        "schema": SCHEMA,
        "kind": "reference_pose",
        "camera": args.camera,
        "createdAt": now_text(),
        "note": args.note or "",
        "cameraInfo": info,
        "intrinsics": {"path": str(intrinsics_path), "createdAt": intrinsics.get("createdAt"),
                       "rmsPx": intrinsics.get("rmsPx")},
        "board": board.as_dict(),
        "imageSize": {"width": size[0], "height": size[1]},
        "frames": len(detections),
        "cornerSpreadPx": spread,
        "translationSpreadMm": translation_spread,
        "pose": pose,
        "referenceCorners": corners.reshape(-1, 2).tolist(),
        "referenceImage": "reference.png",
    })
    print(f"相机 {args.camera} 参考位姿：距离 {pose['distanceMm']:.2f} mm，倾斜 {pose['tiltDeg']:.2f}°，"
          f"重投影 {pose['reprojectionErrorPx']:.3f} px")
    print(f"{len(detections)} 帧角点最大抖动 {spread:.3f} px，平移抖动 {translation_spread:.4f} mm")
    if spread > 0.5:
        print("需复核：角点抖动偏大，检查标定板是否固定、光照是否闪烁")
    print(f"已写入 {out}；坐标轴示意 {folder / 'reference_axes.png'}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    folder = camera_dir(args)
    reference_path = Path(args.reference).expanduser() if args.reference else folder / "reference_pose.json"
    if not reference_path.exists():
        raise CalibrationError(f"找不到参考位姿 {reference_path}，请先运行 pose")
    reference = read_json(reference_path)
    board = BoardSpec.from_dict(reference["board"])
    reference_corners = np.asarray(reference["referenceCorners"], np.float32).reshape(-1, 1, 2)
    size = (int(reference["imageSize"]["width"]), int(reference["imageSize"]["height"]))
    source = make_source(args)
    try:
        detections, frame = collect_detections(source, board, args.frames)
    finally:
        source.close()
    _check_frame_size(frame, size)
    corners, spread = median_corners(detections)
    comparison = compare_with_reference(corners, reference_corners)
    aligned = comparison.pop("corners")
    delta: dict[str, float] | None = None
    intrinsics_path = Path(reference.get("intrinsics", {}).get("path", ""))
    if intrinsics_path.is_file():
        _, matrix, dist, _ = _load_intrinsics(intrinsics_path)
        delta = pose_delta(solve_pose(aligned, board, matrix, dist), reference["pose"])
    passed = comparison["maxShiftPx"] <= args.max_shift_px
    record = {"checkedAt": now_text(), "camera": args.camera, "reference": str(reference_path),
              "passed": passed, "maxShiftAllowedPx": args.max_shift_px, "cornerSpreadPx": spread,
              **comparison, "poseDelta": delta}
    with (folder / "checks.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    overlay = frame.copy()
    for (x0, y0), (x1, y1) in zip(reference_corners.reshape(-1, 2), aligned.reshape(-1, 2), strict=True):
        cv2.circle(overlay, (int(round(x0)), int(round(y0))), 3, (0, 0, 255), 1)
        cv2.circle(overlay, (int(round(x1)), int(round(y1))), 1, (0, 255, 0), -1)
    write_image(folder / "check_latest.png", overlay)
    print(f"相机 {args.camera}：角点平均偏移 {comparison['meanShiftPx']:.3f} px，"
          f"最大 {comparison['maxShiftPx']:.3f} px（允许 ≤ {args.max_shift_px} px）")
    if delta is not None:
        print(f"位姿变化：平移 {delta['translationMm']:.4f} mm，转角 {delta['rotationDeg']:.4f}°")
    print("结论：通过，安装未发现移动" if passed else
          "结论：不通过——相机或标定板位置与定型参考不一致，先确认标定板放置，再检查相机固定，未处理前不要采集")
    return 0 if passed else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="相机标定（张正友法）：采集、内参计算、参考位姿、安装复核")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--camera", required=True, choices=CAMERA_ROLES, help="相机角色")
        p.add_argument("--root", default=str(DEFAULT_ROOT), help=f"标定结果根目录（默认 {DEFAULT_ROOT}）")

    def board(p: argparse.ArgumentParser, required: bool) -> None:
        p.add_argument("--board", type=parse_board, required=required, help="内角点数 列x行，例如 9x6")
        p.add_argument("--square-mm", type=float, required=required, help="方格边长（mm，按实测值填写）")

    def source(p: argparse.ArgumentParser) -> None:
        p.add_argument("--source", choices=("api", "device", "file"), default="api",
                       help="api=后端快照（默认），device=直连相机（需先停服务），file=离线图像")
        p.add_argument("--base-url", default=DEFAULT_BASE_URL, help="后端地址")
        p.add_argument("--index", type=int, help="device 模式的相机序号")
        p.add_argument("--size", type=parse_size, default=(640, 480), help="device 模式分辨率，须与录制一致")
        p.add_argument("--image", nargs="+", help="file 模式的图像路径")

    capture = sub.add_parser("capture", help="采集标定图像")
    common(capture)
    board(capture, True)
    source(capture)
    capture.add_argument("--auto", action="store_true", help="启动即开启自动保存（静止且换了位置才保存）")
    capture.add_argument("--no-preview", action="store_true", help="无窗口，自动采集")
    capture.add_argument("--count", type=int, default=0, help="本次采集张数后自动结束（0=手动退出）")
    capture.set_defaults(func=cmd_capture)

    calibrate = sub.add_parser("calibrate", help="张正友法计算内参")
    common(calibrate)
    board(calibrate, False)
    calibrate.add_argument("--images", help="图像目录（默认 <root>/<camera>/images）")
    calibrate.add_argument("--free-k3", action="store_true", help="同时估计 k3（广角镜头才需要）")
    calibrate.add_argument("--max-view-error", type=float, default=MAX_VIEW_ERROR_PX, help="单张误差剔除阈值 px")
    calibrate.add_argument("--min-views", type=int, default=MIN_VIEWS, help="最少有效图像数")
    calibrate.set_defaults(func=cmd_calibrate)

    pose = sub.add_parser("pose", help="记录定型参考位姿")
    common(pose)
    board(pose, False)
    source(pose)
    pose.add_argument("--intrinsics", help="内参文件（默认 <root>/<camera>/intrinsics.json）")
    pose.add_argument("--frames", type=int, default=10, help="取中位数的帧数")
    pose.add_argument("--note", help="备注，例如参与人员、标定板放置位置")
    pose.add_argument("--force", action="store_true", help="覆盖已有参考（旧文件会备份）")
    pose.set_defaults(func=cmd_pose)

    check = sub.add_parser("check", help="复核相机安装是否移动")
    common(check)
    source(check)
    check.add_argument("--reference", help="参考位姿文件（默认 <root>/<camera>/reference_pose.json）")
    check.add_argument("--frames", type=int, default=5, help="取中位数的帧数")
    check.add_argument("--max-shift-px", type=float, default=1.0, help="允许的最大角点偏移 px")
    check.set_defaults(func=cmd_check)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except CalibrationError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
