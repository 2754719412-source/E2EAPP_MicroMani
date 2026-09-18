# 前端组件与页面异步稳定性复核

日期：2026-09-11。范围：轻量 UI 组件、Canvas 图表，以及 Model、FineTune、Dataset 页面请求生命周期。保留此前安全与布局修改；本轮未修改 CSS、API、store、连接 hook、后端或 HAL。

## 已证实并修复

### P2：Model / FineTune 请求拒绝逃逸，旧响应覆盖新状态

- 原始隔离布局浏览器记录的 14 个 `Failed to fetch`，对应两页在 7 个窗口宽度下的初始列表请求，均未捕获 Promise 拒绝。
- 初始读取、导入/启动、创建/取消等操作统一捕获错误，页面显示错误与读取重试入口。Model 在真实模式不再用静态“ready”模型掩盖尚未读取的列表。
- 请求序号决定回写归属。新操作开始或页面卸载后，旧请求不能回写，也不能在迟到完成后继续发送列表刷新。
- 操作按钮的 pending 覆盖命令与后续列表刷新全程，阻止重复启动/创建；保留 Stop / Cancel 入口以终止当前任务。
- 文件：`frontend/src/views/ModelView.tsx`、`frontend/src/views/FineTuneView.tsx`。
- 证据：先补 10 条回归，旧代码 9 条失败并出现 4 个未处理拒绝；修复后 10 条通过。

### P2：Dataset 修改失败仍显示已删除/已复核，跨数据集污染同名 episode

- 删除数据集或 episode 时，旧代码先永久加入本地过滤集合；即使后端拒绝，当前页面也无法找回条目。标记和重命名同样在后端确认前覆盖显示。
- 不同数据集的真实 episode ID 常重复，例如 `episode_000001`。旧本地删除、名字和状态覆盖只使用 episode ID，操作 A 会影响 B。
- 现在真实请求成功后才应用本地结果；失败保留原条目和复核值，重命名失败保留编辑内容。修改在途时阻止重复提交，卸载后不再续发列表请求。
- 本地 episode 标识改为 `[datasetId, episodeId]` 的组合；重命名捕获打开对话框时所属数据集。
- 文件：`frontend/src/views/DatasetView.tsx`。

### P2：Dataset 详情失败被永久记为已读取，迟到错误污染新选择

- 旧代码在 `finally` 中记录已请求 key，网络失败后重新选中同一条也不再请求；所有详情响应还能修改当前页共享错误状态。
- 只缓存成功详情；切换条目/卸载时撤销旧请求回写资格，迟到错误不能覆盖当前成功结果。
- 错误提供“重试读取”；失败后重新选择原条目也会重新请求。
- 证据：上述 Dataset 原始 5 条最小用例全部失败；修复后扩充的 10 条用例全部通过，覆盖失败保持、组合标识、重复提交、卸载续发和乱序详情结果。

## 验证

- `npm --prefix frontend test -- src/views/DatasetView.lifecycle.test.tsx src/views/TaskPages.lifecycle.test.tsx src/DatasetView.lazy.test.tsx`：3 个文件，21 / 21 通过。
- 本轮 3 个生产文件与 2 个测试文件定向 ESLint：通过。
- `node --check output/stability-20260911/components-browser.mjs`：通过。
- 最终 dist 浏览器复验：`node output/stability-20260911/components-browser.mjs` 通过。2 页 × 7 宽度共 14 个场景，初始读取失败、重试失败、提交失败均显示可见错误；全局急停始终可见；`pageErrors: []`。共拦截 111 个非静态请求，WebSocket 同样在发送前拦截。完整记录：`components-browser.json`。
- 整体 typecheck、build、全套测试由主任务统一执行，避免并行重复。

## 其余审查范围与限制

- `components/ui.tsx` 的按钮 loading/disabled 使用原生 disabled，数值输入、开关和下拉也传递 disabled；未发现本轮足以证明崩溃的新增缺陷，未作推测性改写。
- `components/Charts.tsx` 在效果清理时 disconnect ResizeObserver；空 Canvas context 可正常返回。历史遥测结构约束由主任务在帧接收边界处理，本轮未重复引入全套组件级校验。
- Promise 与外部回调中的错误不应仅依靠 React ErrorBoundary，故上述网络错误在调用方接住；壳层模块隔离由主任务独立处理。
- 本次为离线前端验证，不代表后端任务执行完成或设备安全性验证。未启动、连接或控制设备。
