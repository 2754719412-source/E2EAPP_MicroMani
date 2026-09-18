# 后端阻塞隔离与浏览器控制租约

2026-09-11，工作目录 `D:\E2EAPP_MicroMani`。保留现有前端、后端和 HAL 部署，不增加独立服务、外部模块、硬件或操作配置。全部验证使用离线替身，没有运行设备启动生命周期或连接实机。

## 已确认的问题与修复

1. `HEAD:backend/hal_client/dds_client.py` 直接在事件循环调用原生 publish/get_latest，把 wait_for_command_reply 放入共享 `asyncio.to_thread`。原生调用堵塞可冻结事件循环，或占满配置、遥测、清理共用的线程池；协程取消本身也不能取消原生调用。
2. 原有 WS 没有验证浏览器主线程是否仍可处理消息；进程存活或 TCP 连接存在不能说明主线程响应正常。
3. 新增租约还必须防止旧应答重复续租、在途 HAL 续租确认错误绑定到后续 nonce，以及本地失联后 HAL 租约尚未到期时直接调用 HTTP ACK。以上边界均已补回归。

主要文件：`backend/hal_client/bounded_lane.py`、`backend/hal_client/dds_client.py`、`backend/services/control_watchdog.py`、`backend/app.py`、`backend/services/command_service.py`。`protocol.py` 加入控制租约命令，`TestHalClient` 明确模拟 `leaseFresh=true`。

### DDS 调用通道

- 普通命令 4 个槽、急停 1 个槽、租约 1 个槽、缓存读取 2 个槽、关闭 1 个槽；各自独立，无等待队列。容量耗尽即拒绝，不把动作藏入等待队列。
- 每次调用使用有容量限制的 daemon 线程；不使用默认 executor。调用方超时/取消后，原生线程仍占槽，直到实际退出才释放。取消发生在工作线程真正执行前时，不再运行其函数。
- 普通动作发送 `commandExpiresAtUnixMs`；值由后端创建，覆盖调用方输入。HAL 接收端检查消费时限（另由 HAL 代理验证），应答超时后不自动补发非幂等动作。
- 原生控制调用超时、取消、异常或无应答使控制传输进入隔离，同步触发旧操作/策略失效，并停止续租；不自动恢复。停止入口仍可尝试，普通动作与 ACK 被拒绝。
- 急停与 lease 的原生等待上限均为 0.5 秒，外层等待另有 0.05 秒调度余量。急停无应答、原生异常或 HAL 拒绝也停止续租，防止健康心跳掩盖急停通道失败。安全停止命令保留原有幂等重试策略，已阻塞的原生调用不释放槽、不重新排队。
- 关闭时若仍有原生调用持有句柄，保留句柄并记录错误，避免提前释放后使用；等待原生 close 也不占事件循环/默认池。永久阻塞故障需要重启原有进程，不自动恢复运动。

GIL 核查：当前绑定由 `backend/hal_client/dds_runtime.py:57` 的 `ctypes.CDLL` 加载，publish/get_latest/wait 均走该 CDLL 的 C 导出；本地 Python `ctypes.CDLL.__doc__` 明确调用期间释放 GIL，原生导出没有回调 Python。本结论不涵盖未来改成 `PyDLL` 或未知 SDK 回调的情况。

线程创建开销在本机做过 500 次无操作调用抽样：中位数 0.339 ms，P95 0.451 ms，总计 176.3 ms。这是 Python 空调用测量，不是 DDS、设备延迟或生产性能保证；保留当前简单有界实现，没有引入持久 worker 服务。

### WS 与执行租约契约

`/ws` 独立接收主线程应答，监控任务不依赖遥测组帧或默认线程池。每个已登记 WS 都必须健康，任一断开或过期会调用原有完整急停并清空待执行策略动作，不丢弃已经录下的 episode。

```json
{"type":"safety_challenge","data":{"sessionId":"每个WS独立UUID","challengeId":"随机nonce","ttlMs":2000}}
{"type":"safety_heartbeat","data":{"sessionId":"对应WS","challengeId":"对应nonce"}}
{"type":"control_lease","data":{"sessionId":"对应WS","challengeId":"实际续租消耗的nonce","status":"active","ttlMs":2500}}
```

