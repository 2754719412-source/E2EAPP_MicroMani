#include "ForceControlRuntime.h"
#include "HalCommandDispatcher.h"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdlib>
#include <future>
#include <iostream>
#include <mutex>
#include <stdexcept>
#include <string>
#include <thread>

using namespace appstation::hal;
using namespace std::chrono_literals;

namespace appstation::hal {
// 仅建立离线运动快照；测试不初始化硬件，控制线程使用未连接设备的状态。
struct ForceTareDispatcherTestAccess {
  static void initializeOffline(LTDMCDriver& motion) { motion.initialized_ = true; }
  static void setServoEnabled(LTDMCDriver& motion, bool enabled) {
    std::scoped_lock lock(motion.mutex_);
    motion.enabled_[0] = enabled;
    motion.commandedEnabled_[0] = enabled;
  }
  static std::mutex& driverMutex(LTDMCDriver& motion) { return motion.mutex_; }
};
}  // namespace appstation::hal

namespace {
// Windows 默认 Sleep(1) 可能约 15.6 ms；注入源按单调时钟提供约 1 kHz。
void sampleInterval() {
  const auto until = std::chrono::steady_clock::now() + 1ms;
  while (std::chrono::steady_clock::now() < until) std::this_thread::yield();
}

void require(bool condition, const std::string& message) {
  if (!condition) throw std::runtime_error(message);
}

template <typename Check>
void await(Check check, const char* message) {
  const auto deadline = std::chrono::steady_clock::now() + 3s;
  while (!check() && std::chrono::steady_clock::now() < deadline) std::this_thread::sleep_for(1ms);
  require(check(), message);
}

template <typename Action>
void rejects(Action action, const std::string& expected) {
  try { action(); }
  catch (const std::exception& error) {
    require(std::string(error.what()).find(expected) != std::string::npos,
        "unexpected rejection: " + std::string(error.what()));
    return;
  }
  throw std::runtime_error("expected rejection: " + expected);
}

// 即使回归引入锁死，离线测试进程也必须在固定时间内退出。
class ProcessDeadline {
 public:
  ProcessDeadline() : worker_([this]() {
    std::unique_lock lock(mutex_);
    if (!condition_.wait_for(lock, 45s, [this]() { return finished_; })) {
      std::cerr << "ForceTareRuntimeTests exceeded the process deadline\n";
      std::_Exit(2);
    }
  }) {}
  ~ProcessDeadline() {
    { std::scoped_lock lock(mutex_); finished_ = true; }
    condition_.notify_all();
    worker_.join();
  }
 private:
  std::mutex mutex_;
  std::condition_variable condition_;
  bool finished_{false};
  std::thread worker_;
};

struct Samples {
  std::array<std::atomic_bool, 2> paused{};
  std::array<std::atomic_bool, 2> pauseObserved{};
  std::array<std::atomic_int, 2> sent{};
  std::atomic_int failedSide{-1};
  std::atomic_bool overload{false};

  HkvlForceDriver::ReadLoop reader() {
    return [this](int side, const auto& callback, const std::atomic_bool& running) {
      while (running.load()) {
        if (failedSide.load() == side) throw std::runtime_error("injected serial reader failure");
        if (paused[side].load()) {
          pauseObserved[side].store(true);
        } else {
          pauseObserved[side].store(false);
          HkvlDriverSample sample;
          sample.raw[0] = overload.load() ? 40.0 : (side == 0 ? 0.5 : -0.25);
          callback(sample);
          ++sent[side];
        }
        sampleInterval();
      }
    };
  }

