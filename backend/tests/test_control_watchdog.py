from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from backend.core.logging import LogService
from backend.services.control_watchdog import ControlLeaseUnavailable, ControlWatchdog


def make_watchdog():
    now = [0.0]
    hal = Mock(command=AsyncMock(return_value={"response": {"ok": True, "leaseFresh": True, "timeoutMs": 2500}}))
    invalidate = Mock()
    stop = AsyncMock()
    watchdog = ControlWatchdog(hal, LogService(emit_startup=False), invalidate, stop, clock=lambda: now[0])
    # 周期由测试显式推进；仍测试真正的挑战、应答、续租和急停协程。
    watchdog._run = AsyncMock()
    return watchdog, now, hal, invalidate, stop


async def flush() -> None:
    await asyncio.sleep(0.001)


def test_quarantined_transport_tells_browser_restart_is_required() -> None:
    async def exercise():
        watchdog, _, hal, _, _ = make_watchdog()
        messages = []
        async def send(message):
            messages.append(message)
        watchdog.register(send)
        hal._control_transport_failed = True
        watchdog.trip("DDS reply timed out")
        await flush()
        assert messages[-1]["data"]["restartRequired"] is True
        with pytest.raises(ControlLeaseUnavailable):
            watchdog.require_ready()
        await watchdog.close()
    asyncio.run(exercise())


async def confirm_mock_browser_lease(watchdog: ControlWatchdog) -> str:
    """旧业务测试显式完成执行侧确认；不覆盖 require_ready 或修改内部确认状态。"""
    watchdog._run = AsyncMock()
    messages = []

    async def send(message):
        messages.append(message)

    session = watchdog.register(send)
    await watchdog.cycle()
    await flush()
    watchdog.require_ready()
    return session


def test_ack_readiness_requires_confirmed_current_session_and_rejects_trip_before_hal_expiry() -> None:
    async def exercise() -> None:
        watchdog, _now, _hal, _invalidate, _stop = make_watchdog()
        with pytest.raises(ControlLeaseUnavailable):
            watchdog.require_ready()
        try:
            await confirm_mock_browser_lease(watchdog)
            watchdog.require_ready()
            watchdog.trip("browser lost while HAL TTL remains fresh")
            with pytest.raises(ControlLeaseUnavailable):
                watchdog.require_ready()
        finally:
            await watchdog.close()

    asyncio.run(exercise())






def test_second_controller_is_rejected_and_owner_disconnect_trips_control() -> None:
    async def exercise() -> None:
        watchdog, _now, hal, invalidate, stop = make_watchdog()
        watchdog.disconnect_grace_s = 0.0
        messages = [[], []]

        async def send_first(message):
            messages[0].append(message)

        async def send_second(message):
            messages[1].append(message)

        first = watchdog.register(send_first)
        with pytest.raises(ControlLeaseUnavailable, match="another browser"):
            watchdog.register(send_second)
        try:
            await watchdog.cycle()
            await flush()
            await watchdog.cycle()
            await flush()
            assert hal.command.call_count == 1
            watchdog.remove(first)
            invalidate.assert_called_once()
            await flush()
            stop.assert_awaited_once()
            await watchdog.cycle()
            assert hal.command.call_count == 1
            assert not watchdog.clients
        finally:
            await watchdog.close()

    asyncio.run(exercise())


def test_idle_disconnect_keeps_lease_blocks_motion_and_reconnects_without_ack() -> None:
    async def exercise() -> None:
        watchdog, now, hal, invalidate, stop = make_watchdog()
        watchdog.motion_active = lambda: False
        watchdog.axes_stationary = AsyncMock(return_value=True)
        first = await confirm_mock_browser_lease(watchdog)
        watchdog.remove(first)
        await flush()
        watchdog.axes_stationary.assert_awaited_once()
        invalidate.assert_not_called()
        stop.assert_not_awaited()
        with pytest.raises(ControlLeaseUnavailable):
            watchdog.require_ready()
        renewals = hal.command.call_count
        for _ in range(2):
            now[0] += 1.0
            await watchdog.cycle()
        assert hal.command.call_count == renewals + 2  # 后端继续续租，HAL 租约不过期
        second = await confirm_mock_browser_lease(watchdog)
        try:
            assert second in watchdog.clients
            invalidate.assert_not_called()
            stop.assert_not_awaited()
        finally:
            await watchdog.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("cause", ["motion_started", "check_failed"])