- 挑战间隔 500 ms，一次最多一个未回答挑战。服务器只接受当前 session 的匹配 nonce；应答和周期检查都按 `last_response_at + 2000 ms` 判断，初始使用连接登记时间。不能靠下一挑战较晚的 deadline 接受已经失联的浏览器。
- 每次 HAL 续租必须消耗所有已登记 WS 的新 nonce。返回 `active` 前要求 HAL 明确确认，且仍是同一会话代际；在途期间收到的新 nonce 不能被冒认为已经续租。
- 续租使用既有紧急 DDS topic，命令为 `control.lease`，payload 为 `{sessionId,sequence,timeoutMs:2500,issuedAtUnixMs}`。HAL 区分租约与急停并校验时间/序列；不改 DDS IDL。
- ACK 路由在发送 HAL ACK 前和返回后均检查 `require_ready()`：要求当前全部浏览器健康、HAL 已确认的当前代际租约有效。没有应答、仅有待确认应答、断连/超时、在途 ACK 期间失联均返回 409 并保持本地锁存。确认不恢复伺服、不启动运动。
- Test HAL 模式走同一 WS/ACK 规则；其 lease 命令返回明确的模拟确认，不静默绕过规则。旧 ACK 正向回归显式完成挑战/应答/租约确认夹具。

## 实际验证

最终相关测试：

```powershell
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_control_watchdog.py backend/tests/test_dds_blocking_isolation.py backend/tests/test_hal_dds_client.py backend/tests/test_hal_protocol.py backend/tests/test_module_isolation.py backend/tests/test_control_stop_races.py -q --disable-warnings --tb=short
```

结果：`65 passed, 60 warnings in 4.42s`。其中新增 watchdog 10 项、阻塞隔离 9 项；覆盖：普通 publish/reply 堵满、默认池不可用、缓存读取堵塞、超时槽保留、关闭不提前释放句柄、线程尚未执行即取消、急停堵塞/无应答/原生异常/拒绝、错误/迟到/复用 nonce、多 WS、续租在途会话变化、ACK 恢复边界。

完整接入回归 `test_app_websocket_lease_confirmation_allows_ack_and_disconnect_blocks_it` 直接运行真实 `/ws` 路由协程与 HTTP ASGI ACK 路由，用伪 Socket 和 Test HAL 替换外部边界：未建立租约 ACK=409且未发 HAL ACK → challenge/response → HAL lease 确认 → ACK=200且伺服不恢复 → WS 断连触发完整急停/策略关闭 → ACK立即409。另有主线程持续不应答及 ACK 在途失联回归。均不运行 app startup 设备生命周期。

已有 WS、急停、ACK、关闭回归：

```powershell
$env:APPSTATION_HAL_MODE='test'
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_app.py -k 'websocket or app_shutdown or emergency_stop or acknowledge_safety' -q --disable-warnings --tb=short
```

结果：`9 passed, 157 deselected, 39 warnings in 3.50s`。

相关生产模块 `py_compile` 通过；相关文件 `git diff --check` 通过，只有 LF/CRLF 提示。本轮未重跑完整后端集合，历史完整 app 测试的原生 DDS DLL 环境限制见 `output/safety-20260911/BACKEND_VALIDATION.md`。跨层 HAL 编译/测试和真实浏览器替身测量由根代理汇总，不在本文冒充为已完成的后端结果。

## 真实限制

- 2 秒浏览器应答窗口、2500 ms HAL 租约和轮询周期是工程配置，不是调度硬截止或物理停止时间；不能据此保证固定 4.5 秒内实体静止。
- Python 无法安全强杀已阻塞的 C 调用；此实现限制其容量并拒绝迟到请求，无法捕获进程访问违规、系统崩溃、控制器失效。DDS 初始化仍在启动阶段同步执行；尚未建立执行租约时不能放行真实运动。
- 相机/配置/遥测原有后台池没有在本轮全部替换；它们阻塞时控制监控和 DDS 急停不再依赖该共享池。线程/操作系统整体失效时仍依赖 HAL 层租约，而 HAL/整机同时失效的物理停机属于现有硬件边界。
- 保持现有 DMC3000+DMC5C10 与无实体急停按钮的架构；本轮不增加接线、硬件、外部模块或额外服务。离线替身通过不等同于实机安全验收。
