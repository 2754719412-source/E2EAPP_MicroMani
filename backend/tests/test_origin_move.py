from __future__ import annotations

import ast
import asyncio
import inspect
import queue
import sys
import textwrap
from concurrent.futures import Future
from pathlib import Path
from threading import Lock
from types import ModuleType, SimpleNamespace

import pytest

from backend.services.dataset_recorder import (
    ORIGIN_MOVE_POSITION_NAMES,
    ORIGIN_MOVE_WRITE_BATCH_SIZE,
    DatasetRecorderService,
    DatasetSaveError,
    LeRobotWriterThread,
    TimedRingBuffer,
    TimedSample,
    WriterCommand,
)


@pytest.fixture
def recording(tmp_path: Path):
    recorder = object.__new__(DatasetRecorderService)
    recorder._recording = True
    recorder._episode_start_monotonic_s = 50.
    recorder._origin_move_lock = Lock()
    recorder._origin_move_closed = False
    recorder._origin_move_last_s = None
    recorder._origin_move_error = ""
    recorder._sample_buffers = {"hal": TimedRingBuffer(retention_s=.1, maxlen=8)}
    recorder._native_live_episode_metadata = {}
    recorder._dataset_dir = tmp_path
    recorder._episode_index = 0
    recorder._native_error = ""
    recorder._episode_frames = 0
    recorder.warnings = []
    recorder.logs = SimpleNamespace(warning=lambda tag, msg: recorder.warnings.append(msg),
                                    error=lambda tag, msg: recorder.warnings.append(msg))
    writer = LeRobotWriterThread(recorder, queue.Queue(maxsize=1200))
    writer._dataset = SimpleNamespace(meta=SimpleNamespace(total_frames=0, latest_episode={"episode_index": 0}),
                                     save_episode=lambda **kw: None, clear_episode_buffer=lambda: None)

    def submit(kind, payload=None):
        future = Future()
        writer._handle_command(WriterCommand(kind, future, payload))
        return future

    writer.submit = submit
    recorder._writer_thread = writer

    async def command(kind, payload=None):
        return writer.submit(kind, payload).result()

    recorder._native_writer_command = command
    try:
        yield recorder, writer
    finally:
        writer._discard_origin_move()


def feed(recorder, count=1000, *, start=50., step=.005):
    for index in range(count):
        recorder._append_hal_sample(TimedSample("hal", start + index * step, {"positions": [float(index)] * 12}))


def read_origin(tmp_path):
    parquet = pytest.importorskip("pyarrow.parquet")
    return parquet.read_table(tmp_path / "origin_move/episode_000000.parquet")


@pytest.mark.parametrize("maxlen", [8, 1000])
def test_origin_move_streams_evicted_samples_without_episode_history(recording, tmp_path, maxlen):
    recorder, writer = recording
    recorder._sample_buffers["hal"] = TimedRingBuffer(retention_s=.1, maxlen=maxlen)
    feed(recorder)
    assert not hasattr(recorder, "_origin_move_buffer")
    assert len(recorder._sample_buffers["hal"]) <= min(maxlen, 21)
    assert len(writer._origin_move_pending) < ORIGIN_MOVE_WRITE_BATCH_SIZE
    assert (tmp_path / "origin_move/episode_000000.parquet.tmp").stat().st_size > 0
    assert not (tmp_path / "origin_move/episode_000000.parquet").exists()
    asyncio.run(recorder._save_native_episode())
    table = read_origin(tmp_path)
    assert table.num_rows == 1000
    assert table["timestamp_s"].to_pylist() == pytest.approx([i * .005 for i in range(1000)])
    assert table["left_x_um"].to_pylist() == list(range(1000))
    assert writer._origin_move_pending == [] and writer._origin_move_writer is None
    assert not (tmp_path / "origin_move/episode_000000.parquet.tmp").exists()
    # 封口后仍有在途反馈，也不能重新打开已保存 episode 的临时文件。
    feed(recorder, 30, start=60.)
    assert read_origin(tmp_path).num_rows == 1000
    assert writer._origin_move_identity is None


