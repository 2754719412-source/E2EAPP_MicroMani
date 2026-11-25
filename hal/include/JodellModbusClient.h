/*
 * 阅读导航 06｜HAL 硬件与安全
 * 职责：worker 独占串口时的钧舵 Modbus 读写逻辑：一次读取状态/位置/电流、仅在未使能时使能、故障时拒绝运动。
 * 先看：ModbusTransport → JodellModbusClient::readSample → JodellModbusClient::moveTo。
 * 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。
 */
#pragma once

#include <chrono>
#include <cstdint>
#include <functional>
#include <sstream>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "JodellModbus.h"

namespace appstation::hal::jodell {

// 串口一问一答。normalLength 为正常应答长度；实现须在读到异常应答（功能码 | 0x80，5 字节）时提前返回。
class ModbusTransport {
 public:
  virtual ~ModbusTransport() = default;
  virtual bool exchange(const std::vector<std::uint8_t>& request, std::size_t normalLength,
      std::vector<std::uint8_t>* response, std::string* error) = 0;
};

inline std::int64_t steadyNowUs() {
  return std::chrono::duration_cast<std::chrono::microseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
}

class JodellModbusClient {
 public:
  using Clock = std::function<std::int64_t()>;
  using Sleep = std::function<void(int)>;

  JodellModbusClient(ModbusTransport& transport, int slaveId, double strokeMm,
      Clock nowUs = steadyNowUs,
      Sleep sleepMs = [](int ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); })
      : transport_(transport), slaveId_(slaveId), strokeMm_(strokeMm),
        nowUs_(std::move(nowUs)), sleepMs_(std::move(sleepMs)) {}

  // 一次 0x04 请求得到位置、状态和电流；时间戳取请求发出与应答收齐的中点。
  bool readSample(GripperFeedbackSample* sample, std::string* error) {
    const auto started = nowUs_();
    std::vector<std::uint8_t> response;
    const bool exchanged = transport_.exchange(readStatusRequest(slaveId_), kStatusResponseLength, &response, error);
    const auto finished = nowUs_();
    StatusRegisters status;
    if (!exchanged || !parseStatusResponse(response.data(), response.size(), slaveId_, &status, error)) {
      *sample = GripperFeedbackSample{};
      sample->transport = "modbus";
      sample->monotonicUs = started + (finished - started) / 2;
      return false;
    }
    *sample = sampleFromStatus(status, started + (finished - started) / 2);
    return true;
  }

  // 运动前先读一次：故障时拒绝；只有未使能（gACT=0 或 gSTA≠3）时才写 rACT=1 并等待使能完成，
  // 因为手册说明使能过程可能带动手指，不能每条命令都重新使能。latest 返回运动前那次读数。
  bool moveTo(double targetGapMm, int speedRaw, int forceRaw, int activationTimeoutMs,
      GripperFeedbackSample* latest, std::string* message) {
    std::string error;
    if (!readSample(latest, &error)) return fail(message, "pre-move status read failed: " + error);
    if (latest->fault != 0) return fail(message, "gripper fault code " + std::to_string(latest->fault));
    if (!(latest->gACT == 1 && latest->gSTA == kGstaActivated)) {
      if (!activate(activationTimeoutMs, latest, &error)) return fail(message, error);
    }
    const auto request = moveRequest(slaveId_, positionRawForGapMm(targetGapMm, strokeMm_), speedRaw, forceRaw);
    std::vector<std::uint8_t> response;
    if (!transport_.exchange(request, kWriteResponseLength, &response, &error)
        || !checkWriteResponse(response.data(), response.size(), request, &error)) {
      return fail(message, "move write failed: " + error);
    }
    std::ostringstream out;
    out << "modbus move slave=" << slaveId_ << ", pos=" << static_cast<int>(request[9])
        << ", speed=" << static_cast<int>(request[12]) << ", force=" << static_cast<int>(request[11]);
    if (message) *message = out.str();
    return true;
  }

  double gapMm(const GripperFeedbackSample& sample) const {
    return sample.positionValid ? gapMmForPositionRaw(sample.positionRaw, strokeMm_) : -1.0;
  }

 private:
  bool activate(int timeoutMs, GripperFeedbackSample* latest, std::string* error) {
    const auto request = activationRequest(slaveId_, true);
    std::vector<std::uint8_t> response;
    if (!transport_.exchange(request, kWriteResponseLength, &response, error)
        || !checkWriteResponse(response.data(), response.size(), request, error)) {
      *error = "activation write failed: " + *error;
      return false;
    }
    const auto deadline = nowUs_() + static_cast<std::int64_t>(timeoutMs) * 1000;
    while (true) {
      std::string readError;
      if (readSample(latest, &readError)) {
        if (latest->fault != 0) {
          *error = "gripper fault during activation: " + std::to_string(latest->fault);
          return false;
        }
        if (latest->gACT == 1 && latest->gSTA == kGstaActivated) return true;
      }
      if (nowUs_() >= deadline) {
        *error = "activation timeout (gSTA=" + std::to_string(latest->gSTA) + ")";
        return false;
      }
      sleepMs_(10);
    }
  }

  static bool fail(std::string* message, const std::string& text) {
    if (message) *message = text;
    return false;
  }

  ModbusTransport& transport_;
  int slaveId_;
  double strokeMm_;
  Clock nowUs_;
  Sleep sleepMs_;
};

}  // namespace appstation::hal::jodell
