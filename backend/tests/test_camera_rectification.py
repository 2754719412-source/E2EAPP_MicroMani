"""真实镜头内参只用于已绑定的角色，覆盖预览、录像及标定取原图。"""
import json
from pathlib import Path
from threading import Lock

import pytest

from backend.drivers.camera_opencv import OpenCVCameraDriver

cv2 = pytest.importorskip('cv2')
np = pytest.importorskip('numpy')
ASSETS = Path(__file__).resolve().parents[2] / 'docs/camera-calibration/2026-11-26/assets'


@pytest.fixture
def frames(monkeypatch):
    role = 'wrist_left'
    p = json.loads((ASSETS / f'{role}-intrinsics.json').read_text(encoding='utf-8'))
    settings = {'wristLeftIdentity': p['cameraInfo']['identity'], 'lensIntrinsics': {role: p}}
    cfg = {'cameras': settings}
    driver = OpenCVCameraDriver()
    monkeypatch.setattr(driver, '_resolved_indices', lambda *_: {role: 3})
    monkeypatch.setattr(driver, '_get_capture', lambda *_: object())
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    frame[::12, :, 1] = 255
    frame[:, ::14, 2] = 240
    jpeg = cv2.imencode('.jpg', frame)[1].tobytes()
    driver._latest_jpegs[3] = jpeg
    driver._latest_frames[3] = frame
    driver._latest_sequences[3] = 42
    driver._latest_at[3] = 17.5
    driver._frame_locks[3] = Lock()
    return driver, cfg, role, frame, jpeg, p


def expected(frame, profile):
    k, d = np.array(profile['cameraMatrix']), np.array(profile['distCoeffs'])
    new_k, _ = cv2.getOptimalNewCameraMatrix(k, d, (640, 480), 0)
    return cv2.undistort(frame, k, d, None, new_k)


@pytest.mark.parametrize('jpeg_only', [True, False])
def test_snapshot_stream_and_timestamped_rgb_share_geometry(frames, jpeg_only):
    driver, cfg, role, frame, jpeg, p = frames
    raw_bgr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if jpeg_only:
        driver._latest_frames.clear()
    assert driver.snapshot(cfg, role, raw=True) == jpeg
    snapshot = driver.snapshot_frame_with_timestamp(cfg, role)
    assert snapshot.monotonic_s == 17.5
    np.testing.assert_array_equal(snapshot.frame, expected(raw_bgr if jpeg_only else frame, p)[:, :, ::-1])
    seq, preview = driver.wait_for_frame(cfg, role)
    assert seq == 42 and preview != jpeg and driver.snapshot(cfg, role) == preview
    image = cv2.imdecode(np.frombuffer(preview, np.uint8), cv2.IMREAD_COLOR)
    assert cv2.PSNR(image, expected(raw_bgr, p)) > cv2.PSNR(image, raw_bgr) + 4


def test_unmatched_profile_and_wrong_frame_size_cannot_be_used(frames):
    driver, cfg, role, frame, jpeg, _ = frames
    cfg['cameras']['wristLeftIdentity'] = 'swapped-device'
    with pytest.raises(RuntimeError, match='身份'):
        driver.snapshot(cfg, role)
    assert driver.snapshot(cfg, role, raw=True) == jpeg
    cfg['cameras']['wristLeftIdentity'] = cfg['cameras']['lensIntrinsics'][role]['cameraInfo']['identity']
    driver._latest_frames[3] = frame[::2, ::2]
    with pytest.raises(RuntimeError, match='分辨率'):
        driver.snapshot_frame_with_timestamp(cfg, role)
    cfg['cameras'].pop('lensIntrinsics')
    assert driver.snapshot(cfg, role) == jpeg


def test_http_config_activation_raw_bypass_and_recording_guard(frames, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import create_app

    driver, cfg, role, _, jpeg, _ = frames
    monkeypatch.setenv('APPSTATION_HAL_MODE', 'test')
    monkeypatch.setenv('APPSTATION_DISABLE_CAMERA_PROBE', '1')
    app = create_app(tmp_path)
    client = TestClient(app)
    app.state.hardware.cameras = driver
    settings = client.get('/api/settings').json()
    settings['cameras'].update(cfg['cameras'])
    url = f'/api/cameras/{role}/snapshot'
    assert client.put('/api/settings', json=settings).status_code == 200
    raw = client.get(url + '?raw=true')
    assert raw.content == jpeg and raw.headers['x-appstation-image-space'] == 'raw'
    corrected = client.get(url)
    assert corrected.status_code == 200 and corrected.content != raw.content
    assert corrected.headers['x-appstation-image-space'] == 'undistorted'
    settings['cameras']['lensIntrinsics'][role]['cameraInfo']['identity'] = 'wrong'
    assert client.put('/api/settings', json=settings).status_code == 400
    settings['cameras']['lensIntrinsics'] = {}
    monkeypatch.setattr(app.state.recorder, 'camera_configuration_busy', lambda: True)
    assert client.put('/api/settings', json=settings).status_code == 409
    assert client.get(url).content == corrected.content