def test_idle_detached_watchdog_stops_when_motion_starts_or_cannot_be_checked(cause) -> None:
    async def exercise() -> None:
        watchdog, _now, _hal, invalidate, stop = make_watchdog()
        state = {"moving": False}

        def motion_active():
            if state["moving"] and cause == "check_failed":
                raise RuntimeError("status unavailable")
            return state["moving"]

        watchdog.motion_active = motion_active
        watchdog.axes_stationary = AsyncMock(return_value=True)
        session = await confirm_mock_browser_lease(watchdog)
        watchdog.remove(session)
        await flush()
        state["moving"] = True
        await watchdog.cycle()
        await flush()
        try:
            invalidate.assert_called_once()
            stop.assert_awaited_once()
        finally:
            await watchdog.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("stationary", [True, False])
def test_idle_send_failure_detaches_only_when_axes_are_stationary(stationary) -> None:
    async def exercise() -> None:
        watchdog, _now, _hal, invalidate, stop = make_watchdog()
        watchdog.motion_active = lambda: False
        watchdog.axes_stationary = AsyncMock(return_value=stationary)

        async def broken(_message):
            raise ConnectionError("socket closed")

        watchdog.register(broken)
        await watchdog.cycle()
        await flush()
        await flush()
        try:
            assert not watchdog.clients
            if stationary:
                invalidate.assert_not_called()
                stop.assert_not_awaited()
            else:
                invalidate.assert_called_once()
                stop.assert_awaited_once()
        finally:
            await watchdog.close()

    asyncio.run(exercise())


@pytest.mark.parametrize("feedback", ["moving", "check_failed", "timeout", "not_configured"])
def test_idle_disconnect_stops_when_hal_cannot_confirm_axes_stationary(feedback) -> None:
    """单段点动应答后后端已无运动任务，但轴可能仍在移动；断线须以 HAL 反馈为准。"""
    async def exercise() -> None:
        watchdog, now, hal, invalidate, stop = make_watchdog()
        watchdog.motion_active = lambda: False

        async def axes_stationary():
            if feedback == "check_failed":
                raise RuntimeError("stationary motion feedback is stale or unavailable")
            if feedback == "timeout":
                await asyncio.sleep(5)
            return False

        if feedback != "not_configured":
            watchdog.axes_stationary = axes_stationary
        session = await confirm_mock_browser_lease(watchdog)
        renewals = hal.command.call_count
        watchdog.remove(session)
        try:
            await asyncio.wait_for(_until(lambda: stop.await_count == 1), 2.0)
            invalidate.assert_called_once()
            now[0] += 1.0
            await watchdog.cycle()
            assert hal.command.call_count == renewals  # 急停后不再为断线会话续租
            with pytest.raises(ControlLeaseUnavailable):
                watchdog.require_ready()
        finally:
            await watchdog.close()

    asyncio.run(exercise())


def test_reconnect_during_idle_check_cancels_the_pending_stop() -> None:
    async def exercise() -> None:
        watchdog, _now, _hal, invalidate, stop = make_watchdog()
        watchdog.motion_active = lambda: False
        release = asyncio.Event()

        async def axes_stationary():
            await release.wait()
            return False

        watchdog.axes_stationary = axes_stationary
        first = await confirm_mock_browser_lease(watchdog)
        watchdog.remove(first)
        await flush()
        second = await confirm_mock_browser_lease(watchdog)
        release.set()
        await flush()
        try:
            assert second in watchdog.clients
            invalidate.assert_not_called()
            stop.assert_not_awaited()
        finally:
            await watchdog.close()

    asyncio.run(exercise())


async def _until(condition) -> None:
    while not condition():
        await asyncio.sleep(0.005)


