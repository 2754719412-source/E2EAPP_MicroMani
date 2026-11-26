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
#include "JodellModbusClient.h"
#include "NativeTeleopController.h"
#include "OfflineMotion.h"

using namespace appstation::hal;
namespace jodell = appstation::hal::jodell;
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
    if (line == "READ" || line == "READPOS") {
      { std::ofstream verbs(path + ".verbs", std::ios::app); verbs << line << '\n'; }
      if (port == "SLOW") {
        { std::ofstream entered(path + ".read"); entered << "entered"; }
        Sleep(1000);
      }
      else Sleep(15);
      if (port == "SAMPLE" || port == "STALE") {
        // 结构化样本：SAMPLE 每次新时间戳；STALE 恒定时间戳，模拟同一读数被重复上报。
        static int counter = 0;
        jodell::StatusRegisters registers{1, 0, 1, 3, 2, 0, 200, 0, 100 + (counter++ % 50)};
        const auto stamp = port == "STALE" ? std::int64_t{1} : jodell::steadyNowUs() - 7000;
        std::cout << "OK\t12\tmeasured\t" << jodell::formatSampleFields(jodell::sampleFromStatus(registers, stamp))
            << std::endl;
        continue;
      }
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

std::string readText(const std::string& path) {
  std::ifstream in(path);
  return std::string(std::istreambuf_iterator<char>(in), {});
}
void testReadVerbFollowsScenario(const char* exe) {
  Fixture f(exe, "_verbs");
  const auto verbs = f.log.string() + ".verbs";
  std::filesystem::remove(verbs);
  f.driver.configure(f.config);
  std::string message;
  require(f.driver.readPositionMm(Side::Left, &message), "default READ failed");
  require(f.driver.readPositionMm(Side::Left, &message, false), "position-only READ failed");
  require(readText(verbs) == "READ\nREADPOS\n", "worker verb did not follow withStatus");
  std::filesystem::remove(verbs);
  f.teleop.prepareReplayGripper(f.config, f.motion.commandEpoch(), {true, false});
  await([&] { return readText(verbs).size() >= 10; }, "replay sampler did not READ");
  require(readText(verbs).find("READPOS") == std::string::npos, "replay sampler dropped torque");
  f.teleop.stop();
  std::filesystem::remove(verbs);
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

void testStructuredSamplesGetSequenceAndHistory(const char* exe) {
  Fixture f(exe, "_samples");
  f.config.ports = {"SAMPLE", "STALE"};
  f.teleop.configureGripperFeedback(f.config, {true, true});
  // 第一个 "seq" 属于左侧最新样本。
  await([&] { return jsonNumberValue(f.status(), "seq", 0) >= 3; }, "structured samples missing");
  const auto status = f.status();
  require(status.find("\"timestampSource\":\"worker\"") != std::string::npos, "worker timestamp rejected");
  require(status.find("\"currentValid\":true") != std::string::npos, "current not reported");
  require(jsonNumberValue(status, "gOBJ", -1) == 2, "gOBJ missing");
  const auto history = status.substr(status.find("\"gripperSampleHistory\":{"));
  require(history.find("\"left\":[[1,") != std::string::npos && history.find("],[3,") != std::string::npos,
      "left history not sequential");
  // 恒定时间戳的右侧只能记一次；该时间戳不在请求窗口内，退回 HAL 中点。
  const auto rightStart = history.find("\"right\":[");
  const auto right = history.substr(rightStart, history.find("]]", rightStart) + 2 - rightStart);
  require(right.rfind("\"right\":[[1,", 0) == 0 && right.find("],[") == std::string::npos, "duplicate reading recorded");
  require(status.find("\"timestampSource\":\"hal_midpoint\"") != std::string::npos, "out-of-window stamp trusted");
  require(status.find("\"effectiveHz\":") != std::string::npos && status.find("\"maxGapMs\":") != std::string::npos,
      "sample statistics missing");
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
    testReadVerbFollowsScenario(argv[0]);
    testStructuredSamplesGetSequenceAndHistory(argv[0]);
    std::cout << "GripperFeedbackTests passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
