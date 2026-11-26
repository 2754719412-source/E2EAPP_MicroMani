# 阅读导航 07｜测试与验证
# 职责：回归验证：夹爪真实读数按 seq 去重与缺样计数、录制前空载放行、接触片段换算到训练帧、旁路 parquet 往返。
# 先看：native_status → test_ingest_dedupes_overlapping_history_and_counts_missed_seq → test_idle_start_blocker_cases。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。

from __future__ import annotations

import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.data_contract import RECORDING_FORMAT_VERSION, hardware_to_dataset_grippers
from backend.core.defaults import default_config
from backend.services import gripper_raw_samples as raw
from backend.services.dataset_recorder import (
    GRIPPER_RAW_COLUMNS,
    DatasetRecorderService,
    GripperRawWrite,
    LeRobotWriterThread,
)

STROKE = 26.0
OPEN_RAW = 0  # 全开 26 mm


def row(seq: int, t_s: float, *, pos: int = OPEN_RAW, cur: int = 3, gto: int = 0, obj: int = 3,
        fault: int = 0, valid: bool = True) -> list[int]:
    flag = 1 if valid else 0
    return [seq, int(round(t_s * 1_000_000)), 0, flag, flag, flag, pos, cur, 1, gto, 3, obj, fault]


def native_status(left: list[list[int]], right: list[list[int]] | None = None) -> dict[str, object]:
    return {
        "gripperSampleHistoryFormat": raw.GRIPPER_SAMPLE_HISTORY_FORMAT,
        "gripperSampleHistory": {"left": left, "right": right or []},
    }


def test_parse_rejects_unknown_format_and_bad_rows() -> None:
    assert raw.parse_sample_history({"gripperSampleHistoryFormat": "v0", "gripperSampleHistory": {}}) == {}
    parsed = raw.parse_sample_history(native_status([row(2, 1.0), [1, 2], row(1, 0.99), ["x"] * 13]))
    assert [sample.seq for sample in parsed["left"]] == [1, 2]
    assert parsed["left"][0].monotonic_s == pytest.approx(0.99)
    out_of_range = raw.parse_sample_history(native_status([row(1, 1.0, cur=300)]))["left"][0]
    assert not out_of_range.current_valid


def test_ingest_dedupes_overlapping_history_and_counts_missed_seq() -> None:
    collector = raw.GripperRawCollector()
    collector.ingest(native_status([row(1, 9.98), row(2, 9.99)]))
    collector.begin_episode(10.0)
    # 重叠历史：seq 2 重复；seq 3 在起点前（只用于第 0 帧对齐，不进旁路文件）；seq 6 前跳号 2 条。
    collector.ingest(native_status([row(2, 9.99), row(3, 9.995), row(4, 10.01), row(5, 10.02)]),
                     target_stamp_s=10.0, targets=[2.0, 20.0])
    collector.ingest(native_status([row(4, 10.01), row(5, 10.02), row(8, 10.05)]))
    snapshot = collector.end_episode()
    assert [sample.seq for sample in snapshot["samples"]["left"]] == [4, 5, 8]
    assert snapshot["missedSeq"]["left"] == 2
    assert snapshot["duplicateRows"]["left"] == 3
    summary = raw.episode_summary(snapshot, ["left"])["left"]
    assert summary["samples"] == 3 and summary["missedSeq"] == 2
    assert summary["maxGapMs"] == pytest.approx(30.0)
    assert summary["effectiveHz"] == pytest.approx(2 / 0.04)