def test_owner_disconnect_allows_quick_reconnect_before_fail_safe_stop() -> None:
    async def exercise() -> None:
        watchdog, _now, _hal, invalidate, stop = make_watchdog()
        watchdog.disconnect_grace_s = 0.05

        async def send(_message):
            return None

        first = await confirm_mock_browser_lease(watchdog)
        watchdog.remove(first)
        await asyncio.sleep(0.01)
        second = watchdog.register(send)
        try:
            await watchdog.cycle()
            await flush()
            watchdog.require_ready()
            invalidate.assert_not_called()
            stop.assert_not_awaited()
            assert second in watchdog.clients
        finally:
            await watchdog.close()

    asyncio.run(exercise())


def test_hal_renewal_failure_never_reports_active_or_automatically_acknowledges() -> None:
    async def exercise() -> None:
        watchdog, _now, hal, invalidate, stop = make_watchdog()
        messages = []

        async def send(message):
            messages.append(message)

        session = watchdog.register(send)
        try:
            hal.command.side_effect = RuntimeError("lease transport unavailable")
            await watchdog.cycle()
            await flush()
            invalidate.assert_called_once()
            stop.assert_awaited_once()
            assert not any(message["data"].get("status") == "active" for message in messages)
            assert all(call.args[0] == "control.lease" for call in hal.command.call_args_list)
        finally:
            await watchdog.close()

    asyncio.run(exercise())


def test_slow_but_confirmed_hal_renewal_keeps_control_session() -> None:
    async def exercise() -> None:
        watchdog, _now, hal, invalidate, stop = make_watchdog()
        watchdog.register(AsyncMock())

        async def slow_renewal(_name, _payload):
            await asyncio.sleep(0.85)
            return {"response": {"ok": True, "leaseFresh": True, "timeoutMs": 2500}}

        hal.command.side_effect = slow_renewal
        try:
            await watchdog.cycle()
            watchdog.require_ready()
            invalidate.assert_not_called()
            stop.assert_not_awaited()
        finally:
            await watchdog.close()

    asyncio.run(exercise())


def test_unconfirmed_hal_renewal_still_trips_control_session() -> None:
    async def exercise() -> None:
        watchdog, _now, hal, invalidate, stop = make_watchdog()
        watchdog.register(AsyncMock())

        async def stalled_renewal(_name, _payload):
            await asyncio.sleep(1.35)
            return {"response": {"ok": True, "leaseFresh": True, "timeoutMs": 2500}}

        hal.command.side_effect = stalled_renewal
        try:
            await watchdog.cycle()
            with pytest.raises(ControlLeaseUnavailable):
                watchdog.require_ready()
            invalidate.assert_called_once()
            await flush()
            stop.assert_awaited_once()
        finally:
            await watchdog.close()

    asyncio.run(exercise())


def test_late_successful_renewal_cannot_reactivate_disconnected_session() -> None:
    async def exercise() -> None:
        watchdog, _now, hal, invalidate, stop = make_watchdog()
        watchdog.disconnect_grace_s = 0.0
        messages = []
        entered, release = asyncio.Event(), asyncio.Event()

        async def send(message):
            messages.append(message)

        async def delayed_renew(*_args):
            entered.set()
            await release.wait()
            return {"response": {"ok": True, "leaseFresh": True}}

        session = watchdog.register(send)
        try:
            hal.command.side_effect = delayed_renew
            pending = asyncio.create_task(watchdog.cycle())
            await entered.wait()
            watchdog.remove(session)
            release.set()
            await pending
            await flush()
            invalidate.assert_called_once()
            stop.assert_awaited_once()
            assert not any(message["data"].get("status") == "active" for message in messages)
        finally:
            await watchdog.close()

    asyncio.run(exercise())




