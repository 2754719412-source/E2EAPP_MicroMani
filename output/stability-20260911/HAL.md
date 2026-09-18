# HAL 线程与回调稳定性复核（2026-09-11）

本轮定位并修复了三组具体缺陷：控制回调异常后继续运行、力安全回调异常向采样/监控线程传播，以及诊断 HTTP 无界创建线程。安全控制发生未预期 C++ 异常时锁存运动急停、退出相关控制循环并保留诊断；没有把控制异常简单吞掉后继续运动。常规主手断连仍使用原有按侧处理分支。

所有验证均离线完成；没有启动 HAL、HTTP 监听、串口采样、真实设备或启停栈，没有覆盖运行二进制。工作区已有的注释、前端重构和前轮急停代际修复全部保留。

## 证据与修复

### 1. P1：Native 控制回调异常未保证停止，非标准异常可能结束进程

- 修复前 `NativeTeleopController::loop` 捕获 `std::exception` 后只设置错误，下一帧仍继续运行；主控制线程和夹爪线程没有完整异常边界。DDS 映射回调也没有统一处理未预期异常。
- 离线注入发布回调异常，修复前确实失败：`publisher exception was swallowed while control kept running without a safety latch`。证据：[baseline-tests.log](hal-offline/baseline-tests.log)。这证明回调控制流缺陷，不表示在真机上触发过该故障。
- `hal/src/NativeTeleopController.cpp:465`、`:579` 给两类线程增加标准/非标准异常边界及线程创建失败处理。`:548` 的 `reportControlFailure(...) noexcept` 先停止循环，再分别尝试运动急停、清空待执行命令、关闭 Omega 力输出；各动作异常不会阻断后续动作，诊断失败也不向线程入口传播。
- `hal/src/NativeTeleopController.cpp:910` 的按侧未预期异常进入同一锁存路径；没有修改正常断连判定、单位、映射或物理阈值。
- `hal/src/TeleopMappingNode.cpp:402` 为 DDS Leader 回调增加同样的失败入口；`:396` 与 `hal/src/TeleopLeaderPublisher.cpp:234` 检查 DDS 发布返回值，防止发布失败被当作成功控制帧。DDS SDK 不在当前环境，这部分只有源码契约检查，未进行 SDK 编译或集成运行。
- 回归涵盖标准异常、`throw 42`、仅调用一次失败发布回调、停机锁存、可见错误，以及显式确认恢复后回收旧线程并重新启动。

### 2. P1：力安全回调抛错会传播到共享采样/监控调用链

- `ForceControlRuntime` 的 emergency callback 由 HKVL 采样和 watchdog 监控共同调用；修复前直接调用，回调异常会逃出当前调用栈。离线注入标准异常，修复前确实失败：`emergency callback exceptions must not escape into serial or monitor workers`。证据：[baseline-force-callback.log](hal-offline/baseline-force-callback.log)。
- `hal/src/ForceControlRuntime.cpp:506` 的回调边界现在捕获标准及非标准异常，保留已有力锁存，记录错误；`:237` 禁止仅靠安全采样/普通 ACK 消除回调失败。`:391` 的遥测将 `canAcknowledge` 置为 false，并输出 `emergencyCallbackError` 和恢复阻断原因。重新配置后仍要满足原有安全恢复条件。
- `hal/src/HalServer.cpp:49` 将实际组合回调中的 motion、native、Omega 三个停止动作分别尝试，最后把首个错误交给 ForceRuntime 记录；避免某一停止动作抛错时漏掉后续安全动作。
- 离线测试覆盖两类异常被包含、力锁存保留、已经收到满足时间要求的安全样本仍拒绝 ACK、诊断信息可见。

### 3. P2：诊断 HTTP 无界 detached 线程及线程创建失败路径

