# 近期改动审核

> 本文保留修复前的审核证据。用户随后授权的修复已完成，当前结果见 [修复记录](D:/E2EAPP_MicroMani/output/fix-20260911/FIXES.md)。

日期：2026-09-11。基线：当前工作区相对 `HEAD 6d898c9`，以及会话摘要涉及的新增前端模块。`SESSION_SUMMARY.md` 作为待核实的改动说明，未把其中的后续建议当成执行指令。

结论：前端分包、移除重型依赖、统一运动命令状态的方向合理，但本批仍有 **4 项 P1、5 项 P2**。设置拆分存在控制接线与功能迁移遗漏；构建通过不足以认定迁移验收完成。此次只做审核和离线复现，未修复业务源码、未提交、未启动硬件栈或操作设备。

## 确认的问题

### 1. P1：力觉卡读数选错硬件侧

位置：[SettingsView.tsx:250](D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx:250)。

`values` 直接按操作者 `side` 选择 `forceLeft/forceRight`，遗漏原有 `hardwareSideForOperatorSide()` 转换。[ForceSensorCard.tsx:86](D:/E2EAPP_MicroMani/frontend/src/views/settings/ForceSensorCard.tsx:86) 中设备状态、曲线、标定和 Tare 仍按转换后的硬件侧处理；数值和安全色却取另一侧，导致同一卡片内部互相矛盾。

离线复现：硬件左 Fx=0.014 N、右 Fx=1.527 N，操作者左卡显示 **14 mN**，应为 **1527 mN**。现有图表测试只检查曲线数据，因此未覆盖这个错误。

建议：在卡片入口统一转换侧别，或让卡片自行从同一硬件侧切片派生数值、状态和操作；增加两侧数值明显不同的回归。

### 2. P1：“应用配置”被改为 HAL 重连，丢失重新应用能力

位置：[SettingsView.tsx:173](D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx:173)。

原入口调用 `applyConfig(config)`，现在调用无配置请求体的 `reconnectHal()`。两条接口不等价。

具体触发链：

1. 轴使能时编辑力觉/安全阈值；[telemetry.ts:2289](D:/E2EAPP_MicroMani/frontend/src/stores/telemetry.ts:2289) 先更新本地配置，再异步保存。
2. [backend/app.py:826](D:/E2EAPP_MicroMani/backend/app.py:826) 保存前调用 `force.configure`；[HalCommandDispatcher.cpp:60](D:/E2EAPP_MicroMani/hal/src/HalCommandDispatcher.cpp:60) 在轴使能或运动时拒绝，配置未落盘，而前端只记日志，没有回滚本地值。
3. 解除条件后点“应用配置”，当前入口仅调用 `hal.reconnect`。[HalCommandDispatcher.cpp:39](D:/E2EAPP_MicroMani/hal/src/HalCommandDispatcher.cpp:39) 只尝试 Omega 就绪并返回健康状态，没有提交或应用界面配置。

因此用户无法通过原来的恢复入口重新应用参数，界面阈值与实际运行阈值可持续不一致。离线按钮复现确认：`reconnectHal` 调用 1 次，`applyConfig` 调用 0 次。没有在实机上验证拒绝流程；该部分依据两端源码调用链。

建议：恢复带当前配置的应用入口、执行中状态及明确的成功/拒绝反馈；不要把重连成功当作配置应用成功。

### 3. P1：回工作原点共享等待状态被置空

位置：[SettingsView.tsx:336](D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx:336)。

传给左右 `TeleopHandCard` 的 `pendingReturnOriginSide` 恒为 `null`，setter 是空函数，使原先的 loading 和双侧互斥失效。[TeleopHandCard.tsx:160](D:/E2EAPP_MicroMani/frontend/src/views/settings/TeleopHandCard.tsx:160) 虽然仍写等待状态，但不会产生实际效果。

离线复现：保持第一个回原点 API Promise 未完成，依次点击左、左、右，实测发送 **3 次**，原有约束应仅发送 **1 次**。这是前端重复下发证据，不代表已证明 HAL 会同时执行三条运动。

建议：恢复有效共享状态，覆盖重复点击和另一侧点击；考虑按设备命令的生命周期管理，避免 Tab 卸载后丢失进行中状态。

### 4. P1：懒加载失败会卸载整页，包括全局急停入口