def test_websocket_control_session_does_not_wait_for_initial_telemetry(tmp_path, monkeypatch) -> None:
    from backend.app import create_app
    from starlette.websockets import WebSocketState

    monkeypatch.setenv("APPSTATION_HAL_MODE", "test")
    app = create_app(tmp_path)
    app.state.telemetry.hardware = None

    async def exercise() -> None:
        active = asyncio.Event()
        inbox = asyncio.Queue()

        async def blocked_health():
            await asyncio.Event().wait()

        class Socket:
            client_state = WebSocketState.CONNECTED

            async def accept(self):
                pass

            async def send_json(self, message):
                if message["type"] == "control_lease" and message["data"]["status"] == "active":
                    active.set()

            async def receive_json(self):
                return await inbox.get()

        app.state.hal.health = blocked_health
        endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/ws")
        task = asyncio.create_task(endpoint(Socket()))
        try:
            await asyncio.wait_for(active.wait(), 0.5)
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await app.state.control_watchdog.close()
            app.state.telemetry.shutdown()

    asyncio.run(exercise())


def test_websocket_without_browser_heartbeats_keeps_hal_lease(tmp_path, monkeypatch) -> None:
    from backend.app import create_app
    from starlette.websockets import WebSocketState

    monkeypatch.setenv("APPSTATION_HAL_MODE", "test")
    monkeypatch.setenv("APPSTATION_WS_PERIOD_SEC", "0.001")
    app = create_app(tmp_path)
    app.state.telemetry.hardware = None
    watchdog = app.state.control_watchdog
    watchdog.renew_interval_s = 0.01

    async def exercise() -> None:
        inbox = asyncio.Queue()
        active, stopped = asyncio.Event(), asyncio.Event()
        original_command = app.state.hal.command

        async def command(name, payload=None):
            if name == "motion.emergency_stop":
                stopped.set()
            return await original_command(name, payload)

        class Socket:
            client_state = WebSocketState.CONNECTED

            async def accept(self):
                pass

            async def send_json(self, message):
                if message["type"] == "control_lease" and message["data"]["status"] == "active":
                    active.set()

            async def receive_json(self):
                return await inbox.get()

        app.state.hal.command = command
        endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/ws")
        task = asyncio.create_task(endpoint(Socket()))
        try:
            await asyncio.wait_for(active.wait(), 1)
            await asyncio.sleep(0.2)
            assert not stopped.is_set()
            watchdog.require_ready()
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            await watchdog.close()
            app.state.telemetry.shutdown()

    asyncio.run(exercise())


