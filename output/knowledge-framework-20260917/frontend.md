# 前端知识模块：从浏览器界面读懂 MicroMani

本模块依据 2026-09-17 工作区当前源码，包括已有未提交修改编写。它解释代码职责和学习方法，不代表已经完成实机验收。本次只读源码与测试，未启动前端、后端或硬件，未运行测试。先读 [main.tsx](<D:/E2EAPP_MicroMani/frontend/src/main.tsx>)、[App.tsx](<D:/E2EAPP_MicroMani/frontend/src/App.tsx>)，再沿一个按钮读到 API，比一次阅读整个状态仓库更容易建立认识。

## 1. 前端在平台中负责什么

浏览器负责显示设备状态、收集操作者输入、管理交互流程和发送请求；后端与 HAL 负责业务、设备通信及执行。页面中的“已点击”“请求已返回”“设备已确认”是三个不同事实。理解这个区别，是学习本平台最重要的一步。

```text
main.tsx → App.tsx → BrowserRouter → AppLayout → 当前业务页面
                                         ├─ 导航、全局状态、日志、急停
                                         └─ 组件与 hook
组件事件 → Zustand action 或 api/index.ts → HTTP → 后端
后端 → WebSocket → 校验/租约/命令确认 → Zustand → 订阅者重渲染
后端相机 → HTTP MJPEG → <img>                   （独立图像通道）
```

前端没有直接调用运动控制卡 SDK。不要把浏览器 WebSocket、后端到 HAL 的通信，以及相机视频流当成同一条通道；前端也不是精密运动实时循环的执行者。

## 2. 当前技术选型与版本

以下是 [package.json](<D:/E2EAPP_MicroMani/frontend/package.json>) 的**声明版本范围**，不是现场设备能力，也不等于当前安装版本。`^` 表示 npm 的兼容版本范围，具体依赖解析还要看 [package-lock.json](<D:/E2EAPP_MicroMani/frontend/package-lock.json>)。

| 库/工具 | 声明版本 | 当前职责及选型理解 |
|---|---|---|
| React / React DOM | 均 `^18.3.1` | 组件描述 UI，React DOM 将它提交到浏览器 DOM；适合拆分多页面、共享状态视图，这是适用性解释，并非开发历史记录 |
| react-router-dom | `^6.30.3` | BrowserRouter、Route、Outlet、NavLink 管理页面和导航；URL 本身记录当前页面与设置定位 |
| Zustand | `^5.0.12` | 共享遥测、配置、录制和控制状态；组件可以只订阅需要的字段 |
| @tanstack/react-virtual | `^3.13.24` | 日志列表虚拟滚动，减少长列表 DOM 数量 |
| lucide-react | `^1.11.0` | 图标组件 |
| dayjs | `^1.11.20` | 顶栏时间格式化 |
| clsx | `^2.1.1` | 声明了条件类名工具；本次 `src` 检索未见导入，不能将依赖清单等同实际使用清单 |
| TypeScript | `^6.0.3` | 编译期检查接口、状态与参数；类型不会自动验证网络 JSON |
| Vite / @vitejs/plugin-react | `^8.0.10` / `^6.0.1` | JSX 转换与应用构建；当前配置使用 Rolldown 输出分包项 |
| Vitest / jsdom | `^4.1.5` / `^29.0.2` | 单元/组件测试与模拟 DOM 环境 |
| Testing Library | react `^16.3.2`、dom `^10.4.1`、jest-dom `^6.9.1`、user-event `^14.6.1` | 通过可见文字、角色、事件检查用户可观察行为 |
| Playwright | `^1.59.1` | 浏览器视觉检查脚本 |
| ESLint 相关 | eslint `^10.2.1`、@eslint/js `^10.0.1`、typescript-eslint `^8.58.2`、react-hooks `^7.1.1`、react-refresh `^0.5.2`、globals `^17.5.0` | 静态规则与 Hooks 用法检查 |
| 类型声明包 | @types/node `^24.12.2`、@types/react `^18.3.28`、@types/react-dom `^18.3.7` | 为第三方 API 提供 TypeScript 类型 |

