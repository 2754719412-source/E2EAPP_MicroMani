# 远端上传完整性审计（2026-09-17）

结论：所检查的源码结构、内部引用和新增功能依赖基本完整，但存在已经复现的跨模块契约未同步问题。远端也未包含当前本地的全部优化，不能作为当前工作区的完整替代版本。

## 审计范围

- 实时核对远端 `ccoxo` 的 `codex/hal-native-teleop-v2`，仍为 [72a7e2e6c8e640e87a94cb2992f60392ace66501](https://github.com/ccoxo/E2EAPP_MicroMani/commit/72a7e2e6c8e640e87a94cb2992f60392ace66501)。默认分支 `master` 仍是 `55587e2e`，不要把默认分支下载包当作这次新增功能的版本。
- 当前本地 HEAD 为 `6d898c9df4a3b13b415e3dabd75591ed2aabc2ac`，未切分支、合并、提交或推送。另一远端 `origin` 的同名分支为 `11143543`，并非本次审计版本。
- 用 `git archive` 创建独立快照。依赖安装、类型检查和测试均在审计目录内进行；未修改生产源码、配置或设备状态。Windows 的 Git 归档转换了文本换行符，验证以归档原始字节为准，318 个受管文件均未被测试修改。
- 这里只能判断远端内部是否闭合、与本地有哪些差异；无法仅凭远端证明上传者机器上的所有工作都已提交。

## 文件结构与引用

| 检查 | 结果 |
| --- | --- |
| Git 文件树 | 共 318 文件：根目录 10、`.specify` 36、backend 73、docs 24、frontend 112、hal 46、scripts 17 |
| 子模块、符号链接、LFS | 无 gitlink、无符号链接；文本扫描未发现 LFS 指针或合并冲突标记 |
| Python | 73 个 Python 文件语法解析通过；扫描的 176 个 backend/scripts 绝对内部 import 均有对应模块 |
| C++ | CMake 显式列出的 29 个源码/头文件均存在；所查双引号 include 无缺失 |
| 前端 | 61 个 JS/TS 源码文件的相对 import 均可解析；外部 import 包已声明；package 与锁文件根依赖一致 |
| 腕相机新增链路 | 设置页组件 → API → 后端路由 → driver → 配置保存 → 预览刷新均有实现；新增组件及前后端测试已上传 |
| HKVL 新增链路 | 协议统计、驱动两阶段 tare、运行时自检状态、命令入口、前端类型/门控及原生测试均已上传 |

这些检查不能替代完整构建、所有动态导入验证或实机验收。

## 已确认的功能同步缺口

### 1. P1：新录制左右顺序与在线策略接口不一致

[录制 state 组装](https://github.com/ccoxo/E2EAPP_MicroMani/blob/72a7e2e6c8e640e87a94cb2992f60392ace66501/backend/services/dataset_recorder.py#L3581) 已交换左右；[policy_bridge](https://github.com/ccoxo/E2EAPP_MicroMani/blob/72a7e2e6c8e640e87a94cb2992f60392ace66501/backend/services/policy_bridge.py#L9) 的 observation 与 action 索引仍沿用原顺序。`/api/policy/observation`、`/api/policy/action` 调用的就是这条链路。

纯函数复现：同一物理状态，新录制首 X 为 7，在线 observation 首 X 为 1。把新录制格式下“保持当前位置”的目标交给在线 bridge，会生成左 X +6 μm、右 X −6 μm，并交换夹爪目标。复现只生成计划，未向设备发送指令；实际执行仍受后续保护约束。

已核对上游原点转换和遥测，没有额外左右交换可以抵消该差异。外部模型部署程序可能自行转换，但该程序不在此仓库中，不能据此认定完整部署已经补偿。

### 2. P1：原点归一化脚本未适配新的 pulses 顺序

[录制 pulses](https://github.com/ccoxo/E2EAPP_MicroMani/blob/72a7e2e6c8e640e87a94cb2992f60392ace66501/backend/services/dataset_recorder.py#L337) 已交换；原点与 kinematics 元信息保留原硬件左右顺序。[normalize_origin.py](https://github.com/ccoxo/E2EAPP_MicroMani/blob/72a7e2e6c8e640e87a94cb2992f60392ace66501/scripts/normalize_origin.py#L52) 仍直接按原顺序相减和转换。

纯函数复现：右侧 Y=10000 pulses、两侧原点均为零，新录制 Y 为 −1000 μm。归一化到同一原点后变成 +2000 μm，并返回 `changed=true`、`needs_manual_review=false`。这是把右侧脉冲套入左侧换算系数。未打开或写入任何实际数据集，未使用 `--apply`。

### 3. 旧数据续录缺少左右顺序版本检查

新旧数据保留相同 feature 名称、14 维 shape 和 `lerobot-v3-native` / `v3.0` 格式标记。[旧集恢复路径](https://github.com/ccoxo/E2EAPP_MicroMani/blob/72a7e2e6c8e640e87a94cb2992f60392ace66501/backend/services/dataset_recorder.py#L2913) 仍允许 resume，未加入左右顺序版本或旧集阻断。因此升级后续录同名旧集会有混合两种通道语义的风险。此项是静态调用链确认，未对真实旧集进行续录实验。

### 4. HKVL 默认值未在各层统一

[后端默认](https://github.com/ccoxo/E2EAPP_MicroMani/blob/72a7e2e6c8e640e87a94cb2992f60392ace66501/backend/core/defaults.py#L329) 和启动脚本已为 `hkvl_serial`，但 [前端默认](https://github.com/ccoxo/E2EAPP_MicroMani/blob/72a7e2e6c8e640e87a94cb2992f60392ace66501/frontend/src/data.ts#L427)、初始遥测帧、[HAL 原生默认](https://github.com/ccoxo/E2EAPP_MicroMani/blob/72a7e2e6c8e640e87a94cb2992f60392ace66501/hal/include/ForceControlRuntime.h#L19) 仍是 `nidaq`；部分缺字段 fallback 也未同步。

正常从后端成功加载配置后会覆盖前端默认，标准启动脚本也会向 HAL 提供 source。实际差异主要出现在初始显示、配置加载失败、缺字段或直接启动 HAL 的路径；不能把它表述为标准启动必然选错硬件。当前本地已经统一这些默认值，应保留。

## 部署文件与版本配套

- `backend/runtime/`、`frontend/dist/`、虚拟环境、HAL 二进制、SDK/DLL 被 `.gitignore` 明确排除。这属于运行环境和构建产物，不是源码漏传。现有硬件绑定、标定路径和依赖安装不会随 Git 自动复制。
- [start-hal.ps1](https://github.com/ccoxo/E2EAPP_MicroMani/blob/72a7e2e6c8e640e87a94cb2992f60392ace66501/scripts/start-hal.ps1#L176) 只提升已有 `.next.exe`、检查二进制是否存在；没有根据源码版本自动重编 HAL。前端启动则会构建源码。
- 因此仅更新源码可能形成新前端 + 旧 HAL。旧 HAL 没有新的 `calibration.state`，而 [录制预检](https://github.com/ccoxo/E2EAPP_MicroMani/blob/72a7e2e6c8e640e87a94cb2992f60392ace66501/frontend/src/components/record/PreCheckModal.tsx#L81) 要求该字段为 `ready`，HKVL 录制预检会无法通过。这是部署配套问题，不是要求把所有二进制提交 Git。
- [ACT 启动脚本](https://github.com/ccoxo/E2EAPP_MicroMani/blob/72a7e2e6c8e640e87a94cb2992f60392ace66501/scripts/run-act-deploy.ps1#L66) 使用仓库外的 `act_deploy.py` 和 checkpoint。本次新增了传给外部脚本的参数，但仓库没有该脚本及版本锁定，不能仅靠本仓库核实参数兼容性或左右转换。
- Python 依赖采用版本范围且没有锁文件；本次 Python 测试复用已安装的项目 venv。前端则独立按远端 lock 安装。未宣称全新机器环境可以一键复现。
- 附注：普通 DDS 命令与遥测共用同步 worker 是旧架构。两阶段 tare 期间中间 calibration phase 可能无法及时发布；此问题应归为既有架构限制被新流程加重，不归类为漏上传文件。

## 与当前本地优化的区别

当前本地有 37 个实现文件在远端不存在（统计 frontend/src、backend、hal、scripts，排除测试）；另有根目录 `Start-UI.cmd`。典型包括 UI 公共组件与 settings 拆分、frameSelectors、motionCommands、controlLease、control_watchdog、bounded_lane、ControlLeaseGuardian、WorkerExceptionBoundary。

这些是本地尚未进入远端的实现，远端源码本身没有引用它们。因此不能据此认定远端无法运行，但用远端整套覆盖会失去相关本地优化。合并应以当前本地为基础移植需要的功能，并保留现有执行侧保护与 HKVL 主用设置。

## 实际验证与限制

| 验证 | 结果 |
| --- | --- |
| backend 相机识别、硬件默认、力配置 | 35 passed |
| backend 遥测及配置 PermissionError 重试 | 7 passed |
| frontend 独立依赖安装 | 成功，禁用安装 lifecycle scripts；首次离线缓存不足，随后联网安装成功 |
| frontend `npm run typecheck` | 通过 |
| frontend 新功能筛选测试 | 3 文件，5 passed、88 因测试名筛选 skipped |
| HAL ForceCoreTests | 独立目录编译、运行通过；未启用 SDK/DDS，未调用设备 start/initialize |
| 数据契约纯函数复现 | 两个错配样例断言通过；另验证了上游原点转换一致 |

遥测兼容测试首次被审计环境的 `APPSTATION_HAL_MODE=test` 覆盖，导致 3 个原本使用 real 模式假硬件的断言失败；移除环境覆盖后，使用测试自身的假硬件，7 项通过，未改代码。前端曾尝试三个文件全量合跑，超过两分钟后中止；没有全量通过或失败结论。未运行前端生产打包、完整后端套件、完整 HAL/DDS 构建或实机验收。

证据文件均在本报告同目录：`inventory.json`、`remote-tree.json`、`static-closure.json`、`local-remote-coverage.json`、`source-verification.json`、`backend-focused-tests.log`、`backend-compatibility-tests-native-fixtures.log`、`frontend-typecheck.log`、`frontend-new-features-tests.log`、`recording_contract_repro.py`、`recording-contract-repro.json`，以及 `hal-forcecore-build/build.log`、`hal-forcecore-build/test.log`。

本轮仅生成审计快照、报告和验证产物。尚未修复以上缺口，也未进行合并。