@pytest.mark.parametrize("motion_hz", [100, 200, 1000])
def test_origin_move_keeps_every_read_without_rate_limit(recording, tmp_path, motion_hz):
    recorder, _ = recording
    feed(recorder, motion_hz, step=1 / motion_hz)
    asyncio.run(recorder._save_native_episode())
    table = read_origin(tmp_path)
    assert table.num_rows == motion_hz
    assert table["timestamp_s"].to_pylist() == pytest.approx([i / motion_hz for i in range(motion_hz)])


@pytest.mark.parametrize("degrees", [-1.25, 0., .0125, 37.])
def test_origin_move_parquet_units_columns_and_short_episode_tail(recording, tmp_path, degrees):
    recorder, _ = recording
    positions = [1., 2., 3., degrees, degrees, degrees, 7., 8., 9., degrees, degrees, degrees]
    for stamp in (50., 50.01):
        recorder._append_hal_sample(TimedSample("hal", stamp, {"positions": positions, "pulses": [999] * 12}))
    asyncio.run(recorder._save_native_episode())
    table = read_origin(tmp_path)
    assert table.column_names == ["timestamp_s", *ORIGIN_MOVE_POSITION_NAMES]
    assert table["timestamp_s"].to_pylist() == pytest.approx([0., .01])
    row = table.to_pylist()[0]
    for side in ("left", "right"):
        for axis in ("roll", "pitch", "yaw"):
            assert row[f"{side}_{axis}_mdeg"] == pytest.approx(degrees * 1000.)
    assert row["left_x_um"] == 1. and row["right_x_um"] == 7.
    assert positions[3] == degrees
    assert not (tmp_path / "data").exists() and not (tmp_path / "meta").exists()


def test_origin_move_orders_irregular_reads_and_deduplicates_across_eviction(recording, tmp_path):
    recorder, _ = recording
    recorder._sample_buffers["hal"] = TimedRingBuffer(retention_s=.1, maxlen=4)
    for stamp in (50.003, 50., 50.002, 50., 50.017, 50.003, 50.02, 50.02):
        recorder._append_hal_sample(TimedSample("hal", stamp, {"positions": [stamp] * 12}))
    asyncio.run(recorder._save_native_episode())
    table = read_origin(tmp_path)
    assert table["timestamp_s"].to_pylist() == pytest.approx([0., .002, .003, .017, .02])
    assert table["left_x_um"].to_pylist() == [50., 50.002, 50.003, 50.017, 50.02]


def test_origin_move_rejects_invalid_and_preparation_samples(recording, tmp_path):
    recorder, writer = recording
    recorder._origin_move_closed = True
    feed(recorder, 300)
    assert writer._origin_move_identity is None
    recorder._episode_start_monotonic_s = 60.
    recorder._origin_move_closed = False
    recorder._append_hal_sample(TimedSample("hal", 60., {"positions": [1.] * 12}, ok=False))
    recorder._append_hal_sample(TimedSample("hal", 60.001, {"positions": [1.] * 11}))
    recorder._append_hal_sample(TimedSample("hal", 60.002, {"positions": ["invalid"] * 12}))
    recorder._append_hal_sample(TimedSample("hal", 60.003, {"positions": [2.] * 12}))
    asyncio.run(recorder._save_native_episode())
    assert read_origin(tmp_path)["timestamp_s"].to_pylist() == pytest.approx([.003])


def test_origin_move_discard_cleans_partial_file_and_reused_episode(recording, tmp_path):
    recorder, writer = recording
    feed(recorder, 600)
    temporary = tmp_path / "origin_move/episode_000000.parquet.tmp"
    assert temporary.exists()
    asyncio.run(recorder._clear_native_episode_buffer())
    assert not temporary.exists()
    assert recorder._origin_move_closed and recorder._origin_move_last_s is None
    assert writer._origin_move_pending == [] and writer._origin_move_identity is None
    recorder._episode_start_monotonic_s = 70.
    recorder._sample_buffers["hal"] = TimedRingBuffer(retention_s=.1, maxlen=8)
    recorder._origin_move_closed = False
    feed(recorder, 10, start=70.)
    asyncio.run(recorder._save_native_episode())
    assert read_origin(tmp_path)["timestamp_s"].to_pylist() == pytest.approx([i * .005 for i in range(10)])


def test_origin_move_native_save_failure_removes_partial_file(recording, tmp_path):
    recorder, writer = recording
    feed(recorder, 600)

    def fail(**kwargs):
        raise RuntimeError("native failure")

    writer._dataset.save_episode = fail
    with pytest.raises(DatasetSaveError, match="native failure"):
        asyncio.run(recorder._save_native_episode())
    assert not list((tmp_path / "origin_move").iterdir())
    assert writer._origin_move_writer is None