当前 UI 采用 [components/ui.tsx](<D:/E2EAPP_MicroMani/frontend/src/components/ui.tsx>) 自建的 `UiButton`、`UiTag`、`UiTabs` 等组件和 [index.css](<D:/E2EAPP_MicroMani/frontend/src/index.css>)。当前 package.json 没有 Ant Design，源码检索也未见 antd 导入；共享流程仍提到 Ant Design，Vite 仍保留 antd 分包判断，属于与当前代码不完全一致的内容。当前曲线使用 Canvas，不应按旧资料写成 ECharts。

本地控件及 Canvas 注释明确提到减少首屏依赖和高频图表开销；它们说明设计意图，不能证明性能提高了多少。CSS 使用变量统一颜色、圆角、阴影，以 Flex/Grid 等布局组织页面；浏览器样式按层叠规则生效，阅读大 CSS 文件要检查后面是否覆盖前面的同名规则。

## 3. 学懂 JavaScript、TypeScript 与 React 的必要基础

**JavaScript 先抓对象、函数和异步。** 遥测是对象，多个轴是数组，按钮回调是函数。`map` 把数据转为组件，`filter` 选择日志，`...state` 创建新对象。`async/await` 等待 Promise，不会让网络变成同步，也不能保证先发请求先返回。因此本项目大量使用 `requestId`、`generation`、`cancelled`：旧请求可以返回，但失去继续修改当前状态的资格。

浏览器通常在主线程处理脚本、事件及界面工作。`setTimeout` 是最早可调度时间，不保证准时执行；繁忙或后台标签会延迟任务。租约代码因此使用真实时间检查过期，而不是靠定时器次数证明活跃。`AbortController` 可取消客户端等待，但不能证明服务器已经撤销物理动作；超时运动请求不能自动重发。

**TypeScript 让约定可检查。** [types.ts](<D:/E2EAPP_MicroMani/frontend/src/types.ts>) 的 `interface` 描述数据形状，联合类型限制状态集合，例如遥测 `connecting | live | stale | offline`。`Pick<T, K>` 只取需要字段，泛型使选择器保留返回类型。`unknown` 要检查后再使用；`as TelemetryFrame` 只是类型断言，不会在运行时检查字段，所以 [telemetryIngress.ts](<D:/E2EAPP_MicroMani/frontend/src/stores/telemetryIngress.ts>) 另做边界校验。

当前 [tsconfig.app.json](<D:/E2EAPP_MicroMani/frontend/tsconfig.app.json>) 面向 ES2023 与 DOM，使用 ES modules、`react-jsx`、bundler 模块解析、`noEmit`，打开未使用变量/参数检查；它没有显式开启 `strict`。不要因为用了 TypeScript 就声称启用了所有严格检查。根 [tsconfig.json](<D:/E2EAPP_MicroMani/frontend/tsconfig.json>) 引用应用配置和 Vite 的 Node 配置；`tsc -b` 做项目检查，实际应用资源由 Vite 构建。

**React 可以理解为“当前状态→界面”。** 组件是返回 JSX 的函数；props 是父组件传入数据，state 是组件自身记忆，事件回调改变状态后触发新的渲染。JSX 是表达式，不是 HTML 字符串。列表 `key` 表示同一个业务对象，不能随意用会变化的位置代替稳定身份。

| API | 本项目中的学习抓手 | 容易误解之处 |
|---|---|---|
| `useState` | 数据集选择、输入框、弹窗是否打开 | 改 state 会安排渲染，不应当作同步可变变量 |
| `useRef` | 请求编号、在途锁、Canvas DOM | 改 `.current` 不触发渲染，适合保存流程控制信息 |
| `useEffect` | 根连接、快捷键、播放定时器 | 建立订阅时必须返回相应清理；依赖变化会重新执行 |
| `useMemo` / `useCallback` | 日志过滤、曲线序列、录制处理函数 | 是计算/引用优化，不能作为安全状态或业务正确性的依赖 |
| `memo` | `UiButton`、曲线组件 | props 引用变化仍可能重渲染，也不会阻止组件自己的 store 更新 |
| `lazy` / `Suspense` | App 的全部业务页 | 按需加载代码并显示占位；加载失败还需要错误边界 |
| `useSyncExternalStore` | `useFrameField` | 让 React 安全订阅外部状态，快照相等时复用引用 |