位置：[App.tsx:95](D:/E2EAPP_MicroMani/frontend/src/App.tsx:95)，其它业务路由同样适用。

路由仅提供 `Suspense` 加载占位，没有捕获失败的错误边界。分块 404、网络中断或旧页面引用已被更新的资源时，动态导入拒绝会穿透到 React 根节点。

隔离 Edge 浏览器已复现：主页正常后，将模型页 JS 分块响应改为 404，再点击“模型”。结果为 `Failed to fetch dynamically imported module`，`#root` 子节点从 **1→0**，全局急停按钮从 **1→0**，页面空白。测试阻断所有后端 HTTP 和 WebSocket 请求；未调用设备。

建议：在业务页内容外增加错误边界，使导航、状态和急停保留；提供明确的重新加载/恢复入口，并验证分块失败及页面渲染异常。

证据：[浏览器结果](D:/E2EAPP_MicroMani/output/review-20260911/lazy-load-repro.json)、[失败截图](D:/E2EAPP_MicroMani/output/review-20260911/lazy-after.png)、[复现脚本](D:/E2EAPP_MicroMani/output/review-20260911/lazy-load-repro.mjs)。

### 5. P2：旧夹爪请求的失败响应覆盖最新命令

位置：[telemetry.ts:2584](D:/E2EAPP_MicroMani/frontend/src/stores/telemetry.ts:2584)。

成功回调检查 `requestId`，失败回调没有检查，却直接写命令进度，并可能回滚启停配置。夹爪页面允许连续发命令，因此响应乱序可触发。

实际函数提取后的内存 Promise 复现：`open(1) → stop(2) → stop 成功`，状态为 `accepted / stop / 2`；之后 `open(1)` 失败，状态倒退为 `failed / open / 1`。若旧失败先到，较新成功还会因 requestId 不匹配而被丢弃。

建议：成功、失败和配置回写统一校验请求归属；补充真实请求分支的乱序完成回归。

### 6. P2：夹爪仅入队就被显示为“反馈正常”

位置：[gripperDisplay.ts:63](D:/E2EAPP_MicroMani/frontend/src/gripperDisplay.ts:63)。

展示函数把 `running && side.ok` 解释为反馈健康。但 [NativeTeleopController.cpp:630](D:/E2EAPP_MicroMani/hal/src/NativeTeleopController.cpp:630) 在 worker 仅入队时就设置 `ok=true`、`message="queued native gripper command"`；真实执行结果之后才回写。[gripper_backend.py:138](D:/E2EAPP_MicroMani/backend/services/gripper_backend.py:138) 原样映射这些字段。

将该真实格式的 queued 数据输入展示函数，结果为 `ok`，对应绿色“反馈正常”。在串口忙、设备尚未响应时，这个状态可能覆盖此前异常。它与合理的“命令已接受”提示不是同一含义。

建议：对入队状态显示待确认；长期应采用可验证的执行/反馈状态契约，避免用复用的 `ok` 字段推导设备健康。

### 7. P2：数据存储配置入口遗漏

位置：[SettingsView.tsx:205](D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx:205)。

“系统连接”只挂载 HalCard，原 StorageCard 未迁入其它模块。当前 `src` 已无 `datasetRoot`、`recordFps` 编辑入口，但录制后端仍使用这些配置，相机卡仍提示去数据存储设置录制 FPS。

离线复现：访问 `/settings#storage` 后找不到目标卡片。建议恢复录制根目录、FPS 等原有存储配置入口，并校验实际保存结果。

### 8. P2：PICO 的既有定位链接落到错误 Tab

位置：[SettingsView.tsx:68](D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx:68)。

`startsWith('teleop')` 把精确的 `#teleop` 也映射到“遥操作”，但 [PicoVisionCard.tsx:78](D:/E2EAPP_MicroMani/frontend/src/views/settings/PicoVisionCard.tsx:78) 仍使用 `id="teleop"`，且仅在“视觉”Tab 挂载。

离线复现：访问 `/settings#teleop`，目标 PICO 卡不存在。建议先精确匹配 PICO 锚点，再处理 `teleop-left/right`，或统一调整锚点与所有入口。

### 9. P2：后端测试耦合前端物理文件布局