def test_app_websocket_lease_allows_ack_idle_disconnect_keeps_lease_and_motion_disconnect_stops(tmp_path, monkeypatch) -> None:
    from backend.app import create_app
    from httpx import ASGITransport, AsyncClient
    from starlette.websockets import WebSocketDisconnect, WebSocketState

    monkeypatch.setenv("APPSTATION_HAL_MODE", "test")
    monkeypatch.setenv("APPSTATION_WS_PERIOD_SEC", "0.001")
    app = create_app(tmp_path)
    app.state.telemetry.hardware = None
    watchdog = app.state.control_watchdog
    watchdog.disconnect_grace_s = 0.0

    async def exercise() -> None:
        active, stopped = asyncio.Event(), asyncio.Event()
        commands_seen = []
        original_command = app.state.hal.command

        async def command(name, payload=None):
            commands_seen.append(name)
            result = await original_command(name, payload)
            if name == "motion.emergency_stop":
                stopped.set()
            return result

        class Socket:
            client_state = WebSocketState.CONNECTED

            def __init__(self):
                self.inbox = asyncio.Queue()

            async def accept(self):
                pass

            async def send_json(self, message):
                if self.client_state != WebSocketState.CONNECTED:
                    raise WebSocketDisconnect()
                if message["type"] == "control_lease" and message["data"]["status"] == "active":
                    active.set()

            async def receive_json(self):
                message = await self.inbox.get()
                if message is None:
                    self.client_state = WebSocketState.DISCONNECTED
                    raise WebSocketDisconnect()
                return message

        app.state.hal.command = command
        endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/ws")
        task = second = None
        try:
            # ASGITransport 不运行 startup；这里只用 Test HAL 与伪 WebSocket，不连接设备。
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
                response = await http.post("/api/motion/safety/acknowledge")
                assert response.status_code == 409
                assert app.state.commands.safety.latched
                assert "motion.acknowledge_estop" not in commands_seen
                socket = Socket()
                task = asyncio.create_task(endpoint(socket))
                await asyncio.wait_for(active.wait(), 1)
                assert "control.lease" in commands_seen
                watchdog.require_ready()
                http.headers["X-Control-Session"] = next(iter(watchdog.clients))
                response = await http.post("/api/motion/safety/acknowledge")
                assert response.status_code == 200
                assert response.json()["data"]["servoRestored"] is False
                assert not app.state.commands.safety.latched
                assert "motion.enable_side" not in commands_seen

                # 空闲时断开：不急停、不锁存，后端继续续租；无会话时不能确认或运动。
                await socket.inbox.put(None)
                await task
                renewals = commands_seen.count("control.lease")
                await asyncio.sleep(0.7)
                assert commands_seen.count("control.lease") > renewals
                assert "motion.emergency_stop" not in commands_seen
                assert not app.state.commands.safety.latched
                assert not watchdog.clients
                with pytest.raises(ControlLeaseUnavailable):
                    watchdog.require_ready()
                assert (await http.post("/api/motion/safety/acknowledge")).status_code == 409

                # 重连后无需确认安全态；运动操作进行中断开则急停并锁存。
                active.clear()
                socket = Socket()
                second = asyncio.create_task(endpoint(socket))
                await asyncio.wait_for(active.wait(), 1)
                watchdog.require_ready()
                with app.state.commands.safety.operation():
                    await socket.inbox.put(None)
                    await asyncio.wait_for(stopped.wait(), 1)
                assert app.state.commands.safety.latched
                assert not app.state.policy.auto_status()["running"]
                response = await http.post("/api/motion/safety/acknowledge")
                assert response.status_code == 409
                assert commands_seen.count("motion.acknowledge_estop") == 1
                assert not watchdog.clients
        finally:
            for pending in (task, second):
                if pending is not None and not pending.done():
                    pending.cancel()
                    try:
                        await pending
                    except asyncio.CancelledError:
                        pass
            await watchdog.close()
            app.state.telemetry.shutdown()

    asyncio.run(exercise())


def test_app_disconnect_after_jog_reply_stops_while_hal_reports_axis_moving(tmp_path, monkeypatch) -> None:
    """单段点动应答后后端运动操作已结束，但 HAL 反馈轴仍在移动；此时断开浏览器必须急停。"""
    from backend.app import create_app
    from starlette.websockets import WebSocketDisconnect, WebSocketState

    monkeypatch.setenv("APPSTATION_HAL_MODE", "test")
    monkeypatch.setenv("APPSTATION_WS_PERIOD_SEC", "0.001")
    app = create_app(tmp_path)
    app.state.telemetry.hardware = None
    watchdog = app.state.control_watchdog
    watchdog.disconnect_grace_s = 0.0

    async def exercise() -> None:
        active, stopped = asyncio.Event(), asyncio.Event()
        original_command = app.state.hal.command
        original_state = app.state.hal.motion_state

        async def command(name, payload=None):
            result = await original_command(name, payload)
            if name == "motion.emergency_stop":
                stopped.set()
            return result

        async def motion_state():
            state = await original_state()
            state["moving"] = [False] * 3 + [True] + [False] * 8
            return state

        class Socket:
            client_state = WebSocketState.CONNECTED

            def __init__(self):
                self.inbox = asyncio.Queue()

            async def accept(self):
                pass

            async def send_json(self, message):
                if self.client_state != WebSocketState.CONNECTED:
                    raise WebSocketDisconnect()
                if message["type"] == "control_lease" and message["data"]["status"] == "active":
                    active.set()

            async def receive_json(self):
                message = await self.inbox.get()
                if message is None:
                    self.client_state = WebSocketState.DISCONNECTED
                    raise WebSocketDisconnect()
                return message

        app.state.hal.command = command
        endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/ws")
        socket = Socket()
        task = asyncio.create_task(endpoint(socket))
        try:
            await asyncio.wait_for(active.wait(), 1)
            watchdog.require_ready()
            app.state.commands.safety.acknowledge(app.state.commands.safety.capture())
            assert not app.state.commands.safety.latched
            assert not app.state.commands.safety.operation_active()
            app.state.hal.motion_state = motion_state
            await socket.inbox.put(None)
            await task
            await asyncio.wait_for(stopped.wait(), 2)
            assert app.state.commands.safety.latched
            assert not watchdog.clients
        finally:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
            await watchdog.close()
            app.state.telemetry.shutdown()

    asyncio.run(exercise())