  void waitHealthy() {
    await([&]() { return sent[0].load() >= 3 && sent[1].load() >= 3; }, "fake sensors did not become ready");
  }
  void pause() {
    paused[0].store(true);
    paused[1].store(true);
    await([&]() { return pauseObserved[0].load() && pauseObserved[1].load(); }, "fake sensors did not pause");
  }
  void resume() {
    paused[0].store(false);
    paused[1].store(false);
  }
};

ForceRuntimeConfig testConfig() {
  ForceRuntimeConfig config;
  config.serial.lowpassEnabled = false;
  config.safety.watchdogMs = 200;
  return config;
}

std::string state(ForceControlRuntime& force) {
  return force.forceStateJson(forceMonotonicMilliseconds());
}

bool calibrationIs(ForceControlRuntime& force, const char* expected) {
  return state(force).find(std::string("\"state\":\"") + expected + "\"") != std::string::npos;
}

void requireOldBias(ForceControlRuntime& force) {
  const auto json = state(force);
  const std::string zero = "\"sensorTareBias\":[0,0,0,0,0,0]";
  const auto first = json.find(zero);
  require(first != std::string::npos && json.find(zero, first + zero.size()) != std::string::npos,
      "cancelled self-check changed a sensor bias");
}

struct Fixture {
  Samples samples;
  std::atomic_int stops{0};
  std::atomic_int acknowledgements{0};
  std::atomic_bool failStop{false};
  ForceRuntimeConfig config{testConfig()};
  ForceControlRuntime force;

