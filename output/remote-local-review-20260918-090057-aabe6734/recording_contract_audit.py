"""隔离快照的数据契约检查；只用临时数字/元数据及离线替身。"""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

audit_dir = Path(__file__).resolve().parent
source_dir = audit_dir / "source"
sys.path.insert(0, str(source_dir))
os.environ["APPSTATION_HAL_MODE"] = "test"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

from fastapi.testclient import TestClient
import backend.app as app_module
import backend.services.dataset_recorder as recorder_module
import backend.services.policy_bridge as policy_module
import scripts.normalize_origin as normalize_module
from backend.core.defaults import default_config
from backend.core.data_contract import data_contract_metadata, hardware_to_dataset_motion

for module in (app_module, recorder_module, policy_module, normalize_module):
    assert Path(module.__file__).resolve().is_relative_to(source_dir)

recorder = object.__new__(recorder_module.DatasetRecorderService)
config = default_config()
positions = [1, 2, 3, 0.1, 0.2, 0.3, 7, 8, 9, 0.4, 0.5, 0.6]
recorded = recorder._compose_observation_state(positions, [4.5, 5.5])
observed = policy_module.lerobot_state_from_ui(positions, [4.5, 5.5])
plan = policy_module.build_policy_action_plan(observed, recorded, config, max_translation_um=500, max_rotation_deg=1, max_gripper_mm=10)
assert recorded == observed
assert all(delta == 0 for side in plan["motion"].values() for delta in side["deltas"].values())

config["motion"]["origin"] = {"valid": True, "leftValid": True, "rightValid": True, "leftPulse": [0.0] * 6, "rightPulse": [0.0] * 6}
pulses = [0.0] * 12
pulses[7] = 10000.0
positions = recorder._recording_motion_positions(config, [0.0] * 12, pulses)
recorded = recorder._compose_observation_state(positions, [0, 0])
normalized = normalize_module.normalize_frame_to_origin({"observation.state": recorded, "action": recorded, "observation.pulses": hardware_to_dataset_motion(pulses)}, recorder._episode_motion_origin_snapshot(config), config)
assert normalized["changed"] is False
assert normalized["observation.state"][1] == -1000.0

fixture_root = Path(tempfile.mkdtemp(prefix="recording-contract-fixtures-", dir=audit_dir))
assert fixture_root.resolve().is_relative_to(audit_dir.resolve())
native_dir = fixture_root / "unknown_native"
legacy_dir = fixture_root / "unknown_legacy"
for path in (native_dir, legacy_dir):
    (path / "meta").mkdir(parents=True)
(native_dir / "meta/info.json").write_text(json.dumps({"format": "lerobot-v3-native", "total_frames": 1}), encoding="utf-8")
(legacy_dir / "meta/info.json").write_text(json.dumps({"format": "legacy-jsonl", "total_frames": 1}), encoding="utf-8")
native_episode = {"id": "episode_000000", "native": True, "frames": 1, "datasetFromIndex": 0, "datasetToIndex": 1}
legacy_episode = {"id": "episode_000000", "native": False, "frames": 1, "dataPath": "frames.jsonl"}
(native_dir / "meta/episodes.jsonl").write_text(json.dumps(native_episode) + "\n", encoding="utf-8")
(legacy_dir / "meta/episodes.jsonl").write_text(json.dumps(legacy_episode) + "\n", encoding="utf-8")
(legacy_dir / "frames.jsonl").write_text(json.dumps({"frame_index": 0, "observation.state": list(range(14)), "observation.pulses": list(range(12)), "observation.force_left": [1] * 6, "observation.force_right": [2] * 6}) + "\n", encoding="utf-8")

native_error = recorder._dataset_contract_error(native_dir)
assert "manual migration" in native_error
legacy_error = recorder._dataset_contract_error(legacy_dir)
legacy_samples = recorder._episode_samples(legacy_dir, "unknown_legacy", legacy_episode)
assert legacy_error == ""
assert len(legacy_samples) == 1

recorder._dataset_path = lambda dataset_id: fixture_root / dataset_id
config["storage"]["pushToHub"] = True
recorder.settings = SimpleNamespace(get_config=lambda: config)
mock_upload_calls = []
recorder._start_hub_push_job = lambda *args, **kwargs: (mock_upload_calls.append(str(args[2])), "mock-job-no-upload")[1]
upload = recorder.push_dataset("unknown_native", {"dryRun": False, "repoId": "audit/never-upload"})
assert upload["queued"] is True
assert mock_upload_calls == [str(native_dir)]

class FakeDataset:
    def __init__(self, *args, **kwargs):
        pass
    def __len__(self):
        return 1
    def __getitem__(self, key):
        return {"observation.images.global": "fake-image"}

recorder._native_imports = lambda: (FakeDataset, None)
recorder._encode_rgb_tensor_to_jpeg = lambda image, _: b"mock-jpeg-no-camera"
preview = recorder.resolve_frame_image("unknown_native", "episode_000000", "global", 0)
assert preview == b"mock-jpeg-no-camera"
raw_download = recorder.resolve_file("unknown_native", "meta/info.json")
assert raw_download.is_file()

app = app_module.create_app(fixture_root / "runtime")
app.state.recorder._dataset_path = lambda dataset_id: fixture_root / dataset_id
client = TestClient(app, raise_server_exceptions=False)
stats_response = client.get("/api/datasets/unknown_native/stats")
episode_response = client.get("/api/datasets/unknown_native/episodes/episode_000000")
assert stats_response.status_code == 500
assert episode_response.status_code == 500

print(json.dumps({
    "remote_source": str(source_dir),
    "fixture_root": str(fixture_root),
    "imports": {module.__name__: module.__file__ for module in (app_module, recorder_module, policy_module, normalize_module)},
    "fixed": {"recorded_and_policy_states_equal": True, "hold_motion_deltas_are_zero": True, "same_origin_normalize_y_um": normalized["observation.state"][1], "same_origin_normalize_changed": normalized["changed"], "unknown_native_resume_error": native_error},
    "remaining": {"unknown_legacy_contract_error": legacy_error, "unknown_legacy_numeric_samples_returned": len(legacy_samples), "unknown_native_upload_reached_mock_job": upload["queued"], "unknown_native_image_preview_reached_mock_decoder": preview.decode(), "unknown_native_file_download_allowed": str(raw_download), "unknown_native_stats_response": {"status": stats_response.status_code, "body": stats_response.text}, "unknown_native_episode_response": {"status": episode_response.status_code, "body": episode_response.text}},
    "limitations": "No real upload, hardware, cameras, dataset decoding, startup lifespan, or user dataset was used. LeRobot operations were replaced with offline fakes."
}, ensure_ascii=False, indent=2))
