# 阅读导航 07｜测试与验证
# 职责：回归验证：相机标定脚本用合成棋盘图像还原已知内参、参考位姿，并识别相机移动。
# 先看：render_view → test_calibration_recovers_known_intrinsics → test_reference_pose_and_drift_check。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。

from __future__ import annotations

import importlib.util
import json
import math
import sys
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "calibrate_camera.py"
SIZE = (640, 480)
TRUE_K = np.array([[820.0, 0.0, 322.0], [0.0, 815.0, 236.0], [0.0, 0.0, 1.0]])
TRUE_DIST = np.array([-0.12, 0.08, 0.0005, -0.0004, 0.0])


def load_module():
    spec = importlib.util.spec_from_file_location("calibrate_camera", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def render_view(board, rvec, tvec, matrix=TRUE_K, dist=TRUE_DIST, size=SIZE, scale=2):
    """按针孔+畸变模型逐像素反投影到标定板平面，超采样后缩小以得到抗锯齿的边缘。"""
    width, height = size[0] * scale, size[1] * scale
    k_hi = matrix.copy()
    k_hi[:2] *= scale
    k_hi[0, 2] = matrix[0, 2] * scale + (scale - 1) / 2
    k_hi[1, 2] = matrix[1, 2] * scale + (scale - 1) / 2
    xs, ys = np.meshgrid(np.arange(width, dtype=np.float64), np.arange(height, dtype=np.float64))
    pixels = np.stack([xs.ravel(), ys.ravel()], axis=-1).reshape(-1, 1, 2)
    rays = cv2.undistortPoints(pixels, k_hi, dist).reshape(-1, 2)
    rays = np.hstack([rays, np.ones((rays.shape[0], 1))])
    rotation, _ = cv2.Rodrigues(np.asarray(rvec, np.float64))
    t = np.asarray(tvec, np.float64).reshape(3)
    normal = rotation[:, 2]
    depth = (normal @ t) / (rays @ normal)
    local = (rays * depth[:, None] - t) @ rotation
    s = board.square_mm
    i = np.floor((local[:, 0] + s) / s)
    j = np.floor((local[:, 1] + s) / s)
    on_board = (i >= 0) & (i <= board.cols) & (j >= 0) & (j <= board.rows)
    margin = (i >= -1) & (i <= board.cols + 1) & (j >= -1) & (j <= board.rows + 1)
    image = np.full(i.shape, 90.0)
    image[margin] = 235.0
    image[on_board & ((i + j) % 2 == 0)] = 25.0
    image[depth <= 0] = 90.0
    hi = image.reshape(height, width).astype(np.float32)
    return cv2.resize(hi, size, interpolation=cv2.INTER_AREA).round().astype(np.uint8)


def view_poses():
    """按操作步骤的要求：标定板走遍画面九宫格，每个位置一正一斜两种朝向。"""
    tilts = [(0, 0), (25, 0), (0, 25), (-25, 0), (0, -25), (20, 20), (-20, 20), (20, -20), (-20, -20)]
    poses = []
    for index, (ox, oy) in enumerate([(x, y) for y in (-11.0, 0.0, 11.0) for x in (-14.0, 0.0, 14.0)]):
        for ax, ay in (tilts[index], tilts[(index + 4) % len(tilts)]):
            rotation = cv2.Rodrigues(np.radians([ax, ay, 4.0 * (index % 3 - 1)]))[0]
            center = np.array([8 * 2.5 / 2, 5 * 2.5 / 2, 0.0])
            tvec = np.array([ox, oy, 70.0]) - rotation @ center
            poses.append((cv2.Rodrigues(rotation)[0].reshape(3), tvec))
    return poses


@pytest.fixture(scope="module")
def calib():
    return load_module()


@pytest.fixture(scope="module")
def board(calib):
    return calib.BoardSpec(9, 6, 2.5)


@pytest.fixture(scope="module")
def image_dir(tmp_path_factory, board):
    folder = tmp_path_factory.mktemp("calib") / "images"
    folder.mkdir()
    for index, (rvec, tvec) in enumerate(view_poses()):
        cv2.imwrite(str(folder / f"view_{index:02d}.png"), render_view(board, rvec, tvec))
    return folder


def test_calibration_recovers_known_intrinsics(calib, board, image_dir) -> None:
    result = calib.calibrate_images(sorted(image_dir.glob("*.png")), board)

    assert result["undetected"] == []
    assert result["verdict"] == "ok", result["warnings"]
    assert result["rmsPx"] < 0.2
    assert result["coverage"]["fraction"] >= 0.75
    assert result["fx"] == pytest.approx(TRUE_K[0, 0], rel=0.005)
    assert result["fy"] == pytest.approx(TRUE_K[1, 1], rel=0.005)
    assert result["cx"] == pytest.approx(TRUE_K[0, 2], abs=2.0)
    assert result["cy"] == pytest.approx(TRUE_K[1, 2], abs=2.0)
    assert result["distCoeffs"][0] == pytest.approx(TRUE_DIST[0], abs=0.01)


def test_capture_saves_only_still_and_new_board_positions(calib, board, image_dir, tmp_path) -> None:
    first, second = sorted(image_dir.glob("*.png"))[0:3:2]
    # 每张图重复 12 次（约 0.6 s）模拟拿稳标定板；同一位置只应保存一次。
    frames = [str(first)] * 12 + [str(second)] * 12

    assert calib.main(["capture", "--camera", "wrist_left", "--root", str(tmp_path), "--board", "9x6",
                       "--square-mm", "2.5", "--source", "file", "--no-preview", "--image", *frames]) == 0

    meta = json.loads((tmp_path / "wrist_left" / "capture.json").read_text(encoding="utf-8"))
    assert meta["board"] == board.as_dict()
    assert len(meta["images"]) == 2
    assert len(list((tmp_path / "wrist_left" / "images").glob("*.png"))) == 2
    # 换一种标定板继续写入同一目录必须被拒绝，避免混用。
    assert calib.main(["capture", "--camera", "wrist_left", "--root", str(tmp_path), "--board", "8x6",
                       "--square-mm", "2.5", "--source", "file", "--no-preview", "--image", str(first)]) == 1


def test_calibration_flags_only_fronto_parallel_views(calib, board, tmp_path) -> None:
    for index, (ox, oy) in enumerate([(x, y) for x in (-20, 0, 20) for y in (-12, 0, 12)] + [(10, 5)]):
        tvec = np.array([ox * 0.5 - 10.0, oy * 0.5 - 6.25, 120.0])
        cv2.imwrite(str(tmp_path / f"flat_{index:02d}.png"), render_view(board, np.zeros(3), tvec))

    result = calib.calibrate_images(sorted(tmp_path.glob("*.png")), board)

    assert result["verdict"] == "review"
    assert any("倾斜" in warning for warning in result["warnings"])


@pytest.mark.parametrize("spin_deg", [0.0, 90.0, 180.0, 270.0])
def test_origin_corner_follows_dark_outer_square(calib, board, spin_deg) -> None:
    # 无论标定板在画面中怎样转，原点都落在外侧对角方格为黑色的物理角上。
    rotation = cv2.Rodrigues(np.radians([10.0, -6.0, 0.0]))[0] @ cv2.Rodrigues(np.radians([0.0, 0.0, spin_deg]))[0]
    tvec = np.array([-3.0, 2.0, 90.0])
    image = render_view(board, cv2.Rodrigues(rotation)[0].reshape(3), tvec)

    corners = calib.detect_corners(image, board)

    assert corners is not None
    pose = calib.solve_pose(corners, board, TRUE_K, TRUE_DIST)
    assert pose["tvecMm"] == pytest.approx(tvec.tolist(), abs=0.3)


def test_reference_pose_and_drift_check(calib, board, image_dir, tmp_path) -> None:
    root = tmp_path / "root"
    camera_dir = root / "global"
    camera_dir.mkdir(parents=True)
    result = calib.calibrate_images(sorted(image_dir.glob("*.png")), board)
    (camera_dir / "intrinsics.json").write_text(json.dumps({**result, "board": board.as_dict()}), encoding="utf-8")

    rvec = cv2.Rodrigues(cv2.Rodrigues(np.radians([12.0, -8.0, 3.0]))[0])[0].reshape(3)
    tvec = np.array([-10.0, -6.0, 110.0])
    reference_image = tmp_path / "reference.png"
    cv2.imwrite(str(reference_image), render_view(board, rvec, tvec))
    assert calib.main(["pose", "--camera", "global", "--root", str(root), "--source", "file",
                       "--image", str(reference_image), "--frames", "3"]) == 0

    saved = json.loads((camera_dir / "reference_pose.json").read_text(encoding="utf-8"))
    assert saved["pose"]["tvecMm"] == pytest.approx(tvec.tolist(), abs=0.5)
    assert saved["pose"]["reprojectionErrorPx"] < 0.2
    # 定型参考默认不允许覆盖。
    assert calib.main(["pose", "--camera", "global", "--root", str(root), "--source", "file",
                       "--image", str(reference_image)]) == 1

    assert calib.main(["check", "--camera", "global", "--root", str(root), "--source", "file",
                       "--image", str(reference_image), "--frames", "2"]) == 0

    # 相机绕光轴外的轴转 0.5°，对应画面约 7 px 的偏移，必须判为不通过。
    camera_tilt = cv2.Rodrigues(np.radians([0.0, 0.5, 0.0]))[0]
    moved_r = cv2.Rodrigues(camera_tilt @ cv2.Rodrigues(rvec)[0])[0].reshape(3)
    moved_image = tmp_path / "moved.png"
    cv2.imwrite(str(moved_image), render_view(board, moved_r, camera_tilt @ tvec))
    assert calib.main(["check", "--camera", "global", "--root", str(root), "--source", "file",
                       "--image", str(moved_image), "--frames", "2"]) == 1

    records = [json.loads(line) for line in (camera_dir / "checks.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [record["passed"] for record in records] == [True, False]
    assert records[1]["maxShiftPx"] > 3.0
    assert records[1]["poseDelta"]["rotationDeg"] == pytest.approx(0.5, abs=0.1)
    assert math.isfinite(records[0]["meanShiftPx"])