  Fixture() : force([this]() {
    ++stops;
    if (failStop.load()) throw std::runtime_error("injected emergency callback failure");
  }, [this]() { ++acknowledgements; }, samples.reader()) {
    force.configure(config, forceMonotonicMilliseconds());
    force.start();
    samples.waitHealthy();
  }
};

void testSuccessfulSelfCheckCommitsWithoutEmergencyStop() {
  Fixture fixture;
  const int stopsBefore = fixture.stops.load();
  const auto result = fixture.force.tare(-1, kHkvlTareMinSamples);
  require(result.find("\"ok\":true") != std::string::npos, "successful self-check did not return a result");
  require(result.find("\"preMean\":[0.5,0,0,0,0,0]") != std::string::npos
      && result.find("\"preMean\":[-0.25,0,0,0,0,0]") != std::string::npos,
      "successful self-check omitted measured pre-tare statistics");
  require(calibrationIs(fixture.force, "ready") && fixture.stops.load() == stopsBefore,
      "self-check must finish ready without its own emergency stop");
  // 去皮不解除已有锁存，也不自动确认；配置锁存仍需人工确认。
  require(fixture.force.safetyLatched() && fixture.acknowledgements.load() == 0,
      "self-check must not release an existing latch automatically");
  fixture.force.acknowledgeEmergencyStop(forceMonotonicMilliseconds());
  require(!fixture.force.safetyLatched() && calibrationIs(fixture.force, "ready")
      && fixture.acknowledgements.load() == 1, "explicit acknowledgement did not finish startup");
  const auto json = state(fixture.force);
  require(json.find("\"sensorTareBias\":[0.5,0,0,0,0,0]") != std::string::npos
      && json.find("\"sensorTareBias\":[-0.25,0,0,0,0,0]") != std::string::npos,
      "successful self-check did not commit both raw sensor biases");

  // 运行中再次去皮：不锁存、不急停，提交后仍保持就绪。
  fixture.force.tare(-1, kHkvlTareMinSamples);
  require(!fixture.force.safetyLatched() && calibrationIs(fixture.force, "ready")
      && fixture.stops.load() == stopsBefore, "repeated self-check while unlatched must not stop motion");
}

void testAcknowledgementNoLongerRequiresSelfCheck() {
  Fixture fixture;
  require(state(fixture.force).find("\"completedAtUnixMs\":0,\"sides\":{}") != std::string::npos,
      "incomplete self-check must not report fabricated zero statistics");
  rejects([&]() { fixture.force.tare(0, kHkvlTareMinSamples); }, "side=all");
  rejects([&]() { fixture.force.tare(1, kHkvlTareMinSamples); }, "side=all");
  // 双侧在线且样本新鲜即可确认；未自检时校准状态保持未就绪，录制预检仍会拦截。
  fixture.force.acknowledgeEmergencyStop(forceMonotonicMilliseconds());
  require(!fixture.force.safetyLatched() && fixture.acknowledgements.load() == 1,
      "healthy sensors must allow acknowledgement without a completed self-check");
  require(calibrationIs(fixture.force, "waiting_sensors"),
      "acknowledgement must not mark an untared sensor as calibrated");
}

void testWorkerFailureAndEmergencyCallbackFailureRejectSelfCheck() {
  {
    Fixture fixture;
    fixture.samples.failedSide.store(0);
    await([&]() { return !fixture.force.running(); }, "serial worker failure did not stop the runtime");
    rejects([&]() { fixture.force.tare(-1, kHkvlTareMinSamples); }, "worker or emergency-stop callback failed");
    rejects([&]() { fixture.force.acknowledgeEmergencyStop(forceMonotonicMilliseconds()); }, "worker failed");
    require(fixture.force.safetyLatched(), "failed serial worker lost the safety latch");
  }
  {
    Fixture fixture;
    fixture.failStop.store(true);
    fixture.force.configure(fixture.config, forceMonotonicMilliseconds());
    rejects([&]() { fixture.force.tare(-1, kHkvlTareMinSamples); }, "worker or emergency-stop callback failed");
    require(fixture.force.safetyLatched(), "failed emergency callback lost the safety latch");
  }
}

enum class Cancellation { externalStop, commandEpoch, overload, watchdog, workerFailure, validationStop };

void testCancellationPreservesBothOldBiases(Cancellation cancellation, bool acknowledgedFirst) {
  Fixture fixture;
  if (acknowledgedFirst) {
    fixture.force.acknowledgeEmergencyStop(forceMonotonicMilliseconds());
    require(!fixture.force.safetyLatched(), "precondition: configuration latch was not acknowledged");
  }
  const int stopsBefore = fixture.stops.load();
  fixture.samples.pause();
  std::atomic_bool commandAllowed{true};
  auto pending = std::async(std::launch::async, [&]() {
    try { fixture.force.tare(-1, kHkvlTareMinSamples, [&]() { return commandAllowed.load(); }); }
    catch (const std::exception& error) { return std::string(error.what()); }
    return std::string{};
  });
  await([&]() { return state(fixture.force).find("\"progress\":10") != std::string::npos; },
      "self-check did not enter collection");
  const int leftBefore = fixture.samples.sent[0].load();
  const int rightBefore = fixture.samples.sent[1].load();
  fixture.samples.resume();
  await([&]() { return fixture.samples.sent[0].load() >= leftBefore + 8
      && fixture.samples.sent[1].load() >= rightBefore + 8; }, "collection did not receive new samples");
  if (cancellation == Cancellation::validationStop) {
    await([&]() { return calibrationIs(fixture.force, "validating"); }, "self-check did not reach residual validation");
  }
  fixture.samples.pause();
  switch (cancellation) {
    case Cancellation::externalStop:
    case Cancellation::validationStop:
      fixture.force.recordExternalEmergencyStop("new manual stop", forceMonotonicMilliseconds());
      break;
    case Cancellation::commandEpoch:
      commandAllowed.store(false);
      break;
    case Cancellation::overload:
      fixture.samples.overload.store(true);
      fixture.samples.paused[0].store(false);
      break;
    case Cancellation::watchdog:
      // 保持两侧暂停，真实监控线程必须按旧采样时间发现失联。
      break;
    case Cancellation::workerFailure:
      fixture.samples.failedSide.store(0);
      break;
  }
  require(pending.wait_for(3s) == std::future_status::ready, "cancelled self-check did not finish promptly");
  const auto error = pending.get();
  require(!error.empty() && error.find("timed out") == std::string::npos,
      "self-check was not cancelled by the safety event: " + error);
  require(calibrationIs(fixture.force, "failed") && fixture.force.safetyLatched(),
      "cancelled self-check must remain failed and latched");
  if (acknowledgedFirst && (cancellation == Cancellation::overload || cancellation == Cancellation::watchdog)) {
    // 去皮期间主力锁存持续监测，未锁存时超限或失联仍须触发一次全局急停。
    require(fixture.stops.load() == stopsBefore + 1, "force event during self-check did not invoke one emergency stop");
  }
  requireOldBias(fixture.force);
}

void testStopAndConfigurationInvalidateCompletedSelfCheck() {
  for (bool reconfigure : {false, true}) {
    Fixture fixture;
    fixture.force.tare(-1, kHkvlTareMinSamples);
    require(calibrationIs(fixture.force, "ready"), "precondition: self-check was not successful");
    fixture.force.acknowledgeEmergencyStop(forceMonotonicMilliseconds());
    require(!fixture.force.safetyLatched(), "precondition: startup did not complete");
    if (reconfigure) fixture.force.configure(fixture.config, forceMonotonicMilliseconds());
    else fixture.force.stop();
    require(calibrationIs(fixture.force, "waiting_sensors"), "stop/configuration retained a completed self-check");
    require(fixture.force.safetyLatched(), "stop/configuration must latch previously ready acquisition");
    if (!reconfigure) {
      // 停止采集后旧样本失效，未重新启动并收到双侧新样本前不能确认。
      rejects([&]() { fixture.force.acknowledgeEmergencyStop(forceMonotonicMilliseconds()); }, "not healthy");
    } else {
      // 重配置会立即重启采集；收到双侧新样本后可确认，但未重新去皮前校准保持未就绪。
      await([&]() { return state(fixture.force).find("\"canAcknowledge\":true") != std::string::npos; },
          "reconfigured acquisition did not deliver fresh samples");
      fixture.force.acknowledgeEmergencyStop(forceMonotonicMilliseconds());
      require(!fixture.force.safetyLatched() && calibrationIs(fixture.force, "waiting_sensors"),
          "acknowledgement after reconfiguration must not mark calibration ready");
    }
  }
}

void testParameterHotUpdateKeepsAcquisitionAndCalibration() {
  Fixture fixture;
  fixture.force.tare(-1, kHkvlTareMinSamples);
  fixture.force.acknowledgeEmergencyStop(forceMonotonicMilliseconds());
  const int stopsBefore = fixture.stops.load();
  require(!fixture.force.parametersOnlyChange(fixture.config),
      "identical configuration must keep the full reconfigure path for reconnect and recovery");
  auto tuned = fixture.config;
  tuned.safety.warn[0] = 5.0;
  tuned.safety.stop[0] = 12.0;
  tuned.compliance.sides[0].deadbandN = {0.5, 0.5};
  require(fixture.force.parametersOnlyChange(tuned), "threshold and compliance changes must hot update");
  fixture.force.updateParameters(tuned);
  require(fixture.force.running() && !fixture.force.safetyLatched() && calibrationIs(fixture.force, "ready")
      && fixture.stops.load() == stopsBefore, "hot update restarted acquisition, reset calibration or stopped motion");
  require(fixture.force.config().safety.stop[0] == 12.0
      && fixture.force.config().compliance.sides[0].deadbandN[0] == 0.5, "hot update did not store new parameters");
  auto invalid = tuned;
  invalid.safety.warn[0] = invalid.safety.stop[0];
  rejects([&]() { fixture.force.updateParameters(invalid); }, "0 < warn < stop");
  require(fixture.force.config().safety.warn[0] == 5.0, "rejected hot update replaced active thresholds");
  auto moved = tuned;
  moved.serial.leftPort = "COM16";
  require(!fixture.force.parametersOnlyChange(moved), "serial identity changes must use full reconfiguration");
  fixture.samples.failedSide.store(0);
  await([&]() { return !fixture.force.running(); }, "serial worker failure did not stop the runtime");
  auto recovery = tuned;
  recovery.safety.stop[0] = 13.0;
  require(!fixture.force.parametersOnlyChange(recovery), "failed acquisition must recover through full reconfiguration");
}

void testHotUpdateAppliesToLiveSamplesAndKeepsLatch() {
  Fixture fixture;
  fixture.force.acknowledgeEmergencyStop(forceMonotonicMilliseconds());
  const int stopsBefore = fixture.stops.load();
  auto lowered = fixture.config;
  lowered.safety.warn[0] = 0.1;
  lowered.safety.stop[0] = 0.3;
  fixture.force.updateParameters(lowered);
  // 未去皮时左侧 0.5 N 已超过新停机阈值的 120%，热更新后的新样本必须立即锁存并急停一次。
  await([&]() { return fixture.stops.load() == stopsBefore + 1; }, "lowered threshold was not applied to live samples");
  require(fixture.force.safetyLatched(), "hot-update trip did not latch");
  fixture.force.updateParameters(fixture.config);
  require(fixture.force.safetyLatched(), "threshold update must not clear an existing latch");
  fixture.force.acknowledgeEmergencyStop(forceMonotonicMilliseconds());
  std::this_thread::sleep_for(20ms);
  require(!fixture.force.safetyLatched() && fixture.stops.load() == stopsBefore + 1,
      "restored threshold did not allow a stable acknowledgement");
}

struct DispatcherFixture {
  Samples samples;
  LTDMCDriver motion;
  Omega7Driver omega;
  JodellGripperDriver gripper;
  MotionExecutor motionExecutor{motion};
  NativeTeleopController native{motion, motionExecutor, omega, gripper};
  ForceControlRuntime force;
  std::chrono::steady_clock::time_point started{std::chrono::steady_clock::now()};
  HalCommandDispatcher dispatcher{motion, motionExecutor, omega, native, force, started};

