# 夹爪结构化反馈、电流数据与现场验收

本文说明夹爪反馈从 worker 到数据集的链路、新数据集格式，以及现场需要完成的验收步骤。
离线测试只覆盖模拟设备、源码契约和 mingw 编译链接；**MSVC 构建、真实串口和夹爪都还没验证**。

## 链路

| 环节 | 位置 | 说明 |
| --- | --- | --- |
| 读取 | `hal/src/JodellGripperWorker.cpp`、`hal/include/JodellModbusClient.h` | `gripper.workerTransport=modbus` 时，每侧 worker 独占串口。读取用一次 `0x04` 请求连读 `0x07D0` 起 3 个寄存器，位置、状态、gCU 来自同一次应答，共用同一个时间戳（请求发出到应答收齐的中点，取 steady_clock） |
| 写命令 | 同上 | 先读状态：有故障就拒绝。只有 `gACT/gSTA` 显示未使能时，才写 `rACT=1` 并等待使能完成（手册说明使能可能带动手指）。然后写运动帧，并校验回显 |
| 默认路径 | 同上 | 默认 `dll`，行为与原来一致。DLL 遥操作只读位置（READPOS），没有电流；样本里电流标为无效 |
| 编号与历史 | `hal/src/NativeTeleopController.cpp` | 每次成功读数分配该侧递增的 `seq`，按 worker 时间戳去重。时间戳不在请求窗口内时，改用 HAL 侧中点（`timestampSource=hal_midpoint`）。状态 JSON 提供最新样本 `grippers.<side>.sample`、`sampleStats`（样本数、有效频率、最长断样），以及每侧最近 256 条的 `gripperSampleHistory` |
| 采样间隔 | `gripper.sampleHz` → `gripperSampleIntervalMs` | 默认 30 Hz，不变。HAL 每次读完等这么久再读下一次，并夹紧到 5–1000 ms |
| 收集 | `backend/services/gripper_raw_samples.py` | 录制采样线程每次取 native 状态时按 `seq` 收入新读数。重复行丢弃；跳号计为 `missedSeq`（HAL 历史已滚动覆盖，样本确实丢失） |

## 新数据集格式

- 数值侧序契约仍是 `appstation.dual_arm.operator_sides.v2`，Policy API 的校验不变。
- 新增录制格式 `appstation.recording.gripper_current.v1`，写在 `meta/appstation_info.json` 和 `meta/info.json` 的 `recordingFormat` 中。
  - 没有该字段或版本不同的旧数据集：照常读取和回放，但**拒绝续录**，需要新建数据集。
- 新增 feature，均按操作者左、操作者右排列；14 维 `state/action` 含义不变：
  - `observation.gripper_current_raw`：gCU 原码 0–255，未换算成牛顿；
  - `observation.gripper_current_valid`：1 表示这一帧对齐到了一个有效电流读数；没有读数、读数无效或该侧未参与时为 0，对应的原码也写 0。
- 训练帧取离目标时刻最近的读数（偏差不超过 70 ms），同一个读数可以被多帧引用。
- 每个 episode 另存 `gripper_raw/episode_XXXXXX.parquet`：每个 `seq` 一行，包含硬件侧和数据集侧、时间、各有效标志、位置原码和开口、gCU、gACT/gGTO/gSTA/gOBJ、故障码，以及读数时刻之前最近一次的命令开口。
  - 保存失败不影响训练帧保存，原因写入 episode 元数据。
  - 复核时弃用某个 episode，会同时删除它的旁路文件。
- episode 元数据新增 `gripperRaw` 段：
  - `stats`：每侧条数、有效频率、最长断样、跳号数等；
  - `idleStartCheck`：录制前空载检查结果；
  - `contactEvents`：接触片段（训练帧区间、读数 seq 区间、证据、峰值原码）；
  - `transport`。

## 录制前空载放行（仅 modbus 传输）

