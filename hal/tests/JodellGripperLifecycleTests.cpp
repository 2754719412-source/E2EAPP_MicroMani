#include <windows.h>
#include <iostream>
#include <stdexcept>
#include <string>
#include "JodellGripperDriver.h"

using namespace appstation::hal;

int main(int argc, char** argv) {
  // 自身充当管道 worker，不加载厂商 DLL、不连接串口。
  if (argc > 1) {
    std::string line;
    while (std::getline(std::cin, line) && line != "EXIT") {
      std::cout << "OK\t12\t" << GetCurrentProcessId() << std::endl;
    }
    return 0;
  }
  try {
    using namespace std::chrono_literals;
    const auto start = std::chrono::steady_clock::now();
    const auto period = 33333us;
    const auto next = nextGripperSampleAt(start, period, start + 19ms);
    if (next != start + period || nextGripperSampleAt(next, period, next + 27ms) != start + 2 * period) {
      throw std::runtime_error("serial read time added to the gripper sampling period");
    }
    if (nextGripperSampleAt(start, period, start + 500ms) < start + 500ms) {
      throw std::runtime_error("delayed gripper read left a backlog of polls");
    }
    JodellGripperDriver driver;
    JodellGripperConfig config;
    config.workerExePath = argv[0];
    driver.configure(config);
    const auto worker = [&]() {
      std::string message;
      if (!driver.commandTarget(Side::Left, 12, 10, 1, &message)) {
        throw std::runtime_error(message);
      }
      return message;
    };
    const auto first = worker();
    driver.configure(config);
    if (worker() != first) throw std::runtime_error("identical config restarted worker");
    config.ports[0] = "COM_TEST_ONLY";
    driver.configure(config);
    if (worker() == first) throw std::runtime_error("changed config retained old worker");
    config.enabled = false;
    driver.configure(config);
    if (driver.commandTarget(Side::Left, 12, 10, 1)) {
      throw std::runtime_error("disabled driver accepted command");
    }
    std::cout << "JodellGripperLifecycleTests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
