import json
import os
import threading
import time

import pytest

from backend.core.config import SettingsService
from backend.core.logging import LogService


def make_service(tmp_path):
    return SettingsService(tmp_path, LogService(log_file_path=tmp_path / "logs" / "test.log", emit_startup=False))


def count_reads(monkeypatch, service):
    reads = []
    read_text = type(service.config_path).read_text

    def counting(path, *args, **kwargs):
        if path == service.config_path:
            reads.append(path)
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(type(service.config_path), "read_text", counting)
    return reads


def test_unchanged_file_is_not_reopened(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    first = service.get_config()
    reads = count_reads(monkeypatch, service)
    for _ in range(50):
        assert service.get_config() == first
    assert reads == []


def test_returned_config_is_a_private_copy(tmp_path):
    service = make_service(tmp_path)
    config = service.get_config()
    config["teleop"]["leftConnected"] = not config["teleop"]["leftConnected"]
    assert service.get_config()["teleop"]["leftConnected"] != config["teleop"]["leftConnected"]


def test_save_is_read_back_once_through_the_migrating_load(tmp_path, monkeypatch):
    # get_config migrates and validates what it reads (legacy labels, work-origin checks), so a save is not served from
    # memory: the next get_config reads the file once, later ones do not.
    service = make_service(tmp_path)
    config = service.get_config()
    config["teleop"]["leftConnected"] = not config["teleop"]["leftConnected"]
    service.save_config(config, emit_log=False)
    reads = count_reads(monkeypatch, service)
    loaded = service.get_config()
    assert len(reads) == 1
    for _ in range(20):
        assert service.get_config() == loaded
    assert len(reads) == 1
    monkeypatch.undo()
    assert make_service(tmp_path).get_config() == loaded
    assert loaded["teleop"]["leftConnected"] == config["teleop"]["leftConnected"]


def test_external_edit_is_picked_up(tmp_path):
    service = make_service(tmp_path)
    config = service.get_config()
    data = json.loads(service.config_path.read_text(encoding="utf-8"))
    data["teleop"]["leftConnected"] = not config["teleop"]["leftConnected"]
    time.sleep(0.02)
    service.config_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    assert service.get_config()["teleop"]["leftConnected"] == data["teleop"]["leftConnected"]


@pytest.mark.skipif(os.name != "nt", reason="Windows: an open reader makes the atomic replace fail with WinError 5")
def test_saves_survive_readers_polling_like_camera_snapshots(tmp_path):
    # 11-05 run: trial video polled each camera snapshot every 10 ms and every snapshot read the config, so the
    # gripper command's save_config replace was refused 5 times in a row and the backend latched a software e-stop.
    service = make_service(tmp_path)
    config = service.get_config()
    stop = threading.Event()
    errors = []

    def reader():
        while not stop.is_set():
            try:
                service.get_config()
            except Exception as exc:  # noqa: BLE001  (reported by the assertion below)
                errors.append(exc)

    threads = [threading.Thread(target=reader) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        for i in range(150):
            config["teleop"]["leftConnected"] = bool(i % 2)
            service.save_config(config, emit_log=False)
    finally:
        stop.set()
        for t in threads:
            t.join()
    assert errors == []
    assert service.get_config()["teleop"]["leftConnected"] is True    # last save, i = 149
    assert make_service(tmp_path).get_config() == service.get_config()
