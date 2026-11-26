# 阅读导航 04｜后端业务与采集
# 职责：从 HAL 夹爪样本历史按 seq 去重收集真实读数，提供帧对齐、录制前空载放行检查、episode 统计、接触片段和旁路文件行。
# 先看：parse_sample_history → GripperRawCollector.ingest → nearest → idle_start_blocker → episode_rows / contact_events。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。
"""夹爪原始读数收集。

HAL 每次成功读到夹爪就分配每侧递增的 seq，并保留最近一段历史。录制采样线程用只读命令 gripper.samples 按
seq 增量拉取（DDS 遥测缓存只带最新样本）：seq 不大于已见最大值的行是重复，seq 跳号说明 HAL 历史已经滚动
覆盖、样本确实丢失，计入 missedSeq。seq 只在同一 HAL 实例内单调；实例 ID 变化（HAL 重启）时清空已见序号，
并在当前 episode 记一次中断。训练帧可以按 30/60 fps 多次引用同一读数，但旁路文件每个 seq 只写一行。
侧别一律是硬件侧；写入数据集 feature 时再按数据契约换成操作者侧顺序。
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from threading import Lock
from typing import Any

from backend.core.gripper_contact import ContactFrame, detect_contact_events
from backend.core.jodell_modbus import GOBJ_CONTACT_CLOSING, GOBJ_CONTACT_OPENING, gap_mm_for_position_raw

GRIPPER_SAMPLE_HISTORY_FORMAT = "seq_monotonicUs_halTs_pv_sv_cv_pos_cur_act_gto_sta_obj_fault_v1"
HARDWARE_SIDES = ("left", "right")
# 录制开始前只保留最近一段读数，供空载检查和第 0 帧对齐。
IDLE_RETENTION_S = 2.0
# 空载放行：最近这段时间内的连续读数都必须有效、无故障、无接触且电流不超过阈值。
IDLE_WINDOW_S = 0.3
IDLE_MIN_SAMPLES = 5
IDLE_MAX_AGE_S = 0.25
# 接触片段只在连续观测内成立：seq 跳号、HAL 重启或相邻读数间隔超过该值都会切断片段。
CONTACT_MAX_GAP_S = 0.25


@dataclass(frozen=True)
class GripperRawSample:
    side: str
    seq: int
    monotonic_s: float
    hal_timestamp: bool
    position_valid: bool
    status_valid: bool
    current_valid: bool
    position_raw: int
    current_raw: int
    gACT: int
    gGTO: int
    gSTA: int
    gOBJ: int
    fault: int


def parse_sample_history(native_status: Any) -> dict[str, list[GripperRawSample]]:
    """解析 HAL gripperSampleHistory；格式不认识时返回空，不猜测字段含义。"""
    if not isinstance(native_status, Mapping):
        return {}
    if native_status.get("gripperSampleHistoryFormat") != GRIPPER_SAMPLE_HISTORY_FORMAT:
        return {}
    history = native_status.get("gripperSampleHistory")
    if not isinstance(history, Mapping):
        return {}
    parsed: dict[str, list[GripperRawSample]] = {}
    for side in HARDWARE_SIDES:
        rows = history.get(side)
        if not isinstance(rows, list):
            continue
        samples: list[GripperRawSample] = []
        for row in rows:
            if not isinstance(row, list) or len(row) != 13:
                continue
            try:
                values = [int(value) for value in row]
            except (TypeError, ValueError):
                continue
            seq, monotonic_us, hal_ts, pv, sv, cv, pos, cur, act, gto, sta, obj, fault = values
            if seq <= 0 or monotonic_us <= 0:
                continue
            samples.append(GripperRawSample(
                side, seq, monotonic_us / 1_000_000.0, hal_ts == 1, pv == 1, sv == 1,
                cv == 1 and 0 <= cur <= 255, pos, cur, act, gto, sta, obj, fault))
        parsed[side] = sorted(samples, key=lambda sample: sample.seq)
    return parsed


def history_reply_error(reply: Any, *, request: Mapping[str, Any] | None = None) -> str:
    """校验 gripper.samples 应答结构；空增量（各侧空列表）合法，格式不认识或行结构不对返回错误原因。

    parse_sample_history 会静默跳过坏行，不能用“解析出 0 条”判断应答是否可用。
    """
    if not isinstance(reply, Mapping):
        return "reply is not an object"
    if reply.get("gripperSampleHistoryFormat") != GRIPPER_SAMPLE_HISTORY_FORMAT:
        return f"unknown history format: {reply.get('gripperSampleHistoryFormat')!r}"
    history = reply.get("gripperSampleHistory")
    if not isinstance(history, Mapping):
        return "gripperSampleHistory missing"
    instance = reply.get("gripperSampleInstanceId")
    latest = reply.get("latestSeq")
    if request is not None and (
        not isinstance(instance, str) or not instance.strip()
        or not isinstance(latest, list) or len(latest) != 2
        or not all(type(seq) is int and seq >= 0 for seq in latest)
    ):
        return "invalid gripper.samples cursor"
    for index, side in enumerate(HARDWARE_SIDES):
        rows = history.get(side)
        if not isinstance(rows, list):
            return f"{side} history is not a list"
        for row in rows:
            if (not isinstance(row, list) or len(row) != 13 or not all(type(value) is int for value in row)
                    or row[0] <= 0 or row[1] <= 0):
                return f"{side} history row malformed"
        if request is not None:
            cursor_key = "afterSeqLeft" if side == "left" else "afterSeqRight"
            after = request[cursor_key] if instance == request["instanceId"] else 0
            # 同一实例从请求游标往后读。合法空增量要与 HAL 声明的最新序号一致。
            for row in rows:
                if row[0] <= after:
                    return f"{side} history sequence does not advance"
                after = row[0]
            if after != latest[index]:
                return f"{side} history does not reach latestSeq"
    return ""


def sample_in_contact_state(sample: GripperRawSample) -> bool:
    """gOBJ 只在 gGTO=1（正在执行到位命令）时有效；1/2 表示手指因接触物体停止。"""
    return sample.status_valid and sample.gGTO == 1 and sample.gOBJ in (GOBJ_CONTACT_OPENING, GOBJ_CONTACT_CLOSING)


class GripperRawCollector:
    """线程安全：采样线程 ingest，事件循环做空载检查，组帧线程查最近读数。"""

    def __init__(self) -> None:
        self._lock = Lock()
        self._samples: dict[str, list[GripperRawSample]] = {side: [] for side in HARDWARE_SIDES}
        self._times: dict[str, list[float]] = {side: [] for side in HARDWARE_SIDES}
        self._last_seq: dict[str, int] = {side: 0 for side in HARDWARE_SIDES}
        self._missed: dict[str, int] = {side: 0 for side in HARDWARE_SIDES}
        self._duplicates: dict[str, int] = {side: 0 for side in HARDWARE_SIDES}
        self._targets: list[tuple[float, tuple[float, float]]] = []
        self._episode_start_s: float | None = None
        self._instance_id: str | None = None
        self._hal_restarts = 0
        self._fetch_errors = 0
        # 当前接受的拉取会话代际；带旧代际的应答（成功或失败）一律不改动状态，核对与修改在同一把锁内完成。
        self._session = 0

    def set_session(self, session: int) -> None:
        with self._lock:
            self._session = session

    def fetch_payload(self) -> dict[str, Any]:
        """gripper.samples 请求参数：本实例已见的最大 seq；实例不认识时 HAL 返回全部历史。"""
        with self._lock:
            return {"instanceId": self._instance_id or "", "afterSeqLeft": self._last_seq["left"],
                    "afterSeqRight": self._last_seq["right"]}

    def note_fetch_error(self, *, session: int | None = None) -> bool:
        """记一次拉取失败；session 不是当前会话（迟到的旧请求）时不计入，返回是否计入。"""
        with self._lock:
            if session is not None and session != self._session:
                return False
            self._fetch_errors += 1
            return True

    def ingest_targets(self, target_stamp_s: float, targets: Sequence[float]) -> None:
        self.ingest({}, target_stamp_s=target_stamp_s, targets=targets)

    def ingest(
        self,
        native_status: Any,
        *,
        target_stamp_s: float | None = None,
        targets: Sequence[float] | None = None,
        session: int | None = None,
    ) -> int:
        """收入新的读数和当时的命令开口（硬件侧），返回新增读数条数；旧会话的应答返回 -1 且不改动任何状态。"""
        parsed = parse_sample_history(native_status)
        instance = native_status.get("gripperSampleInstanceId") if isinstance(native_status, Mapping) else None
        added = 0
        with self._lock:
            if session is not None and session != self._session:
                return -1
            if isinstance(instance, str) and instance and instance != self._instance_id:
                if self._instance_id is not None:
                    # HAL 重启：seq 从 1 重新计数，旧序号作废；新旧之间的读数无法计数，按中断记录。
                    self._last_seq = {side: 0 for side in HARDWARE_SIDES}
                    if self._episode_start_s is not None:
                        self._hal_restarts += 1
                self._instance_id = instance
            for side, samples in parsed.items():
                for sample in samples:
                    last = self._last_seq[side]
                    if sample.seq <= last:
                        self._duplicates[side] += 1
                        continue
                    if last and sample.seq > last + 1 and self._episode_start_s is not None:
                        self._missed[side] += sample.seq - last - 1
                    self._last_seq[side] = sample.seq
                    if self._episode_start_s is not None and sample.monotonic_s < self._episode_start_s:
                        continue
                    self._samples[side].append(sample)
                    self._times[side].append(sample.monotonic_s)
                    added += 1
            if (target_stamp_s is not None and targets is not None and len(targets) == 2
                    and math.isfinite(target_stamp_s)):
                if not self._targets or target_stamp_s > self._targets[-1][0]:
                    self._targets.append((float(target_stamp_s), (float(targets[0]), float(targets[1]))))
            if self._episode_start_s is None:
                self._trim_idle_locked()
        return added

    def _trim_idle_locked(self) -> None:
        newest = max((times[-1] for times in self._times.values() if times), default=None)
        if newest is None:
            return
        cutoff = newest - IDLE_RETENTION_S
        for side in HARDWARE_SIDES:
            index = bisect.bisect_left(self._times[side], cutoff)
            if index:
                del self._samples[side][:index]
                del self._times[side][:index]
        keep = bisect.bisect_left([stamp for stamp, _ in self._targets], cutoff)
        if keep:
            del self._targets[:keep]

    def begin_episode(self, start_s: float) -> None:
        """丢弃起点之前的读数并开始累积；第 0 帧附近的读数在对齐时仍可用。"""
        with self._lock:
            self._episode_start_s = float(start_s)
            # 保留起点前一个对齐窗口内的读数，供第 0 帧取最近值；旁路文件只写起点之后的行。
            for side in HARDWARE_SIDES:
                index = bisect.bisect_left(self._times[side], start_s - 0.2)
                del self._samples[side][:index]
                del self._times[side][:index]
            keep = bisect.bisect_left([stamp for stamp, _ in self._targets], start_s - 0.2)
            del self._targets[:keep]
            self._missed = {side: 0 for side in HARDWARE_SIDES}
            self._duplicates = {side: 0 for side in HARDWARE_SIDES}
            self._hal_restarts = 0
            self._fetch_errors = 0

    def end_episode(self) -> dict[str, Any]:
        """取出本 episode 的读数快照并回到空闲保留模式。"""
        with self._lock:
            start_s = self._episode_start_s
            snapshot = {
                "startS": start_s,
                "samples": {side: [s for s in self._samples[side] if start_s is None or s.monotonic_s >= start_s]
                            for side in HARDWARE_SIDES},
                "targets": list(self._targets),
                "missedSeq": dict(self._missed),
                "duplicateRows": dict(self._duplicates),
                "halRestarts": self._hal_restarts,
                "fetchErrors": self._fetch_errors,
            }
            self._episode_start_s = None
            self._trim_idle_locked()
            return snapshot

    def nearest(self, side: str, target_s: float, max_skew_s: float) -> GripperRawSample | None:
        with self._lock:
            times = self._times.get(side, [])
            index = bisect.bisect_left(times, target_s)
            best: GripperRawSample | None = None
            for candidate in (index - 1, index):
                if 0 <= candidate < len(times) and abs(times[candidate] - target_s) <= max_skew_s:
                    sample = self._samples[side][candidate]
                    if best is None or abs(sample.monotonic_s - target_s) < abs(best.monotonic_s - target_s):
                        best = sample
            return best

    def current_feature(
        self, sides: Iterable[str], target_s: float, max_skew_s: float
    ) -> tuple[list[float], list[float]]:
        """硬件侧顺序的 (gCU 原码, 有效标志)；无读数、电流无效或未参与的一侧均为 (0, 0)。"""
        active = set(sides)
        values = [0.0, 0.0]
        valid = [0.0, 0.0]
        for index, side in enumerate(HARDWARE_SIDES):
            if side not in active:
                continue
            sample = self.nearest(side, target_s, max_skew_s)
            if sample is not None and sample.current_valid:
                values[index] = float(sample.current_raw)
                valid[index] = 1.0
        return values, valid

    def recent(self, side: str, window_s: float) -> list[GripperRawSample]:
        with self._lock:
            times = self._times.get(side, [])
            if not times:
                return []
            index = bisect.bisect_left(times, times[-1] - window_s)
            return list(self._samples[side][index:])


def idle_start_blocker(
    collector: GripperRawCollector,
    sides: Iterable[str],
    *,
    now_s: float,
    stroke_mm: float,
    expected_gap_mm: float,
    gap_tolerance_mm: float,
    thresholds_raw: Mapping[str, float | None],
) -> str:
    """录制前空载放行：每个参与侧最近 IDLE_WINDOW_S 内的读数须连续（seq 不跳号）、有效、无故障、无接触，
    实际开口接近起始开口；有标定阈值时 gCU 也须不超过阈值。返回阻塞原因，空字符串表示放行。"""
    for side in sides:
        label = "硬件左" if side == "left" else "硬件右"
        samples = collector.recent(side, IDLE_WINDOW_S)
        if not samples:
            return f"{label}夹爪没有结构化读数（需 gripper.workerTransport=modbus）"
        if now_s - samples[-1].monotonic_s > IDLE_MAX_AGE_S:
            return f"{label}夹爪读数过期 {1000 * (now_s - samples[-1].monotonic_s):.0f} ms"
        if len(samples) < IDLE_MIN_SAMPLES:
            return f"{label}夹爪近 {IDLE_WINDOW_S * 1000:.0f} ms 只有 {len(samples)} 条读数"
        seqs = [sample.seq for sample in samples]
        if any(b != a + 1 for a, b in zip(seqs, seqs[1:], strict=False)):
            return f"{label}夹爪读数不连续（seq 跳号），存在缺样"
        for sample in samples:
            if not (sample.position_valid and sample.status_valid and sample.current_valid):
                return f"{label}夹爪读数无效（seq {sample.seq}）"
            if sample.fault:
                return f"{label}夹爪故障码 0x{sample.fault:02X}"
            if sample_in_contact_state(sample):
                return f"{label}夹爪报告接触物体（gOBJ={sample.gOBJ}），两指间可能有东西"
            gap = gap_mm_for_position_raw(sample.position_raw, stroke_mm)
            if abs(gap - expected_gap_mm) > gap_tolerance_mm:
                return f"{label}夹爪实际开口 {gap:.1f} mm，需接近 {expected_gap_mm:g} mm"
        threshold = thresholds_raw.get(side)
        if threshold is not None:
            peak = max(sample.current_raw for sample in samples)
            if peak > threshold:
                return f"{label}夹爪电流 {peak} 高于空载阈值 {threshold:g}，两指间可能有接触"
    return ""


def episode_summary(snapshot: Mapping[str, Any], sides: Iterable[str]) -> dict[str, Any]:
    """每侧真实读数统计：条数、有效频率、最长断样、跳号缺样、电流有效条数、HAL 时间戳回落条数。"""
    summary: dict[str, Any] = {}
    for side in sides:
        samples: list[GripperRawSample] = snapshot["samples"].get(side, [])
        times = [sample.monotonic_s for sample in samples]
        span = times[-1] - times[0] if len(times) > 1 else 0.0
        gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
        summary[side] = {
            "samples": len(samples),
            "effectiveHz": round((len(samples) - 1) / span, 3) if span > 0 else 0.0,
            "maxGapMs": round(max(gaps) * 1000.0, 3) if gaps else None,
            "missedSeq": int(snapshot["missedSeq"].get(side, 0)),
            "currentValidSamples": sum(1 for sample in samples if sample.current_valid),
            "halTimestampSamples": sum(1 for sample in samples if sample.hal_timestamp),
            "firstSeq": samples[0].seq if samples else None,
            "lastSeq": samples[-1].seq if samples else None,
        }
    return summary


def _commanded_at(targets: Sequence[tuple[float, tuple[float, float]]], stamps: list[float], index: int,
                  monotonic_s: float) -> float | None:
    position = bisect.bisect_right(stamps, monotonic_s) - 1
    if position < 0:
        return None
    return targets[position][1][index]


def episode_rows(snapshot: Mapping[str, Any], sides: Iterable[str], *, stroke_mm: float,
                 dataset_side_for_hardware: Mapping[str, str]) -> list[dict[str, Any]]:
    """旁路 parquet 行：每个 seq 一行，附读数时刻之前最近一次命令开口（无则为 NaN）。"""
    start_s = snapshot.get("startS") or 0.0
    targets = snapshot["targets"]
    stamps = [stamp for stamp, _ in targets]
    rows: list[dict[str, Any]] = []
    for side in sides:
        index = HARDWARE_SIDES.index(side)
        for sample in snapshot["samples"].get(side, []):
            commanded = _commanded_at(targets, stamps, index, sample.monotonic_s)
            rows.append({
                "hardware_side": side,
                "dataset_side": dataset_side_for_hardware[side],
                "seq": sample.seq,
                "t_s": round(sample.monotonic_s - start_s, 6),
                "monotonic_s": sample.monotonic_s,
                "hal_timestamp": sample.hal_timestamp,
                "position_valid": sample.position_valid,
                "status_valid": sample.status_valid,
                "current_valid": sample.current_valid,
                "position_raw": sample.position_raw,
                "gap_mm": gap_mm_for_position_raw(sample.position_raw, stroke_mm) if sample.position_valid
                else math.nan,
                "current_raw": sample.current_raw,
                "gACT": sample.gACT,
                "gGTO": sample.gGTO,
                "gSTA": sample.gSTA,
                "gOBJ": sample.gOBJ,
                "fault": sample.fault,
                "commanded_gap_mm": math.nan if commanded is None else commanded,
            })
    return rows


def _contiguous_segments(samples: Sequence[GripperRawSample]) -> list[list[GripperRawSample]]:
    """按连续观测切段：seq 不是逐一递增（缺样、HAL 重启、位置无效被滤掉）或相邻间隔过大即断开。"""
    segments: list[list[GripperRawSample]] = []
    for sample in samples:
        if (segments and sample.seq == segments[-1][-1].seq + 1
                and 0 <= sample.monotonic_s - segments[-1][-1].monotonic_s <= CONTACT_MAX_GAP_S):
            segments[-1].append(sample)
        else:
            segments.append([sample])
    return segments


def contact_events(snapshot: Mapping[str, Any], sides: Iterable[str], *, stroke_mm: float, min_gap_mm: float,
                   fps: float, thresholds_raw: Mapping[str, float | None],
                   dataset_side_for_hardware: Mapping[str, str],
                   frame_count: int | None = None) -> list[dict[str, Any]]:
    """按读数检测接触片段并换算成训练帧区间；仅凭位置推断的片段标为候选。

    片段只在连续观测内成立，不跨越缺样或 HAL 重启。frame_count 为实际写入的帧数：完全落在最后一帧之后
    （停止录制、排空写队列期间）的片段丢弃，跨过末尾的片段截到最后一帧并标记 clippedToLastFrame。
    """
    start_s = snapshot.get("startS") or 0.0
    targets = snapshot["targets"]
    stamps = [stamp for stamp, _ in targets]
    events: list[dict[str, Any]] = []
    for side in sides:
        index = HARDWARE_SIDES.index(side)
        valid = [s for s in snapshot["samples"].get(side, []) if s.position_valid]
        for samples in _contiguous_segments(valid):
            limit = None if frame_count is None else bisect.bisect_left(
                samples, frame_count, key=lambda s: math.floor((s.monotonic_s - start_s) * fps))
            if limit == 0:
                continue
            frames = [
                ContactFrame(
                    gap_mm=gap_mm_for_position_raw(sample.position_raw, stroke_mm),
                    commanded_gap_mm=_commanded_at(targets, stamps, index, sample.monotonic_s),
                    gobj=sample.gOBJ if sample.status_valid else None,
                    current_raw=float(sample.current_raw) if sample.current_valid else None,
                    gripper_moving=sample.gGTO == 1 if sample.status_valid else None,
                )
                for sample in samples
            ]
            threshold = thresholds_raw.get(side)
            detected = detect_contact_events(frames, min_gap_mm=min_gap_mm, current_threshold_raw=threshold,
                                             sample_limit=limit)
            for event in detected:
                kept = samples[event["startFrame"]:event["endFrame"] + 1]
                first, last = kept[0], kept[-1]
                currents = [sample for sample in kept if sample.current_valid]
                peak = max(currents, key=lambda sample: sample.current_raw) if currents else None
                start_t = first.monotonic_s - start_s
                end_t = last.monotonic_s - start_s
                events.append({
                    "hardwareSide": side,
                    "datasetSide": dataset_side_for_hardware[side],
                    "startS": round(start_t, 4),
                    "endS": round(end_t, 4),
                    "startFrame": max(0, int(math.floor(start_t * fps))),
                    "endFrame": max(0, int(math.floor(end_t * fps))),
                    "clippedToLastFrame": event.get("clippedToLastFrame", False),
                    "startSeq": first.seq,
                    "endSeq": last.seq,
                    "evidence": event["evidence"],
                    "candidate": event["candidate"],
                    "minGapMm": round(
                        min(gap_mm_for_position_raw(sample.position_raw, stroke_mm) for sample in kept), 4),
                    "peakCurrentRaw": float(peak.current_raw) if peak is not None else None,
                    "peakSeq": peak.seq if peak is not None else None,
                })
    return sorted(events, key=lambda item: (item["startS"], item["hardwareSide"]))
