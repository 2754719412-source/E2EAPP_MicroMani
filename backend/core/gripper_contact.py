# 阅读导航 03｜后端契约与配置
# 职责：从逐帧夹爪开口、命令开口、gOBJ 与 gCU 中检测抓取/接触片段，供挑选数据和录制前空载检查使用。
# 先看：ContactFrame → detect_contact_events → idle_current_check。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。
"""夹爪接触片段检测（纯函数，不访问硬件）。

接触判据：实测开口停在最小开度之上（两指没有互碰），命令开口比实测更小（仍在往里夹），
并且 gOBJ=2（手册：闭合时碰到物体停止）或 gCU 越过空载阈值。手册 6.3.1 说明 gGTO=0 时 gOBJ 无效，
因此只在 gGTO=1 时采用 gOBJ；物体过细时 gOBJ 也可能检测不到，所以电流是并列证据。
两者都无法判断时只用位置判据，片段标为候选（candidate），不能当作力测量。
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
# 只有位置证据时还要求开口已停住（与上一读数相差不超过此值），否则正常闭合过程也会被误判为接触。
POSITION_STALL_TOLERANCE_MM = 0.05
# 条件连续不成立这么多帧才结束片段，避免单帧丢样把一次抓取拆成两段。
RELEASE_DEBOUNCE_FRAMES = 3


@dataclass(frozen=True)
class ContactFrame:
    gap_mm: float
    commanded_gap_mm: float | None
    gobj: int | None = None
    current_raw: float | None = None
    # gGTO=1 表示正在执行到位命令；None 表示状态不可用。只有为 True 时 gOBJ 才可信。
    gripper_moving: bool | None = None


def frame_evidence(
    frame: ContactFrame, *, min_gap_mm: float, current_threshold_raw: float | None, stalled: bool = True
) -> str | None:
    """单帧是否处于接触状态；返回证据类型，不接触时返回 None。"""
    commanded, current = frame.commanded_gap_mm, frame.current_raw
    if not math.isfinite(frame.gap_mm) or commanded is None or not math.isfinite(commanded):
        return None
    if frame.gap_mm <= min_gap_mm + FINGER_SEPARATION_MARGIN_MM:
        return None
    if commanded > frame.gap_mm - CLOSING_MARGIN_MM:
        return None
    gobj_usable = frame.gobj is not None and frame.gripper_moving is True
    if gobj_usable and frame.gobj == GOBJ_CONTACT_CLOSING:
        return "gobj"
    current_usable = current_threshold_raw is not None and current is not None and math.isfinite(current)
    if current_usable:
        assert current is not None and current_threshold_raw is not None
        if current > current_threshold_raw:
            return "current"
        return None
    if gobj_usable:
        # 状态有效且没有报告接触，又没有电流阈值可判断：不推断接触。
        return None
    return "position_only" if stalled else None


def frame_evidences(
    frames: Sequence[ContactFrame], *, min_gap_mm: float, current_threshold_raw: float | None = None
) -> list[str | None]:
    """逐帧证据（含“开口是否已停住”的判断）；检测片段与裁剪后重算证据共用同一套判据。"""
    evidences: list[str | None] = []
    previous_gap: float | None = None
    for frame in frames:
        stalled = (previous_gap is not None and math.isfinite(frame.gap_mm)
                   and abs(frame.gap_mm - previous_gap) <= POSITION_STALL_TOLERANCE_MM)
        previous_gap = frame.gap_mm if math.isfinite(frame.gap_mm) else previous_gap
        evidences.append(frame_evidence(
            frame, min_gap_mm=min_gap_mm, current_threshold_raw=current_threshold_raw, stalled=stalled))
    return evidences


def evidence_summary(evidences: Iterable[str | None]) -> tuple[list[str], bool]:
    """片段证据列表与候选标志：只有位置证据的片段保留为候选，供人工复核，不计为确认接触。"""
    kinds = sorted({evidence for evidence in evidences if evidence is not None})
    return kinds, kinds == ["position_only"]


def detect_contact_events(
    frames: Sequence[ContactFrame],
    *,
    min_gap_mm: float,
    current_threshold_raw: float | None = None,
    fps: float | None = None,
    debounce_frames: int = RELEASE_DEBOUNCE_FRAMES,
    sample_limit: int | None = None,
) -> list[dict[str, Any]]:
    """检测前 sample_limit 条读数内的接触；窗口外的读数仅用于标记片段是否被裁剪。"""
    events: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    misses = 0
    limit = len(frames) if sample_limit is None else sample_limit
    evidences = frame_evidences(frames[:limit + debounce_frames], min_gap_mm=min_gap_mm,
                                current_threshold_raw=current_threshold_raw)
    for index, evidence in enumerate(evidences[:limit]):
        frame = frames[index]
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
        if sample_limit is not None:
            # 录像外只检查已有接触是否在去抖窗口内延续，不能延长录像内片段或改变其证据。
            current["clippedToLastFrame"] = any(evidences[limit:limit + debounce_frames - misses])
        events.append(current)
    for event in events:
        event["evidence"], event["candidate"] = evidence_summary(event["evidence"])
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