在原有“开口接近起始开口并稳定 300 ms”之外，对每个参与侧最近 300 ms 的真实读数逐条检查。下面任一条件不满足就不放行，并提示原因：

- 至少 5 条，最新一条不超过 250 ms；
- `seq` 连续，没有跳号；
- 位置、状态、电流都有效，故障码为 0；
- 没有 `gGTO=1` 且 `gOBJ∈{1,2}` 的接触报告；
- 实际开口在起始开口 ±1 mm 内；
- 有匹配的夹持力标定时，gCU 不超过标定得到的空载阈值。没有标定时不判电流大小，记为 `passed_without_current_threshold`。

`dll` 传输读不到电流，不做这项检查，在元数据里记为 `skipped_dll_transport`。

## 接触片段判据

一个读数算作接触，需要同时满足：
- 实测开口高于最小开度 + 0.2 mm；
- 命令开口比实测开口小 0.3 mm 以上（仍在往里夹）；
- 并且满足下面任一证据：
  - `gGTO=1` 且 `gOBJ=2`；
  - gCU 高于空载阈值。

`gGTO` 不为 1 时不采用 `gOBJ`。既没有可用的 gOBJ、又没有电流阈值时，只有在开口已经停住（与上一读数相差 ≤ 0.05 mm）的情况下，才记为位置候选片段（`candidate=true`），供人工复核。

> **手册矛盾，需现场确认**：手册 6.3.1 正文说“gGTO=0 时 gOBJ 无效”，但第 7 章的“到位完成”（状态 `0xF1`）和“夹到物体”（`0xB1`）示例应答里，gGTO 都是 0，gOBJ 分别为 3 和 2。如果实机也这样，夹持完成后的 gOBJ=2 会被上面的规则忽略，接触片段主要依靠电流阈值，所以需要先完成夹持力标定。请在验收时记录夹持过程中 gGTO 和 gOBJ 的实际取值。

## 现场验收步骤

1. **确认 DLL 导出**（只读）：`dumpbin /exports jodellTool.dll`，记录是否有块读接口。当前实现不依赖它：选 `modbus` 时 worker 不加载 DLL。
2. **构建**：从同一份源码用 MSVC 构建 `HalServer.exe` 和 `JodellGripperWorker.exe`，并运行 `hal/tests/run_motion_tests.cmd`（含新增 `JodellModbusTests`）和 CMake 的 `GripperFeedbackTests`（含结构化样本用例）。不要覆盖正在运行的程序。
3. **只读验证**：部署后保持 `workerTransport=dll`，确认行为和原来一致。然后停机改成 `modbus`，只开只读反馈采样，查看 `teleop.native.status` 中每侧的 `sample`（`transport=modbus`，三个有效标志均为 true）和 `sampleStats`。
4. **命令验证**（需要运动授权）：在空载、指间无物体时下发小幅开合，核对：
   - 首次命令是否触发使能，之后的命令不再触发；
   - 不切换 rGTO、直接改写 rPR 时，夹爪是否跟随新目标（手册没有说明是否需要先把 rGTO 拉低再置高，这是重点确认项）；
   - gCU 在运动、到位、夹持时的取值，以及上面那条手册矛盾。
5. **频率与延迟**：双侧同时工作，把 `gripper.sampleHz` 从 30 逐步提高（例如 60、100）。每档记录每侧的 `effectiveHz`、`maxGapMs`、`missedSeq`，以及 `lastCommandDurationMs`（命令延迟）。选一个命令延迟不明显增加的档位。
6. **录制**：新建数据集，确认空载放行能拦下“指间有物体”和“故障”两种情况；录几个抓取 episode 后，检查 `gripper_raw` 旁路文件的行数与 `stats.samples` 一致，`contactEvents` 的帧区间和视频对得上。

验收通过之前，`workerTransport` 默认保持 `dll`，`applyCommandForceLimit` 默认保持关闭。