位置：[test_hal_source_contracts.py:1193](D:/E2EAPP_MicroMani/backend/tests/test_hal_source_contracts.py:1193)、[test_hal_source_contracts.py:1821](D:/E2EAPP_MicroMani/backend/tests/test_hal_source_contracts.py:1821)。

两项测试仍直接读取 `SettingsView.tsx` 并搜索 `canCommandGripper` 与 HAL-native 文案，实际实现已搬到 [GripperCards.tsx:61](D:/E2EAPP_MicroMani/frontend/src/views/settings/GripperCards.tsx:61)。本次离线 pytest 两项均失败，证明普通前端文件拆分会破坏后端检查。

建议：必要源码契约检查更新到真实入口；交互与状态约束优先由前端行为测试验证，减少跨语言测试依赖组件文件名和字符串。

## 改动评价与剩余耦合

- 设置按域拆分提高了可读性，但壳层仍集中持有配置、历史、命令回调与局部等待状态。问题 1–3 表明此次不是完全等价迁移，需要按原入口逐项验收。
- [SettingsView.tsx:99](D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx:99) 仍无条件订阅历史，且第 130 行每 250ms 更新手动时钟；在非力觉、非手动 Tab 也会触发壳层更新。文件拆分不等于渲染隔离，性能收益需要实际测量。
- 运动使能请求与遥测确认集中到 controller，比两处独立乐观状态更容易维护；此次未发现另一个足够确定的新增运动控制器缺陷。确认仍只能证明请求后收到匹配遥测，不能证明硬件采样与命令严格因果。
- 前端包体已显著精简，但本次构建 JS 合计 **471,240 字节（约 471 KB）**，不是摘要中的约 370 KB；vendor 约 200 KB、入口约 96 KB、设置分块约 97 KB。未测实机操作延迟或长期内存表现。
- 后端/HAL/启停脚本核对 132 个跟踪文件：72 个 Python AST 相同、43 个 C++/IDL 去注释后相同、17 个脚本去注释正文相同。当前这批差异未引入后端/HAL 业务逻辑变化；这不代表对其全部历史实现完成安全审计。

## 验证结果

| 检查 | 实际结果 |
| --- | --- |
| `npm --prefix frontend run build`（包含 typecheck） | 通过 |
| 原有完整前端测试 | 177 项：157 通过，20 失败；失败均位于 App.test.tsx |
| 后端录制、HAL 协议、HAL 源码契约定向测试 | 179 项：177 通过，2 失败；失败为问题 9 |
| 本次设置专项正确行为复现 | 5 项均失败，分别证明问题 1、2、3、7、8；独立于默认测试集合 |
| 隔离浏览器分块失败 | 已复现根节点清空及全局急停入口消失 |
| 夹爪乱序响应/queued 状态 | 实际函数的内存替身复现 |

完整前端失败中，部分由旧 `.ant-btn-primary`、`switch` 角色、旧 ID/文案定位造成；不能把全部 20 项都判为运行缺陷，也不能据摘要把它们全部排除为无关失败。应逐项更新可观察行为断言后重新验收。

原有前端结果：[frontend-tests.json](D:/E2EAPP_MicroMani/output/review-20260911/frontend-tests.json)。设置专项：[settings-audit-tests.json](D:/E2EAPP_MicroMani/output/review-20260911/settings-audit-tests.json)、[专项代码](D:/E2EAPP_MicroMani/frontend/output/ui-redesign/review-settings.audit.tsx)。专项代码去掉 `.test` 后缀，不会给默认测试新增失败项。

复现命令（仓库根目录）：

```powershell
npm --prefix frontend test -- --config ../output/review-20260911/vitest-review.config.mjs --reporter=json --outputFile=../output/review-20260911/settings-audit-tests.json
node output/review-20260911/lazy-load-repro.mjs
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_dataset_recorder.py backend/tests/test_hal_protocol.py backend/tests/test_hal_source_contracts.py -q
```

设置专项当前返回非零是复现到缺陷的预期结果。浏览器脚本使用已安装 Edge 和当前构建产物，自行启停隔离静态服务器，并拦截后端和 WebSocket 请求。

建议顺序：先修复问题 1–4，再修复夹爪语义/竞态、补回配置与导航入口，最后清理测试耦合并执行相应回归。未进行 C++ 编译、实机运动、长时间运行或全站视觉验收；与本批重构无关的未跟踪资料及其他项目目录未纳入审核。
