// 仅供跨进程 DDS 测试：运行真实控制服务，但不启动或连接任何设备。
#if defined(APPSTATION_ENABLE_VENDOR_SDKS) && APPSTATION_ENABLE_VENDOR_SDKS
#error Shared-memory fixture must not enable device SDKs
#endif
#include "OfflineMotion.h"
#include "MotionControlThread.h"
#include "HalDdsControlServer.h"
#include <cstdlib>
#include <iostream>

using namespace appstation::hal;

int main(int argc, char** argv) {
  try {
    if (argc != 2) throw std::runtime_error("an isolated test domain is required");
    _putenv_s("APPSTATION_DDS_DOMAIN_ID", argv[1]);
    _putenv_s("APPSTATION_HAL_DDS_ENABLED", "1");
    const auto started = std::chrono::steady_clock::now();
    LTDMCDriver motion;
    MotionExecutorTestAccess::initialize(motion);
    MotionControlThread polling(motion);
    polling.start(100);
    MotionExecutor executor(motion);
    Omega7Driver omega;
    JodellGripperDriver gripper;
    NativeTeleopController native(motion, executor, omega, gripper);
    ForceControlRuntime force([&] { motion.emergencyStop(); }, [] {});
    HalCommandDispatcher dispatcher(motion, executor, omega, native, force, started);
    HalDdsControlServer server(dispatcher, motion, omega, native, force, started);
    server.start();
    std::cout << "READY" << std::endl;
    std::string command;
    while (std::getline(std::cin, command) && command != "quit") {
      if (command == "lock") {
        auto executorLock = MotionExecutorTestAccess::holdExecutor(executor);
        auto driverLock = MotionExecutorTestAccess::holdDriver(motion);
        std::cout << "LOCKED" << std::endl;
        std::getline(std::cin, command);
        if (command != "unlock") throw std::runtime_error("expected unlock");
        std::cout << (motion.estopActive() ? "ESTOP_LATCHED" : "ESTOP_MISSING") << std::endl;
      }
    }
    // 先回收测试创建的夹爪子进程，再释放 DDS 资源，避免继承句柄影响重连。
    native.stop();
    JodellGripperConfig stoppedGripper;
    stoppedGripper.enabled = false;
    native.configureGripper(stoppedGripper);
    server.stop();
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << std::endl;
    return 1;
  }
}
