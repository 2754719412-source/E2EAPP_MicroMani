"""远端快照的纯数值契约复现；不导入硬件服务，不读写数据集。"""
import ast
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

source = Path(__file__).resolve().parent / "source"
sys.path.insert(0, str(source))
os.chdir(source)

import backend.core.defaults as defaults
import backend.core.units as units
import backend.services.policy_bridge as policy_bridge
import scripts.normalize_origin as normalize_origin

for module in (defaults, units, policy_bridge, normalize_origin):
    assert Path(module.__file__).resolve().is_relative_to(source)

recorder_path = source / "backend/services/dataset_recorder.py"
parsed = ast.parse(recorder_path.read_text(encoding="utf-8-sig"))
recorder_class = next(node for node in parsed.body if isinstance(node, ast.ClassDef) and node.name == "DatasetRecorderService")
method_names = {
    "_compose_observation_state", "_float_or_zero", "_recording_motion_positions",
    "_origin_side_pulses", "_episode_motion_origin_snapshot",
}
methods = [node for node in recorder_class.body if isinstance(node, ast.FunctionDef) and node.name in method_names]
assert len(methods) == len(method_names)
minimal = ast.Module(body=[ast.ClassDef(name="PureRecorder", bases=[], keywords=[], body=methods, decorator_list=[])], type_ignores=[])
ast.fix_missing_locations(minimal)
namespace = {"Any": Any, "math": math, "pulses_to_ui_state": units.pulses_to_ui_state, "stable_config_hash": lambda _: "unused-in-numeric-repro"}
exec(compile(minimal, str(recorder_path), "exec"), namespace)
recorder = namespace["PureRecorder"]()
app_path = source / "backend/app.py"
app_ast = ast.parse(app_path.read_text(encoding="utf-8-sig"))
app_functions = [node for node in app_ast.body if isinstance(node, ast.FunctionDef) and node.name in {"origin_side_pulses", "relative_motion_positions"}]
assert len(app_functions) == 2
exec(compile(ast.Module(body=app_functions, type_ignores=[]), str(app_path), "exec"), namespace)

config = defaults.default_config()
positions = [1, 2, 3, 0.1, 0.2, 0.3, 7, 8, 9, 0.4, 0.5, 0.6]
grippers = [4.5, 5.5]
recorded_state = recorder._compose_observation_state(positions, grippers)
policy_state = policy_bridge.lerobot_state_from_ui(positions, grippers)
plan = policy_bridge.build_policy_action_plan(policy_state, recorded_state, config, max_translation_um=500, max_rotation_deg=1, max_gripper_mm=10)
assert recorded_state != policy_state
assert plan["motion"]["left"]["deltas"]["X"] == 6.0
assert plan["motion"]["right"]["deltas"]["X"] == -6.0

config["motion"]["origin"] = {"valid": True, "leftValid": True, "rightValid": True, "leftPulse": [0.0] * 6, "rightPulse": [0.0] * 6}
hardware_pulses = [0.0] * 12
hardware_pulses[7] = 10000.0
hardware_positions = recorder._recording_motion_positions(config, [0.0] * 12, hardware_pulses)
policy_hardware_positions = namespace["relative_motion_positions"](config, [0.0] * 12, hardware_pulses)
assert hardware_positions == policy_hardware_positions
state_before = recorder._compose_observation_state(hardware_positions, [0, 0])
recorded_pulses = hardware_pulses[6:12] + hardware_pulses[0:6]
origin = recorder._episode_motion_origin_snapshot(config)
result = normalize_origin.normalize_frame_to_origin({"observation.state": state_before, "action": state_before, "observation.pulses": recorded_pulses}, origin, config)
assert state_before[1] == -1000.0
assert result["observation.state"][1] == 2000.0
assert result["changed"] is True
assert result["needs_manual_review"] is False

print(json.dumps({
    "source": str(source),
    "import_sources": {module.__name__: module.__file__ for module in (defaults, units, policy_bridge, normalize_origin)},
    "recorder_methods_extracted_from_snapshot_ast": sorted(method_names),
    "policy_contract": {"hardware_positions": positions, "hardware_grippers": grippers, "recorded_state": recorded_state, "policy_observation_state": policy_state, "motion_plan_when_recorded_hold_state_is_submitted": plan["motion"], "gripper_plan": plan["grippers"]},
    "normalize_same_origin": {"hardware_pulses": hardware_pulses, "recorder_and_policy_relative_position_functions_agree": hardware_positions == policy_hardware_positions, "recorded_pulses": recorded_pulses, "origin_snapshot": origin, "recorded_state_before": state_before, "normalization_result": result},
    "validation": "All assertions passed; no hardware services imported or called, no dataset files opened or modified."
}, ensure_ascii=False, indent=2))
