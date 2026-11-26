# 阅读导航 07｜测试与验证
# 职责：回归验证：夹爪接触片段检测的判据（两指分离、仍在闭合、gOBJ/电流证据）、去抖与录制前空载电流检查。
# 先看：test_contact_event_from_gobj_and_current → test_finger_touch_below_min_gap_is_not_contact → test_idle_current_check。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。

from __future__ import annotations

import math

import pytest

from backend.core.gripper_contact import ContactFrame, detect_contact_events, idle_current_check

MIN_GAP = 1.02


def _grasp(
    current: list[float | None], gobj: list[int | None], moving: bool | None = True
) -> list[ContactFrame]:
    gaps = [20.0, 15.0, 10.0, 6.0, 6.0, 6.0, 6.0, 6.0, 12.0, 20.0, 20.0, 20.0]
    commanded = [2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 20.0, 20.0, 20.0, 20.0]
    return [ContactFrame(g, c, o, i, moving) for g, c, o, i in zip(gaps, commanded, gobj, current, strict=True)]


def test_contact_event_from_gobj_and_current() -> None:
    current = [3, 4, 3, 40, 120, 254, 254, 254, 3, 0, 0, 0]
    gobj = [0, 0, 0, 0, 2, 2, 2, 2, 0, 3, 3, 3]
    events = detect_contact_events(_grasp(current, gobj), min_gap_mm=MIN_GAP, current_threshold_raw=10, fps=30)
    assert len(events) == 1
    event = events[0]
    assert (event["startFrame"], event["endFrame"], event["frames"]) == (3, 7, 5)
    assert event["evidence"] == ["current", "gobj"]
    assert event["candidate"] is False
    assert (event["peakCurrentRaw"], event["peakCurrentFrame"]) == (254.0, 5)
    assert event["minGapMm"] == 6.0
    assert event["startS"] == pytest.approx(0.1)


def test_current_only_detects_thin_object_without_gobj() -> None:
    current = [3, 4, 3, 40, 120, 200, 200, 200, 3, 0, 0, 0]
    events = detect_contact_events(_grasp(current, [0] * 12), min_gap_mm=MIN_GAP, current_threshold_raw=10)
    assert [(e["startFrame"], e["endFrame"], e["evidence"]) for e in events] == [(3, 7, ["current"])]


def test_position_only_when_no_current_or_status_is_recorded() -> None:
    events = detect_contact_events(_grasp([None] * 12, [None] * 12, moving=None), min_gap_mm=MIN_GAP)
    # 第 3 帧刚到 6 mm 仍在运动，从开口停住的第 4 帧起才算候选。
    assert [(e["startFrame"], e["endFrame"]) for e in events] == [(4, 7)]
    assert events[0]["evidence"] == ["position_only"]
    assert events[0]["candidate"] is True
    assert events[0]["peakCurrentRaw"] is None


def test_gobj_ignored_when_ggto_is_zero() -> None:
    # 手册 6.3.1：gGTO=0 时 gOBJ 无效；没有电流阈值时只剩位置判据，片段为候选。
    gobj = [0, 0, 0, 0, 2, 2, 2, 2, 0, 3, 3, 3]
    events = detect_contact_events(_grasp([None] * 12, gobj, moving=False), min_gap_mm=MIN_GAP)
    assert [e["evidence"] for e in events] == [["position_only"]] and events[0]["candidate"]
    # gGTO=1 但未报告接触、又无电流可判时，不推断接触。
    assert detect_contact_events(_grasp([None] * 12, [0] * 12, moving=True), min_gap_mm=MIN_GAP) == []


def test_finger_touch_below_min_gap_is_not_contact() -> None:
    frames = [ContactFrame(1.1, 0.0, 2, 254.0, True) for _ in range(5)]
    assert detect_contact_events(frames, min_gap_mm=MIN_GAP, current_threshold_raw=10) == []


def test_free_closing_motion_and_invalid_samples_are_not_contact() -> None:
    frames = [ContactFrame(20.0 - i, 2.0, 0, 4.0, True) for i in range(10)]
    frames += [ContactFrame(math.nan, 2.0, 2, 254.0, True), ContactFrame(6.0, None, 2, 254.0, True)]
    assert detect_contact_events(frames, min_gap_mm=MIN_GAP, current_threshold_raw=10) == []


def test_short_dropout_does_not_split_event() -> None:
    frames = [ContactFrame(6.0, 2.0, 2, 250.0, True)] * 3 + [ContactFrame(6.0, 2.0, 0, None, True)] * 2
    frames += [ContactFrame(6.0, 2.0, 2, 250.0, True)] * 3 + [ContactFrame(20.0, 20.0, 3, 0.0, True)] * 3
    events = detect_contact_events(frames, min_gap_mm=MIN_GAP, current_threshold_raw=10)
    assert [(e["startFrame"], e["endFrame"]) for e in events] == [(0, 7)]


def test_idle_current_check() -> None:
    assert idle_current_check([3, 4, 3, 5, 4], threshold_raw=10)["ok"]
    high = idle_current_check([3, 4, 30, 5, 4], threshold_raw=10)
    assert not high["ok"] and "空载阈值" in high["reason"]
    assert not idle_current_check([3, None, 3, 5, 4], threshold_raw=10)["ok"]
    assert not idle_current_check([3, 4], threshold_raw=10)["ok"]


def test_free_closing_without_status_or_current_is_not_a_candidate() -> None:
    frames = [ContactFrame(26.0 - 2.0 * i, 1.02, None, None, None) for i in range(10)]
    assert detect_contact_events(frames, min_gap_mm=MIN_GAP) == []
