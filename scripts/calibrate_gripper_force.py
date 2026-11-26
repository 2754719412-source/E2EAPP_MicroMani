# 阅读导航 08｜启动、部署与工具
# 职责：钧舵夹爪夹持力标定——空载电流基线、参考测力计下 rFC→N 拟合、写入 gripper.forceCalibration。
# 先看：main → capture_baseline / capture_points → fit → apply；纯计算在 backend/core/gripper_force.py。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；操作步骤：docs/gripper-force-calibration.md。
"""夹爪夹持力标定。

现场流程（详见 docs/gripper-force-calibration.md）：
1. 停止 HAL/后端（串口独占），确认手指间无异物。
2. baseline：空载开合若干次，记录 gCU 基线和噪声。会让夹爪运动，必须加 --confirm-hardware-motion。
3. points：两指间夹参考测力计，按 rFC 升序再降序、每档重复，记录稳态 gCU 与测力计读数。
4. fit：拟合 rFC→N、稳态 gCU，输出残差/回差；apply：写入 config.json 的 gripper.forceCalibration。

闭合目标始终不小于 gripper.icfTargetMinGapMm（默认 1.02 mm），本脚本不会让两指互碰。
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.core.defaults import default_config  # noqa: E402
from backend.core.gripper_force import CalibrationError, fit_force_calibration, rfc_for_force_n  # noqa: E402
from backend.core.jodell_modbus import (  # noqa: E402
    GOBJ_ARRIVED_NO_OBJECT,
    GOBJ_CONTACT_CLOSING,
    GOBJ_MOVING,
    GripperStatus,
    move_request,
    move_response_length,
    parse_status_response,
    position_raw_for_gap_mm,
    read_status_request,
    status_response_length,
)

SESSION_FORMAT = "appstation.gripper_force_session.v1"
DEFAULT_RFC_SETTINGS = (20, 60, 100, 140, 180, 220, 255)


class Transport(Protocol):
    def write(self, data: bytes) -> int | None: ...
    def read(self, size: int) -> bytes: ...
    def reset_input_buffer(self) -> None: ...


class JodellModbusGripper:
    """停机标定用的最小 Modbus RTU 客户端；运行中的 HAL 占用串口时不能使用。"""

    def __init__(self, transport: Transport, slave_id: int, stroke_mm: float, min_gap_mm: float) -> None:
        self.transport = transport
        self.slave_id = int(slave_id)
        self.stroke_mm = float(stroke_mm)
        self.min_gap_mm = float(min_gap_mm)

    def _exchange(self, request: bytes, response_length: int) -> bytes:
        self.transport.reset_input_buffer()
        self.transport.write(request)
        response = self.transport.read(response_length)
        if len(response) != response_length:
            raise TimeoutError(f"slave {self.slave_id} 应答长度 {len(response)} != {response_length}")
        return response

    def status(self) -> GripperStatus:
        return parse_status_response(
            self._exchange(read_status_request(self.slave_id), status_response_length()), self.slave_id
        )

    def move_to_gap(self, gap_mm: float, speed_raw: int, force_raw: int) -> float:
        safe_gap = min(max(float(gap_mm), self.min_gap_mm), self.stroke_mm)
        response = self._exchange(
            move_request(self.slave_id, position_raw_for_gap_mm(safe_gap, self.stroke_mm), speed_raw, force_raw),
            move_response_length(),
        )
        if response[0] != self.slave_id or response[1] != 0x10:
            raise RuntimeError(f"写命令应答异常: {response.hex(' ')}")
        return safe_gap


def wait_motion(
    gripper: JodellModbusGripper,
    *,
    timeout_s: float,
    poll_s: float = 0.01,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """轮询到 gOBJ 离开“运动中”或超时，返回带时间戳的状态序列。"""
    samples: list[dict[str, Any]] = []
    started = clock()
    while True:
        status = gripper.status()
        samples.append({"t": round(clock() - started, 4), **status.as_dict()})
        if status.fault:
            raise RuntimeError(f"夹爪故障码 0x{status.fault:02X}")
        if status.gOBJ != GOBJ_MOVING:
            return samples
        if clock() - started > timeout_s:
            raise TimeoutError(f"{timeout_s}s 内未停止，最后状态 {status.as_dict()}")
        sleep(poll_s)


def hold_samples(
    gripper: JodellModbusGripper,
    *,
    duration_s: float,
    poll_s: float = 0.01,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    samples: list[dict[str, Any]] = []
    started = clock()
    while clock() - started < duration_s:
        samples.append({"t": round(clock() - started, 4), **gripper.status().as_dict()})
        sleep(poll_s)
    return samples


def capture_baseline(
    gripper: JodellModbusGripper,
    *,
    cycles: int,
    close_gap_mm: float,
    speed_raw: int,
    force_raw: int,
    timeout_s: float,
    **timing: Any,
) -> dict[str, Any]:
    """空载开合：只收运动中和到位（gOBJ=3）的电流；出现接触停止说明指间有物体，直接中止。"""
    trace: list[dict[str, Any]] = []
    for cycle in range(cycles):
        for phase, gap in (("close", close_gap_mm), ("open", gripper.stroke_mm)):
            commanded = gripper.move_to_gap(gap, speed_raw, force_raw)
            samples = wait_motion(gripper, timeout_s=timeout_s, **timing)
            if samples[-1]["gOBJ"] != GOBJ_ARRIVED_NO_OBJECT:
                raise RuntimeError(
                    f"空载第 {cycle} 次 {phase} 未到位（gOBJ={samples[-1]['gOBJ']}），检查指间是否有物体"
                )
            trace.extend({"cycle": cycle, "phase": phase, "commandedGapMm": commanded, **s} for s in samples)
    return {"forceRaw": force_raw, "speedRaw": speed_raw, "closeGapMm": close_gap_mm, "trace": trace}


def rfc_sequence(settings: list[int], repeats: int) -> list[tuple[int, str]]:
    ascending = sorted(set(settings))
    plan = [(rfc, "ascending") for rfc in ascending for _ in range(repeats)]
    plan += [(rfc, "descending") for rfc in reversed(ascending) for _ in range(repeats)]
    return plan


_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")


def parse_dynamometer_value(text: str, scale: float = 1.0) -> float:
    """取一行测力计输出中的最后一个数值（多数串口测力计格式为“  3.52 N”之类）。"""
    numbers = _NUMBER.findall(text)
    if not numbers:
        raise ValueError(f"测力计输出中没有数值: {text!r}")
    return float(numbers[-1]) * scale


def capture_point(
    gripper: JodellModbusGripper,
    *,
    rfc_raw: int,
    sequence: str,
    speed_raw: int,
    hold_s: float,
    timeout_s: float,
    read_reference_n: Callable[[], float],
    wait_ready: Callable[[str], None],
    **timing: Any,
) -> dict[str, Any]:
    gripper.move_to_gap(gripper.stroke_mm, speed_raw, rfc_raw)
    wait_motion(gripper, timeout_s=timeout_s, **timing)
    wait_ready(f"rFC={rfc_raw} ({sequence})：放好测力计后回车")
    gripper.move_to_gap(gripper.min_gap_mm, speed_raw, rfc_raw)
    closing = wait_motion(gripper, timeout_s=timeout_s, **timing)
    if closing[-1]["gOBJ"] != GOBJ_CONTACT_CLOSING:
        raise RuntimeError(f"rFC={rfc_raw} 未检测到夹持（gOBJ={closing[-1]['gOBJ']}），测力计是否夹在两指之间")
    hold = hold_samples(gripper, duration_s=hold_s, **timing)
    reference_n = float(read_reference_n())
    currents = [float(s["currentRaw"]) for s in hold]
    point = {
        "rfcRaw": rfc_raw,
        "sequence": sequence,
        "forceN": reference_n,
        "currentRaw": statistics.median(currents),
        "currentStdRaw": statistics.pstdev(currents),
        "contactGapMm": round(gripper.stroke_mm * (1 - hold[-1]["positionRaw"] / 255.0), 4),
        "closingTrace": closing,
        "holdTrace": hold,
    }
    gripper.move_to_gap(gripper.stroke_mm, speed_raw, rfc_raw)
    wait_motion(gripper, timeout_s=timeout_s, **timing)
    return point


def fit_session(session: dict[str, Any]) -> dict[str, Any]:
    if session.get("format") != SESSION_FORMAT:
        raise CalibrationError(f"不是标定会话文件: {session.get('format')!r}")
    baseline = session.get("baseline") or {}
    # 只用运动中的样本作基线：到位静止时电流接近 0，会把阈值压低。
    baseline_current = [s["currentRaw"] for s in baseline.get("trace", []) if s.get("gOBJ") == GOBJ_MOVING]
    return fit_force_calibration(
        session.get("points", []),
        baseline_current,
        port=str(session["port"]),
        slave_id=int(session["slaveId"]),
        reference=str(session.get("reference", "")),
    )


def format_report(calibration: dict[str, Any], targets_n: list[float]) -> str:
    fit = calibration["rfcToForceN"]
    base = calibration["baseline"]
    hold = calibration["holdCurrentRaw"]
    lines = [
        f"夹爪 {calibration['port']} / slave {calibration['slaveId']}",
        f"  rFC→N: N = {fit['slope']:.6f}·rFC + {fit['intercept']:.4f}"
        f"  (rFC {fit['rfcMin']:g}–{fit['rfcMax']:g}, {fit['points']} 点)",
        f"  残差 RMS {fit['rmsResidualN']:.4f} N, 最大 {fit['maxAbsResidualN']:.4f} N;"
        f" 重复差 {fit['repeatSpreadN']:.4f} N; 升降回差 {fit['hysteresisN']:.4f} N",
        f"  稳态 gCU = {hold['slope']:.4f}·rFC + {hold['intercept']:.3f}  (RMS {hold['rmsResidualRaw']:.3f})",
        f"  空载 gCU 均值 {base['currentMeanRaw']}, σ {base['currentStdRaw']}, 最大 {base['currentMaxRaw']},"
        f" 接触阈值 {base['contactThresholdRaw']}",
    ]
    for target in targets_n:
        inverse = rfc_for_force_n(calibration, target)
        note = ""
        if inverse["clampedHigh"]:
            note = " (超出标定上限，已截断)"
        elif inverse["extrapolatedLow"]:
            note = " (低于标定范围，外推)"
        lines.append(f"  {target:g} N → rFC {inverse['rfcRaw']} (预计 {inverse['expectedForceN']:.3f} N){note}")
    return "\n".join(lines)


def apply_calibration(config_path: Path, side: str, calibration: dict[str, Any], *, enable_limit: bool) -> Path:
    """写入 config.json 前先备份；须在后端停止时执行，否则可能被运行中的后端覆盖。"""
    config = json.loads(config_path.read_text(encoding="utf-8"))
    gripper = config.setdefault("gripper", {})
    port_key, slave_key = f"{side}Port", f"{side}SlaveId"
    expected = default_config()["gripper"]
    port = str(gripper.get(port_key, expected[port_key]))
    slave = int(gripper.get(slave_key, expected[slave_key]))
    if port.upper() != str(calibration["port"]).upper() or slave != int(calibration["slaveId"]):
        raise CalibrationError(
            f"{side} 侧配置为 {port}/slave {slave}，标定来自 {calibration['port']}/slave {calibration['slaveId']}"
        )
    store = gripper.get("forceCalibration")
    if not isinstance(store, dict):
        store = {"applyCommandForceLimit": False, "left": None, "right": None}
    store[side] = calibration
    if enable_limit:
        store["applyCommandForceLimit"] = True
    gripper["forceCalibration"] = store
    backup = config_path.with_name(f"{config_path.name}.bak-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(config_path, backup)
    tmp = config_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(config_path)
    return backup


def _load_session(path: Path, args: argparse.Namespace) -> dict[str, Any]:
    if path.exists():
        session = json.loads(path.read_text(encoding="utf-8"))
        if session.get("port") != args.port or int(session.get("slaveId", -1)) != args.slave:
            raise CalibrationError(f"{path} 属于 {session.get('port')}/slave {session.get('slaveId')}")
        return dict(session)
    return {"format": SESSION_FORMAT, "port": args.port, "slaveId": args.slave, "strokeMm": args.stroke_mm,
            "minGapMm": args.min_gap_mm, "reference": args.reference, "baseline": None, "points": []}


def _save_session(path: Path, session: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(session, ensure_ascii=False, indent=1), encoding="utf-8")


def _open_gripper(args: argparse.Namespace) -> tuple[Any, JodellModbusGripper]:
    import serial  # pyserial；仅现场采集需要

    port = serial.Serial(args.port, args.baudrate, bytesize=8, parity="N", stopbits=1, timeout=0.2)
    return port, JodellModbusGripper(port, args.slave, args.stroke_mm, args.min_gap_mm)


def _reference_reader(args: argparse.Namespace) -> tuple[Callable[[], float], Any]:
    if not args.dynamometer_port:
        def manual() -> float:
            return parse_dynamometer_value(input("输入测力计读数 (N): "), args.dynamometer_scale)
        return manual, None
    import serial

    meter = serial.Serial(args.dynamometer_port, args.dynamometer_baudrate, timeout=1.0)

    def automatic() -> float:
        meter.reset_input_buffer()
        line = meter.readline().decode("ascii", errors="replace")
        line = meter.readline().decode("ascii", errors="replace") or line  # 丢弃可能不完整的首行
        value = parse_dynamometer_value(line, args.dynamometer_scale)
        print(f"  测力计: {value:.4f} N  ({line.strip()!r})")
        return value
    return automatic, meter


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    defaults = default_config()["gripper"]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("baseline", "points"):
        live = sub.add_parser(name)
        live.add_argument("--session", type=Path, required=True)
        live.add_argument("--port", required=True, help="夹爪串口，如 COM8（须与 config 中该侧一致）")
        live.add_argument("--slave", type=int, required=True)
        live.add_argument("--baudrate", type=int, default=int(defaults["baudrate"]))
        live.add_argument("--stroke-mm", type=float, default=float(defaults["strokeMm"]))
        live.add_argument("--min-gap-mm", type=float, default=float(defaults["icfTargetMinGapMm"]))
        live.add_argument("--speed-raw", type=int, default=64)
        live.add_argument("--timeout-s", type=float, default=5.0)
        live.add_argument("--reference", default="", help="测力计型号/编号，写入标定结果")
        live.add_argument("--confirm-hardware-motion", action="store_true",
                          help="确认已停止 HAL/后端、指间无异物，允许脚本驱动夹爪运动")
    baseline = sub.choices["baseline"]
    baseline.add_argument("--cycles", type=int, default=5)
    baseline.add_argument("--close-gap-mm", type=float, default=6.0, help="空载闭合目标，不小于最小开度")
    baseline.add_argument("--force-raw", type=int, default=255)
    points = sub.choices["points"]
    points.add_argument("--rfc", type=int, nargs="+", default=list(DEFAULT_RFC_SETTINGS))
    points.add_argument("--repeats", type=int, default=2)
    points.add_argument("--hold-s", type=float, default=1.0)
    points.add_argument("--dynamometer-port", default="", help="测力计串口；留空则手动输入读数")
    points.add_argument("--dynamometer-baudrate", type=int, default=9600)
    points.add_argument("--dynamometer-scale", type=float, default=1.0, help="读数换算到 N 的系数（kgf 用 9.80665）")
    fit = sub.add_parser("fit")
    fit.add_argument("--session", type=Path, required=True)
    fit.add_argument("--output", type=Path, required=True)
    fit.add_argument("--report-force-n", type=float, nargs="*", default=[2.0, 4.0, 6.0, 8.0])
    apply = sub.add_parser("apply")
    apply.add_argument("--calibration", type=Path, required=True)
    apply.add_argument("--config", type=Path, required=True, help="后端运行目录下的 config.json（先停止后端）")
    apply.add_argument("--side", choices=("left", "right"), required=True, help="硬件侧")
    apply.add_argument("--enable-force-limit", action="store_true",
                       help="同时开启 applyCommandForceLimit，让 commandForceLimitN 决定下发的 rFC")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "fit":
        calibration = fit_session(json.loads(args.session.read_text(encoding="utf-8")))
        args.output.write_text(json.dumps(calibration, ensure_ascii=False, indent=2), encoding="utf-8")
        print(format_report(calibration, args.report_force_n))
        return 0
    if args.command == "apply":
        calibration = json.loads(args.calibration.read_text(encoding="utf-8"))
        backup = apply_calibration(args.config, args.side, calibration, enable_limit=args.enable_force_limit)
        print(f"已写入 {args.config}（备份 {backup}）")
        return 0
    if not args.confirm_hardware_motion:
        print("该步骤会驱动夹爪运动：先停止 HAL/后端并确认指间无异物，再加 --confirm-hardware-motion。")
        return 2
    session = _load_session(args.session, args)
    serial_port, gripper = _open_gripper(args)
    meter = None
    try:
        if args.command == "baseline":
            session["baseline"] = capture_baseline(
                gripper, cycles=args.cycles, close_gap_mm=args.close_gap_mm,
                speed_raw=args.speed_raw, force_raw=args.force_raw, timeout_s=args.timeout_s,
            )
            _save_session(args.session, session)
            print(f"基线样本 {len(session['baseline']['trace'])} 条已写入 {args.session}")
            return 0
        reader, meter = _reference_reader(args)
        for rfc, sequence in rfc_sequence(args.rfc, args.repeats):
            point = capture_point(
                gripper, rfc_raw=rfc, sequence=sequence, speed_raw=args.speed_raw, hold_s=args.hold_s,
                timeout_s=args.timeout_s, read_reference_n=reader, wait_ready=lambda text: input(text),
            )
            session["points"].append(point)
            _save_session(args.session, session)  # 每点落盘，中断后可续采
            print(f"  rFC={rfc} {sequence}: gCU={point['currentRaw']:.1f}, 参考力 {point['forceN']:.4f} N")
        return 0
    finally:
        if meter is not None:
            meter.close()
        serial_port.close()


if __name__ == "__main__":
    raise SystemExit(main())