入口启用了 `StrictMode`。理解开发环境中的重复挂载/Effect 检查，有助于发现未清理连接与重复订阅；不能把每次调试时看到的重复调用都当作设备故障。

## 4. 页面、组件、Hook、Store、API 怎样分层

| 层 | 当前源码入口 | 应学习的职责 |
|---|---|---|
| 入口和路由 | [main.tsx](<D:/E2EAPP_MicroMani/frontend/src/main.tsx>)、[App.tsx](<D:/E2EAPP_MicroMani/frontend/src/App.tsx>) | 根节点挂载、退出释放、连接生命周期、按需路由 |
| 公共壳层 | [AppLayout.tsx](<D:/E2EAPP_MicroMani/frontend/src/components/AppLayout.tsx>) | 导航、顶栏、Outlet、日志、安全提示与始终可达的急停 |
| 主页 | [DashboardView.tsx](<D:/E2EAPP_MicroMani/frontend/src/views/DashboardView.tsx>) | 组合相机、双臂轴值、力觉、诊断，并跳到对应设置 |
| 录制页 | [RecordPage.tsx](<D:/E2EAPP_MicroMani/frontend/src/views/RecordPage.tsx>)、[record 组件](<D:/E2EAPP_MicroMani/frontend/src/components/record>) | 预检查、会话控制、快捷键、质量报告与历史；组件显示与 store 流程分开 |
| 数据复核 | [DatasetView.tsx](<D:/E2EAPP_MicroMani/frontend/src/views/DatasetView.tsx>) | 列表→按需 episode 详情→抽样轨迹/图像→复核、重命名、删除、上传 |
| 模型与微调 | [ModelView.tsx](<D:/E2EAPP_MicroMani/frontend/src/views/ModelView.tsx>)、[FineTuneView.tsx](<D:/E2EAPP_MicroMani/frontend/src/views/FineTuneView.tsx>) | 读取列表、提交任务、停止/取消、失败提示、排除迟到响应 |
| 自动执行 | [AutoView.tsx](<D:/E2EAPP_MicroMani/frontend/src/views/AutoView.tsx>) | 启停自动流程、显示队列与视觉、动作注入的安全检查 |
| 设置 | [SettingsView.tsx](<D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx>)、[settings 子模块](<D:/E2EAPP_MicroMani/frontend/src/views/settings>) | 系统/力觉/运动/遥操作/视觉分域；壳层保存跨 Tab 的在途锁 |
| 复用行为 | [hooks](<D:/E2EAPP_MicroMani/frontend/src/hooks>) | `useMotionEnable`、`useGripperDisplay`、相机流生命周期；Hook 不等于独立全局状态 |
| 状态与命令 | [telemetry.ts](<D:/E2EAPP_MicroMani/frontend/src/stores/telemetry.ts>)、[motionCommands.ts](<D:/E2EAPP_MicroMani/frontend/src/stores/motionCommands.ts>) | 共享状态、流程编排、命令确认、串行与过期处理 |
| 网络适配 | [api/index.ts](<D:/E2EAPP_MicroMani/frontend/src/api/index.ts>) | URL、HTTP、会话头、错误解释与超时；没有使用 Axios |
| 契约与纯函数 | [types.ts](<D:/E2EAPP_MicroMani/frontend/src/types.ts>)、[data.ts](<D:/E2EAPP_MicroMani/frontend/src/data.ts>)、[hardwareStatus.ts](<D:/E2EAPP_MicroMani/frontend/src/hardwareStatus.ts>) | 类型、默认值、显示映射、状态推导，便于单独测试 |

不是所有请求都必须经过全局 store。模型/微调列表和数据复核主要属于页面本地状态；设备遥测与全局安全态需要跨页共享。判断依据是“谁需要持续共享”，而不是把所有变量都放入 Zustand。

