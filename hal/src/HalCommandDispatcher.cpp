/*
 * 阅读导航 06｜HAL 硬件与安全
 * 职责：统一解析并分派 HAL 命令，调用运动、主手、遥操作和力运行时。
 * 先看：HalCommandDispatcher::handleEmergencyStop → HalCommandDispatcher::handle。
 * 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。
 */
#include "HalCommandDispatcher.h"

#include "HalJson.h"
#include "CommandDeadline.h"

#include <stdexcept>
#include <chrono>
#include <cmath>
#include <exception>
#include <limits>
#include <thread>

namespace appstation::hal {

HalCommandDispatcher::HalCommandDispatcher(
    LTDMCDriver& motion,
    MotionExecutor& executor,
    Omega7Driver& omega,
    NativeTeleopController& nativeTeleop,
    ForceControlRuntime& forceRuntime,
    const std::chrono::steady_clock::time_point& started)
    : motion_(motion),
      executor_(executor),
      omega_(omega),
      nativeTeleop_(nativeTeleop),
      forceRuntime_(forceRuntime),
      started_(started) {}

std::string HalCommandDispatcher::handleEmergencyStop() {
  return handleEmergencyStop("manual_emergency_stop");
}

std::string HalCommandDispatcher::handleEmergencyStop(const char* reason) {
  emergencyStopsInProgress_.fetch_add(1);
  struct StopCompletion {
    std::atomic_uint32_t& count;
    ~StopCompletion() { count.fetch_sub(1); }
  } completion{emergencyStopsInProgress_};
  // 先撤销软件运动权限；任何停止动作报错也必须继续其余动作。
  motion_.latchEmergencyStop();
  nativeTeleop_.latchControlStop();
  omega_.latchForceStop();
  std::exception_ptr failure;
  const auto attempt = [&failure](auto&& action) {
    try { action(); }
    catch (...) { if (!failure) failure = std::current_exception(); }
  };
  attempt([&]() { motion_.emergencyStop(); });
  attempt([&]() { nativeTeleop_.requestEmergencyStop(); });
  attempt([&]() { omega_.requestEmergencyStop(); });
  attempt([&]() { forceRuntime_.recordExternalEmergencyStop(
      reason, forceMonotonicMilliseconds()); });
  if (failure) std::rethrow_exception(failure);
  return "{\"ok\":true}";
}

MotionState HalCommandDispatcher::requireFreshMotionState(const std::function<MotionState()>& read,
    const char* operation, std::chrono::milliseconds timeout) {
  // 只认本次请求开始后完成的读卡（含运动线程随后发布的缓存）；同一毫秒内完成的无法证明晚于请求。
  const auto requestedAtMs = std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
  const auto deadline = std::chrono::steady_clock::now() + timeout;
  while (true) {
    auto state = read();
    // 先查截止时间再采用结果：一次超时的慢读即使带回新时间戳也不放行。
    if (std::chrono::steady_clock::now() > deadline) {
      throw std::runtime_error(std::string(operation) + " requires fresh motion feedback");
    }
    if (state.readMonotonicMs > requestedAtMs) return state;
    std::this_thread::sleep_for(std::chrono::milliseconds(2));
  }
}

void HalCommandDispatcher::requireForceMutationSafe(const char* operation, bool requireServosDisabled) {
  if (nativeTeleop_.running()) {
    throw std::runtime_error(std::string(operation) + " requires native teleop to be stopped");
  }
  const auto state = requireFreshMotionState([this]() { return motion_.readState(); }, operation);
  for (const auto& axis : state.axes) {
    if (axis.moving) {
      throw std::runtime_error(std::string(operation) + " requires all axes stopped");
    }
    if (requireServosDisabled && axis.enabled) {
      throw std::runtime_error(std::string(operation) + " requires all axes stopped and servos disabled");
    }
  }
}

std::string HalCommandDispatcher::handle(const std::string& name, const std::string& bodyText,
    std::optional<std::uint64_t> expectedEpoch) {
  if (name == "control.lease") {
    const auto sequence = jsonNumberValue(bodyText, "sequence", 0);
    const auto issuedAt = jsonNumberValue(bodyText, "issuedAtUnixMs", 0);
    const auto timeout = jsonNumberValue(bodyText, "timeoutMs", 0);
    const auto now = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::system_clock::now().time_since_epoch()).count();
    if (!std::isfinite(sequence) || sequence < 1 || sequence > 9007199254740991.0
        || std::floor(sequence) != sequence || !std::isfinite(issuedAt)
        || std::abs(static_cast<double>(now) - issuedAt) > 1000
        || timeout != ControlLeaseState::kTimeoutMs)
      throw std::runtime_error("invalid or stale control lease request");
    motion_.renewControlLease(jsonStringValue(bodyText, "sessionId"), static_cast<std::uint64_t>(sequence));
    return "{\"ok\":true,\"leaseFresh\":true,\"timeoutMs\":2500}";
  }
  const auto commandEpoch = expectedEpoch.value_or(motion_.commandEpoch());
  const auto ensureCurrentMotionCommand = [&]() {
    if (!motion_.commandEpochAllowed(commandEpoch)) {
      throw std::runtime_error("HAL command cancelled by emergency stop");
    }
  };
  if (name == "motion.home_all" || name == "motion.home_origin_side" || name == "motion.return_home_reference"
      || name == "motion.teleop_target_update" || name == "motion.replay_absolute_target") {
    // 新调用方携带坐标所属实例；即使校验后 HAL 恰好重启，也不能执行旧计数目标。
    const auto expectedInstance = jsonStringValueOr(bodyText, "expectedInstanceId", "");
    if (!expectedInstance.empty() && expectedInstance != motion_.health(0).instanceId) {
      throw std::runtime_error("motion coordinate reference belongs to another controller instance");
    }
  }
  // DDS command request 使用和 Python backend 相同的 command name；
  // 这里复用既有 HTTP 路由语义，避免两套控制面出现行为分叉。
  if (name == "hal.reconnect") {
    const double uptime =
        std::chrono::duration<double>(std::chrono::steady_clock::now() - started_).count();
    omega_.ensureReady();
    return jsonHealth(motion_.health(uptime), omega_.ok(), omega_.lastError());
  }
  if (name == "omega7.gravity_compensation") {
    omega_.setGravityCompensation(
        jsonBoolValue(bodyText, "leftEnabled", true),
        jsonBoolValue(bodyText, "rightEnabled", true),
        jsonNumberValue(bodyText, "leftScale", 0.45),
        jsonNumberValue(bodyText, "rightScale", 1.0),
        [&]() { return motion_.commandEpochAllowed(commandEpoch); });
    return "{\"ok\":true}";
  }
  if (name == "omega7.zero_force_feedback") {
    omega_.zeroForceFeedback(static_cast<int>(jsonNumberValue(bodyText, "openId", -1)));
    return "{\"ok\":true}";
  }
  if (name == "force.state") {
    return forceRuntime_.forceStateJson(forceMonotonicMilliseconds());
  }
  if (name == "motion.timing") {
    return motion_.timingJson();
  }
  if (name == "force.configure") {
    const auto config = jsonForceRuntimeConfig(bodyText, forceRuntime_.config());
    if (forceRuntime_.parametersOnlyChange(config)) {
      // 仅阈值/柔顺参数：静止即可热更新，不重启采集、不重置去皮、不触发急停；已有锁存保持到确认。
      requireForceMutationSafe("force parameter update", false);
      forceRuntime_.updateParameters(config);
      return "{\"ok\":true,\"applied\":\"parameters\"}";
    }
    requireForceMutationSafe("force configuration");
    forceRuntime_.configure(config, forceMonotonicMilliseconds());
    return "{\"ok\":true}";
  }
  if (name == "force.tare") {
    const auto ensureTareDeadline = [&bodyText]() {
      const auto now = std::chrono::duration<double, std::milli>(
          std::chrono::system_clock::now().time_since_epoch()).count();
      ensureCommandNotExpired(bodyText, now);
    };
    ensureTareDeadline();
    if (!jsonBoolValue(bodyText, "unloadedConfirmed", false)) {
      throw std::runtime_error("force tare requires confirmation that both sensors are unloaded");
    }
    // 去皮只要求静止，不再先急停/下使能；新急停仍通过命令代际取消本次去皮。
    requireForceMutationSafe("force tare", false);
    const auto sideValue = lowercase(jsonStringValueOr(bodyText, "side", "all"));
    if (sideValue != "all" && sideValue != "both") {
      throw std::runtime_error("HKVL startup force self-check requires side=all");
    }
    const auto samples = jsonNumberValue(bodyText, "samples", kHkvlTareMinSamples);
    if (!std::isfinite(samples) || samples < kHkvlTareMinSamples
        || samples > kHkvlTareMaxSamples || std::floor(samples) != samples) {
      throw std::runtime_error("invalid HKVL tare sample count; expected 200..1000");
    }
    if (emergencyStopsInProgress_.load() != 0 || motion_.commandEpoch() != commandEpoch) {
      throw std::runtime_error("HKVL tare cancelled by emergency stop");
    }
    return forceRuntime_.tare(-1, static_cast<int>(samples),
        [this, commandEpoch, &ensureTareDeadline]() {
          ensureTareDeadline();
          return emergencyStopsInProgress_.load() == 0 && motion_.commandEpoch() == commandEpoch;
        });
  }
  if (name == "teleop.native.configure") {
    nativeTeleop_.configure(jsonNativeTeleopConfig(bodyText), commandEpoch);
    return "{\"ok\":true}";
  }
  if (name == "teleop.native.start") {
    ensureCurrentMotionCommand();
    forceRuntime_.resetCompliance();
    nativeTeleop_.configure(jsonNativeTeleopConfig(bodyText), commandEpoch);
    omega_.ensureReady();
    ensureCurrentMotionCommand();
    nativeTeleop_.start(
        jsonBoolValue(bodyText, "leftConnected", false),
        jsonBoolValue(bodyText, "rightConnected", false), commandEpoch);
    return "{\"ok\":true}";
  }
  if (name == "teleop.native.stop") {
    nativeTeleop_.stop();
    forceRuntime_.resetCompliance();
    return "{\"ok\":true}";
  }
  if (name == "teleop.native.status") {
    return nativeTeleop_.statusJson();
  }
  if (name == "gripper.samples") {
    // 只读：录制按 seq 增量取夹爪真实读数，不受 100 Hz 遥测缓存只带最新样本的限制。
    const auto after = [&](const char* key) {
      const double value = jsonNumberValue(bodyText, key, 0.0);
      return value > 0.0 && std::isfinite(value) ? static_cast<std::uint64_t>(value) : std::uint64_t{0};
    };
    return nativeTeleop_.gripperSamplesJson(
        jsonStringValue(bodyText, "instanceId"), {after("afterSeqLeft"), after("afterSeqRight")});
  }
  if (name == "gripper.feedback.configure") {
    const auto config = jsonNativeTeleopConfig(bodyText);
    nativeTeleop_.configureGripperFeedback(config.gripper, config.gripperParticipating);
    return nativeTeleop_.statusJson();
  }
  if (name == "gripper.prepare_replay") {
    ensureCurrentMotionCommand();
    const auto config = jsonNativeTeleopConfig(bodyText);
    nativeTeleop_.prepareReplayGripper(config.gripper, commandEpoch, config.gripperParticipating);
    nativeTeleop_.configureGripperProtection(config.gripperIcfTargetProtectionEnabled, config.gripperIcfTargetMinGapMm);
    return "{\"ok\":true}";
  }
  if (name == "teleop.native.gripper_command" || name == "gripper.command" || name == "gripper.replay_target") {
    ensureCurrentMotionCommand();
    const auto config = jsonNativeTeleopConfig(bodyText);
    if (name == "gripper.replay_target") {
      if (!nativeTeleop_.replayGripperReady()) throw std::runtime_error("replay gripper sampling is not ready");
    } else {
      nativeTeleop_.configureGripper(config.gripper);
      nativeTeleop_.configureGripperProtection(
          config.gripperIcfTargetProtectionEnabled,
          config.gripperIcfTargetMinGapMm);
    }
    const auto side = parseSide(jsonStringValue(bodyText, "side"));
    const auto targetMm = jsonNumberValue(bodyText, "targetMm", 0.0);
    const auto effectiveTargetMm = effectiveGripperTargetMm(config, targetMm);
    const auto speed = static_cast<int>(jsonNumberValue(bodyText, "gripSpeed", config.gripper.speed));
    const auto torque = static_cast<int>(jsonNumberValue(bodyText, "gripTorque", config.gripper.torque));
    std::string message;
    ensureCurrentMotionCommand();
    if (!nativeTeleop_.commandGripperTarget(side, targetMm, speed, torque, &message, commandEpoch)) {
      throw std::runtime_error(message);
    }
    return "{\"ok\":true,\"message\":\"" + jsonEscape(message) + "\",\"targetMm\":"
        + std::to_string(effectiveTargetMm) + "}";
  }
  if (name == "motion.emergency_stop") {
    return handleEmergencyStop();
  }
  if (name == "motion.acknowledge_estop") {
    if (emergencyStopsInProgress_.load() != 0) {
      throw std::runtime_error("emergency stop is still being applied; acknowledge again after it completes");
    }
    const auto expectedEpoch = commandEpoch;
    forceRuntime_.acknowledgeEmergencyStop(forceMonotonicMilliseconds(), [&]() {
      motion_.acknowledgeEmergencyStop(expectedEpoch);
    });
    return "{\"ok\":true,\"servoRestored\":false}";
  }
  if (name == "motion.home_all") {
    motion_.ensureMotionReturnAllowed();
    const auto enabledAxes = jsonHomeAllEnabledAxes(bodyText);
    nativeTeleop_.stop();
    ensureCurrentMotionCommand();
    executor_.homeAll(jsonWorkOriginPulse(bodyText), enabledAxes, commandEpoch);
    return "{\"ok\":true}";
  }
  if (name == "motion.home_origin_side" || name == "motion.return_home_reference") {
    motion_.ensureMotionReturnAllowed();
    const auto side = parseSide(jsonStringValue(bodyText, "side"));
    const bool referenceReturn = name == "motion.return_home_reference";
    const auto enabledAxes = jsonBoolArray6(bodyText, "enabledAxes", referenceReturn ? std::array<bool, 6>{} : kAllAxesEnabled);
    nativeTeleop_.stop();
    ensureCurrentMotionCommand();
    executor_.homeOriginSide(side, jsonSideWorkOriginPulse(bodyText), enabledAxes, commandEpoch, referenceReturn);
    if (referenceReturn) return "{\"ok\":true,\"referenceReturnCompleted\":true}";
    return "{\"ok\":true}";
  }
  if (name == "motion.enable_side") {
    const auto side = parseSide(jsonStringValue(bodyText, "side"));
    const auto message = executor_.enableSide(side, true, jsonBoolArray6(bodyText, "enabledAxes", kAllAxesEnabled), commandEpoch);
    return "{\"ok\":true,\"message\":\"" + jsonEscape(message) + "\"}";
  }
  if (name == "motion.disable_side") {
    const auto side = parseSide(jsonStringValue(bodyText, "side"));
    const auto message = executor_.enableSide(side, false, kAllAxesEnabled, commandEpoch);
    return "{\"ok\":true,\"message\":\"" + jsonEscape(message) + "\"}";
  }
  if (name == "motion.home_side") {
    const auto side = parseSide(jsonStringValue(bodyText, "side"));
    nativeTeleop_.stop();
    ensureCurrentMotionCommand();
    const auto homeConfig = jsonHardwareHomeConfig(bodyText);
    const auto limitReferenceAxes = executor_.homeSide(
        side, jsonBoolArray6(bodyText, "enabledAxes", {}), homeConfig, commandEpoch);
    std::string response = "{\"ok\":true,\"homeCompleted\":true,\"limitReferenceAxes\":[";
    for (std::size_t index = 0; index < limitReferenceAxes.size(); ++index) {
      if (index) response += ',';
      response += limitReferenceAxes[index] ? "true" : "false";
    }
    return response + "]}";
  }
  if (name == "motion.manual_axis_move") {
    const auto side = parseSide(jsonStringValue(bodyText, "side"));
    const auto axis = parseAxis(jsonStringValue(bodyText, "axis"));
    const auto direction = jsonNumberValue(bodyText, "direction", 0);
    const auto step = jsonNumberValue(bodyText, "step", 0);
    const auto maxVelocity = jsonNumberValue(bodyText, "maxVelocityUiPerSec", 0);
    const auto startVelocity = jsonNumberValue(bodyText, "startVelocityUiPerSec", 0);
    const auto accTime = jsonNumberValue(bodyText, "accTimeSec", 0);
    const auto decTime = jsonNumberValue(bodyText, "decTimeSec", 0);
    executor_.moveRelativeUi(
        side,
        axis,
        step * (direction >= 0 ? 1.0 : -1.0),
        maxVelocity,
        startVelocity,
        accTime,
        decTime, commandEpoch);
    return "{\"ok\":true}";
  }
  if (name == "motion.teleop_target_update" || name == "motion.replay_absolute_target") {
    const auto side = parseSide(jsonStringValue(bodyText, "side"));
    const double missing = name == "motion.replay_absolute_target"
        ? std::numeric_limits<double>::quiet_NaN() : 0.0;
    const std::array<double, 6> deltas{
        jsonNumberValue(bodyText, "X", missing),
        jsonNumberValue(bodyText, "Y", missing),
        jsonNumberValue(bodyText, "Z", missing),
        jsonNumberValue(bodyText, "Roll", missing),
        jsonNumberValue(bodyText, "Pitch", missing),
        jsonNumberValue(bodyText, "Yaw", missing)};
    TeleopHardwareTarget target;
    target.side = side == Side::Left ? 0 : 1;
    target.deltas = deltas;
    target.translationStepLimitPulse = jsonNumberValue(bodyText, "translationStepLimitPulse", 0.0);
    target.rotationStepLimitPulse = jsonNumberValue(bodyText, "rotationStepLimitPulse", 0.0);
    target.translationPulseDeadband = jsonNumberValue(bodyText, "translationPulseDeadband", 0.0);
    target.rotationPulseDeadband = jsonNumberValue(bodyText, "rotationPulseDeadband", 0.0);
    target.enabledAxes = jsonTeleopEnabledAxes(bodyText);
    target.syncZeroDeltaTarget = jsonBoolValue(bodyText, "syncZeroDeltaTarget", false);
    const auto limits = jsonTeleopSoftLimits(bodyText);
    for (std::size_t i = 0; i < limits.size(); ++i) {
      target.softLimitMin[i] = limits[i].min;
      target.softLimitMax[i] = limits[i].max;
    }
    target.translationVelocityUiPerSec = jsonNumberValue(bodyText, "translationVelocityUiPerSec", 0.0);
    target.rotationVelocityUiPerSec = jsonNumberValue(bodyText, "rotationVelocityUiPerSec", 0.0);
    target.translationStartVelocityUiPerSec = jsonNumberValue(bodyText, "translationStartVelocityUiPerSec", 0.0);
    target.rotationStartVelocityUiPerSec = jsonNumberValue(bodyText, "rotationStartVelocityUiPerSec", 0.0);
    target.accTimeSec = jsonNumberValue(bodyText, "accTimeSec", 0.0);
    target.decTimeSec = jsonNumberValue(bodyText, "decTimeSec", 0.0);
    const auto result = executor_.applyExternal(target, commandEpoch, name == "motion.replay_absolute_target");
    return jsonTeleopTargetUpdateResult(side, result);
  }
  if (name == "motion.teleop_stop_side") {
    const auto side = parseSide(jsonStringValue(bodyText, "side"));
    executor_.stopSide(side);
    return "{\"ok\":true}";
  }
  throw std::runtime_error("unknown HAL command: " + name);

}

}  // namespace appstation::hal
