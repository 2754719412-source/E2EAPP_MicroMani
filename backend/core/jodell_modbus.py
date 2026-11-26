# 阅读导航 03｜后端契约与配置
# 职责：钧舵 EPG 夹爪 Modbus RTU 帧编解码（CRC、读状态、写运动命令、gOBJ/gCU 解析），不含串口 I/O。
# 先看：read_status_request → move_request → parse_status_response → position_raw_for_gap_mm。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。

"""钧舵 EPG 夹爪 Modbus RTU 帧编解码（不含串口 I/O）。

依据 docs/hardware/jodell/EPG-series-C0-C7-A.1.pdf：
- 控制寄存器首址 0x03E8：低字节 rACT/rMODE/rGTO，0x03E9 高字节 rPR，0x03EA 低字节 rSP、高字节 rFC。
- 状态寄存器首址 0x07D0：低字节 gACT/gMODE/gGTO/gSTA/gOBJ，0x07D1 低字节故障、高字节 gPR，
  0x07D2 低字节速度、高字节 gCU（电机电流标幺值，手册无换算公式）。
仅供离线解析和停机标定脚本使用；运行中的 HAL 独占串口，不能与本模块混用同一端口。
"""

from __future__ import annotations

from dataclasses import dataclass

CONTROL_REGISTER = 0x03E8
STATUS_REGISTER = 0x07D0
STATUS_REGISTER_COUNT = 3
READ_INPUT_REGISTERS = 0x04
WRITE_MULTIPLE_REGISTERS = 0x10

GOBJ_MOVING = 0
GOBJ_CONTACT_OPENING = 1
GOBJ_CONTACT_CLOSING = 2
GOBJ_ARRIVED_NO_OBJECT = 3


def crc16_modbus(data: bytes) -> int:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def with_crc(body: bytes) -> bytes:
    crc = crc16_modbus(body)
    return body + bytes((crc & 0xFF, crc >> 8))


def check_crc(frame: bytes) -> bool:
    return len(frame) >= 4 and crc16_modbus(frame[:-2]) == frame[-2] | (frame[-1] << 8)


def _byte(name: str, value: int) -> int:
    if not 0 <= int(value) <= 255:
        raise ValueError(f"{name} must be 0..255, got {value}")
    return int(value)


def read_status_request(slave_id: int) -> bytes:
    """功能码 0x04 一次读 0x07D0 起 3 个寄存器（状态、故障+位置、速度+电流）。"""
    return with_crc(bytes((
        _byte("slave_id", slave_id), READ_INPUT_REGISTERS,
        STATUS_REGISTER >> 8, STATUS_REGISTER & 0xFF, 0, STATUS_REGISTER_COUNT,
    )))


def move_request(slave_id: int, position_raw: int, speed_raw: int, force_raw: int) -> bytes:
    """功能码 0x10 写 0x03E8–0x03EA：rACT=1、rGTO=1、参数模式，按 rPR/rSP/rFC 运动。"""
    return with_crc(bytes((
        _byte("slave_id", slave_id), WRITE_MULTIPLE_REGISTERS,
        CONTROL_REGISTER >> 8, CONTROL_REGISTER & 0xFF, 0, 3, 6,
        0x00, 0x09,
        _byte("position_raw", position_raw), 0x00,
        _byte("force_raw", force_raw), _byte("speed_raw", speed_raw),
    )))


def move_response_length() -> int:
    return 8


def status_response_length() -> int:
    return 5 + STATUS_REGISTER_COUNT * 2


@dataclass(frozen=True)
class GripperStatus:
    gACT: int
    gMODE: int
    gGTO: int
    gSTA: int
    gOBJ: int
    fault: int
    position_raw: int
    speed_raw: int
    current_raw: int

    def as_dict(self) -> dict[str, int]:
        return {
            "gACT": self.gACT, "gMODE": self.gMODE, "gGTO": self.gGTO, "gSTA": self.gSTA,
            "gOBJ": self.gOBJ, "fault": self.fault, "positionRaw": self.position_raw,
            "speedRaw": self.speed_raw, "currentRaw": self.current_raw,
        }


def parse_status_response(frame: bytes, slave_id: int) -> GripperStatus:
    if len(frame) != status_response_length():
        raise ValueError(f"status response length {len(frame)} != {status_response_length()}")
    if not check_crc(frame):
        raise ValueError("status response CRC mismatch")
    if frame[0] != slave_id or frame[1] != READ_INPUT_REGISTERS or frame[2] != STATUS_REGISTER_COUNT * 2:
        raise ValueError(f"unexpected status response header {frame[:3].hex(' ')}")
    status_low = frame[4]
    return GripperStatus(
        gACT=status_low & 0x01,
        gMODE=(status_low >> 2) & 0x01,
        gGTO=(status_low >> 3) & 0x01,
        gSTA=(status_low >> 4) & 0x03,
        gOBJ=(status_low >> 6) & 0x03,
        fault=frame[6],
        position_raw=frame[5],
        speed_raw=frame[8],
        current_raw=frame[7],
    )


def position_raw_for_gap_mm(gap_mm: float, stroke_mm: float) -> int:
    """与 HAL/后端换算一致：gap = stroke × (1 − raw/255)。"""
    ratio = min(max(1.0 - float(gap_mm) / float(stroke_mm), 0.0), 1.0)
    return int(round(ratio * 255.0))


def gap_mm_for_position_raw(position_raw: int, stroke_mm: float) -> float:
    return float(stroke_mm) * (1.0 - int(position_raw) / 255.0)
