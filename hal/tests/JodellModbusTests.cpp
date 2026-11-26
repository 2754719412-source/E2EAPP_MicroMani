// 离线测试：钧舵 Modbus 帧与手册 A.1 第 7 章示例逐字节一致，worker 样本字段往返无损，
// 以及 worker 的使能/故障/应答校验逻辑（模拟设备）；不打开串口。
#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <functional>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

// 模拟先包含 windows.h 且未定义 NOMINMAX 的调用方（如 GripperFeedbackTests）：公共头文件不能依赖 max/min 名字。
#define max(a, b) (((a) > (b)) ? (a) : (b))
#define min(a, b) (((a) < (b)) ? (a) : (b))
#include "JodellWorkerProtocol.h"
#undef max
#undef min

using namespace appstation::hal::jodell;
namespace {
void require(bool value, const char* text) { if (!value) throw std::runtime_error(text); }
std::vector<std::uint8_t> hex(const std::string& text) {
  std::istringstream in(text);
  std::vector<std::uint8_t> bytes;
  std::string token;
  while (in >> token) bytes.push_back(static_cast<std::uint8_t>(std::stoi(token, nullptr, 16)));
  return bytes;
}
std::vector<std::string> split(const std::string& line) {
  std::vector<std::string> parts;
  std::size_t start = 0;
  while (true) {
    const auto next = line.find('\t', start);
    parts.push_back(line.substr(start, next == std::string::npos ? std::string::npos : next - start));
    if (next == std::string::npos) return parts;
    start = next + 1;
  }
}

void framesMatchManual() {
  require(readStatusRequest(9) == hex("09 04 07 D0 00 03 B1 CE"), "read status frame");
  require(moveRequest(9, 0xFF, 0xFF, 0xFF) == hex("09 10 03 E8 00 03 06 00 09 FF 00 FF FF 9E 95"), "move frame");
  require(activationRequest(9, true) == hex("09 10 03 E8 00 01 02 00 01 24 78"), "activate frame");
  require(activationRequest(9, false) == hex("09 10 03 E8 00 01 02 00 00 E5 B8"), "reset frame");
  const auto reply = hex("09 10 03 E8 00 03 01 30");
  std::string error;
  require(checkWriteResponse(reply.data(), reply.size(), moveRequest(9, 0xFF, 0xFF, 0xFF), &error), "write echo");
  require(!checkWriteResponse(reply.data(), reply.size(), moveRequest(10, 0xFF, 0xFF, 0xFF), &error), "wrong slave");
}

void statusParsesManualReplies() {
  StatusRegisters status;
  std::string error;
  const auto moving = hex("09 04 06 00 39 89 00 01 00 B0 9A");
  require(parseStatusResponse(moving.data(), moving.size(), 9, &status, &error), "moving parse");
  require(status.gOBJ == kGobjMoving && status.gSTA == 3 && status.gGTO == 1 && status.gACT == 1, "moving bits");
  require(status.positionRaw == 0x89 && status.currentRaw == 0x01 && status.fault == 0, "moving values");
  const auto clamped = hex("09 04 06 00 B1 AE 00 FE 00 1B C1");
  require(parseStatusResponse(clamped.data(), clamped.size(), 9, &status, &error), "clamped parse");
  require(status.gOBJ == kGobjContactClosing && status.gGTO == 0, "clamped bits");
  require(status.positionRaw == 0xAE && status.currentRaw == 0xFE, "clamped values");
  auto corrupt = clamped;
  corrupt.back() ^= 1;
  require(!parseStatusResponse(corrupt.data(), corrupt.size(), 9, &status, &error), "crc rejected");
  require(!parseStatusResponse(clamped.data(), clamped.size(), 10, &status, &error), "slave rejected");
  const auto exception = withCrc({9, 0x84, 0x02});
  require(!parseStatusResponse(exception.data(), exception.size(), 9, &status, &error)
      && error == "modbus exception code 2", "exception reported");
}

void positionConversionMatchesDriver() {
  require(positionRawForGapMm(26.0, 26.0) == 0, "open raw");
  require(positionRawForGapMm(1.02, 26.0) == 245, "min gap raw");
  require(positionRawForGapMm(-1.0, 26.0) == 255, "clamped raw");
  require(std::abs(gapMmForPositionRaw(0xAE, 26.0) - 26.0 * (1 - 174.0 / 255.0)) < 1e-9, "gap from raw");
}

void sampleFieldsRoundTrip() {
  StatusRegisters status{1, 0, 1, 3, 2, 0, 200, 0, 140};
  const auto sample = sampleFromStatus(status, 123456789);
  const auto line = std::string("OK\t5.6\tmeasured\t") + formatSampleFields(sample);
  GripperFeedbackSample parsed;
  require(parseSampleFields(split(line), 3, &parsed), "sample parse");
  require(parsed.positionValid && parsed.statusValid && parsed.currentValid, "sample valid");
  require(parsed.positionRaw == 200 && parsed.currentRaw == 140 && parsed.gOBJ == 2 && parsed.gGTO == 1, "sample values");
  require(parsed.monotonicUs == 123456789 && parsed.transport == "modbus", "sample stamp");
  require(!parseSampleFields(split("OK\t5.6\tmeasured"), 3, &parsed), "old worker has no sample");
  require(!parseSampleFields(split("OK\t5.6\tm\tSAMPLE1\t1\t1"), 3, &parsed), "truncated sample");
  GripperFeedbackSample bad = sample;
  bad.currentRaw = 300;
  require(parseSampleFields(split("OK\t1\tm\t" + formatSampleFields(bad)), 3, &parsed) && !parsed.currentValid,
      "out-of-range current invalid");
}
// 模拟夹爪：按收到的帧更新寄存器并生成应答；activationPolls 次读之后使能完成。
class FakeDevice final : public ModbusTransport {
 public:
  int slave{9};
  bool activated{false};
  int activationPolls{2};
  int fault{0};
  int position{0};
  bool exceptionOnRead{false};
  std::vector<std::vector<std::uint8_t>> requests;

