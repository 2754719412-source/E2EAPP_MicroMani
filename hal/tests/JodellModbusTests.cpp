// 离线测试：钧舵 Modbus 帧与手册 A.1 第 7 章示例逐字节一致，worker 样本字段往返无损；不打开串口。
#include <cstdint>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#include "JodellModbus.h"

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
}  // namespace

int main() {
  try {
    framesMatchManual();
    statusParsesManualReplies();
    positionConversionMatchesDriver();
    sampleFieldsRoundTrip();
  } catch (const std::exception& error) {
    std::cerr << "JodellModbusTests failed: " << error.what() << '\n';
    return 1;
  }
  std::cout << "JodellModbusTests passed\n";
  return 0;
}
