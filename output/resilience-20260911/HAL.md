# HAL 软件线程与生命周期补强（2026-09-11）

本轮在现有 HAL 进程与 DDS 架构内补齐 Motion 轮询、HKVL 采样、Force watchdog、DDS 普通/紧急线程以及 follower 回调的 C++ 异常边界。没有新增硬件接线、进程侧车、真实设备运行或部署操作。既有物理阈值、左右映射、单位和急停代际保护保留。

## 本轮完成

| 位置 | 缺陷与最终行为 |
| --- | --- |
| `hal/src/MotionControlThread.cpp:26` | 原线程入口异常会越过 `std::thread`；异常把 running 清零后，原 stop 早退也可能漏 join。现在标准/非标准异常停止轮询、锁存运动并通知服务安全回调，stop 始终回收 joinable 线程。创建失败先关断再向调用方报告；频率为 0/负数的除零输入在启动前拒绝。类层允许显式 ACK 后本地 start；真实 HalServer 的故障回调永久撤销 lease，要求服务重启。 |
| `hal/src/HkvlForceDriver.cpp:88`、`:355` | 原双侧 serial 线程无异常边界，第二条线程创建失败会留下第一条运行。现在故障原子停止双侧、通知 ForceRuntime、取消去皮等待并记录侧诊断；启动失败立即 join 已启动线程。生命周期修改串行化，重新 start 先回收旧线程。 |
| `hal/src/HkvlForceDriver.cpp:313` | 读取或样本回调抛错时，原 `CloseHandle` 可能被跳过。串口 handle 现在由作用域对象关闭；该对象在更新状态和处理数据之前建立。 |
| `hal/src/ForceControlRuntime.cpp:125`、`:536` | 原 monitor 入口异常会终止进程，monitor 创建失败会留下 serial readers。现在故障先撤销运行/采样权限并调用安全关断，再记录 workerError 与力锁存；即使此前已锁存，也必须尝试停止。创建失败回收所有已启动线程。普通 ACK、直接 start 不清除此故障，需 configure 重建；诊断中明确 canAcknowledge=false。 |
| `hal/src/HalDdsControlServer.cpp:436`、`:463` | 普通与紧急线程都有完整标准/非标准异常边界，部分启动失败回收已创建线程；故障中止两个循环和余下批次，先撤销运动/Native/Omega 软件执行权限，再停机、记录故障。读取/发布的 SDK 错误返回不再只打印后继续控制。无远程重建入口的 DDS 线程故障永久撤销 lease，ACK/续租不能假恢复。 |
| `hal/src/TeleopFollowerTargetSubscriber.cpp:331` | 原仅包裹 executor.apply 的部分标准异常。现在整个 listener 都受异常边界保护，异常退出消费并通过 executor 完整停机、永久撤销 lease。stop 先禁止消费、detach listener，再等待在途回调及其失败处理完成。 |
| `hal/src/TeleopMappingNode.cpp:372`、`:416` | 补上原 listening 的跨线程数据竞争与停止期间继续 drain 的生命周期窗口。listening 改为原子；callback 串行化；stop 先 detach 再等在途回调退出，异常处理也在等待范围内。 |

共享 `WorkerExceptionBoundary.h` 仅负责包含标准/非标准 C++ 异常；每个组件自己的失败处理负责锁存与诊断，不能用“捕获后继续控制”代替安全停止。默认依赖仍为原线程创建和硬件读取；离线测试通过构造依赖注入使用内存读取循环，不打开串口。

## 跨层补充

- DDS 紧急 topic 仅允许 `motion.emergency_stop` 与 `control.lease`。续租直接进入 dispatcher，不经过可能阻塞在回原点的普通队列；其 session/sequence/issuedAt 检查由根代理实现的 lease 逻辑负责。IDL 未改。
- 普通非停止/只读命令在进入 dispatcher 前检查 `commandExpiresAtUnixMs`：字段存在但非法、非有限或已到期时拒绝执行。后端按请求超时自动覆盖该毫秒时间。旧客户端缺少字段时保留兼容；它们不因此绕过新服务所需的控制 lease。
- 复核 `ControlLeaseGuardian::stop` 时发现等待 join 后才撤销 lease 的窗口：若 SDK 停机阻塞，等待期间仍可能续租。已向根代理提供触发链，根代理将 stop 改为先永久撤权，再停止/等待，并增加阻塞 shutdown 回归；本轮原生批次包含该测试。
- 主程序构造/异常展开必须先停止 Native 与 DDS 命令再析构其捕获的 publisher/mapping。已向根代理指出启动过早和逆序析构窗口；根代理已完成 HalServer 顶层异常边界与 shutdown guard，本代理补充了顺序契约和最终 HalServer vendor 宏编译，见 [compile-server.log](hal-vendor-compile/compile-server.log)。

