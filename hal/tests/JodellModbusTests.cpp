// 离线测试：钧舵 Modbus 帧与手册 A.1 第 7 章示例逐字节一致，worker 样本字段往返无损，
// 以及 worker 的使能/故障/应答校验逻辑（模拟设备）；不打开串口。
#include <cstdint>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "JodellModbusClient.h"

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

void clientActivatesOnlyWhenNeeded() {
  FakeDevice device;
  auto gripper = client(device);
  GripperFeedbackSample sample;
  std::string message;
  require(gripper.moveTo(5.0, 64, 30, 1500, &sample, &message), "move after activation failed");
  require(device.requests[1] == activationRequest(9, true), "activation not written");
  require(device.requests.back() == moveRequest(9, positionRawForGapMm(5.0, 26.0), 64, 30), "move frame wrong");
  require(device.position == positionRawForGapMm(5.0, 26.0), "device did not move");
  const auto before = device.requests.size();
  require(gripper.moveTo(10.0, 64, 30, 1500, &sample, &message), "second move failed");
  require(device.requests.size() == before + 2, "activated gripper was activated again");
  for (std::size_t i = before; i < device.requests.size(); ++i) {
    require(device.requests[i] != activationRequest(9, true), "re-activation sent");
  }
}

void clientRejectsFaultAndActivationTimeout() {
  FakeDevice faulted;
  faulted.activated = true;
  faulted.fault = 0x0B;
  auto gripper = client(faulted);
  GripperFeedbackSample sample;
  std::string message;
  require(!gripper.moveTo(5.0, 64, 30, 1500, &sample, &message) && message.find("fault") != std::string::npos,
      "fault not rejected");
  require(faulted.requests.size() == 1, "faulted gripper received a write");

  FakeDevice stuck;
  stuck.activationPolls = 1000000;
  auto slow = client(stuck);
  require(!slow.moveTo(5.0, 64, 30, 50, &sample, &message) && message.find("activation timeout") != std::string::npos,
      "activation timeout not reported");
  require(stuck.requests.back()[1] == kReadInputRegisters, "move sent without activation");
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
    clientActivatesOnlyWhenNeeded();
    clientRejectsFaultAndActivationTimeout();
    clientReadMarksExceptionInvalid();
  } catch (const std::exception& error) {
    std::cerr << "JodellModbusTests failed: " << error.what() << '\n';
    return 1;
  }
  std::cout << "JodellModbusTests passed\n";
  return 0;
}