左右侧必须追踪语义：[data.ts](<D:/E2EAPP_MicroMani/frontend/src/data.ts>) 的 `hardwareSideForOperatorSide` 当前交换左右；双侧合计 12 维的位置数组中，硬件左/右各占 6 维，起点分别为 0/6。不能看到按钮“左臂”就向 `/motion/left/...` 发送。遥操作主手映射还受具体配置影响，应与后端操作者视角规则核对。

## 5. 遥测、连接生命周期与性能

[App.tsx](<D:/E2EAPP_MicroMani/frontend/src/App.tsx>) 在真实模式调用 `startBackend`，卸载时调用 `stopBackend`；`mockMode` 当前只由 `import.meta.env.MODE === 'test'` 决定。普通页面不会因后端离线自动进入模拟运行。

`startBackend` 防止重复创建连接，并发读取配置、参数快照、硬件概况，再连接默认 `ws://127.0.0.1:18082/ws`。HTTP 默认基址是 `http://127.0.0.1:18082`，分别可由 `VITE_WS_URL`、`VITE_API_BASE` 配置；这些构建变量不应存放密钥。配置返回后还会触发 PICO 网络自动配置调用，因此“打开真实页面”不宜等同“只读静态预览”。

每次连接生成新的 generation；异步返回前检查当前 generation，防止旧连接的配置覆盖新连接。`onopen` 只进入 connecting，收到有效遥测才成为 live。后端 WebSocket 发送 `telemetry`、`log`、安全挑战/租约与特定中断录制状态 `record_status`。前端另保留 `config` 处理分支，当前后端未见主动推送该消息；初始配置通过 HTTP 读取。遥测边界检查数组长度：位置 12、夹爪 2、左右力各 6；坏帧会使遥测失效并撤销租约。即使同一帧其余字段损坏，明确的安全锁存也会优先被识别。

普通断连指数退避重连，等待依次从 1 秒增长，最多 15 秒；关闭码 1008 表示控制权冲突时不自动抢占。`?mode=observe` 进入观察模式且不回答续租挑战。停止连接会清理 WS 回调、重连计时器、失效监测、可见性监听及等待中的 UI 提交；退出页面优先 `sendBeacon`、回退 `fetch keepalive` 发送 `release_handles`。入口安装的是释放句柄逻辑，并非自动关闭整个后端；退出通知本身是尽力发送。

高频数据不等于高频 React 渲染。当前源码规定：

- 普通可见页约每 66 ms 提交最新帧；隐藏页约 400 ms。期间替换待提交帧，而非积压每帧 UI 工作。
- 图表历史约每 100 ms 采样，最多 120 条；日志最多 5000 条。这些是前端显示缓存，不是数据集保存策略。
- 安全锁存、连接、录制、轴使能等重要变化立即提交；运动命令确认在接收时处理，不等待 UI 节流。
- 遥测超过 2000 ms 未更新被判过期，监测定时器每 250 ms 检查；显示上保留最后数值不代表仍可用于控制。

Zustand 的 `useTelemetryStore(s => s.frame.halOk)` 仅关注这个值；订阅整个 `frame` 会随整帧替换刷新。`useFrameField` 用自定义比较缓存数组或对象切片；`numberArrayEqual` 判断内容，避免内容相同但引用变化造成无用更新。比较器漏掉字段又会吞掉真实变化，因此相机比较器同时覆盖帧龄、时钟偏差等健康字段。

[LogPanel.tsx](<D:/E2EAPP_MicroMani/frontend/src/components/LogPanel.tsx>) 过滤日志后虚拟滚动；[Charts.tsx](<D:/E2EAPP_MicroMani/frontend/src/components/Charts.tsx>) 用 Canvas 绘线，处理 devicePixelRatio 和 ResizeObserver 并在卸载时释放。优化应围绕实际订阅与绘制成本，不能靠到处加 `useMemo` 推断系统更快。

## 6. 完整实例：点击使能到遥测确认

以设置页某个操作者侧的“使能”为例，完整阅读顺序如下：