def test_frames_can_share_one_reading_but_rows_hold_each_seq_once() -> None:
    collector = raw.GripperRawCollector()
    collector.begin_episode(10.0)
    collector.ingest(native_status([row(1, 10.0, cur=40)], [row(1, 10.0, cur=7, valid=False)]),
                     target_stamp_s=9.99, targets=[13.0, 13.0])
    # 两个 60 fps 帧都引用同一读数；右侧电流无效 → 值 0、有效 0。
    for target in (10.0, 10.0167):
        values, valid = collector.current_feature(["left", "right"], target, 0.07)
        assert (values, valid) == ([40.0, 0.0], [1.0, 0.0])
    # 数据集侧序：操作者左 = 硬件右。
    assert hardware_to_dataset_grippers([40.0, 0.0]) == [0.0, 40.0]
    # 未参与的一侧不取值；超出偏差窗口时为无读数。
    assert collector.current_feature(["right"], 10.0, 0.07) == ([0.0, 0.0], [0.0, 0.0])
    assert collector.current_feature(["left"], 10.5, 0.07) == ([0.0, 0.0], [0.0, 0.0])
    snapshot = collector.end_episode()
    rows = raw.episode_rows(snapshot, ["left", "right"], stroke_mm=STROKE,
                            dataset_side_for_hardware={"left": "right", "right": "left"})
    assert [(r["hardware_side"], r["dataset_side"], r["seq"]) for r in rows] == [
        ("left", "right", 1), ("right", "left", 1)]
    assert rows[0]["commanded_gap_mm"] == 13.0 and rows[0]["gap_mm"] == pytest.approx(26.0)
    assert set(rows[0]) == set(GRIPPER_RAW_COLUMNS)


def _idle(collector: raw.GripperRawCollector, **overrides: object) -> str:
    options = {"now_s": 10.3, "stroke_mm": STROKE, "expected_gap_mm": 26.0, "gap_tolerance_mm": 1.0,
               "thresholds_raw": {"left": 10.0}}
    options.update(overrides)
    return raw.idle_start_blocker(collector, ["left"], **options)  # type: ignore[arg-type]


def _collector(rows: list[list[int]]) -> raw.GripperRawCollector:
    collector = raw.GripperRawCollector()
    collector.ingest(native_status(rows))
    return collector


def test_idle_start_blocker_cases() -> None:
    good = [row(i, 10.0 + i * 0.03) for i in range(1, 11)]
    assert _idle(_collector(good)) == ""
    assert "过期" in _idle(_collector(good), now_s=11.0)
    assert "只有" in _idle(_collector(good[-3:]))
    assert "seq 跳号" in _idle(_collector(good[:5] + good[6:]))
    assert "无效" in _idle(_collector(good[:-1] + [row(10, 10.3, valid=False)]))
    assert "故障码 0x0B" in _idle(_collector(good[:-1] + [row(10, 10.3, fault=0x0B)]))
    assert "实际开口" in _idle(_collector(good[:-1] + [row(10, 10.3, pos=128)]))
    assert "高于空载阈值" in _idle(_collector(good[:-1] + [row(10, 10.3, cur=30)]))
    # 没有标定阈值时不判电流大小，但其余条件照查。
    assert _idle(_collector(good[:-1] + [row(10, 10.3, cur=30)]), thresholds_raw={"left": None}) == ""
    # gOBJ 只在 gGTO=1 时采用：gGTO=0 的 gOBJ=2 不判为接触，gGTO=1 时判为接触。
    assert _idle(_collector(good[:-1] + [row(10, 10.3, gto=0, obj=2)])) == ""
    assert "接触物体" in _idle(_collector(good[:-1] + [row(10, 10.3, gto=1, obj=2)]))
    assert "没有结构化读数" in _idle(raw.GripperRawCollector())


def test_contact_events_map_readings_to_training_frames() -> None:
    collector = raw.GripperRawCollector()
    collector.begin_episode(10.0)
    contact_raw = 140  # 26 × (1 − 140/255) ≈ 11.7 mm，远高于最小开度
    rows = [row(1, 10.0)]
    rows += [row(i, 10.0 + i * 0.01, pos=contact_raw, cur=200 if i >= 4 else 3, gto=1, obj=0) for i in range(2, 12)]
    rows += [row(12, 10.2), row(13, 10.21), row(14, 10.22), row(15, 10.23)]
    collector.ingest(native_status(rows), target_stamp_s=10.0, targets=[2.0, 2.0])
    collector.ingest(native_status([]), target_stamp_s=10.115, targets=[26.0, 26.0])
    snapshot = collector.end_episode()
    events = raw.contact_events(snapshot, ["left"], stroke_mm=STROKE, min_gap_mm=1.02, fps=30.0,
                                thresholds_raw={"left": 10.0}, dataset_side_for_hardware={"left": "right"})
    assert len(events) == 1
    event = events[0]
    assert (event["startSeq"], event["endSeq"], event["peakCurrentRaw"]) == (4, 11, 200.0)
    assert event["evidence"] == ["current"] and event["candidate"] is False
    assert (event["startFrame"], event["endFrame"]) == (1, 3)
    assert event["datasetSide"] == "right"
    # 没有电流阈值、gGTO=1 但未报告接触：不推断接触。
    assert raw.contact_events(snapshot, ["left"], stroke_mm=STROKE, min_gap_mm=1.02, fps=30.0,
                              thresholds_raw={"left": None}, dataset_side_for_hardware={"left": "right"}) == []


