# 审核问题修复记录

日期：2026-09-11。对应 [原审核报告](D:/E2EAPP_MicroMani/output/review-20260911/REVIEW.md)。保留用户原有工作区改动，未提交、未操作实机。

## 已修复

| 原问题 | 修复结果与入口 |
| --- | --- |
| 力觉侧别错误 | [SettingsView.tsx:292](D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx:292) 统一操作者侧到硬件侧转换；回归覆盖读数、危险色、曲线和 Tare。 |
| 应用配置误接 HAL 重连 | [SettingsView.tsx:158](D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx:158) 恢复提交当前完整配置；添加等待、防重复、拒绝后重试，配置再次编辑后清除旧成功提示。 |
| 回原点等待状态失效 | [SettingsView.tsx:151](D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx:151) 恢复共享状态及同步锁；跨 Tab 保持互斥，成功/失败均释放。 |
| 懒加载失败清空整页 | [RouteErrorBoundary.tsx](D:/E2EAPP_MicroMani/frontend/src/components/RouteErrorBoundary.tsx) 仅隔离业务页，保留导航、遥测连接和全局急停；切换页面或重新加载可恢复。 |
| 旧夹爪响应覆盖新状态 | [telemetry.ts:2579](D:/E2EAPP_MicroMani/frontend/src/stores/telemetry.ts:2579) 成功、失败与延迟配置回读均检查归属；全量回读不会覆盖其间的新配置或另一侧请求。 |
| queued 被误标为反馈正常 | [gripperDisplay.ts:64](D:/E2EAPP_MicroMani/frontend/src/gripperDisplay.ts:64) 与 [hardwareStatus.ts:115](D:/E2EAPP_MicroMani/frontend/src/hardwareStatus.ts:115) 共用入队判据，显示待确认，不计入健康数量。 |
| 存储设置遗漏 | [StorageCard.tsx](D:/E2EAPP_MicroMani/frontend/src/views/settings/StorageCard.tsx) 恢复数据集目录与录制 FPS 编辑；FPS 限制为 1–60 整数，独立于相机采集 FPS。 |
| PICO hash 指向错误 Tab | 精确区分 `#teleop`/PICO 与 `#teleop-left/right`/主手，原链接正确挂载目标卡。 |
| 后端测试依赖旧前端文件布局 | [test_hal_source_contracts.py](D:/E2EAPP_MicroMani/backend/tests/test_hal_source_contracts.py) 改为设置域契约检查；实际夹爪入口是否被缓存配置阻止由前端行为测试验证。 |

验收过程中还恢复了启动回工作原点开关、全局快照恢复和两类快照删除；修正 [EpisodeControlPanel.tsx:154](D:/E2EAPP_MicroMani/frontend/src/components/record/EpisodeControlPanel.tsx:154) 进度底轨与填充同色的问题，恢复可访问的百分比语义。

设置页取消非活动 Tab 的主要遥测值订阅；历史订阅下放力觉卡，手动时钟下放仅运动 Tab 挂载的面板。未宣称具体性能或实机延迟改善。

## 验证

- 完整前端测试：**205/205 通过，无跳过**；原 App 测试 **82/82 通过**，原有 20 项失败已清理，同时保留原点、快照、录制进度和夹爪门闩的行为断言。
- 后端录制、HAL 协议和源码契约定向测试：**179/179 通过**。
- `npm --prefix frontend run build`：通过，包含 TypeScript 检查。
- 隔离 Edge 浏览器：模拟模型 JS 分块 404 后，根节点与急停保留；急停点击仍产生请求意图（测试拦截）；导航恢复、网络恢复后重新加载均通过。
- 改动相关 `git diff --check`：通过。
- 定向 ESLint：错误边界及夹爪相关检查通过；设置域仍有 **8 项既有规则问题**（hash/初次状态读取 effect、主手 pending 同步、shared 混合导出），没有执行额外的全仓 lint 清理。详见 [settings-eslint.json](D:/E2EAPP_MicroMani/output/fix-20260911/settings-eslint.json)。

结果文件：[前端测试](D:/E2EAPP_MicroMani/output/fix-20260911/frontend-tests.json)、[构建日志](D:/E2EAPP_MicroMani/output/fix-20260911/build.log)、[浏览器验证](D:/E2EAPP_MicroMani/output/fix-20260911/route-recovery.json)、[异常被隔离的截图](D:/E2EAPP_MicroMani/output/fix-20260911/route-error-contained.png)。

复现命令：

```powershell
npm --prefix frontend test
npm --prefix frontend run build
backend/.venv/Scripts/python.exe -m pytest backend/tests/test_dataset_recorder.py backend/tests/test_hal_protocol.py backend/tests/test_hal_source_contracts.py -q
node output/fix-20260911/verify-route-recovery.mjs
```

浏览器脚本自行启动隔离静态服务器，拦截所有后端和 WebSocket 请求；其 `Failed to fetch` 来自被主动阻断的后端请求，不代表分块异常逃逸或页面再次清空。

未进行 C++ 编译、实机运动和长期运行验证。重新加载沿用既有硬件句柄释放流程，不自动恢复先前硬件会话；错误页已提示这一影响。夹爪入队判定沿用现有 HAL 消息字段，未扩展为新的硬件反馈契约。