def test_ack_response_after_lease_loss_does_not_clear_backend_latch(tmp_path, monkeypatch) -> None:
    from backend.app import create_app
    from httpx import ASGITransport, AsyncClient

    monkeypatch.setenv("APPSTATION_HAL_MODE", "test")
    app = create_app(tmp_path)
    watchdog = app.state.control_watchdog

    async def exercise() -> None:
        entered, release = asyncio.Event(), asyncio.Event()
        original_command = app.state.hal.command

        async def command(name, payload=None):
            if name == "motion.acknowledge_estop":
                entered.set()
                await release.wait()
            return await original_command(name, payload)

        app.state.hal.command = command
        session = await confirm_mock_browser_lease(watchdog)
        try:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
                http.headers["X-Control-Session"] = session
                pending = asyncio.create_task(http.post("/api/motion/safety/acknowledge"))
                await entered.wait()
                watchdog.trip("lost during HAL acknowledgement")
                release.set()
                response = await pending
                assert response.status_code == 409
                assert app.state.commands.safety.latched
        finally:
            await watchdog.close()
            app.state.telemetry.shutdown()

    asyncio.run(exercise())


def test_backend_renews_without_any_browser_response():
    async def exercise():
        watchdog, now, hal, invalidate, stop = make_watchdog()
        messages = []
        async def send(message):
            messages.append(message)
        watchdog.register(send)
        try:
            for tick in range(121):
                now[0] = tick * 0.5
                await watchdog.cycle()
                watchdog.require_ready()
                await flush()
            assert hal.command.await_count == 121
            assert len(messages) == 1
            assert messages[0]["data"]["renewalOwner"] == "backend"
            invalidate.assert_not_called()
            stop.assert_not_awaited()
        finally:
            await watchdog.close()
    asyncio.run(exercise())


def test_slow_browser_send_does_not_block_renewal_and_is_cancelled_on_close():
    async def exercise():
        watchdog, now, hal, invalidate, _stop = make_watchdog()
        entered, release = asyncio.Event(), asyncio.Event()
        async def send(message):
            entered.set()
            await release.wait()
        watchdog.register(send)
        try:
            await watchdog.cycle()
            await entered.wait()
            await asyncio.sleep(0.55)
            now[0] = 1
            await watchdog.cycle()
            watchdog.require_ready()
            assert hal.command.await_count == 2
            invalidate.assert_not_called()
            assert len(watchdog._send_tasks) == 1
        finally:
            await watchdog.close()
        assert not watchdog._send_tasks
    asyncio.run(exercise())


def _app_for_stationary_check(tmp_path, monkeypatch):
    from backend.app import create_app

    monkeypatch.setenv("APPSTATION_HAL_MODE", "test")
    app = create_app(tmp_path)
    app.state.telemetry.hardware = None
    return app


