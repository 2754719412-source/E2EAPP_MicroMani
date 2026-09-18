# 远端最新代码与本机工作区对比（2026-09-18）

结论：远端已经修复上一轮发现的两个主要数值错配，并补入数据契约、HKVL 默认和能力上报；本机则有远端尚未包含的 UI、控制租约、急停代际和线程隔离实现。应以本机为基础按功能整合远端变更，不能用远端源码或其 HAL 二进制整套替代。远端仍有若干遗漏，本机环境也不具备完整实机部署条件。

## 1. 比较范围与方法

- 本地：`D:/E2EAPP_MicroMani`，HEAD `6d898c9df4a3b13b415e3dabd75591ed2aabc2ac`，另有 198 个已跟踪文件修改、86 个未跟踪状态条目。未跟踪条目包含目录，不能当成文件数。
- 实时远端：`ccoxo/E2EAPP_MicroMani` 的 `codex/hal-native-teleop-v2`，最新为 [aabe6734b2ad39945641fe8a53e107c8d3409b76](https://github.com/ccoxo/E2EAPP_MicroMani/commit/aabe6734b2ad39945641fe8a53e107c8d3409b76)。
- 共同基线：`6d898c9`。远端比基线增加 `ff74427`、`72a7e2e`、`d8cf2cb`、`aabe6734` 四个提交，共涉及 64 个文件，净增 2680 行、删除 311 行。
- 使用远端原样 Git 归档独立检查；按文件在副本上执行三方文本合并模拟，未改分支、索引或业务源码。
- 模拟结果：10 个远端新增文件，35 个文件文本可自动合并，19 个文件存在文本冲突。文本无冲突不代表接口和运行行为兼容。
- 当前本地有 37 个实现文件在远端不存在，另有根目录 `Start-UI.cmd`。这些是本地未上传的工作，并非远端内部引用缺文件。

## 2. 远端已补齐的内容

| 项目 | 远端最新情况 | 对本机的意义 |
| --- | --- | --- |
| 数据集与 Policy 顺序 | 新增共享 `backend/core/data_contract.py`，声明 `appstation.dual_arm.operator_sides.v2`；模型/数据集按操作者侧，HAL 按硬件侧 | 本地目前仍是旧数值契约；要迁入完整转换链，不能只改录制输出 |
| 保持位置动作 | 录制 state 与在线 policy state 已一致 | 额外纯函数交叉复现确认，保持位置得到零运动增量，不再出现左右 X ±6 μm |
| 原点归一化 | pulses 和 origin 按契约映射，使用正确硬件侧的换算系数 | 旧反例现在保持 Y=−1000 μm，`changed=false` |
| native 旧集续录 | 已识别的 native 数据集缺少/未知契约时拒绝继续录制；新集写入契约 | 正常 native 续录路径已补保护；其他消费路径仍有遗漏，见后文 |
| HKVL 默认 | 前端、后端、HAL 初始值和缺字段 fallback 已统一 | 与本地已完成的 HKVL 主用、NI 手动备用方向一致；不应覆盖显式 NI 配置 |
| HAL 能力上报 | `hal-real/0.2` 和 `force_calibration_state_v1` 经 DDS health 返回 | 可吸收字段和诊断，但当前还不是强制入口校验 |
| 腕相机识别 | 组件、API、识别、绑定、保存和流刷新链路齐全 | 应迁入本地视觉设置卡片，保留现有 UI 和生命周期 |
| 相机曝光/FPS | 增加 Windows 相机曝光优先级设置，尝试禁止暗光自动降帧 | 是有用补丁，但运行中切自动曝光存在漏路径，且不等于实测保证 30 FPS |
| 上传文档 | 数据契约、上传契约、PR 模板及架构不变量已加入 | 文档方向可合入，但不能把文档声明当成所有入口已实现 |

已修复项的额外验证位于 `recording-contract-audit.log`，不是仅凭提交说明判断。

## 3. 本地已经具有、合并时需要保留的能力

| 范围 | 本地实现 | 远端情况及整合方式 |
| --- | --- | --- |
| 界面与订阅 | `Ui*` 组件、settings 拆分、路由按需加载、Canvas 图表、frameSelectors | 远端仍保留 Ant Design/ECharts 与大型 SettingsView；迁入功能，不覆盖整页 |
| 控制者与新鲜度 | controlLease、control_watchdog、ControlLeaseGuardian、DDS 租约应答 | 远端没有这套完整协议；必须保留后端到 HAL 的全部连接 |
| 急停和迟到响应 | safety generation、运动命令队列失效、ACK 后等待新反馈 | 远端部分 UI 仍在请求返回后乐观清锁存；不应覆盖本地反馈确认 |
| 驱动和线程 | bounded lanes、worker 异常边界、停止/重配置取消、tare 提交代际检查 | 远端新自检需嵌入这些保护，而不是替换为旧并发结构 |
| 录制与原点 | 启动/下一段原点校验、急停中断保留 episode、排空后保存/结束 | 应与新数据契约校验同时保留 |
| 策略执行 | stop_generation 失效旧队列、最终执行边界检查、有限数值检查 | 远端此次未修改通用 PolicyService；不能用远端文件覆盖本地保护 |
| 启动行为 | 本地已移除开机自动回原点，另有常驻 Start-UI | 远端仍保留开机回原点功能及相关参数，虽然默认 enabled=false；不得因整页/整文件覆盖恢复已移除功能 |

普通 `PolicyService.manual_axis_move` 当前使用硬件侧；不能因为名称含 policy 就再次交换。新的操作者侧转换只应作用于明确的数据集/模型边界。

## 4. 两边不能直接拼接的控制行为

### 4.1 本地后端不能直接配远端构建的 HAL

本地 `backend/hal_client/dds_client.py:170` 将 `control.lease` 发往急停 topic；`backend/services/control_watchdog.py:227` 要求 HAL 返回 `leaseFresh=true`。远端 [HalDdsControlServer.cpp:524](https://github.com/ccoxo/E2EAPP_MicroMani/blob/aabe6734b2ad39945641fe8a53e107c8d3409b76/hal/src/HalDdsControlServer.cpp#L524) 的该通道没有区分租约消息，直接执行急停。

所以混用“本地后端 + 远端 HAL 二进制”会把续租当急停，租约无法建立。应向本地 HAL 加入远端自检和版本字段，保留本地 DDS 租约分支、guardian 和应答。正确的源码三方合并可保留这些文件；此问题不是说任何 Git 合并都必然触发。

### 4.2 Tare 与 ACK 的先后条件冲突

远端启动配置后锁存并等待自检，ACK 要求先完成校准。本地后端 Tare、HAL dispatcher 和 runtime 则要求运动安全许可及未锁存状态。直接拼接会形成“先 ACK 才能 Tare，先 Tare 才能 ACK”。

需要明确受控校准许可，保留有效控制者/租约、全轴停用、新急停和重配置取消。不能通过删除所有安全检查解决。两阶段采样的 bias 提交和 `ready_for_ack` 发布仍须受本地代际校验约束。

ACK 还应保留本地先确认运动急停代际、再清除力锁存的顺序。远端先清力锁存再调用运动确认的顺序，与本地可能拒绝的 epoch/lease 检查结合后会产生部分完成状态。

### 4.3 前端自检门控不能只复制条件

本地 `frontend/src/stores/frameSelectors.ts:93` 的 PreCheckFrameSlice 尚无 `forceStatus`，相等比较也不观察它。迁入远端 `calibration.state === 'ready' && !latched` 时，需要同步 selector、类型、比较和状态变化回归，否则会有类型问题或状态不刷新。

同时保留本地 ACK 防重复、新鲜度、租约及“等待后续未锁存遥测”的逻辑。腕相机 bind 已在后端保存配置，本地 `updateConfig` 会再次保存整份配置，接入时还需明确保存后的状态同步，避免与已有保存队列竞争。

## 5. 远端最新代码仍有的遗漏

| 问题 | 核实方式与影响 |
| --- | --- |
| 无契约 legacy 数值预览仍放行 | `_dataset_contract_error` 对非 native 直接放过；离线 fixture 仍返回 1 条数字样本，未满足禁止未知契约消费的要求 |
| 上传入口没有契约校验 | 未知契约 native fixture 能进入 mock 上传任务；没有实际上传。若上传也属于要求校验的消费入口，应补齐 |
| 契约拒绝返回无说明的 500 | stats、episode 底层新增 RuntimeError，但 API 只捕获 FileNotFoundError；复现为 `500 Internal Server Error`，未给出人工迁移提示 |
| 文档与图像/文件读取范围不一致 | 图像预览、文件下载仍可读取未知契约 native 数据。图像本身不因数值顺序改变而损坏，应明确是收紧实现还是调整文档范围 |
| HAL capability 目前仅诊断 | DDS 能传回 capability，但只在 `/api/health` 装饰结果；前端无消费，录制/控制入口未用其作为强制检查。不能宣称旧 HAL 已被服务端拦截 |
| 启动器校验与最终 EXE 不一致 | 正式 EXE 不存在会跳过源码时间检查；正式 EXE 较新也可能被旧 `.next.exe` 按 hash 替换；已监听旧进程还可在提升前返回。时间戳不能证明构建版本 |
| FPS 补丁漏运行中调参 | direct 模式复用 capture 时提前返回，随后 `apply_tuning(autoExposure=True)` 没有调用固定帧率设置。纯 mock 复现调用数为 0；process 模式重开路径可覆盖 |

Microsoft 对相机自动曝光优先级的[说明](https://learn.microsoft.com/en-us/windows-hardware/drivers/stream/ksproperty-cameracontrol-auto-exposure-priority)要求设备已处于自动曝光模式。远端新建 capture 的设置时序仍需实机核验；失败仅 warning 后继续采集。因此应分别报告属性设置是否成功和测得 FPS，不能仅凭源码声称帧率保证。

此外，外部 `act_deploy.py` 仍不在仓库，仓库/固定版本和参数契约尚待提供。新版 policy action 要求 dataContract，旧外部消费者需要同步适配；不能假设外部程序已经做到。

## 6. 本机配置及部署实际情况

本轮只读取配置、文件和 Windows 设备枚举，没有打开设备。

| 项目 | 本机实测 |
| --- | --- |
| 已保存力源 | `backend/runtime/config.json` 为 `hkvl_serial` |
| 已部署 HAL | 标准 `hal/build` 下未发现 HalServer.exe、JodellGripperWorker.exe 或对应 `.next.exe` |
| 后端原生 DDS binding | `backend/native/build/appstation_fastdds_transport.dll` 不存在 |
| SDK/依赖 | 配置中的 F 盘 LTDMC、dhd 路径不存在；`F:/opt/ros/jazzy`、本地 hal/vendor 不存在 |
| NI 备用标定 | 配置指向的 FT32918.cal、FT38799.cal 不存在；保留参数不代表备用线路已部署可用 |
| MSVC | 本机有 VS2022 Professional；构建脚本硬编码的 Community 路径不存在。可用工具链需要按本机路径调用 |
| LeRobot/parquet | 当前 Python venv 未安装 lerobot、pyarrow；不能验证完整录制落盘及 parquet 迁移 |
| 用户数据集 | 配置目录 `C:/Users/tianxiayifang/.appstation/datasets` 不存在，未发现可供本次核对的该目录下真实旧集 |
| 服务 | 检查时 18082、8091、5173、5174 无监听 |
| 相机设备 | OS 枚举仅见 USB2.0 HD/IR UVC WebCam；未匹配配置中的 VID_0ABD 相机，未见 Ports 类条目 |
| 前端产物 | frontend/dist/index.html 存在，是本地构建结果，不是本轮远端代码的构建 |

这是可以做离线开发与 mock 验证的环境，不能据此宣称已经具备工控机的实机运行条件。旧审计目录中的 ForceCoreTests.exe 是离线测试程序，不等于生产 HAL 已部署。

### 本机配置确实会触发远端相机自动迁移

将本机 config 复制到临时目录，用远端 SettingsService 读取，实际发生以下变化：

| 配置 | 当前本机 | 远端读取临时副本后 |
| --- | --- | --- |
| 全局索引 | index 1 | index 0 |
| 左腕索引 | index 0 | index 1 |
| 全局身份 | 旧 DevicePath `...1396F44D...` | `20250606105` |
| 左腕身份 | 旧 DevicePath `...398F0A3...` | `PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(5)#USB(3)#USB(4)` |
| 右腕身份 | 旧 DevicePath `...3724732E...` | `PCIROOT(0)#PCI(1400)#USBROOT(0)#USB(2)#USB(4)#USB(2)` |

原因是 [config.py:979](https://github.com/ccoxo/E2EAPP_MicroMani/blob/aabe6734b2ad39945641fe8a53e107c8d3409b76/backend/core/config.py#L979) 将完整旧绑定组合认定为历史默认，然后整组替换成远端的固定值。不能把这组机器专属迁移视为通用相机修复。本机原始 config 字节未变，HKVL source 在副本加载后仍保持 HKVL。

## 7. 建议整合顺序

1. 保存包含未跟踪文件、runtime 配置及当前构建信息的本机基线；本次仅完成审计记录，没有代替用户提交这些改动。
2. 先迁入 data_contract、录制/Policy/normalize 全链路和元信息检查，同时补齐遗漏入口与可理解的拒绝响应。保持通用硬件控制 side 语义和本地执行保护。
3. 在本地 HAL/后端租约与急停协议基础上加入远端双阶段自检、版本字段和能力校验。先解决 Tare/ACK 状态条件，再整合 UI。
4. 将腕相机识别和曝光补丁接入本地 CameraCard/驱动；补 direct 运行时调参，移除或限制机器专属绑定自动替换。保留本地 UI、流生命周期和配置保存顺序。
5. 分别在本机和工控机完成匹配的依赖安装、隔离构建及部署核验；不要把远端单独构建的 HAL 直接配本地后端。实机验收需另按授权范围执行。

按“数据契约、HAL 自检与兼容、相机功能、部署文档”拆分变更，便于单独验证与回退。不应通过引回 Ant Design/ECharts、恢复开机回原点或移除控制租约来减少文本冲突。

## 8. 本次实际验证与证据

- 远端 data_contract/policy/normalize 相关测试：19 passed、1 skipped（缺 pyarrow）。
- 远端相机格式、识别、固定 FPS mock 测试：17 passed。
- 额外纯函数/替身复现：录制与在线策略一致、保持动作零增量、同原点归一化不变；legacy 数值读取/上传替身/预览/下载/500 响应遗漏；direct 运行时调参漏固定 FPS。
- 使用临时配置副本验证相机迁移，确认真实配置不变。
- 在副本上完成 64 文件三方文本合并分析。没有执行实际合并。
- 相机测试首次未设置 test HAL，两个 API 用例因缺 DDS binding 在创建应用阶段失败；改为显式 test HAL 并禁用相机探测后 17 项通过，未改源码。原日志保留。
- 本轮没有复跑前端构建/全套测试、完整 C++ 构建、真实 LeRobot/parquet 读写或任何实机操作。上轮旧提交上的验证不当作本轮最新提交验证。

证据均在本报告目录：

- `three-way-comparison.json`：全部文件分类及 19 个冲突文件；`merge-simulation/` 保存对应副本结果。
- `machine-inventory.json`、`machine-paths-and-datasets.json`、`machine-runtime-observation.json`：本机文件、依赖和服务情况。
- `local-config-remote-migration.json`：配置迁移前后及原文件未变化证明。
- `contract-policy-normalize-tests.log`、`recording_contract_audit.py`、`recording-contract-audit.log`：契约测试与复现。
- `camera-mock-tests-isolated.log`、`camera-fixed-fps-direct-tuning-repro.log`：相机 mock 验证。

最终合并或修复尚未执行；本报告不表示已完成上述待补工作。