def test_recorder_episode_payload_and_sidecar_round_trip(tmp_path: Path) -> None:
    pq = pytest.importorskip("pyarrow.parquet")
    recorder = object.__new__(DatasetRecorderService)
    recorder._record_fps_hz = 30
    recorder._episode_index = 3
    # 操作者左（= 硬件右）参与，夹爪读数只取硬件右。
    recorder._participation = {"version": "appstation.participation.v1", "arms": ["left"], "grippers": ["left"]}
    recorder._dataset_dir = tmp_path
    config = default_config()
    config["gripper"]["workerTransport"] = "modbus"
    recorder._recording_config = lambda: config  # type: ignore[method-assign]
    recorder._require_dataset_dir = lambda: tmp_path  # type: ignore[method-assign]
    recorder._gripper_idle_check = "passed_without_current_threshold"
    collector = recorder._gripper_raw_collector()
    collector.begin_episode(10.0)
    collector.ingest(native_status([], [row(1, 10.0), row(2, 10.01, cur=9)]), target_stamp_s=10.0, targets=[26.0, 26.0])

    payload = recorder._gripper_raw_episode_payload()
    meta = recorder._episode_gripper_raw_meta
    assert payload is not None and payload.episode_index == 3
    assert meta["recordingFormat"] == RECORDING_FORMAT_VERSION and meta["transport"] == "modbus"
    assert list(meta["stats"]) == ["right"] and meta["stats"]["right"]["samples"] == 2
    assert meta["idleStartCheck"] == "passed_without_current_threshold"

    writer = object.__new__(LeRobotWriterThread)
    writer._write_gripper_raw(payload)
    table = pq.read_table(tmp_path / "gripper_raw" / "episode_000003.parquet").to_pylist()
    assert [item["seq"] for item in table] == [1, 2]
    assert table[1]["current_raw"] == 9
    assert (table[0]["hardware_side"], table[0]["dataset_side"]) == ("right", "left")
    assert not (tmp_path / "gripper_raw" / "episode_000003.parquet.tmp").exists()
    assert math.isclose(table[0]["commanded_gap_mm"], 26.0)


def test_writer_rejects_missing_payload_without_poisoning_frames() -> None:
    from concurrent.futures import Future

    from backend.services.dataset_recorder import WriterCommand

    writer = object.__new__(LeRobotWriterThread)
    writer._error = ""
    writer._recorder = SimpleNamespace(logs=SimpleNamespace(error=lambda *a: None))
    future: Future[object] = Future()
    writer._handle_command(WriterCommand("write_gripper_raw", future, None))
    with pytest.raises(ValueError):
        future.result()
    assert writer._error == ""
    assert isinstance(GripperRawWrite(Path("."), 0, ()), GripperRawWrite)