  DispatcherFixture() : force([this]() {
    // 与 HalServer 的全局急停回调使用相同的两次 motion trip 顺序。
    motion.latchEmergencyStop();
    native.latchControlStop();
    omega.latchForceStop();
    motion.emergencyStop();
    native.requestEmergencyStop();
    omega.requestEmergencyStop();
  }, [this]() { motion.acknowledgeEmergencyStop(); }, samples.reader()) {
    ForceTareDispatcherTestAccess::initializeOffline(motion);
    force.configure(testConfig(), forceMonotonicMilliseconds());
    force.start();
    samples.waitHealthy();
  }
};

const std::string kConfirmedTare = R"({"side":"all","samples":200,"unloadedConfirmed":true})";

void testLeaseStopRetainsDistinctReason() {
  DispatcherFixture fixture;
  fixture.dispatcher.handle("force.tare", kConfirmedTare);
  fixture.dispatcher.handle("motion.acknowledge_estop", "{}");
  fixture.dispatcher.handleEmergencyStop("control_lease_lost");
  require(fixture.motion.estopActive() && fixture.force.safetyLatched(), "lease stop did not latch");
  require(state(fixture.force).find("\"reason\":\"control_lease_lost\"") != std::string::npos,
      "lease stop lost its diagnostic reason");
  fixture.dispatcher.handleEmergencyStop();
  require(state(fixture.force).find("\"reason\":\"control_lease_lost\"") != std::string::npos,
      "later stop overwrote the first safety cause");
}

void testDispatcherGuardsAndOwnStopEpoch() {
  DispatcherFixture fixture;
  rejects([&]() { fixture.dispatcher.handle("force.tare", "{}"); }, "confirmation");
  rejects([&]() { fixture.dispatcher.handle("force.tare", R"({"side":"left","unloadedConfirmed":true})"); }, "side=all");
  for (const auto* samples : {"0", "-1", "1", "12", "199", "200.5", "1001", "5000"}) {
    rejects([&]() { fixture.dispatcher.handle("force.tare", std::string("{\"unloadedConfirmed\":true,\"samples\":") + samples + "}"); },
        "sample count");
  }
  const auto staleEpoch = fixture.motion.commandEpoch();
  fixture.motion.latchEmergencyStop();
  rejects([&]() { fixture.dispatcher.handle("force.tare", kConfirmedTare, staleEpoch); }, "cancelled by emergency stop");
  auto before = fixture.motion.commandEpoch();
  auto response = fixture.dispatcher.handle("force.tare", kConfirmedTare, before);
  require(response.find("\"ok\":true") != std::string::npos, "dispatcher did not allow self-check while already latched");
  require(fixture.motion.commandEpoch() == before && fixture.motion.estopActive() && calibrationIs(fixture.force, "ready"),
      "self-check must neither add its own stop nor clear the existing one");
  fixture.dispatcher.handle("motion.acknowledge_estop", "{}");
  require(!fixture.motion.estopActive() && !fixture.force.safetyLatched(), "acknowledgement after self-check failed");
  // 伺服使能但静止时可直接去皮，不触发急停、不改变命令代际。
  ForceTareDispatcherTestAccess::setServoEnabled(fixture.motion, true);
  before = fixture.motion.commandEpoch();
  response = fixture.dispatcher.handle("force.tare", kConfirmedTare, before);
  require(response.find("\"ok\":true") != std::string::npos && fixture.motion.commandEpoch() == before
      && !fixture.motion.estopActive() && !fixture.force.safetyLatched(),
      "stationary self-check with servos enabled must not stop motion");
  // 阈值热更新只需静止；采集参数变化仍要求伺服关闭。
  const auto tuned = R"({"source":"hkvl_serial","fxyWarnN":5,"fxyStopN":12})";
  response = fixture.dispatcher.handle("force.configure", tuned);
  require(response.find("\"applied\":\"parameters\"") != std::string::npos
      && !fixture.motion.estopActive() && calibrationIs(fixture.force, "ready"),
      "parameter-only force configuration did not hot update");
  rejects([&]() { fixture.dispatcher.handle("force.configure",
      R"({"source":"hkvl_serial","leftPort":"COM16"})"); }, "servos disabled");
  ForceTareDispatcherTestAccess::setServoEnabled(fixture.motion, false);
  // 两侧均未连接，默认夹爪跟随关闭；只运行不访问硬件的控制线程生命周期。
  fixture.native.start(false, false);
  rejects([&]() { fixture.dispatcher.handle("force.tare", kConfirmedTare); }, "native teleop to be stopped");
  fixture.native.stop();
}

void testDispatcherNewStopCancelsCollection() {
  DispatcherFixture fixture;
  fixture.samples.pause();
  const auto before = fixture.motion.commandEpoch();
  auto pending = std::async(std::launch::async, [&]() {
    try { fixture.dispatcher.handle("force.tare", kConfirmedTare, before); }
    catch (const std::exception& error) { return std::string(error.what()); }
    return std::string{};
  });
  await([&]() { return calibrationIs(fixture.force, "checking_stability"); }, "dispatcher self-check did not begin");
  fixture.dispatcher.handleEmergencyStop();
  require(pending.wait_for(3s) == std::future_status::ready, "new dispatcher stop did not cancel self-check");
  require(!pending.get().empty() && calibrationIs(fixture.force, "failed"), "new stop was adopted as the tare epoch");
  require(fixture.motion.commandEpoch() != before && fixture.motion.estopActive(), "new stop did not latch motion");
  requireOldBias(fixture.force);
}

void testDispatcherRejectsForceMutationOnStaleMotionSnapshot() {
  DispatcherFixture fixture;
  fixture.motion.readState();  // 先发布一帧“静止且断使能”的缓存
  std::promise<void> locked;
  std::promise<void> release;
  auto lockedFuture = locked.get_future();
  auto releaseFuture = release.get_future();
  // 另一线程占住驱动锁，readState 只能返回旧缓存，模拟运动命令长时间持锁。
  std::thread holder([&]() {
    std::scoped_lock lock(ForceTareDispatcherTestAccess::driverMutex(fixture.motion));
    locked.set_value();
    releaseFuture.wait();
  });
  lockedFuture.wait();
  try {
    rejects([&]() { fixture.dispatcher.handle("force.tare", kConfirmedTare); }, "fresh motion feedback");
    rejects([&]() { fixture.dispatcher.handle("force.configure", R"({"source":"hkvl_serial","fxyWarnN":5,"fxyStopN":12})"); },
        "fresh motion feedback");
  } catch (...) {
    release.set_value();
    holder.join();
    throw;
  }
  release.set_value();
  holder.join();
  requireOldBias(fixture.force);
  const auto response = fixture.dispatcher.handle("force.tare", kConfirmedTare);
  require(response.find("\"ok\":true") != std::string::npos, "fresh controller read did not restore self-check");
}

void testFreshMotionStateWaitCoversSlowRead() {
  const auto steadyMs = []() {
    return std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count();
  };
  const auto freshAfter = [&](std::chrono::milliseconds delay) {
    std::this_thread::sleep_for(delay);
    MotionState state;
    state.readMonotonicMs = steadyMs();
    return state;
  };
  // 单次读卡耗时超过时限：返回时带新时间戳也必须拒绝。
  rejects([&]() {
    HalCommandDispatcher::requireFreshMotionState([&]() { return freshAfter(150ms); }, "force tare", 100ms);
  }, "fresh motion feedback");
  // 先返回旧缓存，时限内取得新读卡则放行。
  int reads = 0;
  const auto staleThenFresh = HalCommandDispatcher::requireFreshMotionState([&]() {
    if (++reads < 3) return MotionState{};
    return freshAfter(2ms);
  }, "force tare", 200ms);
  require(reads >= 3 && staleThenFresh.readMonotonicMs > 0, "fresh read within the deadline was not accepted");
  // 始终只有旧缓存：到时限拒绝。
  rejects([&]() {
    HalCommandDispatcher::requireFreshMotionState([]() { return MotionState{}; }, "force tare", 50ms);
  }, "fresh motion feedback");
}

void testDispatcherDeadlineCancelsCollectionBeforeCommit() {
  DispatcherFixture fixture;
  const auto expiresAt = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::system_clock::now().time_since_epoch()).count() + 80;
  const auto payload = std::string("{\"side\":\"all\",\"samples\":200,\"unloadedConfirmed\":true,\"commandExpiresAtUnixMs\":")
      + std::to_string(expiresAt) + "}";
  rejects([&]() { fixture.dispatcher.handle("force.tare", payload); }, "expired");
  require(calibrationIs(fixture.force, "failed"), "expired self-check did not stay failed");
  requireOldBias(fixture.force);
}
}  // namespace

