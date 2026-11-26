/*
 * 阅读导航 06｜HAL 硬件与安全
 * 职责：夹爪 worker 管道协议的可移植部分：应答行格式、Modbus 模式单行命令处理，以及父进程侧
 *       PREPARE → AWAIT → MOVE 的运动编排（每步之前检查运动授权，急停后不再写运动帧）。
 * 先看：formatResponse → handleModbusLine → orchestrateModbusMove。
 * 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。
 */
#pragma once

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdlib>
#include <functional>
#include <sstream>
#include <string>
#include <vector>

#include "JodellModbusClient.h"

namespace appstation::hal::jodell {

constexpr const char* kWorkerStateReady = "READY";
constexpr const char* kWorkerStateActivating = "ACTIVATING";
// 使能等待按片发送，父进程在两片之间检查授权；总时长超过上限即放弃。
constexpr int kActivationSliceMs = 100;
constexpr int kActivationTimeoutMs = 1500;

inline std::vector<std::string> splitWorkerFields(const std::string& value) {
  std::vector<std::string> parts;
  std::size_t start = 0;
  while (true) {
    const auto next = value.find('\t', start);
    parts.push_back(value.substr(start, next == std::string::npos ? std::string::npos : next - start));
    if (next == std::string::npos) return parts;
    start = next + 1;
  }
}

inline std::string sanitizeWorkerField(std::string value) {
  for (char& ch : value) {
    if (ch == '\t' || ch == '\r' || ch == '\n') ch = ' ';
  }
  return value;
}

// 应答行：OK|ERR \t 位置 mm \t 消息，之后依次追加本次请求内每个成功读数的 SAMPLE1 字段（可为 0 个）。
inline std::string formatResponse(bool ok, double positionMm, const std::string& message,
    const std::vector<GripperFeedbackSample>& samples) {
  std::ostringstream out;
  out << (ok ? "OK" : "ERR") << '\t' << positionMm << '\t' << sanitizeWorkerField(message);
  for (const auto& sample : samples) out << '\t' << formatSampleFields(sample);
  return out.str();
}

// Modbus 模式 worker 的单行命令处理。单步 COMMAND 会把使能等待和运动写合在一次请求里，急停无法中途撤销，故拒绝。
inline std::string handleModbusLine(JodellModbusClient& client, const std::string& line) {
  std::vector<GripperFeedbackSample> samples;
  std::string message;
  auto lastGap = [&]() {
    for (auto it = samples.rbegin(); it != samples.rend(); ++it) {
      if (it->positionValid) return client.gapMm(*it);
    }
    return -1.0;
  };
  if (line == "READ" || line == "READPOS") {
    // 一次读取即包含位置、状态和电流，READ 与 READPOS 不再有代价差异。
    GripperFeedbackSample sample;
    const bool ok = client.readSample(&sample, &message);
    if (ok) samples.push_back(sample);
    return formatResponse(ok, lastGap(), ok ? "modbus read" : message, samples);
  }
  if (line == "PREPARE") {
    bool activating = false;
    const bool ok = client.prepare(&samples, &activating, &message);
    return formatResponse(ok, lastGap(), ok ? (activating ? kWorkerStateActivating : kWorkerStateReady) : message,
        samples);
  }
  const auto parts = splitWorkerFields(line);
  if (parts.size() == 2 && parts[0] == "AWAIT") {
    bool ready = false;
    const int sliceMs = std::clamp(static_cast<int>(std::strtol(parts[1].c_str(), nullptr, 10)), 1, 500);
    const bool ok = client.awaitActive(sliceMs, &samples, &ready, &message);
    return formatResponse(ok, lastGap(), ok ? (ready ? kWorkerStateReady : kWorkerStateActivating) : message,
        samples);
  }
  if (parts.size() == 4 && parts[0] == "MOVE") {
    const double targetMm = std::strtod(parts[1].c_str(), nullptr);
    const int speed = std::clamp(static_cast<int>(std::strtol(parts[2].c_str(), nullptr, 10)), 1, 255);
    const int torque = std::clamp(static_cast<int>(std::strtol(parts[3].c_str(), nullptr, 10)), 1, 255);
    const bool ok = client.writeMove(targetMm, speed, torque, &message);
    return formatResponse(ok, -1.0, message, samples);
  }
  return formatResponse(false, -1.0, "unsupported command in modbus mode", samples);
}

inline std::string moveCommandLine(double targetMm, int speed, int torque) {
  std::ostringstream out;
  out << "MOVE\t" << targetMm << '\t' << speed << '\t' << torque;
  return out.str();
}

// 父进程侧编排。request(line, &message) 发一条 worker 请求并返回是否 OK，message 为应答消息字段；
// cancelled() 为 true 表示运动授权已失效（急停或代际变化）。授权在 PREPARE（可能写使能）之前、
// 每片使能等待之间、MOVE（最终运动写）之前各检查一次；失效即返回，不再发送后续写命令。
inline bool orchestrateModbusMove(
    const std::function<bool(const std::string&, std::string*)>& request,
    const std::function<bool()>& cancelled,
    const std::string& moveLine,
    std::string* message,
    const std::function<std::int64_t()>& nowUs = steadyNowUs,
    int activationTimeoutMs = kActivationTimeoutMs,
    int sliceMs = kActivationSliceMs) {
  auto stop = [&](const std::string& text) {
    if (message) *message = text;
    return false;
  };
  if (cancelled()) return stop("gripper command cancelled by emergency stop");
  std::string state;
  if (!request("PREPARE", &state)) return stop(state);
  const auto deadline = nowUs() + static_cast<std::int64_t>(activationTimeoutMs) * 1000;
  while (state == kWorkerStateActivating) {
    if (cancelled()) return stop("gripper command cancelled by emergency stop during activation");
    if (nowUs() >= deadline) return stop("gripper activation timeout");
    if (!request("AWAIT\t" + std::to_string(sliceMs), &state)) return stop(state);
  }
  if (state != kWorkerStateReady) return stop("unexpected worker state: " + state);
  if (cancelled()) return stop("gripper command cancelled by emergency stop");
  return request(moveLine, message);
}

}  // namespace appstation::hal::jodell