def test_recorder_collects_history_even_when_dds_status_cache_is_fresh() -> None:
    """审查复现：DDS 遥测缓存只带最新样本；录制器必须用 gripper.samples 拉到逐读数历史。"""
    import asyncio
    import json

    from backend.core.logging import LogService
    from backend.hal_client.dds_client import DdsHalClient
    from backend.hal_client.dds_types import (
        TOPIC_HAL_NATIVE_TELEOP_STATUS,
        HalCommandReply,
        JsonEnvelope,
        now_unix_ms,
    )

    class Transport:
        def __init__(self) -> None:
            self.latest = {TOPIC_HAL_NATIVE_TELEOP_STATUS: JsonEnvelope(
                stamp_unix_ms=now_unix_ms(), stamp_monotonic_ms=1, source="hal-cpp",
                payload_json=json.dumps({"grippers": {"left": {"sample": {"seq": 3, "currentRaw": 40}}}}))}
            self.requests: list[object] = []
            self.replies: dict[str, HalCommandReply] = {}

        def start(self) -> None: ...
        def close(self) -> None: ...

        def get_latest(self, topic: str) -> JsonEnvelope | None:
            return self.latest.get(topic)

        def publish_command_request(self, request: object) -> None:
            self.requests.append(request)
            payload = json.loads(request.payload_json)  # type: ignore[attr-defined]
            after = int(payload.get("afterSeqLeft", 0))
            history = native_status([r for r in [row(1, 10.0, cur=40), row(2, 10.01, cur=41), row(3, 10.02, cur=42)]
                                     if r[0] > after])
            history["gripperSampleInstanceId"] = "hal-a"
            self.replies[request.request_id] = HalCommandReply(  # type: ignore[attr-defined]
                request_id=request.request_id, ok=True, result_json=json.dumps(history), error="")  # type: ignore[attr-defined]

        def wait_for_command_reply(self, request_id: str, timeout_s: float) -> HalCommandReply | None:
            return self.replies.get(request_id)

    transport = Transport()
    recorder = object.__new__(DatasetRecorderService)
    recorder.hal = DdsHalClient(LogService(emit_startup=False), transport=transport, reply_timeout_s=0.2)
    collector = recorder._gripper_raw_collector()
    # 缓存路径本身仍只给最新样本：
    cached = asyncio.run(recorder.hal.command("teleop.native.status", {}))["response"]
    assert raw.parse_sample_history(cached) == {}

    asyncio.run(recorder._fetch_gripper_samples(collector))
    assert [sample.seq for sample in collector.recent("left", 1.0)] == [1, 2, 3]
    # 下一次只请求更大的 seq。
    asyncio.run(recorder._fetch_gripper_samples(collector))
    assert json.loads(transport.requests[-1].payload_json)["afterSeqLeft"] == 3  # type: ignore[attr-defined]


def test_poll_failure_is_counted_without_raising() -> None:
    import asyncio

    recorder = object.__new__(DatasetRecorderService)

    class Broken:
        async def command(self, *_args: object) -> dict[str, object]:
            raise RuntimeError("dds-gripper-samples channel is busy")

    recorder.hal = Broken()
    collector = recorder._gripper_raw_collector()
    collector.begin_episode(0.0)
    assert asyncio.run(recorder._fetch_gripper_samples(collector)) is False
    assert collector.end_episode()["fetchErrors"] == 1


def test_hal_restart_resets_sequence_and_marks_interruption() -> None:
    """审查复现：HAL 重启后 seq 从 1 重新计数，新读数不能被当作重复丢弃。"""
    collector = raw.GripperRawCollector()
    first = native_status([row(10000, 10.0)])
    first["gripperSampleInstanceId"] = "hal-a"
    collector.ingest(first)
    collector.begin_episode(9.0)
    restarted = native_status([row(1, 12.0), row(2, 12.01)])
    restarted["gripperSampleInstanceId"] = "hal-b"
    collector.ingest(restarted)
    assert collector.fetch_payload() == {"instanceId": "hal-b", "afterSeqLeft": 2, "afterSeqRight": 0}
    snapshot = collector.end_episode()
    assert [sample.seq for sample in snapshot["samples"]["left"]] == [10000, 1, 2]
    assert snapshot["halRestarts"] == 1


def _contact_snapshot(rows: list[list[int]]) -> dict[str, object]:
    collector = raw.GripperRawCollector()
    collector.begin_episode(10.0)
    collector.ingest(native_status(rows), target_stamp_s=10.0, targets=[2.0, 2.0])
    return collector.end_episode()


def _events(snapshot: dict[str, object], frame_count: int | None = None) -> list[dict[str, object]]:
    return raw.contact_events(snapshot, ["left"], stroke_mm=STROKE, min_gap_mm=1.02, fps=30.0,
                              thresholds_raw={"left": 10.0}, dataset_side_for_hardware={"left": "right"},
                              frame_count=frame_count)


