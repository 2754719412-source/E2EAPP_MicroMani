"""Compare current source with the pre-integration snapshot; never modify source."""
from __future__ import annotations

import difflib
import hashlib
import json
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
before = json.loads((OUT / "before-manifest.json").read_text(encoding="utf-8"))

def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

current = set(before)
listed = subprocess.check_output(
    ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT,
).decode("utf-8").split("\0")
for name in listed:
    if not name or name.startswith(("output/", "frontend/output/", "paper/", "codex-provider-sync/")):
        continue
    if any(part in {"node_modules", ".venv", "vendor", "dist", "build", "__pycache__"} for part in Path(name).parts):
        continue
    current.add(name)

changes = []
patch = []
with zipfile.ZipFile(OUT / "before-integration.zip") as archive:
    for name in sorted(current):
        prior = archive.read(name) if name in before else None
        path = ROOT / name
        after = path.read_bytes() if path.is_file() else None
        if prior is not None:
            assert digest(prior) == before[name], f"Snapshot hash mismatch: {name}"
        if prior == after:
            continue
        changes.append({
            "path": name,
            "status": "added" if prior is None else "deleted" if after is None else "modified",
            "before_sha256": digest(prior) if prior is not None else None,
            "after_sha256": digest(after) if after is not None else None,
        })
        old_lines = prior.decode("utf-8").replace("\r\n", "\n").splitlines(keepends=True) if prior is not None else []
        new_lines = after.decode("utf-8").replace("\r\n", "\n").splitlines(keepends=True) if after is not None else []
        patch.append(f"diff --git a/{name} b/{name}\n")
        if prior is None:
            patch.append("new file mode 100644\n")
        elif after is None:
            patch.append("deleted file mode 100644\n")
        patch.extend(difflib.unified_diff(
            old_lines, new_lines,
            fromfile=f"a/{name}" if prior is not None else "/dev/null",
            tofile=f"b/{name}" if after is not None else "/dev/null",
        ))

protected = [
    "backend/runtime/config.json", "backend/core/defaults.py", "backend/core/motion_safety.py",
    "backend/services/control_watchdog.py", "backend/services/command_service.py",
    "frontend/src/data.ts", "frontend/src/stores/telemetry.ts", "frontend/src/main.tsx",
    "hal/src/ForceControlRuntime.cpp", "hal/src/HkvlForceDriver.cpp", "hal/src/HalCommandDispatcher.cpp",
    "hal/include/ControlLeaseState.h", "hal/include/EmergencyStopState.h",
    "scripts/start-hal.ps1", "scripts/start-ui.ps1", "scripts/launch-app.ps1", "scripts/stop-stack.ps1",
]
checks = {name: digest((ROOT / name).read_bytes()) == before[name] for name in protected}
assert all(checks.values()), checks
manifest = {
    "base": json.loads((OUT / "integration-context.json").read_text(encoding="utf-8")),
    "changed_files": len(changes),
    "changes": changes,
    "protected_files_unchanged": checks,
    "note": "Patch normalizes line endings for review; ZIP preserves original bytes for restoration. No source was restored or deleted.",
}
(OUT / "integration-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
(OUT / "integration.patch").write_text("".join(patch), encoding="utf-8", newline="\n")
print(json.dumps({"changed_files": len(changes), "statuses": {
    status: sum(entry["status"] == status for entry in changes) for status in ("modified", "added", "deleted")
}, "protected_files_unchanged": len(checks)}, ensure_ascii=False))
