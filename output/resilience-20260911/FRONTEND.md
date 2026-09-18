# 浏览器主线程失效时的前端控制租约

日期：2026-09-11。保持浏览器、现有后端和 HAL 三个进程的部署结构，不增加服务、Worker、设备、接线或运行依赖。本报告中的 Node 进程仅是离线验证脚本的协议替身。

## 结果

真实模式下，新鲜遥测不能单独授予启动运动的资格；前端必须已回答当前 WebSocket 的安全挑战，并收到匹配挑战的执行侧租约确认。确认租约不会自动使能、启动、解除急停或发送 ACK。

- 未确认、过期或断开的租约阻止启动动作，ACK 也必须等待新鲜租约并由操作者显式发起。
- 停止、断使能与急停保留原有可发送路径。
- 主线程暂停后，后台计时器不会替页面续租；恢复时先检查单调时钟截止时间，积压挑战或确认不能复活旧会话。
- WebSocket 错误、卸载、页面/壳层渲染失败、全局 `error` 或 `unhandledrejection` 会撤销控制连接。先停止 WebSocket，再更新显示状态；显示订阅本身抛错也不会阻止传输关闭。
- 页面显示租约未确认/失效及恢复入口。租约可用但硬件仍锁定时，提示核对设备后显式确认；Safety 不再在缺少租约时显示绿色正常数值。
- mock 模式显式设置 `required: false`，仅隔离离线夹具；真实模式初始化缺租约即拒绝控制。

## 协议与防迟到边界

| 消息 | 字段 | 处理 |
| --- | --- | --- |
| 后端 `safety_challenge` | `sessionId`, `challengeId`, `ttlMs: 2000` | 只在当前 WS 的主线程 message 回调中应答；会话不匹配、非法期限、重复或超时挑战不会续旧会话 |
| 前端 `safety_heartbeat` | 同一 `sessionId`, `challengeId` | 不由 timer 或 Worker 生成；只响应收到的具体挑战 |
| 后端 `control_lease` | `sessionId`, `challengeId`, `status`, `ttlMs` | `active` 必须匹配本线程最近回答的挑战；`pending` 拒绝控制，`expired` 撤销连接 |

本地截止时间使用 `performance.now()`。确认的截止时间从本线程回答挑战时起算，不能从收到迟到确认时重新获得完整期限。前端计时器只有撤销能力；即使积压 message 比过期 timer 先调度，message 入口也会检查截止时间。

后端已约定每次 HAL 续租消耗新的已校验 nonce，不能反复使用旧应答延长租约。后端失联检查从最后有效应答起算 2000 ms；HAL 工程租约配置为 2500 ms。这些是现有软件架构的保护配置，不能表述为精确的物理停止时间或碰撞响应承诺。

## 离线验证

构建使用实际生产前端。独立静态服务器将 dist 加载为内存快照，只放行该快照的页面和资源；所有 API/媒体请求拦截，所有 WebSocket 使用协议替身。没有连接现有后端或 HAL。

`node output/resilience-20260911/browser-main-thread.mjs` 的最终结果：

| 注入方式 | 故障前有效应答 | 故障后有效应答 | Node 替身检测停止时间 |
| --- | ---: | ---: | ---: |
| CDP `Debugger.pause` 实际暂停主线程 2.8 秒 | 2 | 2 | 故障后约 1957 ms |
| CDP `Page.crash` 实际使渲染进程崩溃 | 2 | 2 | 故障后约 1940 ms |
| 实际未处理 Promise 拒绝 | 2 | 2 | 故障后约 5 ms |

暂停恢复后还验证：旧 WS 被关闭，积压挑战没有得到有效应答，ACK 不可用，全局急停仍可见。所有三个场景均未给旧会话续租，最终运行拦截 30 个非静态 HTTP 请求。

以上时间是 Node 协议替身的观测结果，不是实际后端/HAL的停止测量，更不是机械运动停止时间。实际后端和 HAL 的守护与命令拒绝测试由主任务分别验收。

其他验证：

- 前端 build / typecheck：通过。
- 租约协议、store/API、异常监听与可见状态：27 条定向测试通过。
- 包含既有 App、急停、夹爪和遥测入口的定向回归：157 条通过；新增显示断言后的错误边界测试 5 条通过。
- 本轮全部生产文件及测试文件定向 ESLint：通过。
- 最终全套验收 **341/341 通过**，无失败、无跳过，见 [frontend-tests.json](frontend-tests.json)。旧 Settings/Gripper 测试夹具已补齐真实协议或显式 mock 前提，并新增 7 项未确认/过期租约的拒绝回归；没有放宽生产安全条件。

## 文件入口

- `frontend/src/stores/controlLease.ts`：主线程挑战与确认的状态机；只有截止撤销计时器。
- `frontend/src/stores/telemetry.ts`、`frontend/src/utils/controlSafety.ts`：当前连接归属、控制门闩、ACK 条件、迟到流程取消。
- `frontend/src/utils/controlFaults.ts`、`frontend/src/App.tsx`：全局异常监听及对称解绑。
- `frontend/src/components/ModuleErrorBoundary.tsx`、`RouteErrorBoundary.tsx`：显示异常撤销控制。
- `frontend/src/components/ControlLeaseStatus.tsx`、`AppLayout.tsx`、`StatusBar.tsx`：明确显示未确认/失效状态。
- `browser-main-thread.json`：浏览器原始事件与时间记录。
- `main-thread-resumed.png`：主线程恢复后的拒绝控制状态。
- `frontend-targeted.json`：157 条回归结果。
