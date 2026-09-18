# HAL 急停与执行安全复核（2026-09-11）

已完成离线修复和针对性验证。没有启动 HAL、连接硬件、启停业务栈、执行实机动作或覆盖现有运行二进制。

## 已确认并修复

- **P1：旧操作/旧确认跨越急停后继续生效。** 原来的锁存位和序号分离，旧完成路径存在检查后再清锁的窗口；长回原点等待、逐轴使能/运动也只在入口检查。现在使用 `EmergencyStopState` 单原子状态，入口代际一直传到运动、原生启动、夹爪及 Omega 执行入口；等待与 SDK 调用前后复核，旧操作即使经过新确认也不能复活。硬件停车尚未返回，以及 dispatcher 尚未完成原生/Omega/力记账时，确认请求被拒绝。
- **P1：已发布但延迟到达的 DDS 动作在恢复后执行。** 普通命令和 follower 目标在执行前比较原始发送时间与最近急停时间；旧动作被丢弃。停止、只读、全关力和清零保持可用；随后再用入口代际覆盖处理期间发生的新急停。没有修改 IDL 或线协议。
- **P1：夹爪出队后、Omega 重力补偿和 native.configure 存在执行旁路。** 夹爪队列保存代际，出队及驱动锁内/向 SDK 或 worker 发命令之前再次检查。Omega 开力及 native.configure 间接开力使用相同代际；急停请求两侧关力，采样侧继续遵守关力请求。删除了 Omega 左侧重复写入。
- **P1：非有限数及脉冲转换溢出可绕过数值比较。** 运动参数、软限位、夹爪目标拒绝 NaN/Infinity；控制卡脉冲转换和差值检查整数范围，避免 `llround`、窄整数和 `abs(LONG_MIN)` 溢出。未改变物理阈值、坐标映射或既有单位。
- **P2：急停后重启/析构原生线程可能 `std::terminate`。** 急停会将运行标志清零，但旧线程仍然 joinable。现在 configure/start/stop 通过生命周期锁串行化，重启/析构回收已退出线程。DDS follower 的动作异常也在回调边界隔离。
- **恢复条件：** ForceControlRuntime 先完成对应运动代际的确认，失败时保留力安全锁存；成功确认只清锁，不自动使能轴或恢复 Omega 力输出。
- **P1：锁存后 Tare 可抹平持续接触载荷。** dispatcher 拒绝运动锁存/旧代际请求，runtime 在力锁存时拒绝进入驱动。采集窗口保存代际，急停、力超限、看门狗和重新配置都会使旧窗口失效；等待端每 10 ms 检查取消。最终采样先按旧偏置送入力安全，再在安全锁下复核并提交新偏置，避免最后一帧先去皮再检测。双侧先预检连接，并串行化 Tare，失败时清理未完成窗口。

## 验证

1. `backend/.venv/Scripts/python.exe -m pytest backend/tests/test_hal_source_contracts.py -q`：**103 passed**。
2. 不定义 `APPSTATION_ENABLE_VENDOR_SDKS`，在独立输出目录编译并链接：
   - `ForceCoreTests.exe`：**11 组逻辑测试通过**。
   - `EmergencyStopTests.exe`：**新增 9 组通过**，包括 200 次并发旧确认/新急停竞争、过时代际、原生启停析构、夹爪关口、旧 follower 目标、Omega 力门控、非法数值、跨子系统急停记账未完成时拒绝确认，以及 Tare 在力/运动锁存下和旧代际下不得进入串口驱动。
3. 定义 `APPSTATION_ENABLE_VENDOR_SDKS=1`，**9 个 cpp 仅编译通过**：ForceControlRuntime、HkvlForceDriver、LTDMCDriver、NativeTeleopController、Omega7Driver、JodellGripperDriver、HalCommandDispatcher、HalServer、TeleopHardwareTargetExecutor。此步骤没有链接或运行生产 HAL。
4. 修改范围 `git diff --check` 通过。

产物与可重放命令：

- `hal-offline/build-offline.cmd`、`build-offline.log`、`ForceCoreTests.log`、`EmergencyStopTests.log`。
- `hal-vendor-compile/compile-vendor.cmd`、`compile-vendor.log`（仅对象文件）。
- ForceCoreTests 的固定相对 fixture 已复制到本报告同级 `tests/fixtures/`，离线测试从 `hal-offline` 目录执行。

## 真实限制

- 配置中的 `F:/opt/ros/jazzy` Fast-DDS 头文件/库路径不存在，`HalDdsControlServer.cpp` 与 `TeleopFollowerTargetSubscriber.cpp` 的本次修改只完成源码契约检查，**没有完成 DDS 编译、完整 HAL 链接或 DDS 运行测试**。
- DDS 时间戳拒绝沿用当前同机 Unix 时钟契约。没有新增跨机器时钟同步或线协议代际字段。
- 软件无法保证撤回已经进入 vendor SDK 的调用，或夹爪硬件已经接受的命令；此次没有臆造未经 SDK 文档/实机验证的夹爪停车协议。
- Tare 锁存入口拒绝已运行 C++ 离线回归；串口采集窗口的提交顺序及取消门槛完成源码契约检查和编译，没有运行真实串口或模拟串口采样集成测试。
- 离线单元测试和启用真实宏的仅编译都不等于实机急停时延、制动距离、伺服反馈或碰撞安全验证；现有运行二进制未更新。
