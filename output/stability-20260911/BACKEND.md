# 后端模块故障隔离审核与修复

日期：2026-09-11。工作目录：`D:\E2EAPP_MicroMani`。本轮聚焦 3 类高影响异常传播问题，未重复修改前轮急停代际保护。

后续已追加 DDS 阻塞隔离及浏览器控制租约；该阶段的改动、65 项相关回归、9 项路由回归与工程限制记录于同目录 `CONTROL_LEASE.md`。下文保留初轮模块异常审查证据。

## 结论与修改范围

当前后端没有单独的订阅广播总线。每个 `/ws` 连接在自己的循环中串行读取 HAL、原生夹爪状态，再调用 `TelemetryHub.next_frame` 组帧并发送遥测及日志。独立模块异常会在这个串行汇合点传播。

本轮仅修改 `backend/app.py`，新增 `backend/tests/test_module_isolation.py`。以下结构在 `git show HEAD:backend/app.py` 中同样存在，属于原有缺陷；未将前端近期重构归为其原因。

### 1. [P1] 夹爪状态异常使运动、力遥测和日志持续停止发送

- 入口：`backend/app.py` 的 `websocket_endpoint`，修复后局部隔离位于约第 2103 行。
- 原行为：`await gripper_router.status(active_config)` 位于组帧及日志发送之前，只由整个 WS 循环外层捕获异常。持续的夹爪状态读取/解析错误导致循环反复休眠和重试，每次都在发送任何帧之前失败。
- 离线证据：让夹爪状态替身持续抛出 `RuntimeError`，原实现直到 1 秒看门狗超时仍不能完成 3 帧收集；共享通道内的日志同样无法送达。
- 修复：在夹爪读取边界捕获异常，生成明确的 `ok=false`、逐侧 `ok=false`、位置 `-1` 的不可用状态。运动、力和日志继续出帧。错误以限频日志记录，不把缺失反馈当成健康或已停止。
- 回归覆盖：持续失败、失败后恢复两条路径；故障期间正常运动位置仍送达，已有力急停 `safety.latched=true` 与 `dangerIndex=1.1` 保持不变，并确认错误日志实际送达。

### 2. [P1] HAL 健康读取异常会终止新连接或保留过期健康状态

- 入口：`backend/app.py` 的 WS 初始缓存与健康刷新，修复后约第 1978–2010 行。
- 原行为：首次 `hal.health()` 在保护循环和 `finally` 外执行，但客户端已加入 `ws_clients`。该次读取失败会直接退出，且未移除客户端标记。后续健康刷新失败则继续使用上一次 `connected=true` 的缓存，仍发送 `halOk=true`。
- 离线证据：首次读取替身抛错时协程直接失败；先成功再失败时，三帧均为 `halOk=true`，未表现中间一次健康读取丢失。
- 修复：初始状态设为离线，首次读取移入受保护循环；客户端登记置于对应 `try/finally` 前。每次健康读取失败立即将当前 HAL 状态标记为离线，后续成功读取可恢复健康。
- 回归覆盖：首读失败后恢复、运行中失败后恢复；帧健康序列分别为 `[false,true,true]` 和 `[true,false,true]`；连接结束后 `ws_clients` 为空。

### 3. [P2] 一个后台任务或相机清理异常使其他资源跳过释放

- 入口：`backend/app.py:shutdown_runtime_services`，修复后约第 789–801 行。
- 原行为：取消后台任务后仅忽略 `CancelledError`；如果任务在取消清理中改为抛出普通异常，后续相机及遥测资源释放不执行。相机 `close_all` 抛错也会跳过 `telemetry.shutdown`。
- 离线证据：分别注入“任务取消清理抛错”和“相机释放抛错”，原实现直接传播该异常，无法完成剩余资源清理断言。
- 修复：分别处理后台任务异常、相机释放异常和遥测释放异常，记录错误后继续后续独立清理。保持原清理顺序，不将资源释放失败写成健康状态。
- 回归覆盖：两种错误路径均确认遥测资源清理仍被调用，后台任务集合被清空，并有可见错误日志。

## 验证证据

所有测试均从仓库根目录使用项目虚拟环境执行。新测试直接调用路由协程，使用临时目录、HAL 替身、伪 WebSocket 和清理函数替身；不进入应用启动/设备连接生命周期。验证真实状态组帧语义的用例在创建替身应用后才切换模式，并将 `telemetry.hardware=None`，所有 HAL 数据均为 `AsyncMock` 返回值。

修复前，在校正测试夹具的合法日志频道后执行：

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_module_isolation.py -q --disable-warnings --tb=short
```

结果：`5 failed, 20 warnings in 3.81s`。失败对应夹爪导致发送饥饿、首次/后续健康读取异常和两种清理链中断。随后补充夹爪恢复路径，最终新增文件包含 6 项参数展开后的隔离回归。

修复后执行新隔离回归及已有 TelemetryHub 回归：

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_module_isolation.py backend/tests/test_telemetry_hub.py -q --disable-warnings --tb=short
```

最终结果：`12 passed, 24 warnings in 1.46s`。

现有 WebSocket 与应用关闭路由回归：

```powershell
$env:APPSTATION_HAL_MODE='test'
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_app.py -k 'websocket or app_shutdown' -q --disable-warnings --tb=short
```

结果：`6 passed, 160 deselected, 27 warnings in 2.18s`。具体测试：

1. `test_websocket_telemetry_frame_runs_off_event_loop`
2. `test_websocket_telemetry_compatibility_and_log_shape`
3. `test_websocket_reports_card0_dmc5c10_enabled_feedback_as_unknown`
4. `test_websocket_reconnect_cancels_runtime_shutdown`
5. `test_runtime_shutdown_skips_stop_stack_while_websocket_is_active`
6. `test_app_shutdown_closes_telemetry_hardware_resources`

`git diff --check -- backend/app.py backend/tests/test_module_isolation.py` 通过，只有 Git 的 LF/CRLF 提示。未安装依赖或启动实机服务。

## 真实边界与未测项

- 本轮验证的是可抛出异常的模块失败及其恢复；未验证设备 SDK 永久阻塞、操作系统线程无法退出、进程崩溃或真实 DDS/USB 断连时序。
- 保留现有线程模型和等待语义；没有新增硬超时、强杀线程、进程隔离或自动重连策略。
- 未对所有运动、Omega、力和相机字段的畸形数据逐项注入，未扩展到所有驱动及所有启动分支。
- 未重跑整套后端/前端/HAL 测试。相关警告为已有 FastAPI/Starlette 弃用和测试类收集提示；离线通过不代表实机可靠性已获验证。