int main() {
  ProcessDeadline deadline;
  try {
    testSuccessfulSelfCheckCommitsWithoutEmergencyStop();
    testAcknowledgementNoLongerRequiresSelfCheck();
    testWorkerFailureAndEmergencyCallbackFailureRejectSelfCheck();
    for (auto cancellation : {Cancellation::externalStop, Cancellation::commandEpoch,
        Cancellation::overload, Cancellation::watchdog, Cancellation::workerFailure, Cancellation::validationStop}) {
      testCancellationPreservesBothOldBiases(cancellation, false);
    }
    for (auto cancellation : {Cancellation::externalStop, Cancellation::overload, Cancellation::watchdog}) {
      testCancellationPreservesBothOldBiases(cancellation, true);
    }
    testStopAndConfigurationInvalidateCompletedSelfCheck();
    testParameterHotUpdateKeepsAcquisitionAndCalibration();
    testHotUpdateAppliesToLiveSamplesAndKeepsLatch();
    testLeaseStopRetainsDistinctReason();
    testDispatcherGuardsAndOwnStopEpoch();
    testDispatcherNewStopCancelsCollection();
    testDispatcherRejectsForceMutationOnStaleMotionSnapshot();
    testFreshMotionStateWaitCoversSlowRead();
    testDispatcherDeadlineCancelsCollectionBeforeCommit();
    std::cout << "ForceTareRuntimeTests passed (23 cases, injected sensors, no hardware or DDS runtime)\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << "ForceTareRuntimeTests failed: " << error.what() << "\n";
    return 1;
  }
}
