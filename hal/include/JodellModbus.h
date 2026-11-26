/*
 * 阅读导航 06｜HAL 硬件与安全
 * 职责：钧舵 EPG 夹爪 Modbus RTU 帧编解码、结构化反馈样本，以及 worker 应答中样本字段的编解码；不含串口 I/O。
 * 先看：readStatusRequest → parseStatusResponse → GripperFeedbackSample → formatSampleFields / parseSampleFields。
 * 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。
 */
#pragma once

// 依据 docs/hardware/jodell/EPG-series-C0-C7-A.1.pdf：
// 控制寄存器 0x03E8（低字节 rACT/rMODE/rGTO）、0x03E9 高字节 rPR、0x03EA 低字节 rSP / 高字节 rFC；
// 状态寄存器 0x07D0 低字节 gACT/gMODE/gGTO/gSTA/gOBJ、0x07D1 低字节故障 / 高字节 gPR、
// 0x07D2 低字节速度 / 高字节 gCU（电流标幺值）。Python 侧同一实现见 backend/core/jodell_modbus.py。

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include <sstream>
#include <string>
#include <vector>

namespace appstation::hal::jodell {

constexpr std::uint16_t kControlRegister = 0x03E8;
constexpr std::uint16_t kStatusRegister = 0x07D0;
constexpr std::uint8_t kStatusRegisterCount = 3;
constexpr std::uint8_t kReadInputRegisters = 0x04;
constexpr std::uint8_t kWriteMultipleRegisters = 0x10;
constexpr std::size_t kStatusResponseLength = 5 + kStatusRegisterCount * 2;
constexpr std::size_t kWriteResponseLength = 8;
constexpr std::size_t kExceptionResponseLength = 5;

constexpr int kGobjMoving = 0;
constexpr int kGobjContactOpening = 1;
constexpr int kGobjContactClosing = 2;
constexpr int kGobjArrivedNoObject = 3;
constexpr int kGstaActivated = 3;

inline std::uint16_t crc16(const std::uint8_t* data, std::size_t size) {
  std::uint16_t crc = 0xFFFF;
  for (std::size_t i = 0; i < size; ++i) {
    crc ^= data[i];
    for (int bit = 0; bit < 8; ++bit) {
      crc = (crc & 1) ? static_cast<std::uint16_t>((crc >> 1) ^ 0xA001) : static_cast<std::uint16_t>(crc >> 1);
    }
  }
  return crc;
}

inline std::vector<std::uint8_t> withCrc(std::vector<std::uint8_t> body) {
  const auto crc = crc16(body.data(), body.size());
  body.push_back(static_cast<std::uint8_t>(crc & 0xFF));
  body.push_back(static_cast<std::uint8_t>(crc >> 8));
  return body;
}

inline bool checkCrc(const std::uint8_t* frame, std::size_t size) {
  if (size < 4) return false;
  const auto expected = static_cast<std::uint16_t>(frame[size - 2] | (frame[size - 1] << 8));
  return crc16(frame, size - 2) == expected;
}

inline std::uint8_t clampByte(int value) {
  return static_cast<std::uint8_t>(std::clamp(value, 0, 255));
}

// 功能码 0x04 一次读 0x07D0 起 3 个寄存器：状态、故障+位置、速度+电流来自同一次应答。
inline std::vector<std::uint8_t> readStatusRequest(int slaveId) {
  return withCrc({clampByte(slaveId), kReadInputRegisters,
                  static_cast<std::uint8_t>(kStatusRegister >> 8), static_cast<std::uint8_t>(kStatusRegister & 0xFF),
                  0x00, kStatusRegisterCount});
}

// 功能码 0x10 写 0x03E8–0x03EA：rACT=1、rGTO=1、参数模式；与手册“全速全力关闭”示例帧格式一致。
inline std::vector<std::uint8_t> moveRequest(int slaveId, int positionRaw, int speedRaw, int forceRaw) {
  return withCrc({clampByte(slaveId), kWriteMultipleRegisters,
                  static_cast<std::uint8_t>(kControlRegister >> 8), static_cast<std::uint8_t>(kControlRegister & 0xFF),
                  0x00, 0x03, 0x06,
                  0x00, 0x09,
                  clampByte(positionRaw), 0x00,
                  clampByte(forceRaw), clampByte(speedRaw)});
}

// 只写 0x03E8 一个寄存器：active=false 清 rACT（复位并清故障），true 置 rACT=1 使能（可能带动手指自检）。
inline std::vector<std::uint8_t> activationRequest(int slaveId, bool active) {
  return withCrc({clampByte(slaveId), kWriteMultipleRegisters,
                  static_cast<std::uint8_t>(kControlRegister >> 8), static_cast<std::uint8_t>(kControlRegister & 0xFF),
                  0x00, 0x01, 0x02, 0x00, static_cast<std::uint8_t>(active ? 0x01 : 0x00)});
}

struct StatusRegisters {
  int gACT{0};
  int gMODE{0};
  int gGTO{0};
  int gSTA{0};
  int gOBJ{0};
  int fault{0};
  int positionRaw{0};
  int speedRaw{0};
  int currentRaw{0};
};

// 应答头不匹配或 CRC 错误时返回 false；异常应答（功能码 | 0x80）给出异常码。
inline bool parseStatusResponse(
    const std::uint8_t* frame, std::size_t size, int slaveId, StatusRegisters* out, std::string* error) {
  auto fail = [&](const std::string& text) {
    if (error) *error = text;
    return false;
  };
  if (size == kExceptionResponseLength && checkCrc(frame, size) && frame[1] == (kReadInputRegisters | 0x80)) {
    return fail("modbus exception code " + std::to_string(frame[2]));
  }
  if (size != kStatusResponseLength) return fail("status response length " + std::to_string(size));
  if (!checkCrc(frame, size)) return fail("status response CRC mismatch");
  if (frame[0] != slaveId || frame[1] != kReadInputRegisters || frame[2] != kStatusRegisterCount * 2) {
    return fail("unexpected status response header");
  }
  const int low = frame[4];
  out->gACT = low & 0x01;
  out->gMODE = (low >> 2) & 0x01;
  out->gGTO = (low >> 3) & 0x01;
  out->gSTA = (low >> 4) & 0x03;
  out->gOBJ = (low >> 6) & 0x03;
  out->positionRaw = frame[5];
  out->fault = frame[6];
  out->currentRaw = frame[7];
  out->speedRaw = frame[8];
  return true;
}

// 写多寄存器应答回显首址和数量；返回前校验，避免把错位的旧应答当成功。
inline bool checkWriteResponse(
    const std::uint8_t* frame, std::size_t size, const std::vector<std::uint8_t>& request, std::string* error) {
  if (size == kExceptionResponseLength && checkCrc(frame, size) && frame[1] == (kWriteMultipleRegisters | 0x80)) {
    if (error) *error = "modbus exception code " + std::to_string(frame[2]);
    return false;
  }
  if (size != kWriteResponseLength || !checkCrc(frame, size)
      || !std::equal(request.begin(), request.begin() + 6, frame)) {
    if (error) *error = "unexpected write response";
    return false;
  }
  return true;
}

inline int positionRawForGapMm(double gapMm, double strokeMm) {
  // (std::max) 防止 windows.h 未定义 NOMINMAX 时 max 宏展开。
  const double stroke = (std::max)(0.001, strokeMm);
  const double ratio = std::clamp(1.0 - gapMm / stroke, 0.0, 1.0);
  return static_cast<int>(std::lround(ratio * 255.0));
}

inline double gapMmForPositionRaw(int positionRaw, double strokeMm) {
  return (std::max)(0.001, strokeMm) * (1.0 - std::clamp(positionRaw, 0, 255) / 255.0);
}

// 一次读取得到的结构化反馈。monotonicUs 为 steady_clock 微秒（Windows 上 MSVC 与 Python 都基于 QPC），
// 取请求发出到应答收齐的中点；同一样本的位置、状态和电流共用这个时间戳。
struct GripperFeedbackSample {
  bool positionValid{false};
  bool statusValid{false};
  bool currentValid{false};
  int positionRaw{-1};
  int currentRaw{-1};
  int gACT{-1};
  int gGTO{-1};
  int gSTA{-1};
  int gOBJ{-1};
  int fault{-1};
  std::int64_t monotonicUs{0};
  std::string transport{"none"};
};

inline GripperFeedbackSample sampleFromStatus(const StatusRegisters& status, std::int64_t monotonicUs) {
  GripperFeedbackSample sample;
  sample.positionValid = sample.statusValid = sample.currentValid = true;
  sample.positionRaw = status.positionRaw;
  sample.currentRaw = status.currentRaw;
  sample.gACT = status.gACT;
  sample.gGTO = status.gGTO;
  sample.gSTA = status.gSTA;
  sample.gOBJ = status.gOBJ;
  sample.fault = status.fault;
  sample.monotonicUs = monotonicUs;
  sample.transport = "modbus";
  return sample;
}

// worker 一行应答 = "OK|ERR \t positionMm \t message"，之后追加以 SAMPLE1 开头的固定字段；
// 旧 worker 没有这些字段时 parseSampleFields 返回 false，上层把电流/状态标为无效。
constexpr const char* kSampleTag = "SAMPLE1";
constexpr std::size_t kSampleFieldCount = 13;

inline std::string formatSampleFields(const GripperFeedbackSample& sample) {
  std::ostringstream out;
  out << kSampleTag
      << '\t' << (sample.positionValid ? 1 : 0)
      << '\t' << (sample.statusValid ? 1 : 0)
      << '\t' << (sample.currentValid ? 1 : 0)
      << '\t' << sample.positionRaw
      << '\t' << sample.currentRaw
      << '\t' << sample.gACT
      << '\t' << sample.gGTO
      << '\t' << sample.gSTA
      << '\t' << sample.gOBJ
      << '\t' << sample.fault
      << '\t' << sample.monotonicUs
      << '\t' << sample.transport;
  return out.str();
}

inline bool parseSampleFields(const std::vector<std::string>& parts, std::size_t offset, GripperFeedbackSample* out) {
  if (parts.size() < offset + kSampleFieldCount || parts[offset] != kSampleTag) return false;
  auto integer = [&](std::size_t index, long long* value) {
    const auto& text = parts[offset + index];
    char* end = nullptr;
    *value = std::strtoll(text.c_str(), &end, 10);
    return !text.empty() && end == text.c_str() + text.size();
  };
  long long values[11]{};
  for (std::size_t i = 0; i < 11; ++i) {
    if (!integer(i + 1, &values[i])) return false;
  }
  GripperFeedbackSample sample;
  sample.positionValid = values[0] == 1;
  sample.statusValid = values[1] == 1;
  sample.currentValid = values[2] == 1;
  sample.positionRaw = static_cast<int>(values[3]);
  sample.currentRaw = static_cast<int>(values[4]);
  sample.gACT = static_cast<int>(values[5]);
  sample.gGTO = static_cast<int>(values[6]);
  sample.gSTA = static_cast<int>(values[7]);
  sample.gOBJ = static_cast<int>(values[8]);
  sample.fault = static_cast<int>(values[9]);
  sample.monotonicUs = values[10];
  sample.transport = parts[offset + 12];
  // 原码越界说明解析或设备异常，不能当作有效测量。
  if (sample.positionValid && (sample.positionRaw < 0 || sample.positionRaw > 255)) sample.positionValid = false;
  if (sample.currentValid && (sample.currentRaw < 0 || sample.currentRaw > 255)) sample.currentValid = false;
  *out = sample;
  return true;
}

// 一行应答可以带多个样本（例如使能等待期间的多次读取），依次解析直到没有 SAMPLE1 字段。
inline std::vector<GripperFeedbackSample> parseSamples(const std::vector<std::string>& parts, std::size_t offset) {
  std::vector<GripperFeedbackSample> samples;
  GripperFeedbackSample sample;
  while (parseSampleFields(parts, offset, &sample)) {
    samples.push_back(sample);
    offset += kSampleFieldCount;
  }
  return samples;
}

}  // namespace appstation::hal::jodell
