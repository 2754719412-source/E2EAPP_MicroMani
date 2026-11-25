# 阅读导航 03｜后端契约与配置
# 职责：从逐帧夹爪开口、命令开口、gOBJ 与 gCU 中检测抓取/接触片段，供挑选数据和录制前空载检查使用。
# 先看：ContactFrame → detect_contact_events → idle_current_check。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。
"""夹爪接触片段检测（纯函数，不访问硬件）。

接触判据：实测开口停在最小开度之上（两指没有互碰），命令开口比实测更小（仍在往里夹），
并且 gOBJ=2（手册：闭合时碰到物体停止）或 gCU 越过空载阈值。手册说明物体过细时 gOBJ 可能检测不到，
所以电流是并列证据；两者都缺时只用位置判据，并在 evidence 中标明，不能当作力测量。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from backend.core.jodell_modbus import GOBJ_CONTACT_CLOSING

# 命令开口至少比实测小这么多才算“仍在闭合”，避免把到位后的编码器抖动当成夹持。
CLOSING_MARGIN_MM = 0.3
# 实测开口高于最小开度这么多才算两指分离；低于它可能是指尖互碰而不是夹物。
FINGER_SEPARATION_MARGIN_MM = 0.2
# 条件连续不成立这么多帧才结束片段，避免单帧丢样把一次抓取拆成两段。
RELEASE_DEBOUNCE_FRAMES = 3


@dataclass(frozen=True)
class ContactFrame:
    gap_mm: float
    commanded_gap_mm: float | None
    gobj: int | None = None
    current_raw: float | None = None


def frame_evidence(
    frame: ContactFrame, *, min_gap_mm: float, current_threshold_raw: float | None
) -> str | None:
    """单帧是否处于接触状态；返回证据类型，不接触时返回 None。"""
    commanded, current = frame.commanded_gap_mm, frame.current_raw
    if not math.isfinite(frame.gap_mm) or commanded is None or not math.isfinite(commanded):
        return None
    if frame.gap_mm <= min_gap_mm + FINGER_SEPARATION_MARGIN_MM:
        return None
    if commanded > frame.gap_mm - CLOSING_MARGIN_MM:
        return None
    if frame.gobj == GOBJ_CONTACT_CLOSING:
        return "gobj"
    if current_threshold_raw is not None and current is not None and math.isfinite(current):
        return "current" if current > current_threshold_raw else None
    if frame.gobj is None and frame.current_raw is None:
        return "position_only"
    return None


def detect_contact_events(
    frames: Sequence[ContactFrame],
    *,
    min_gap_mm: float,
    current_threshold_raw: float | None = None,
    fps: float | None = None,
    debounce_frames: int = RELEASE_DEBOUNCE_FRAMES,
) -> list[dict[str, Any]]:
    """返回接触片段列表：起止帧（含）、证据类型、最小开口、峰值电流。"""
    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    misses = 0
    for index, frame in enumerate(frames):
        evidence = frame_evidence(frame, min_gap_mm=min_gap_mm, current_threshold_raw=current_threshold_raw)
        if evidence is None:
            if current is not None:
                misses += 1
                if misses >= debounce_frames:
                    events.append(current)
                    current = None
            continue
        misses = 0
        if current is None:
            current = {"startFrame": index, "endFrame": index, "evidence": set(), "minGapMm": frame.gap_mm,
                       "peakCurrentRaw": None, "peakCurrentFrame": None}
        current["endFrame"] = index
        current["evidence"].add(evidence)
        current["minGapMm"] = min(current["minGapMm"], frame.gap_mm)
        value = frame.current_raw
        if value is not None and math.isfinite(value) and (
            current["peakCurrentRaw"] is None or value > current["peakCurrentRaw"]
        ):
            current["peakCurrentRaw"] = float(value)
            current["peakCurrentFrame"] = index
    if current is not None:
        events.append(current)
    for event in events:
        event["evidence"] = sorted(event["evidence"])
        event["frames"] = event["endFrame"] - event["startFrame"] + 1
        if fps:
            event["startS"] = round(event["startFrame"] / fps, 6)
            event["durationS"] = round(event["frames"] / fps, 6)
    return events


def idle_current_check(
    current_raw: Iterable[float | None], *, threshold_raw: float, min_samples: int = 5
) -> dict[str, Any]:
    """录制开始前的空载检查：近期 gCU 全部有效且不超过标定阈值才通过。"""
    values = list(current_raw)
    valid = [float(v) for v in values if v is not None and math.isfinite(v)]
    if len(valid) < min_samples or len(valid) != len(values):
        return {"ok": False, "reason": f"夹爪电流样本不足或无效 ({len(valid)}/{len(values)})"}
    peak = max(valid)
    if peak > threshold_raw:
        return {"ok": False, "reason": f"夹爪电流 {peak:g} 高于空载阈值 {threshold_raw:g}，两指间可能有接触",
                "peakCurrentRaw": peak}
    return {"ok": True, "reason": "", "peakCurrentRaw": peak}