@pytest.mark.parametrize("scenario,expected", [
    ("fresh_stationary", True),
    ("pre_disconnect_cache", False),
    ("fresh_moving_then_stopped", False),
    ("read_busy_then_fresh", True),
])
def test_app_stationary_check_only_trusts_samples_taken_after_disconnect(tmp_path, monkeypatch, scenario, expected) -> None:
    """断线前 75 ms 的静止缓存可能早于刚下发的点动；新采样明确在动时不得等它自行停下再判空闲。"""
    from backend.core.logging import now_ms

    app = _app_for_stationary_check(tmp_path, monkeypatch)
    calls = []
    cached_stamp = now_ms() - 75  # 读卡缓存的采样时刻固定，早于断线

    async def motion_state():
        calls.append(1)
        if scenario == "read_busy_then_fresh" and len(calls) == 1:
            raise RuntimeError("dds-motion-state channel is busy; request was not queued")
        moving = [False] * 12
        if scenario == "fresh_moving_then_stopped" and len(calls) == 1:
            moving[3] = True
        stamp = cached_stamp if scenario == "pre_disconnect_cache" else now_ms() + 1  # 新读卡完成于检查开始之后
        return {"timestamp_ms": stamp, "moving": moving}

    monkeypatch.setattr(app.state.hal, "motion_state", motion_state)
    try:
        assert asyncio.run(app.state.control_watchdog.axes_stationary()) is expected
        if scenario == "fresh_moving_then_stopped":
            assert len(calls) == 1
    finally:
        app.state.telemetry.shutdown()


@pytest.mark.parametrize("detail,expected", [
    ({"sample": {"statusValid": True, "gGTO": 1, "gOBJ": 0}}, False),
    ({"sample": {"statusValid": True, "gGTO": 1, "gOBJ": 3}}, True),
    ({"sample": {"statusValid": True, "gGTO": 1, "gOBJ": 2}}, True),
    ({"sample": {"statusValid": True, "gGTO": 0, "gOBJ": 0}}, True),
    ({"sample": {"statusValid": False, "gGTO": 1, "gOBJ": 3}}, False),
    ({"stale": True, "sample": {"statusValid": True, "gGTO": 1, "gOBJ": 3}}, False),
])
def test_app_stationary_check_requires_recently_commanded_gripper_to_be_stopped(tmp_path, monkeypatch, detail, expected) -> None:
    from backend.core.logging import now_ms

    app = _app_for_stationary_check(tmp_path, monkeypatch)
    app.state.commands._gripper_unconfirmed_since_ms["left"] = now_ms() - 60_000  # 远早于断线，不依赖时间窗

    async def motion_state():
        return {"timestamp_ms": now_ms() + 1, "moving": [False] * 12}

    async def command(name, payload=None):
        assert name == "teleop.native.status"
        stamp = now_ms() - 5000 if detail.get("stale") else now_ms() + 1
        return {"response": {"grippers": {"left": {"positionSampleTs": stamp, "sample": detail["sample"]}}}}

    monkeypatch.setattr(app.state.hal, "motion_state", motion_state)
    monkeypatch.setattr(app.state.hal, "command", command)
    try:
        assert asyncio.run(app.state.control_watchdog.axes_stationary()) is expected
        # 确认停止后清除待确认；否则保留到下次断线继续核对。
        assert ("left" in app.state.commands.unconfirmed_gripper_sides()) is (not expected)
    finally:
        app.state.telemetry.shutdown()


def test_app_motion_activity_includes_inflight_gripper_command(tmp_path, monkeypatch) -> None:
    app = _app_for_stationary_check(tmp_path, monkeypatch)
    try:
        watchdog = app.state.control_watchdog
        assert watchdog.motion_active() is False
        app.state.commands._gripper_motion_inflight = 1
        assert watchdog.motion_active() is True
    finally:
        app.state.telemetry.shutdown()


def test_app_stationary_check_rejects_sample_in_same_millisecond_as_check_start(tmp_path, monkeypatch) -> None:
    """整数毫秒下同一毫秒的样本无法证明晚于断线；时间戳不推进时必须判为未确认。"""
    import backend.app as app_module

    app = _app_for_stationary_check(tmp_path, monkeypatch)
    frozen = 1_800_000_000_000
    monkeypatch.setattr(app_module, "now_ms", lambda: frozen)

    async def motion_state():
        return {"timestamp_ms": frozen, "moving": [False] * 12}

    monkeypatch.setattr(app.state.hal, "motion_state", motion_state)
    try:
        assert asyncio.run(app.state.control_watchdog.axes_stationary()) is False
    finally:
        app.state.telemetry.shutdown()