def test_contact_events_do_not_span_missing_samples() -> None:
    """审查复现：相隔 2 s、seq 从 1 跳到 70 的两条接触读数不能连成一个片段。"""
    contact = {"pos": 140, "cur": 200, "gto": 1, "obj": 0}
    events = _events(_contact_snapshot([row(1, 10.0, **contact), row(70, 12.0, **contact)]))
    assert [(event["startSeq"], event["endSeq"]) for event in events] == [(1, 1), (70, 70)]
    # seq 连续但相邻间隔超过上限同样切断。
    events = _events(_contact_snapshot([row(1, 10.0, **contact), row(2, 10.5, **contact)]))
    assert [(event["startSeq"], event["endSeq"]) for event in events] == [(1, 1), (2, 2)]


def test_contact_events_are_limited_to_written_frames() -> None:
    """审查复现：15 帧 episode（帧 0–14）中，停止后排空期间的接触不能指向第 17 帧。"""
    contact = {"pos": 140, "cur": 200, "gto": 1, "obj": 0}
    tail = [row(i, 10.0 + 0.55 + i * 0.01, **contact) for i in range(1, 5)]  # 0.56–0.59 s → 帧 16–17
    assert _events(_contact_snapshot(tail), frame_count=15) == []
    # 0.43–0.64 s → 帧 12–19；电流逐条升高，峰值 220 在第 8 条读数（尾帧之后）。
    rising = {"pos": 140, "gto": 1, "obj": 0}
    spanning = [row(i, 10.4 + i * 0.03, cur=150 + i * 10, **rising) for i in range(1, 9)]
    events = _events(_contact_snapshot(spanning), frame_count=15)
    assert len(events) == 1 and events[0]["endFrame"] == 14 and events[0]["clippedToLastFrame"] is True
    # 审查复现：结束时间、结束序号和峰值都只能来自第 14 帧以内（t < 0.5 s）的读数。
    assert events[0]["endS"] < 0.5 and events[0]["endSeq"] == 3
    assert (events[0]["peakCurrentRaw"], events[0]["peakSeq"]) == (180.0, 3)
    assert _events(_contact_snapshot(spanning), frame_count=0) == []


def test_slow_history_fetch_does_not_delay_position_sampling() -> None:
    """审查复现：历史读取延迟 300 ms 时，位置样本不能跟着等待（帧对齐只允许 70 ms）。"""
    import time
    from threading import Event

    recorder = object.__new__(DatasetRecorderService)
    recorder._participation = {"version": "appstation.participation.v1", "arms": ["left"], "grippers": ["left"]}
    now_ms = time.time() * 1000
    status = {"monotonic_s": time.monotonic(), "grippers": {
        "right": {"positionMm": 13.0, "positionOk": True, "positionSampleTs": now_ms}}}
    fetched = Event()

    class Hal:
        async def command(self, name: str, payload: dict[str, object]) -> dict[str, object]:
            if name == "gripper.samples":
                time.sleep(0.3)
                fetched.set()
                reply = native_status([], [row(1, time.monotonic())])
                reply["gripperSampleInstanceId"] = "hal-a"
                return {"response": reply}
            return {"response": status}

    recorder.hal = Hal()
    recorder.teleop = SimpleNamespace(status=lambda: {"nativeStatus": status})
    config = {"hal": {"mode": "real"}, "teleop": {"engine": "hal_native"}}
    started = time.monotonic()
    sample = recorder._sample_source_once_sync("gripper", config, time.monotonic())
    assert time.monotonic() - started < 0.07
    assert sample.value == [0.0, 13.0]

    from threading import Event as StopEvent

    recorder._session_active = True
    recorder._sampler_stop_event = StopEvent()
    recorder._start_gripper_samples_thread(config)
    assert fetched.wait(2.0)
    recorder._retire_gripper_samples_thread().join(2.0)
    assert [s.seq for s in recorder._gripper_raw_collector().recent("right", 5.0)] == [1]