  bool exchange(const std::vector<std::uint8_t>& request, std::size_t, std::vector<std::uint8_t>* response,
      std::string* error) override {
    requests.push_back(request);
    if (request[1] == kReadInputRegisters) {
      if (exceptionOnRead) {
        *response = withCrc({static_cast<std::uint8_t>(slave), 0x84, 0x04});
        return true;
      }
      if (pendingActivation > 0 && --pendingActivation == 0) activated = true;
      const int low = (activated ? 0x01 : 0) | (activated ? 0x30 : 0x10) | 0x08;
      *response = withCrc({static_cast<std::uint8_t>(slave), 0x04, 6, 0, static_cast<std::uint8_t>(low),
          static_cast<std::uint8_t>(position), static_cast<std::uint8_t>(fault), 3, 0});
      return true;
    }
    if (request[1] == kWriteMultipleRegisters) {
      if (request[5] == 1 && request[8] == 1) pendingActivation = activationPolls;
      if (request[5] == 3) position = request[9];
      *response = withCrc({request[0], request[1], request[2], request[3], request[4], request[5]});
      return true;
    }
    *error = "unexpected request";
    return false;
  }

 private:
  int pendingActivation{0};
};

JodellModbusClient client(FakeDevice& device) {
  static std::int64_t now = 0;
  return JodellModbusClient(device, device.slave, 26.0, [] { return now += 1000; }, [](int) {});
}

std::int64_t fakeNowUs() {
  static std::int64_t now = 0;
  return now += 1000;
}

bool isActivation(const std::vector<std::uint8_t>& frame) { return frame == activationRequest(9, true); }
bool isMove(const std::vector<std::uint8_t>& frame) { return frame[1] == kWriteMultipleRegisters && frame[5] == 3; }
int countReads(const FakeDevice& device) {
  int reads = 0;
  for (const auto& frame : device.requests) reads += frame[1] == kReadInputRegisters ? 1 : 0;
  return reads;
}

// 用与 worker 相同的 handleModbusLine 处理父进程请求，并收集每个应答里的样本。
struct WorkerHarness {
  FakeDevice device;
  JodellModbusClient gripper{client(device)};
  std::vector<std::string> lines;
  std::vector<GripperFeedbackSample> samples;
  bool request(const std::string& line, std::string* message) {
    lines.push_back(line);
    const auto parts = splitWorkerFields(handleModbusLine(gripper, line));
    for (const auto& sample : parseSamples(parts, 3)) samples.push_back(sample);
    if (message) *message = parts[2];
    return parts[0] == "OK";
  }
  bool move(const std::function<bool()>& cancelled, std::string* message) {
    return orchestrateModbusMove([this](const std::string& line, std::string* reply) { return request(line, reply); },
        cancelled, moveCommandLine(5.0, 64, 30), message, fakeNowUs);
  }
};

void moveActivatesOnlyWhenNeededAndReportsEveryRead() {
  WorkerHarness worker;
  std::string message;
  require(worker.move([] { return false; }, &message), "move after activation failed");
  require(isActivation(worker.device.requests[1]), "activation not written");
  require(isMove(worker.device.requests.back()), "move frame not last");
  require(worker.device.position == positionRawForGapMm(5.0, 26.0), "device did not move");
  // 每次成功读取（运动前读 + 使能等待中的多次读）都随应答上报，不只最后一条。
  require(static_cast<int>(worker.samples.size()) == countReads(worker.device) && worker.samples.size() >= 3,
      "reads during activation were not all reported");
  const auto before = worker.device.requests.size();
  worker.lines.clear();
  require(worker.move([] { return false; }, &message), "second move failed");
  require(worker.device.requests.size() == before + 2, "activated gripper was activated again");
  require(worker.lines.size() == 2 && worker.lines[0] == "PREPARE", "ready gripper still awaited activation");
}

void emergencyStopDuringActivationBlocksMove() {
  // 审查复现：使能等待中撤销授权后，不得再有任何运动写入。
  WorkerHarness worker;
  worker.device.activationPolls = 1000000;
  int awaits = 0;
  std::string message;
  const bool ok = worker.move([&] {
    for (const auto& line : worker.lines) awaits += line.rfind("AWAIT", 0) == 0 ? 1 : 0;
    const bool stop = awaits > 0;
    awaits = 0;
    return stop;
  }, &message);
  require(!ok && message.find("cancelled") != std::string::npos, "cancellation not reported");
  for (const auto& frame : worker.device.requests) require(!isMove(frame), "move written after emergency stop");
  require(worker.lines.back().rfind("AWAIT", 0) == 0, "no AWAIT slice was attempted before cancelling");

  // 使能很快完成的情形：等待片之后授权已失效，最终运动写之前仍须拦下。
  WorkerHarness quick;
  quick.device.activationPolls = 2;
  require(!quick.move([&] {
    for (const auto& line : quick.lines) if (line.rfind("AWAIT", 0) == 0) return true;
    return false;
  }, &message), "quick activation ignored cancellation");
  for (const auto& frame : quick.device.requests) require(!isMove(frame), "move written after emergency stop");

  WorkerHarness beforePrepare;
  require(!beforePrepare.move([] { return true; }, &message) && beforePrepare.device.requests.empty(),
      "cancelled command still touched the device");
}

void faultAndTimeoutKeepReadings() {
  WorkerHarness faulted;
  faulted.device.activated = true;
  faulted.device.fault = 0x0B;
  std::string message;
  require(!faulted.move([] { return false; }, &message) && message.find("fault") != std::string::npos,
      "fault not rejected");
  require(faulted.device.requests.size() == 1, "faulted gripper received a write");
  require(faulted.samples.size() == 1 && faulted.samples[0].fault == 0x0B, "fault reading was not reported");

  WorkerHarness stuck;
  stuck.device.activationPolls = 1000000;
  require(!stuck.move([] { return false; }, &message) && message.find("activation timeout") != std::string::npos,
      "activation timeout not reported");
  for (const auto& frame : stuck.device.requests) require(!isMove(frame), "move sent without activation");
  require(stuck.lines.back().rfind("AWAIT", 0) == 0, "timeout did not happen while awaiting");

  WorkerHarness single;
  require(splitWorkerFields(handleModbusLine(single.gripper, "COMMAND\t5\t64\t30"))[0] == "ERR",
      "single-step COMMAND accepted in modbus mode");
}

void clientReadMarksExceptionInvalid() {
  FakeDevice device;
  device.activated = true;
  device.position = 200;
  auto gripper = client(device);
  GripperFeedbackSample sample;
  std::string error;
  require(gripper.readSample(&sample, &error) && sample.positionRaw == 200 && sample.currentRaw == 3, "read failed");
  require(sample.monotonicUs > 0 && sample.transport == "modbus", "sample stamp missing");
  require(std::abs(gripper.gapMm(sample) - gapMmForPositionRaw(200, 26.0)) < 1e-9, "gap conversion");
  device.exceptionOnRead = true;
  require(!gripper.readSample(&sample, &error) && !sample.positionValid && !sample.currentValid, "exception valid");
  require(error.find("exception") != std::string::npos, "exception not reported");
}
}  // namespace

int main() {
  try {
    framesMatchManual();
    statusParsesManualReplies();
    positionConversionMatchesDriver();
    sampleFieldsRoundTrip();
    moveActivatesOnlyWhenNeededAndReportsEveryRead();
    emergencyStopDuringActivationBlocksMove();
    faultAndTimeoutKeepReadings();
    clientReadMarksExceptionInvalid();
  } catch (const std::exception& error) {
    std::cerr << "JodellModbusTests failed: " << error.what() << '\n';
    return 1;
  }
  std::cout << "JodellModbusTests passed\n";
  return 0;
}