def test_origin_move_write_failure_does_not_publish_partial_or_poison_native(recording, tmp_path, monkeypatch):
    recorder, writer = recording
    feed(recorder, 600)

    def fail():
        raise OSError("sidecar unavailable")

    monkeypatch.setattr(writer, "_flush_origin_move", fail)
    feed(recorder, 600, start=53.)
    assert len(writer._origin_move_pending) <= ORIGIN_MOVE_WRITE_BATCH_SIZE
    assert writer._error == ""
    asyncio.run(recorder._save_native_episode())
    assert recorder._native_error == ""
    assert not list((tmp_path / "origin_move").iterdir())
    assert any("sidecar unavailable" in message for message in recorder.warnings)


def test_origin_move_full_queue_disables_sidecar_without_blocking_sampling(recording, tmp_path):
    recorder, writer = recording
    feed(recorder, 600)
    submit = writer.submit

    def full(*args):
        raise RuntimeError("native LeRobot writer command queue is full")

    writer.submit = full
    feed(recorder, 100, start=53.)
    assert recorder._origin_move_closed and "queue is full" in recorder._origin_move_error
    assert len(recorder._sample_buffers["hal"]) <= 8
    writer.submit = submit
    asyncio.run(recorder._save_native_episode())
    assert recorder._native_error == ""
    assert not list((tmp_path / "origin_move").iterdir())
    assert any("incomplete episode sidecar discarded" in message for message in recorder.warnings)


@pytest.mark.parametrize("save", [False, True])
def test_origin_move_uses_existing_writer_and_cleans_up_on_stop(recording, tmp_path, save):
    recorder, writer = recording
    del writer.submit
    del recorder._native_writer_command
    writer.start()
    try:
        feed(recorder, 600)
        writer.submit("latest_episode_metadata").result(timeout=3)
        assert (tmp_path / "origin_move/episode_000000.parquet.tmp").exists()
        if save:
            asyncio.run(recorder._save_native_episode())
    finally:
        writer._queue.put(None)
        writer.join(3)
    assert not writer.is_alive()
    assert not (tmp_path / "origin_move/episode_000000.parquet.tmp").exists()
    assert (tmp_path / "origin_move/episode_000000.parquet").exists() is save
    if save:
        assert read_origin(tmp_path).num_rows == 600


def test_ring_buffer_returns_all_evictions_in_order_and_preserves_tail():
    buffer = TimedRingBuffer(retention_s=1., maxlen=3)
    evicted = []
    for stamp in (1., .9, 1.2, 1.3, 3.):
        evicted.extend(buffer.append(TimedSample("hal", stamp, {})))
    assert [sample.monotonic_s for sample in evicted] == [.9, 1., 1.2, 1.3]
    assert [sample.monotonic_s for sample in buffer.snapshot()] == [3.]
    assert buffer.nearest(3., .01).monotonic_s == 3.


def test_origin_move_adds_no_sampler_loop_or_sampler_disk_io():
    tree = ast.parse(textwrap.dedent(inspect.getsource(DatasetRecorderService._append_hal_sample)))
    assert not any(isinstance(node, (ast.For, ast.While)) for node in ast.walk(tree))
    calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Attribute)}
    assert not (calls & {"mkdir", "write_table", "open", "write_text", "sleep", "start"})
    assert "submit" in calls


def test_origin_move_hub_upload_excluded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.push_dataset_to_hub import push_dataset

    calls = []

    class Dataset:
        def __init__(self, repo, *, root):
            pass

        def push_to_hub(self, *, private, allow_patterns):
            calls.append(allow_patterns)

    module = ModuleType("lerobot.datasets.lerobot_dataset")
    module.LeRobotDataset = Dataset
    monkeypatch.setitem(sys.modules, module.__name__, module)
    (tmp_path / "meta").mkdir()
    (tmp_path / "meta" / "info.json").write_text("{}", encoding="utf-8")
    (tmp_path / "origin_move").mkdir()
    push_dataset("org/dataset", tmp_path, private=True)
    assert calls == [["data/**", "meta/**", "videos/**", "README.md"]]