## 实际验证

全部产物在本目录，未覆盖 `hal/build` 中的可运行服务二进制。

| 检查 | 实际结果 |
| --- | --- |
| 新增 `WorkerResilienceTests` | **14 项通过**：Motion 标准/非标准失败、创建失败、频率校验、HKVL 样本回调失败与半启动回收、Force monitor 异常与创建失败、follower 多停止动作隔离及永久撤权、过期命令拒绝。 |
| 根代理 `ControlLeaseTests` | **9 项通过**，包含 guardian 阻塞退出期间拒绝续租。 |
| 既有 `ForceCoreTests` | **11 组通过**。 |
| 前轮 `EmergencyStopTests` | **9 项通过**，含 200 次并发 stop/ACK 竞态。 |
| 前轮 `ThreadStabilityTests` | **6 项通过**。 |
| `backend/tests/test_hal_source_contracts.py` | **113 项通过**；更新旧内联断言以验证新 lease/原子停止委托边界，未删除原安全要求。 |
| 独立 MSVC C++20 编译与链接 | 上述 5 个测试程序均编译、链接并运行通过；见 [build-offline.cmd](hal-offline/build-offline.cmd)、[build-offline.log](hal-offline/build-offline.log)。 |
| 真实 vendor 宏编译 | `APPSTATION_ENABLE_VENDOR_SDKS=1` 下 **11 个源文件仅编译通过**，没有链接或设备运行；见 [compile-vendor.cmd](hal-vendor-compile/compile-vendor.cmd)、[compile-vendor.log](hal-vendor-compile/compile-vendor.log)。 |
| `git diff --check` | 通过，仅 Git 换行提示。 |

原生行为日志：[WorkerResilienceTests](hal-offline/WorkerResilienceTests.log)、[ControlLeaseTests](hal-offline/ControlLeaseTests.log)、[ForceCoreTests](hal-offline/ForceCoreTests.log)、[EmergencyStopTests](hal-offline/EmergencyStopTests.log)、[ThreadStabilityTests](hal-offline/ThreadStabilityTests.log)。源码契约：[hal-source-contracts.log](hal-source-contracts.log)。

vendor 宏编译文件：ForceControlRuntime、HkvlForceDriver、LTDMCDriver、NativeTeleopController、Omega7Driver、JodellGripperDriver、HalCommandDispatcher、HalServer、TeleopHardwareTargetExecutor、HalHttpServer、MotionControlThread。测试程序关闭 vendor/DDS 宏，不能以测试程序的通过代替真实 SDK 行为验证。

## 未完成的验证及软件边界

1. 当前配置的 Fast-DDS SDK 根目录 `F:/opt/ros/jazzy` 不存在。DDS 文件本轮只有源码契约复核；**没有真实 DDS 编译、完整 HalServer 链接或 listener 调度/退出集成运行**。follower 测试验证的是相同异常边界与实际 executor 关断动作，不冒充 DDS SDK listener 测试。
2. 所有离线串口测试使用注入的内存读取函数，没有打开 COM 口；句柄关闭路径做了源码复核与 Windows vendor 宏编译，没有真实串口故障测试。
3. 纯软件可以先撤销命令权限、包含 C++ 异常、避免迟到请求与假恢复；无法保证在整个 HAL 被强杀、Windows 整体冻结、驱动 DLL 访问违规、内存破坏或 SDK 永久阻塞时完成真实硬件制动。本轮保持既有部署架构，不增加硬件或独立进程，也不声称这些物理边界已经消失。
4. 线程退出等待实际读取/SDK 调用返回；没有强杀 C++ 线程或在资源仍被使用时强行销毁对象。DDS SDK 内部资源删除失败、原生异常与回调调度保证需要在具备对应 SDK 的环境验证。