def test_save_fetches_tail_samples_before_sealing(tmp_path: Path) -> None:
    """审查复现：两次轮询之间结束录制时，HAL 已有 seq 1–3，封存结果不能只有 seq 1。"""
    import asyncio

    recorder = object.__new__(DatasetRecorderService)
    recorder._record_fps_hz = 30
    recorder._episode_index = 0
    recorder._episode_frames = 30
    recorder._participation = {"version": "appstation.participation.v1", "arms": ["right"], "grippers": ["right"]}
    recorder._native_live_episode_metadata = {}
    recorder.logs = SimpleNamespace(warning=lambda *a: None)
    config = default_config()
    recorder._recording_config = lambda: config  # type: ignore[method-assign]
    recorder._require_dataset_dir = lambda: tmp_path  # type: ignore[method-assign]
    collector = recorder._gripper_raw_collector()
    collector.begin_episode(10.0)
    first = native_status([row(1, 10.0)])
    first["gripperSampleInstanceId"] = "hal-a"
    collector.ingest(first)
    written: list[GripperRawWrite] = []

    class Hal:
        async def command(self, name: str, payload: dict[str, object]) -> dict[str, object]:
            assert name == "gripper.samples" and payload["afterSeqLeft"] == 1
            reply = native_status([row(2, 10.01), row(3, 10.02)])
            reply["gripperSampleInstanceId"] = "hal-a"
            return {"response": reply}

    async def writer_command(kind: str, payload: object = None) -> object:
        if kind == "write_gripper_raw":
            written.append(payload)  # type: ignore[arg-type]
        return {} if kind == "latest_episode_metadata" else 0

    recorder.hal = Hal()
    recorder._native_writer_command = writer_command  # type: ignore[method-assign]
    asyncio.run(recorder._save_native_episode())
    assert [row_["seq"] for row_ in written[0].rows] == [1, 2, 3]
    assert recorder._episode_gripper_raw_meta["stats"]["left"]["missedSeq"] == 0


class _BlockingHalTransport:
    """模拟 DDS 传输：HAL 当前已有的读数由 available 给出；第一个请求的应答被扣住，直到 release 置位。"""

    def __init__(self) -> None:
        from threading import Event

        self.latest: dict[str, object] = {}
        self.requests: list[object] = []
        self.replies: dict[str, object] = {}
        self.available = [row(1, 10.0)]
        self.first_request = Event()
        self.release = Event()

    def start(self) -> None: ...
    def close(self) -> None: ...

    def get_latest(self, topic: str) -> object | None:
        return None

    def publish_command_request(self, request: object) -> None:
        import json

        from backend.hal_client.dds_types import HalCommandReply

        payload = json.loads(request.payload_json)  # type: ignore[attr-defined]
        after = int(payload.get("afterSeqLeft", 0))
        reply = native_status([r for r in self.available if r[0] > after])
        reply["gripperSampleInstanceId"] = "hal-a"
        self.requests.append(request)
        self.replies[request.request_id] = HalCommandReply(  # type: ignore[attr-defined]
            request_id=request.request_id, ok=True, result_json=json.dumps(reply), error="")  # type: ignore[attr-defined]
        if len(self.requests) == 1:
            self.first_request.set()

    def wait_for_command_reply(self, request_id: str, timeout_s: float) -> object | None:
        if request_id == self.requests[0].request_id:  # type: ignore[attr-defined]
            self.release.wait(timeout_s)
        return self.replies.get(request_id)


def _recorder_with_dds(tmp_path: Path, transport: _BlockingHalTransport, grippers: list[str]) -> DatasetRecorderService:
    from backend.core.logging import LogService
    from backend.hal_client.dds_client import DdsHalClient

    recorder = object.__new__(DatasetRecorderService)
    recorder.hal = DdsHalClient(LogService(emit_startup=False), transport=transport, reply_timeout_s=2.0)
    recorder._record_fps_hz = 30
    recorder._episode_index = 0
    recorder._episode_frames = 30
    # 操作者右 = 硬件左
    recorder._participation = {"version": "appstation.participation.v1", "arms": ["right"], "grippers": grippers}
    recorder._native_live_episode_metadata = {}
    recorder._session_active = True
    recorder.logs = SimpleNamespace(warning=lambda *a: None)
    config = default_config()
    recorder._recording_config = lambda: config  # type: ignore[method-assign]
    recorder._require_dataset_dir = lambda: tmp_path  # type: ignore[method-assign]
    recorder._using_real_hal_native_teleop = lambda _config: True  # type: ignore[method-assign]
    return recorder


