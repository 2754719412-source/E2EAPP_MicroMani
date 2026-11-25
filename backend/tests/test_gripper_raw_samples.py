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