1. [MotionCards.tsx](<D:/E2EAPP_MicroMani/frontend/src/views/settings/MotionCards.tsx>) 用 `hardwareSideForOperatorSide` 获得硬件侧，`useMotionEnable(hardwareSide)` 提供按钮状态和操作入口。
2. 点击调用 `setMotionEnabled(side, true)`；[motionCommands.ts](<D:/E2EAPP_MicroMani/frontend/src/stores/motionCommands.ts>) 检查租约、安全与新鲜遥测，给请求编号，记录当前接收序号和遥测时间，置 sending。
3. 每侧 HTTP 串行，重复/相反意图按在途状态合并或排队。即使展示超时，旧 HTTP 真正结束之前仍不释放发送通道。
4. [api/index.ts](<D:/E2EAPP_MicroMani/frontend/src/api/index.ts>) 的 `enableMotionSide` 通过 `postCommand` 请求 `/api/motion/{side}/enable_all`，携带 `X-Control-Session`，再次执行统一前端安全门闩。
5. HTTP 成功只表示请求被接受；尚无匹配反馈时进入 waitingConfirm，若较新且有效的匹配遥测已先到，则可直接 confirmed。HTTP 失败、`ok:false`、超时各自显示失败/结果未知；绝不仅凭 HTTP 成功把 `motionAxisEnabled` 改为 true。
6. 后续 WebSocket 遥测必须来自更新的接收序号、更新的帧时间，且该侧 6 轴全部反馈 true，反馈仍新鲜，并且请求已被接受，才能置 confirmed。
7. Zustand 订阅触发按钮与状态标签刷新；断连、急停或 5 秒确认超时使旧请求失去确认资格。断使能意图与使能意图区别处理，保护发生时仍可保留已请求的断使能。

此例串起事件、Promise、闭包、引用、状态机、HTTP、WebSocket 和订阅。它也说明为什么页面不能把“接口 200”翻译成“电机已使能”。后端是否确实执行到各轴，需要继续读后端路由和 HAL，不能仅由本例确认。

录制按钮可作为第二次练习：[RecordPage](<D:/E2EAPP_MicroMani/frontend/src/views/RecordPage.tsx>) 打开 PreCheck → 用户通过预检查 → `startRecordSession` 防重入并记录安全 generation → 查询现有会话、保存当前配置 → `/api/record/session/create` → 依据返回状态开始显示录制计时。中断片段需要先处理；保存、质量审核、复位是不同阶段。快捷键忽略输入框、长按重复及弹窗期，卸载时删除监听。

## 7. 控制租约、急停与异常隔离

[controlLease.ts](<D:/E2EAPP_MicroMani/frontend/src/stores/controlLease.ts>) 接收 `safety_challenge`，浏览器主线程按 sessionId/challengeId 回答 `safety_heartbeat`；只有匹配的 `control_lease: active` 才给出控制有效期。挑战 TTL 上限 2000 ms，执行租约 TTL 上限 2500 ms。截止时间从本地主线程回答挑战时起算，迟到确认不能延长授权；定时器只能撤销，不能凭空续租。租约有效不表示已经解除急停，也不表示轴已使能。

[controlSafety.ts](<D:/E2EAPP_MicroMani/frontend/src/utils/controlSafety.ts>) 将急停意图、硬件锁存、租约、新鲜遥测统一为阻断原因。全局急停请求立即发送，同时记录本地急停意图并取消继续运动的资格；HTTP 返回后仍保持锁定。显式“确认安全态”请求返回后，还必须收到新的未锁存遥测，才清除本地意图，不自动恢复运动。保护意图写入 sessionStorage，刷新页面不能用界面初值假装已经解除。

[RouteErrorBoundary](<D:/E2EAPP_MicroMani/frontend/src/components/RouteErrorBoundary.tsx>) 和 [ModuleErrorBoundary](<D:/E2EAPP_MicroMani/frontend/src/components/ModuleErrorBoundary.tsx>) 隔离渲染失败并撤销租约；全局错误和未处理 Promise 拒绝由 [controlFaults.ts](<D:/E2EAPP_MicroMani/frontend/src/utils/controlFaults.ts>) 处理。急停区域还有原生按钮后备显示。错误边界主要捕获渲染树异常，不能代替每个异步调用的错误处理。

