"""只整合已核对的数据契约改动，保留本地安全方法和导航注释。"""
import ast
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
remote = root / "output/remote-local-review-20260918-090057-aabe6734/source"

def read(path):
    return path.read_text(encoding="utf-8-sig")

def write(path, content):
    original = path.read_bytes() if path.exists() else b""
    encoding = "utf-8-sig" if original.startswith(b"\xef\xbb\xbf") else "utf-8"
    path.write_text(content, encoding=encoding, newline="\n")

def replace_once(content, old, new):
    assert content.count(old) == 1, old[:120]
    return content.replace(old, new, 1)

for relative in (
    "backend/core/units.py", "backend/services/policy_bridge.py", "scripts/normalize_origin.py",
    "backend/tests/test_policy_bridge.py", "backend/tests/test_normalize_origin.py",
):
    path = root / relative
    local = read(path)
    prefix = local[:local.index("from __future__ import annotations")]
    content = prefix + read(remote / relative)
    if relative == "backend/core/units.py":
        content = replace_once(content, "def pulse_to_ui(", "# 界面平移使用 μm、旋转使用 degree；LeRobot 旋转分量使用 0.001 degree，不能直接混用。\ndef pulse_to_ui(")
    write(path, content)

def method_map(content, class_name=None):
    parsed = ast.parse(content)
    nodes = parsed.body if class_name is None else next(node.body for node in parsed.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return {node.name: node for node in nodes if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}

def replace_methods(local, theirs, names, class_name=None):
    local_nodes = method_map(local, class_name)
    remote_nodes = method_map(theirs, class_name)
    local_lines, remote_lines = local.splitlines(keepends=True), theirs.splitlines(keepends=True)
    edits = []
    for name in names:
        node = remote_nodes[name]
        start = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
        replacement = "".join(remote_lines[start - 1:node.end_lineno])
        if name in local_nodes:
            current = local_nodes[name]
            current_start = min([current.lineno, *(decorator.lineno for decorator in current.decorator_list)])
            edits.append((current_start - 1, current.end_lineno, replacement))
        elif class_name:
            anchor = local_nodes["_open_native_dataset_for_read"].lineno - 1
            edits.append((anchor, anchor, replacement + "\n"))
        else:
            edits.append((len(local_lines), len(local_lines), "\n\n" + replacement))
    for start, end, replacement in sorted(edits, reverse=True):
        local_lines[start:end] = [replacement]
    return "".join(local_lines)

path = root / "backend/services/dataset_recorder.py"
local, theirs = read(path), read(remote / "backend/services/dataset_recorder.py")
local = replace_once(local, "from backend.core.config import SettingsService\n", "from backend.core.config import SettingsService\nfrom backend.core.data_contract import (\n    data_contract_metadata,\n    hardware_to_dataset_grippers,\n    hardware_to_dataset_motion,\n    hardware_to_dataset_state,\n    validate_data_contract,\n)\n")
local = replace_methods(local, theirs, ["assemble"], "FrameAssembler")
local = replace_methods(local, theirs, [
    "_compose_observation_state", "_latest_action_vector", "_write_appstation_info", "_force_metadata",
    "_open_native_dataset_for_writer", "_dataset_contract_error", "_require_dataset_contract",
    "dataset_stats", "episode_detail", "list_datasets", "_episode_samples", "_sample_force_source_sync",
], "DatasetRecorderService")
local = replace_once(local, "            await asyncio.to_thread(dataset_root.mkdir, parents=True, exist_ok=True)\n", "            await asyncio.to_thread(dataset_root.mkdir, parents=True, exist_ok=True)\n            contract_error = self._dataset_contract_error(dataset_dir)\n            if contract_error:\n                raise RuntimeError(contract_error)\n")
write(path, local)

path = root / "backend/tests/test_dataset_recorder.py"
local, theirs = read(path), read(remote / "backend/tests/test_dataset_recorder.py")
base = subprocess.check_output(["git", "show", "6d898c9:backend/tests/test_dataset_recorder.py"], cwd=root).decode("utf-8-sig")
base_nodes, remote_nodes, local_nodes = method_map(base), method_map(theirs), method_map(local)
changed = [name for name, node in remote_nodes.items() if name not in base_nodes or ast.dump(node, include_attributes=False) != ast.dump(base_nodes[name], include_attributes=False)]
for name in changed:
    if name in local_nodes and name in base_nodes:
        if ast.dump(local_nodes[name], include_attributes=False) != ast.dump(base_nodes[name], include_attributes=False):
            assert ast.dump(local_nodes[name], include_attributes=False) == ast.dump(remote_nodes[name], include_attributes=False), name
write(path, replace_methods(local, theirs, changed))
print("已整合共享数据契约、录制和对应测试；本地安全方法保持原样。")