- 原入口每接收一个连接就创建 detached 线程，无并发上限；线程创建失败没有捕获，会逃出 server/main。连接回调持有 dispatcher 引用但没有线程回收所有权。
- 原代码已经设置 30 秒接收超时；不能描述为“完全没有 recv 超时”。问题是返回值未检查、没有发送超时，以及无界并发。
- `hal/src/HalHttpServer.cpp:159` 使用最多 32 个可回收 worker 槽位；饱和时关闭新连接。`:167` 使用 socket 作用域回收，线程创建失败也关闭 socket；标准/非标准连接异常都释放槽位。
- `hal/include/HttpConnectionWorkers.h:17` 使用 `std::jthread`；槽位销毁时先回收线程，再销毁线程访问的状态，不保留 detached 的 dispatcher 引用。`hal/src/HalHttpServer.cpp:84` 保留接收超时、增加等长发送超时，并验证配置结果。健康检查协议保持不变。
- 两项纯内存回归验证并发上限、完成后复用、异常后释放槽位。未启动 socket 服务，未实测 TCP 超时、线程创建资源耗尽或长连接负载；源码检查和 Windows 编译覆盖对应实现。

## 实际验证

| 检查 | 结果 | 产物 |
| --- | --- | --- |
| 新增 `ThreadStabilityTests` | 6 项通过 | [日志](hal-offline/ThreadStabilityTests.log) |
| 既有 `ForceCoreTests` | 11 组通过 | [日志](hal-offline/ForceCoreTests.log) |
| 前轮 `EmergencyStopTests` | 9 项通过，含 200 次并发 stop/ACK 竞态 | [日志](hal-offline/EmergencyStopTests.log) |
| `backend/tests/test_hal_source_contracts.py` | 107 项通过 | [日志](hal-source-contracts.log) |
| MSVC C++20 离线编译、链接上述三个测试程序 | 通过 | [脚本](hal-offline/build-offline.cmd)、[日志](hal-offline/build-offline.log) |
| 开启 `APPSTATION_ENABLE_VENDOR_SDKS=1` 编译 10 个源文件 | 仅编译通过，没有链接/运行 | [脚本](hal-vendor-compile/compile-vendor.cmd)、[日志](hal-vendor-compile/compile-vendor.log) |
| `git diff --check -- hal/include hal/src hal/tests backend/tests/test_hal_source_contracts.py` | 通过，仅 Git 换行提示 | — |

真实 SDK 宏编译范围是 ForceControlRuntime、HkvlForceDriver、LTDMCDriver、NativeTeleopController、Omega7Driver、JodellGripperDriver、HalCommandDispatcher、HalServer、TeleopHardwareTargetExecutor、HalHttpServer。离线测试程序没有启用 vendor/DDS 宏，使用未初始化设备与进程内回调；它们不能证明 SDK 设备动作或真实制动力正常。

项目配置的 Fast-DDS 根目录 `F:/opt/ros/jazzy` 不存在，因此本轮没有编译 DDS 宏分支、链接完整 HalServer 或验证 DDS listener 的运行生命周期。

## 仍然存在的边界与耦合

- HAL 仍是共享地址空间。驱动 DLL 的访问违规、内存破坏、Windows 原生异常、进程被结束以及硬件固件故障，不能靠 `/EHsc` 下的 C++ `try/catch` 消除；本轮没有实现完整进程隔离或外部硬件 watchdog。
- `MotionControlThread::loop`、HKVL `runSide`、Force `monitorLoop`、DDS 普通/急停轮询仍没有覆盖整个入口的通用异常处理。已修复能明确复现的共享回调异常源；其余 SDK、分配或系统层异常仍可能终止整个 HAL。没有证据就不能声称已覆盖所有线程崩溃路径。
- MotionControlThread 的公开 `start(hz)` 假定正数，目前唯一服务调用传入 1000；未将未出现于当前调用图的 `hz=0` 当作已发生的生产故障。其注释中“readState 内部异常隔离”不能作为完整线程隔离的证明。
- DDS follower 现有执行回调只覆盖部分标准异常；DDS 组件拆卸和 SDK listener 并发行为在当前环境未验证。
- 保持进程诊断存活与允许继续运动是两个决策。本轮 Native 未预期异常选择锁存全局运动停止；没有为了单模块“可用性”自动放行其他运动控制。恢复必须经过已有显式 ACK/重启或力配置恢复门槛。
- HTTP 并发已有限制，但没有新增完整服务器关闭协议，也没有承诺能中断永久阻塞的 SDK 调用；`jthread` 回收需要当前回调实际返回。

本报告不替代设备急停链路、控制器断电能力、SDK 故障注入及真实碰撞风险验收。
