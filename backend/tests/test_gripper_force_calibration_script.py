# 阅读导航 07｜测试与验证
# 职责：回归验证：夹持力标定脚本用模拟 Modbus 夹爪跑通基线、测力点、拟合和写配置，且闭合不低于最小开度。
# 先看：FakeJodell → test_live_flow_never_commands_below_min_gap_and_fits → test_baseline_aborts_when_something_is_between_fingers。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。

"""夹持力标定脚本的离线回归：用模拟 Modbus 夹爪跑完 baseline → points → fit → apply。"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from backend.core.defaults import default_config
from backend.core.jodell_modbus import with_crc

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "calibrate_gripper_force.py"


@pytest.fixture(scope="module")
def script() -> Any:
    spec = importlib.util.spec_from_file_location("calibrate_gripper_force", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakeJodell:
    """按手册寄存器布局应答的模拟夹爪；obstacle_raw 为测力计所在的位置原码。"""

    def __init__(self, slave_id: int = 10, obstacle_raw: int | None = None) -> None:
        self.slave_id = slave_id
        self.position = 0
        self.target = 0
        self.force = 1
        self.obstacle_raw = obstacle_raw
        self.response = b""
        self.commanded_targets: list[int] = []

    def reset_input_buffer(self) -> None:
        self.response = b""

    def write(self, data: bytes) -> int:
        if data[1] == 0x10:
            self.target, self.force = data[9], data[11]
            self.commanded_targets.append(self.target)
            self.response = with_crc(bytes((self.slave_id, 0x10, 0x03, 0xE8, 0x00, 0x03)))
        else:
            self.response = self._status()
        return len(data)

    def read(self, size: int) -> bytes:
        response, self.response = self.response[:size], b""
        return response

    def _status(self) -> bytes:
        step = 40
        limit = self.target
        blocked = self.obstacle_raw is not None and self.target > self.obstacle_raw
        if blocked:
            limit = self.obstacle_raw
        if self.position < limit:
            self.position = min(limit, self.position + step)
        elif self.position > limit:
            self.position = max(limit, self.position - step)
        if self.position != limit:
            gobj, current = 0, 3 + self.position % 2
        elif blocked:
            gobj, current = 2, min(254, self.force)
        else:
            gobj, current = 3, 0
        status_low = 0x01 | 0x08 | (0x3 << 4) | (gobj << 6)
        body = bytes((self.slave_id, 0x04, 6, 0x00, status_low, self.position, 0x00, current, 0x00))
        return with_crc(body)


def _gripper(script: Any, fake: FakeJodell) -> Any:
    return script.JodellModbusGripper(fake, fake.slave_id, stroke_mm=26.0, min_gap_mm=1.02)


def _no_sleep() -> dict[str, Any]:
    ticks = iter(range(10**9))
    return {"clock": lambda: next(ticks) * 0.01, "sleep": lambda _s: None}


def test_live_flow_never_commands_below_min_gap_and_fits(script: Any, tmp_path: Path) -> None:
    fake = FakeJodell(obstacle_raw=200)  # 测力计约 5.6 mm 宽
    gripper = _gripper(script, fake)
    # 基线必须空载：用没有障碍物的夹爪采；close_gap_mm=0 也会被钳到最小开度。
    fake_free = FakeJodell()
    baseline = script.capture_baseline(
        _gripper(script, fake_free), cycles=3, close_gap_mm=0.0, speed_raw=64, force_raw=255, timeout_s=5.0,
        **_no_sleep(),
    )
    min_gap_raw = round((26 - 1.02) / 26 * 255)
    assert max(fake_free.commanded_targets) == min_gap_raw

    readings = iter([0.02 * rfc + 1.5 for rfc, _ in script.rfc_sequence([40, 120, 200], 2)])
    points = [
        script.capture_point(
            gripper, rfc_raw=rfc, sequence=sequence, speed_raw=64, hold_s=0.05, timeout_s=5.0,
            read_reference_n=lambda: next(readings), wait_ready=lambda _text: None, **_no_sleep(),
        )
        for rfc, sequence in script.rfc_sequence([40, 120, 200], 2)
    ]
    assert max(fake.commanded_targets) == min_gap_raw
    assert [p["currentRaw"] for p in points[:2]] == [40, 40]
    assert points[0]["contactGapMm"] == pytest.approx(26 * (1 - 200 / 255), abs=1e-3)

    session = {
        "format": script.SESSION_FORMAT, "port": "COM8", "slaveId": 10, "reference": "unit",
        "baseline": baseline, "points": points,
    }
    calibration = script.fit_session(session)
    assert calibration["rfcToForceN"]["slope"] == pytest.approx(0.02)
    assert calibration["baseline"]["currentMaxRaw"] == 4
    assert "rFC" in script.format_report(calibration, [3.0, 10.0])

    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(default_config()), encoding="utf-8")
    backup = script.apply_calibration(config_path, "left", calibration, enable_limit=False)
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert backup.exists()
    assert saved["gripper"]["forceCalibration"]["left"]["slaveId"] == 10
    assert saved["gripper"]["forceCalibration"]["applyCommandForceLimit"] is False
    with pytest.raises(script.CalibrationError, match="right"):
        script.apply_calibration(config_path, "right", calibration, enable_limit=True)


def test_baseline_aborts_when_something_is_between_fingers(script: Any) -> None:
    gripper = _gripper(script, FakeJodell(obstacle_raw=150))
    with pytest.raises(RuntimeError, match="指间是否有物体"):
        script.capture_baseline(
            gripper, cycles=1, close_gap_mm=1.02, speed_raw=64, force_raw=255, timeout_s=5.0, **_no_sleep()
        )


def test_point_requires_object_detection(script: Any) -> None:
    gripper = _gripper(script, FakeJodell())
    with pytest.raises(RuntimeError, match="未检测到夹持"):
        script.capture_point(
            gripper, rfc_raw=60, sequence="ascending", speed_raw=64, hold_s=0.05, timeout_s=5.0,
            read_reference_n=lambda: 1.0, wait_ready=lambda _text: None, **_no_sleep(),
        )


def test_live_commands_require_explicit_confirmation(script: Any, tmp_path: Path, capsys: Any) -> None:
    code = script.main(["baseline", "--session", str(tmp_path / "s.json"), "--port", "COM8", "--slave", "10"])
    assert code == 2
    assert "--confirm-hardware-motion" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("text", "scale", "expected"), [("  3.52 N\r\n", 1.0, 3.52), ("ST,GS,+0.250kg", 9.80665, 2.4516625)]
)
def test_dynamometer_line_parsing(script: Any, text: str, scale: float, expected: float) -> None:
    assert script.parse_dynamometer_value(text, scale) == pytest.approx(expected)
