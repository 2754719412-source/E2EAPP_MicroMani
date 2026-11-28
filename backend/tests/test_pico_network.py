# 阅读导航 07｜测试与验证
# 职责：回归验证：物理网卡选择及 PICO 自动网络配置持久化。
# 先看：test_select_pico_network_prefers_related_physical_lan_over_virtual_default_route → test_pico_network_endpoint_preserves_operator_ip_and_persists_detected_pc_fields。
# 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from pytest import MonkeyPatch

from backend.tests.test_app import _attach_mock_control_lease
from backend.app import create_app
from backend.services.pico_network import IPv4Adapter, IPv4Route, select_pico_network


def test_select_pico_network_prefers_related_physical_lan_over_virtual_default_route() -> None:
    adapters = [
        IPv4Adapter("Mihomo", 23, 0, "198.18.0.1", 30),
        IPv4Adapter("Ethernet", 13, 25, "10.90.1.42", 17),
        IPv4Adapter("vEthernet (Default Switch)", 70, 5000, "172.17.160.1", 20),
    ]
    routes = [
        IPv4Route("0.0.0.0", 0, "198.18.0.2", "198.18.0.1", 0),
        IPv4Route("0.0.0.0", 0, "10.90.0.1", "10.90.1.42", 25),
        IPv4Route("10.90.0.0", 17, "", "10.90.1.42", 281),
    ]

    detected = select_pico_network("10.90.129.166", adapters, routes, preferred_gateway="10.90.0.1")

    assert detected == {
        "ifIndex": 13,
        "gateway": "10.90.0.1",
        "localIp": "10.90.1.42",
        "interfaceAlias": "Ethernet",
        "prefixLength": 17,
        "selection": "related-address",
    }


def test_pico_network_endpoint_preserves_operator_ip_and_persists_detected_pc_fields(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("APPSTATION_HAL_MODE", "test")
    client = TestClient(create_app(tmp_path / "runtime"))
    config = client.get("/api/settings").json()
    config["picoVision"]["gateway"] = "192.168.1.1"
    config["picoVision"]["ifIndex"] = 99
    assert client.put("/api/settings", json=config).status_code == 200

    detected_ips: list[str] = []

    def fake_detect(pico_ip: str, *, preferred_gateway: str = "") -> dict[str, object]:
        detected_ips.append(pico_ip)
        return {
            "ifIndex": 13,
            "gateway": "10.90.0.1",
            "localIp": "10.90.1.42",
            "interfaceAlias": "Ethernet",
            "prefixLength": 17,
            "selection": "related-address",
        }

    monkeypatch.setattr("backend.app.detect_pico_network", fake_detect)

    before = client.get("/api/settings").json()
    for headers in ({}, {"X-Control-Session": "observer"}):
        rejected = client.post("/api/pico/network/auto-configure", headers=headers)
        assert rejected.status_code == 409
    assert detected_ips == []
    assert client.get("/api/settings").json() == before
    _attach_mock_control_lease(client)
    response = client.post("/api/pico/network/auto-configure", json={"picoIp": "10.90.140.22"})

    assert response.status_code == 200
    assert detected_ips == ["10.90.140.22"]
    payload = response.json()["data"]
    assert payload["network"]["changed"] is True
    assert payload["config"]["picoVision"]["ip"] == "10.90.140.22"
    assert payload["config"]["picoVision"]["gateway"] == "10.90.0.1"
    assert payload["config"]["picoVision"]["ifIndex"] == 13
    persisted = client.get("/api/settings").json()["picoVision"]
    assert persisted["ip"] == "10.90.140.22"
    assert persisted["gateway"] == "10.90.0.1"
    assert persisted["ifIndex"] == 13
    assert client.post("/api/pico/network/auto-configure").status_code == 200
    assert detected_ips == ["10.90.140.22", "10.90.140.22"]

    # 探测可能耗时；请求开始后失去租约也不能提交迟到的配置。
    watchdog = client.app.state.control_watchdog
    def expire_during_detection(ip: str, *, preferred_gateway: str) -> dict[str, object]:
        network = fake_detect(ip, preferred_gateway=preferred_gateway)
        monkeypatch.setattr(watchdog, "clock", lambda: float("inf"))
        return network

    monkeypatch.setattr("backend.app.detect_pico_network", expire_during_detection)
    rejected = client.post("/api/pico/network/auto-configure", json={"picoIp": "192.0.2.99"})
    assert rejected.status_code == 409
    assert detected_ips[-1] == "192.0.2.99"
    assert client.get("/api/settings").json()["picoVision"] == persisted