这些前端机制用于控制交互与防止继续发送。真正的租约失效停车、力限位及急停执行仍须由后端/HAL 独立保证，不能以按钮 disabled 代替执行侧保护。

## 8. 相机 MJPEG、snapshot 与数据回放

[useLiveCameraSnapshot.ts](<D:/E2EAPP_MicroMani/frontend/src/hooks/useLiveCameraSnapshot.ts>) 名称保留 Snapshot，当前却生成 `/api/cameras/{key}/stream?t=nonce`，供 `<img>` 显示 MJPEG。MJPEG 是一个 HTTP 响应不断发送 JPEG 帧，不是 WebSocket 传图，也不是前端定时请求单张照片。

Hook 维护加载/失败 URL，失败时通常 2500 ms 后换 nonce 重试；设备 health=error 时不自动启动流，手动刷新可尝试探测。监听自定义相机刷新事件并对称释放，卸载时清理重试定时器。预览只有图像元素成功加载后才显示 ok；遥测健康与浏览器实际能否显示图像是两项证据。

[backend/app.py](<D:/E2EAPP_MicroMani/backend/app.py>) 同时保留 `/snapshot` 单张 JPEG 与 `/stream` multipart 接口。还要区分“参数快照” `/settings/snapshots`，它保存配置，与相机图像不是同一种数据。数据集页从 episode samples 的 `images` 读取已保存图像；其播放条按抽样数据映射，不应声称它已经是逐帧视频播放器。没有图像时的网格/移动标记属于示意显示，不能作为真实装配录像。

## 9. 哪些界面不能直接当作已实现能力

源码核实发现：AutoView 的算法、推理模式和任务文本仅保存在本地 state，启动时没有传入这些值；推理延迟由 `88 + sin(elapsedSec) * 9` 计算，“30Hz”和“ZMQ 8082 / 8083”是固定文案。ModelView 的精度选择也仅修改本地显示，启动请求只传 modelId。微调页面确有创建/取消 API，但实际训练进程与产物要到后端继续核验。

学习时用“输入是否进入函数参数→是否进入 HTTP body→后端是否消费→有无输出反馈”检查闭环，避免把设计界面、配置默认值、模拟夹具误认成已验证功能。当前源码本身仍在演进，这些是事实边界，不是替用户选择另一套框架的建议。

## 10. 测试、构建与渐进学习

[vite.config.ts](<D:/E2EAPP_MicroMani/frontend/vite.config.ts>) 配置 Vitest 的 jsdom 环境和 15 秒用例超时；[test/setup.ts](<D:/E2EAPP_MicroMani/frontend/src/test/setup.ts>) 提供 ResizeObserver、rAF 等替身。Canvas `getContext` 在测试中返回 null，所以测试可检查输入/布局，不能证明曲线像素正确。

建议按问题阅读现有测试：

| 知识点 | 测试入口 |
|---|---|
| HTTP 成功与轴反馈分离、旧请求与排队 | [motionCommands.test.ts](<D:/E2EAPP_MicroMani/frontend/src/stores/motionCommands.test.ts>) |
| 挑战、租约、观察模式、控制权冲突 | [controlLease.test.ts](<D:/E2EAPP_MicroMani/frontend/src/stores/controlLease.test.ts>)、[telemetry.controlLease.test.ts](<D:/E2EAPP_MicroMani/frontend/src/stores/telemetry.controlLease.test.ts>) |
| 坏帧、过期、节流与细粒度订阅 | [telemetry.ingress.test.ts](<D:/E2EAPP_MicroMani/frontend/src/stores/telemetry.ingress.test.ts>)、[frameSelectors.live.test.tsx](<D:/E2EAPP_MicroMani/frontend/src/stores/frameSelectors.live.test.tsx>) |
| 相机流与刷新 | [CameraPreview.test.tsx](<D:/E2EAPP_MicroMani/frontend/src/components/CameraPreview.test.tsx>) |
| 切页后迟到响应、请求归属 | [TaskPages.lifecycle.test.tsx](<D:/E2EAPP_MicroMani/frontend/src/views/TaskPages.lifecycle.test.tsx>)、[DatasetView.lifecycle.test.tsx](<D:/E2EAPP_MicroMani/frontend/src/views/DatasetView.lifecycle.test.tsx>) |
| 全局流程和侧别映射 | [App.test.tsx](<D:/E2EAPP_MicroMani/frontend/src/App.test.tsx>)、[data.test.ts](<D:/E2EAPP_MicroMani/frontend/src/data.test.ts>) |

