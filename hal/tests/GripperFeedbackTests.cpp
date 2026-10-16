// 独立进程替身：只处理测试管道，不加载 SDK、不打开设备串口。
#include <windows.h>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>
#include "HalJson.h"
#include "NativeTeleopController.h"
#include "OfflineMotion.h"

using namespace appstation::hal;
using namespace std::chrono_literals;
namespace {
void require(bool value, const char* text) { if (!value) throw std::runtime_error(text); }
std::string arg(int argc, char** argv, const std::string& key) {
  for (int i = 1; i + 1 < argc; ++i) if (argv[i] == key) return argv[i + 1];
  return "";
}
int worker(int argc, char** argv) {
  const auto port = arg(argc, argv, "--port");
  const auto path = arg(argc, argv, "--dll");
  std::string line;
  while (std::getline(std::cin, line) && line != "EXIT") {
    if (line == "READ") {
      if (port == "SLOW") {
        { std::ofstream entered(path + ".read"); entered << "entered"; }
        Sleep(1000);
      }
      else Sleep(15);
      std::cout << (port == "ERROR" || std::filesystem::exists(path + ".fail")
          ? "ERR\t-1\tread_failed" : "OK\t12\tmeasured") << std::endl;
    } else if (line.rfind("COMMAND", 0) == 0) {
      { std::ofstream log(path, std::ios::app); log << line << '\n'; }
      Sleep(45);
      std::cout << "OK\t12\tcommand_complete" << std::endl;
    }
  }
  return 0;
}
template<class Predicate> void await(Predicate ready, const char* error) {
  const auto end = std::chrono::steady_clock::now() + 2s;
  while (!ready() && std::chrono::steady_clock::now() < end) std::this_thread::sleep_for(2ms);
  require(ready(), error);
}
struct Fixture {
  LTDMCDriver motion;
  MotionExecutor executor{motion};
  Omega7Driver omega;
  JodellGripperDriver driver;
  NativeTeleopController teleop{motion, executor, omega, driver};
  std::filesystem::path log;
  JodellGripperConfig config;
  Fixture(const char* exe, const char* suffix) {
    log = std::filesystem::temp_directory_path() /
        ("MicroManiFeedback_" + std::to_string(GetCurrentProcessId()) + suffix + ".log");
    std::filesystem::remove(log);
    std::filesystem::remove(log.string() + ".read");
    std::filesystem::remove(log.string() + ".fail");
    config.workerExePath = exe;
    config.dllPath = log.string();
    config.ports = {"FAST", "FAST"};
  }
  ~Fixture() {
    teleop.stop();
    std::filesystem::remove(log);
    std::filesystem::remove(log.string() + ".read");
    std::filesystem::remove(log.string() + ".fail");
  }
  std::string status() { return teleop.statusJson(); }
};
void testReadonlyWhileStopped(const char* exe) {
  Fixture f(exe, "_stopped");
  f.motion.latchEmergencyStop();
  f.teleop.configureGripperFeedback(f.config, {true, false});
  await([&] { return jsonBoolValue(f.status(), "positionOk", false); }, "READ did not produce feedback");
  const auto first = jsonNumberValue(f.status(), "positionSampleTs", 0);
  require(first > 1000000000000.0, "measurement time missing");
  require(jsonNumberValue(f.status(), "positionMm", -1) == 12, "measurement replaced by target");
  require(!std::filesystem::exists(f.log), "sampling sent a COMMAND");
  require(f.motion.estopActive() && !f.teleop.running() && !f.teleop.replayGripperReady(), "sampling enabled control mode");
  f.teleop.configureGripperFeedback(f.config, {true, false});
  require(jsonNumberValue(f.status(), "positionSampleTs", 0) >= first, "identical setup discarded feedback");
  await([&] { return jsonNumberValue(f.status(), "positionSampleTs", 0) > first; }, "unchanged position did not get a new READ timestamp");
}
void testSynchronousCommandAndFailureIsolation(const char* exe) {
  Fixture f(exe, "_sync");
  f.config.ports[1] = "SLOW";
  f.teleop.configureGripperFeedback(f.config, {true, true});
  await([&] { return jsonBoolValue(f.status(), "positionOk", false); }, "left feedback unavailable");
  const auto started = std::chrono::steady_clock::now();
  std::string message;
  require(f.teleop.commandGripperTarget(Side::Left, 18, 10, 1, &message), "sync command rejected");
  const auto elapsed = std::chrono::steady_clock::now() - started;
  require(message == "command_complete" && elapsed >= 40ms, "command returned queue acknowledgement");
  require(elapsed < 300ms, "other side slow READ delayed command");
  require(jsonNumberValue(f.status(), "positionMm", -1) == 12, "target masqueraded as position");
  const auto configureStarted = std::chrono::steady_clock::now();
  for (int i = 0; i < 100; ++i) f.teleop.configureGripper(f.config);
  require(std::chrono::steady_clock::now() - configureStarted < 100ms, "same config waited for driver READ");
}
void testReadTimeoutAndEmergency(const char* exe) {
  Fixture f(exe, "_timeout");
  f.config.ports[0] = "SLOW";
  f.teleop.configureGripperFeedback(f.config, {true, false});
  await([&] { return jsonNumberValue(f.status(), "readAttempts", 0) > 0; }, "READ timeout was not reported");
  require(!jsonBoolValue(f.status(), "positionOk", true), "timed out READ marked valid");
  require(jsonNumberValue(f.status(), "positionSampleTs", -1) == 0, "failed READ fabricated a timestamp");
  require(jsonNumberValue(f.status(), "lastReadDurationMs", 2000) < 400, "READ used two-second command timeout");
  const auto started = std::chrono::steady_clock::now();
  f.motion.latchEmergencyStop();
  f.teleop.requestEmergencyStop();
  require(std::chrono::steady_clock::now() - started < 100ms, "emergency stop waited for READ");
  require(!f.teleop.commandGripperTarget(Side::Left, 18, 10, 1), "emergency allowed a command");
  f.config.ports[0] = "FAST";
  f.teleop.configureGripperFeedback(f.config, {true, false});
  await([&] { return jsonBoolValue(f.status(), "positionOk", false); }, "new successful READ did not recover feedback");
  require(!std::filesystem::exists(f.log), "timeout or recovery replayed a command");
}

void testSameSideReadYieldsToSynchronousCommand(const char* exe) {
  Fixture f(exe, "_same_side");
  f.config.ports[0] = "SLOW";
  f.teleop.configureGripperFeedback(f.config, {true, false});
  await([&] { return std::filesystem::exists(f.log.string() + ".read"); }, "slow READ did not start");
  const auto started = std::chrono::steady_clock::now();
  std::string message;
  require(f.teleop.commandGripperTarget(Side::Left, 18, 10, 1, &message), "command behind READ failed");
  require(message == "command_complete", "slow READ changed command into queued target");
  require(std::chrono::steady_clock::now() - started < 300ms, "same-side READ blocked command too long");
  require(jsonNumberValue(f.status(), "readSkippedBusy", 0) > 0, "sampler did not yield to command");
}

void testFailedReadPreservesLastSuccessTime(const char* exe) {
  Fixture f(exe, "_failure_after_success");
  f.teleop.configureGripperFeedback(f.config, {true, false});
  await([&] { return jsonBoolValue(f.status(), "positionOk", false); }, "initial READ failed");
  { std::ofstream fail(f.log.string() + ".fail"); fail << "fail"; }
  await([&] { return !jsonBoolValue(f.status(), "positionOk", true); }, "failed READ not marked invalid");
  const auto failed = f.status();
  const auto lastSuccess = jsonNumberValue(failed, "positionSampleTs", 0);
  const auto attempts = jsonNumberValue(failed, "readAttempts", 0);
  require(lastSuccess > 0, "failure discarded last successful timestamp");
  await([&] { return jsonNumberValue(f.status(), "readAttempts", 0) > attempts; }, "next failure missing");
  require(jsonNumberValue(f.status(), "positionSampleTs", 0) == lastSuccess, "failure refreshed old measurement time");
  std::filesystem::remove(f.log.string() + ".fail");
  await([&] { return jsonBoolValue(f.status(), "positionOk", false); }, "feedback did not recover");
  require(jsonNumberValue(f.status(), "positionSampleTs", 0) > lastSuccess, "recovery reused old timestamp");
  require(!std::filesystem::exists(f.log), "read recovery sent a command");
}
}
int main(int argc, char** argv) {
  if (argc > 1) return worker(argc, argv);
  try {
    testReadonlyWhileStopped(argv[0]);
    testSynchronousCommandAndFailureIsolation(argv[0]);
    testReadTimeoutAndEmergency(argv[0]);
    testSameSideReadYieldsToSynchronousCommand(argv[0]);
    testFailedReadPreservesLastSuccessTime(argv[0]);
    std::cout << "GripperFeedbackTests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