def test_save_waits_for_inflight_fetch_then_reads_tail(tmp_path: Path) -> None:
    """审查复现：后台读取占住容量为 1 的通道时触发保存；封存结果必须含 seq 1、2、3。"""
    import asyncio
    from threading import Timer

    transport = _BlockingHalTransport()
    recorder = _recorder_with_dds(tmp_path, transport, ["right"])
    collector = recorder._gripper_raw_collector()
    collector.begin_episode(9.0)
    written: list[GripperRawWrite] = []

    async def writer_command(kind: str, payload: object = None) -> object:
        if kind == "write_gripper_raw":
            written.append(payload)  # type: ignore[arg-type]
        return {} if kind == "latest_episode_metadata" else 0

    recorder._native_writer_command = writer_command  # type: ignore[method-assign]
    recorder._start_gripper_samples_thread(recorder._recording_config())
    assert transport.first_request.wait(2.0)  # 后台读取已在途，应答被扣住
    transport.available = [row(1, 10.0), row(2, 10.01), row(3, 10.02)]  # 在途期间 HAL 又读到两条
    Timer(0.2, transport.release.set).start()
    asyncio.run(recorder._save_native_episode())
    recorder._retire_gripper_samples_thread().join(2.0)

    assert [item["seq"] for item in written[0].rows] == [1, 2, 3]
    meta = recorder._episode_gripper_raw_meta
    assert meta["tailFetch"] == "ok" and meta["fetchErrors"] == 0
    assert meta["stats"]["left"]["missedSeq"] == 0


def test_previous_session_thread_cannot_serve_next_session(tmp_path: Path) -> None:
    """审查复现：上一会话的读取线程在停止后仍存活时，不能为未选夹爪的新会话请求或入库。"""
    import asyncio

    transport = _BlockingHalTransport()
    recorder = _recorder_with_dds(tmp_path, transport, ["right"])
    recorder._sampler_threads = {}
    recorder._sampler_stop_event = __import__("threading").Event()
    collector = recorder._gripper_raw_collector()
    recorder._start_gripper_samples_thread(recorder._recording_config())
    assert transport.first_request.wait(2.0)
    asyncio.run(recorder._stop_sampler_tasks())  # 只等 200 ms，旧线程仍卡在应答上
    old = recorder._gripper_samples_thread
    assert old.is_alive()

    recorder._participation = {"version": "appstation.participation.v1", "arms": ["right"], "grippers": []}
    recorder._start_gripper_samples_thread(recorder._recording_config())
    transport.release.set()
    old.join(2.0)
    assert not old.is_alive()
    assert len(transport.requests) == 1  # 新会话没有再发 gripper.samples
    assert collector.recent("left", 10.0) == []  # 旧会话的迟到应答未入库


def test_save_without_grippers_skips_tail_fetch(tmp_path: Path) -> None:
    """审查复现：未选择夹爪的 episode 保存时不调用 gripper.samples，也不记录无关的 fetchErrors。"""
    import asyncio

    transport = _BlockingHalTransport()
    transport.release.set()
    recorder = _recorder_with_dds(tmp_path, transport, [])

    async def writer_command(kind: str, payload: object = None) -> object:
        return {} if kind == "latest_episode_metadata" else 0

    recorder._native_writer_command = writer_command  # type: ignore[method-assign]
    recorder._gripper_raw_collector().begin_episode(9.0)
    asyncio.run(recorder._save_native_episode())
    assert transport.requests == []
    meta = recorder._episode_gripper_raw_meta
    assert meta["tailFetch"] == "skipped_no_grippers" and meta["fetchErrors"] == 0


def test_contact_evidence_ignores_readings_after_last_frame() -> None:
    """审查复现：录像内只有位置证据（候选），录像结束后的一条 gOBJ=2 不能把它变成确认接触。"""
    def position_only(seq: int, t_s: float) -> list[int]:
        return [seq, int(round(t_s * 1_000_000)), 0, 1, 0, 0, 140, 0, -1, -1, -1, -1, -1]

    rows = [position_only(i, 10.3 + i * 0.03) for i in range(1, 6)]  # 帧 9–13
    rows.append(row(6, 10.3 + 7 * 0.03, pos=140, cur=0, gto=1, obj=2, valid=True))  # 0.51 s → 帧 15（录像外）
    events = _events(_contact_snapshot(rows), frame_count=15)
    assert len(events) == 1
    event = events[0]
    assert event["endSeq"] == 5 and event["clippedToLastFrame"] is True
    assert event["evidence"] == ["position_only"] and event["candidate"] is True