从仓库根目录执行的针对性命令示例，本文未实际执行：

```powershell
npm --prefix frontend test -- src/stores/motionCommands.test.ts
npm --prefix frontend run typecheck
npm --prefix frontend run build
```

`test` 是 `vitest run`；`typecheck` 是 `tsc -b`；`build` 先类型检查再 Vite 构建；`lint` 的允许警告数为 0。**当前 `dev` 先 build 再运行 serve-dist，不能按常规教程理解成 Vite 热更新。** [serve-dist.mjs](<D:/E2EAPP_MicroMani/frontend/scripts/serve-dist.mjs>) 为 BrowserRouter 路由回退提供 index.html。视觉检查脚本会构建、启动预览并打开真实页面，使用前先读副作用，不能当作无连接的纯单元测试。

学习练习按以下顺序进行，先在离线测试与独立练习文件中完成：

1. 用普通 TS 对一帧遥测提取左/右六轴和力模长，解释每项单位，写输入输出例子。
2. 阅读 `UiButton`，用 props 解释 loading、disabled、aria-busy；画出一个状态到界面的映射表。
3. 追踪主页→设置 hash 导航，说明 URL、组件 state、全局 store 分别存放什么。
4. 用现有 fake WebSocket/假时钟模拟 live→stale→offline，验证显示失效而不是继续正常。
5. 在 motionCommands 测试中按时间顺序手写“先反馈后 HTTP”“先 HTTP 后反馈”“反馈过期”三个过程。
6. 为数据列表构造 A 请求晚于 B 返回的案例，使用 requestId 解释为何旧结果不能覆盖新选择。
7. 读取相机测试，区分服务端 health、图像 onLoad 和帧龄；最后再学习录制多阶段流程。

自测：HTTP 200 为什么不能证明使能？`useRef` 与 state 的区别是什么？TS 接口为何不能挡住坏 JSON？为什么 UI 15Hz 不代表录制 15Hz？为什么过期定时器不能续租？为什么超时后不自动重发运动？为什么有图像占位不代表有录像？能结合上述源码回答这些问题，说明已掌握平台前端的主干知识。

## 供整合者核对的跨层事实

1. 后端与 HAL 是否使用相同 challenge/lease 时间约定，`X-Control-Session` 在哪些路由被执行侧验证；观察模式、release_handles 的实际资源范围。
2. 操作者侧交换、主手通道配置与后端 [operator_view.py](<D:/E2EAPP_MicroMani/backend/core/operator_view.py>) 一致性；12 维遥测与含夹爪 14 维策略不能混用。
3. 前端 µm/degree、力 N 与 mN 的展示及后端 [units.py](<D:/E2EAPP_MicroMani/backend/core/units.py>) 转换，特别是 LeRobot 旋转单位。
4. 默认 UI 参数、后端持久配置和硬件已应用参数是不同层；保存配置和应用配置不能混写为一步。
5. 自动/模型/微调页面已发送的 API 与真实策略服务、训练进程能力的对应；不可按按钮存在推断实现完整。
6. 页面载入触发 PICO auto-configure 的后端副作用；数据集抽样图像、MJPEG 预览和实际录制落盘频率的区别。

可补充的官方学习入口（本次只用本地事实，以下链接未联网核实）：[React Learn](https://react.dev/learn)、[TypeScript Handbook](https://www.typescriptlang.org/docs/handbook/intro.html)、[MDN JavaScript](https://developer.mozilla.org/zh-CN/docs/Web/JavaScript)、[Zustand](https://zustand.docs.pmnd.rs/)、[Vite](https://vite.dev/guide/)、[Vitest](https://vitest.dev/guide/)、[Testing Library](https://testing-library.com/docs/react-testing-library/intro/)。阅读在线资料时核对其版本与本项目声明版本，优先完成源码中的真实小练习。
