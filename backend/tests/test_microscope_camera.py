import json
from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from backend.core.camera_roles import MICROSCOPE_SIZE, STANDARD_CAMERA_KEYS, microscope_mode_matches
from backend.core.defaults import default_config
from backend.drivers.camera_opencv import OpenCVCameraDriver
from backend.services.dataset_recorder import CAMERA_FEATURE_KEYS, DatasetRecorderService


def test_microscope_binding_is_optional_unique_and_never_steals_a_wrist(monkeypatch):
    driver = OpenCVCameraDriver()
    config = default_config()
    devices = {
        index: {"parentId": f"USB\\{serial}", "devicePath": serial, "name": serial}
        for index, serial in enumerate(("20250606105", "wrist-a", "wrist-b", "optics"))
    }
    monkeypatch.setattr(driver, "_camera_identities_by_index", lambda: devices)
    config["cameras"].update(wristLeftIdentity="wrist-a", wristRightIdentity="wrist-b")
    assert [item["name"] for item in driver.microscope_candidates(config)] == ["optics"]
    assert tuple(driver._resolved_indices(object(), config, 30)) == STANDARD_CAMERA_KEYS
    config["cameras"].update(microscopeEnabled=True, microscopeIdentity="optics")
    assert driver._resolved_indices(object(), config, 30)["microscope"] == 3
    config["cameras"]["microscopeIdentity"] = "wrist-a"
    roles = driver._resolved_indices(object(), config, 30)
    assert roles["microscope"] == -1 and roles["wrist_left"] == 1


def test_microscope_format_and_recording_contract(monkeypatch):
    recorder = object.__new__(DatasetRecorderService)
    recorder._native_use_videos = True
    recorder._record_fps_hz = 30
    monkeypatch.setattr(recorder, "_native_imports", lambda: (object(), np))
    config = default_config()
    config["storage"]["recordFps"] = 20
    key = CAMERA_FEATURE_KEYS["microscope"]
    assert key not in recorder._native_features(config)
    assert "camera_microscope" not in recorder._new_sample_buffers(config)
    assert recorder._record_fps_from_config(config) == 20
    config["cameras"].update(microscopeEnabled=True, fps=15)
    assert recorder._native_features(config)[key]["shape"] == (2160, 3840, 3)
    assert recorder._record_fps_from_config(config) == 60
    assert recorder._source_sample_rate_hz("camera_microscope", config) == 60
    assert recorder._source_sample_rate_hz("camera_global", config) == 15
    assert "camera_microscope" in recorder._new_sample_buffers(config)
    assert OpenCVCameraDriver()._capture_size(config, "microscope") == MICROSCOPE_SIZE
    assert microscope_mode_matches(3840, 2160, 59.94)
    assert microscope_mode_matches(3840, 2160, 60)
    assert not microscope_mode_matches(3840, 2160, 30)
    assert not microscope_mode_matches(3840, 2160, 0)
    assert not microscope_mode_matches(3840, 2160, None)
    assert not microscope_mode_matches(3840, 2160, 15)
    assert not microscope_mode_matches(1920, 1080, 60)
    with pytest.raises(ValueError, match="3840"):
        recorder._coerce_rgb_frame(np.zeros((480, 640, 3), np.uint8), "microscope")


def test_microscope_record_payload_and_video_review(tmp_path, monkeypatch):
    recorder = object.__new__(DatasetRecorderService)
    recorder._task = "显微测试"
    monkeypatch.setattr(recorder, "_native_imports", lambda: (object(), np))
    config = {"cameras": {"microscopeEnabled": True}}
    recorder._recording_config_snapshot = config
    rgb = np.zeros((2160, 3840, 3), np.uint8)
    rgb[:, :, 0] = 220
    recorder.hardware = SimpleNamespace(cameras=SimpleNamespace(
        snapshot_frame_with_timestamp=lambda *_: SimpleNamespace(frame=rgb, monotonic_s=42.5)))
    frame, timestamp = recorder._camera_recording_frame_with_time(config, "microscope")
    assert timestamp == 42.5
    key = CAMERA_FEATURE_KEYS["microscope"]
    images = {CAMERA_FEATURE_KEYS[camera]: np.zeros((480, 640, 3), np.uint8) for camera in STANDARD_CAMERA_KEYS}
    images[key] = frame
    payload = recorder._native_frame_payload({
        "observation.state": [0] * 14, "action": [0] * 14, "observation.pulses": [0] * 12,
        "observation.force_left": [0] * 6, "observation.force_right": [0] * 6, "images": images,
    })
    assert set(images).issubset(payload) and payload[key].shape == (2160, 3840, 3)
    path = tmp_path / "videos" / key / "chunk-000" / "file-000.mp4"
    path.parent.mkdir(parents=True)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 60, MICROSCOPE_SIZE)
    assert writer.isOpened()
    try:
        for _ in range(3):
            writer.write(cv2.cvtColor(payload[key], cv2.COLOR_RGB2BGR))
    finally:
        writer.release()
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta" / "info.json").write_text(json.dumps({"features": {key: {"dtype": "video"}}}))
    assert recorder._camera_resolution_summary(tmp_path)["microscope"]["saved"] == "3840x2160"
    prefix = f"videos/{key}"
    row = {prefix + "/chunk_index": 0, prefix + "/file_index": 0,
           prefix + "/from_timestamp": 0, prefix + "/to_timestamp": 3 / 60}
    jpeg = recorder._native_video_row_to_jpeg(tmp_path, {"fps": 60}, "microscope", 2, row)
    bgr = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    assert bgr.shape == frame.shape and int(bgr[100, 100, 2]) > 200


def test_microscope_stream_and_snapshot_over_http(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from backend.app import create_app

    monkeypatch.setenv("APPSTATION_HAL_MODE", "test")
    monkeypatch.setenv("APPSTATION_DISABLE_CAMERA_PROBE", "1")
    app = create_app(tmp_path)
    client = TestClient(app)
    base = "/api/cameras/microscope"
    assert client.get(f"{base}/stream").status_code == 409
    assert client.get(f"{base}/snapshot").status_code == 409

    config = client.get("/api/settings").json()
    config["cameras"].update(microscopeEnabled=True, microscopeIdentity="fixture-4k60")
    assert client.put("/api/settings", json=config).status_code == 200
    ok, encoded = cv2.imencode(".jpg", np.zeros((2160, 3840, 3), np.uint8))
    assert ok
    jpeg = encoded.tobytes()
    driver = app.state.hardware.cameras

    def snapshot(config, camera):
        assert camera == "microscope" and config["cameras"]["microscopeEnabled"]
        return jpeg

    def last_frame(config, camera, sequence, timeout):
        assert sequence == -1
        frame = snapshot(config, camera)
        config["cameras"]["microscopeEnabled"] = False
        app.state.settings.save_config(config, emit_log=False)
        return 1, frame

    monkeypatch.setattr(driver, "snapshot", snapshot)
    monkeypatch.setattr(driver, "wait_for_frame", last_frame)
    still = client.get(f"{base}/snapshot")
    assert still.headers["content-type"] == "image/jpeg" and still.content == jpeg
    response = client.get(f"{base}/stream")
    assert response.headers["content-type"] == "multipart/x-mixed-replace; boundary=frame"
    assert response.content.startswith(b"--frame") and jpeg in response.content
