/*
 * 阅读导航 06｜HAL 硬件与安全
 * 职责：独立夹爪工作进程入口；按 --transport 用 vendor DLL 或直接 Modbus RTU 执行父进程命令，返回位置和结构化样本。
 * 先看：main → Win32SerialTransport → writeResponse。
 * 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。
 */
#include "JodellGripperDriver.h"
#include "JodellWorkerProtocol.h"

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <vector>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace {

// worker 与父进程使用 tab 分隔的一行协议，因此这里提供最小拆分函数。
std::vector<std::string> splitTabs(const std::string& value) {
  std::vector<std::string> parts;
  size_t start = 0;
  while (start <= value.size()) {
    const auto next = value.find('\t', start);
    if (next == std::string::npos) {
      parts.push_back(value.substr(start));
      break;
    }
    parts.push_back(value.substr(start, next - start));
    start = next + 1;
  }
  return parts;
}

// 响应字段不能包含制表符或换行，否则父进程无法可靠解析。
std::string sanitizeField(std::string value) {
  for (char& ch : value) {
    if (ch == '\t' || ch == '\r' || ch == '\n') {
      ch = ' ';
    }
  }
  return value;
}

// worker 参数规模很小，使用直接扫描避免引入额外命令行解析依赖。
std::string argValue(int argc, char** argv, const std::string& key, const std::string& fallback = "") {
  for (int i = 1; i + 1 < argc; ++i) {
    if (std::string(argv[i]) == key) {
      return argv[i + 1];
    }
  }
  return fallback;
}

// 解析失败时使用 fallback，让父进程仍能用默认串口参数启动 worker。
int intArg(int argc, char** argv, const std::string& key, int fallback) {
  const auto value = argValue(argc, argv, key);
  if (value.empty()) {
    return fallback;
  }
  char* end = nullptr;
  const long parsed = std::strtol(value.c_str(), &end, 10);
  return end == value.c_str() ? fallback : static_cast<int>(parsed);
}

double doubleArg(int argc, char** argv, const std::string& key, double fallback) {
  const auto value = argValue(argc, argv, key);
  if (value.empty()) {
    return fallback;
  }
  char* end = nullptr;
  const double parsed = std::strtod(value.c_str(), &end);
  return end == value.c_str() ? fallback : parsed;
}

// 应答行格式见 JodellWorkerProtocol.h：OK|ERR \t 位置 \t 消息，之后是本次请求内每个读数的 SAMPLE1 字段。
void writeResponse(bool ok, double positionMm, const std::string& message,
    const std::vector<appstation::hal::jodell::GripperFeedbackSample>& samples) {
  std::cout << appstation::hal::jodell::formatResponse(ok, positionMm, message, samples) << '\n';
  std::cout.flush();
}

void writeResponse(bool ok, double positionMm, const std::string& message,
    const appstation::hal::jodell::GripperFeedbackSample& sample) {
  writeResponse(ok, positionMm, message, std::vector<appstation::hal::jodell::GripperFeedbackSample>{sample});
}

#ifdef _WIN32
// worker 独占该侧串口；同一端口不能再交给 vendor DLL，否则两者会争抢句柄。
class Win32SerialTransport final : public appstation::hal::jodell::ModbusTransport {
 public:
  Win32SerialTransport(std::string port, int baudrate, int timeoutMs)
      : port_(std::move(port)), baudrate_(baudrate), timeoutMs_(std::max(10, timeoutMs)) {}
  ~Win32SerialTransport() override { close(); }

  bool exchange(const std::vector<std::uint8_t>& request, std::size_t normalLength,
      std::vector<std::uint8_t>* response, std::string* error) override {
    if (!ensureOpen(error)) return false;
    // 丢弃上一轮迟到或残留字节，保证应答与本次请求对应。
    PurgeComm(handle_, PURGE_RXCLEAR | PURGE_TXCLEAR);
    DWORD written = 0;
    if (!WriteFile(handle_, request.data(), static_cast<DWORD>(request.size()), &written, nullptr)
        || written != request.size()) {
      close();
      if (error) *error = "serial write failed " + port_;
      return false;
    }
    response->clear();
    const auto deadline = std::chrono::steady_clock::now() + std::chrono::milliseconds(timeoutMs_);
    if (!readExact(2, deadline, response)) {
      if (error) *error = "modbus response timeout " + port_;
      return false;
    }
    const std::size_t total = ((*response)[1] & 0x80) != 0
        ? appstation::hal::jodell::kExceptionResponseLength : normalLength;
    if (!readExact(total - 2, deadline, response)) {
      if (error) *error = "modbus response truncated " + port_;
      return false;
    }
    return true;
  }

 private:
  bool readExact(std::size_t count, std::chrono::steady_clock::time_point deadline,
      std::vector<std::uint8_t>* out) {
    std::uint8_t buffer[64];
    while (count > 0) {
      if (std::chrono::steady_clock::now() >= deadline) return false;
      DWORD read = 0;
      const DWORD chunk = static_cast<DWORD>(std::min<std::size_t>(count, sizeof(buffer)));
      if (!ReadFile(handle_, buffer, chunk, &read, nullptr)) {
        close();
        return false;
      }
      out->insert(out->end(), buffer, buffer + read);
      count -= read;
    }
    return true;
  }

  bool ensureOpen(std::string* error) {
    if (handle_ != INVALID_HANDLE_VALUE) return true;
    std::string name = port_;
    if (!name.empty() && name.find_first_not_of("0123456789") == std::string::npos) name = "COM" + name;
    const std::string path = "\\\\.\\" + name;
    handle_ = CreateFileA(path.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr, OPEN_EXISTING, 0, nullptr);
    if (handle_ == INVALID_HANDLE_VALUE) {
      if (error) *error = "open " + name + " failed error=" + std::to_string(GetLastError());
      return false;
    }
    DCB dcb{};
    dcb.DCBlength = sizeof(dcb);
    COMMTIMEOUTS timeouts{};
    // 有数据立即返回，无数据最多等 5 ms；整帧期限由 exchange 的 deadline 控制。
    timeouts.ReadIntervalTimeout = MAXDWORD;
    timeouts.ReadTotalTimeoutMultiplier = MAXDWORD;
    timeouts.ReadTotalTimeoutConstant = 5;
    timeouts.WriteTotalTimeoutConstant = 50;
    if (!GetCommState(handle_, &dcb)) return failOpen(error, "GetCommState");
    dcb.BaudRate = static_cast<DWORD>(baudrate_);
    dcb.ByteSize = 8;
    dcb.Parity = NOPARITY;
    dcb.StopBits = ONESTOPBIT;
    dcb.fBinary = TRUE;
    dcb.fParity = FALSE;
    dcb.fOutxCtsFlow = FALSE;
    dcb.fOutxDsrFlow = FALSE;
    dcb.fDtrControl = DTR_CONTROL_ENABLE;
    dcb.fRtsControl = RTS_CONTROL_ENABLE;
    dcb.fOutX = FALSE;
    dcb.fInX = FALSE;
    if (!SetCommState(handle_, &dcb)) return failOpen(error, "SetCommState");
    if (!SetCommTimeouts(handle_, &timeouts)) return failOpen(error, "SetCommTimeouts");
    return true;
  }

  bool failOpen(std::string* error, const char* step) {
    if (error) *error = std::string(step) + " failed " + port_ + " error=" + std::to_string(GetLastError());
    close();
    return false;
  }

  void close() {
    if (handle_ != INVALID_HANDLE_VALUE) CloseHandle(handle_);
    handle_ = INVALID_HANDLE_VALUE;
  }

  std::string port_;
  int baudrate_;
  int timeoutMs_;
  HANDLE handle_{INVALID_HANDLE_VALUE};
};
#endif

}  // namespace

int main(int argc, char** argv) {
  // 每个 worker 只服务单侧夹爪，避免同一进程内频繁切换串口。
  const std::string sideArg = argValue(argc, argv, "--side", "left");
  const auto side = sideArg == "right" ? appstation::hal::Side::Right : appstation::hal::Side::Left;
  const int sideIndex = side == appstation::hal::Side::Left ? 0 : 1;

  appstation::hal::JodellGripperConfig config;
  config.processWorkersEnabled = false;
  config.ports[sideIndex] = argValue(argc, argv, "--port", sideIndex == 0 ? "COM8" : "COM9");
  config.slaveIds[sideIndex] = intArg(argc, argv, "--slave", sideIndex == 0 ? 10 : 9);
  config.baudrate = intArg(argc, argv, "--baudrate", 115200);
  config.strokeMm = doubleArg(argc, argv, "--stroke-mm", 26.0);
  config.dllPath = argValue(argc, argv, "--dll", config.dllPath);

  const std::string transport = argValue(argc, argv, "--transport", "dll");
  const int modbusTimeoutMs = intArg(argc, argv, "--modbus-timeout-ms", 100);
  namespace jodell = appstation::hal::jodell;

  if (transport == "modbus") {
#ifdef _WIN32
    // Modbus 模式：本进程直接独占串口，不加载 vendor DLL；读写共用同一串口句柄。
    // 运动拆成 PREPARE / AWAIT / MOVE 三个请求（见 JodellWorkerProtocol.h），父进程在每个请求之前检查运动授权。
    Win32SerialTransport serial(config.ports[sideIndex], config.baudrate, modbusTimeoutMs);
    jodell::JodellModbusClient client(serial, config.slaveIds[sideIndex], config.strokeMm);
    std::string line;
    while (std::getline(std::cin, line)) {
      if (line == "EXIT") break;
      std::cout << jodell::handleModbusLine(client, line) << '\n';
      std::cout.flush();
    }
    return 0;
#else
    (void)modbusTimeoutMs;
    writeResponse(false, -1.0, "modbus transport is Windows-only", jodell::GripperFeedbackSample{});
    return 1;
#endif
  }

  appstation::hal::JodellGripperDriver driver;
  driver.configure(config);

  // 父进程通过 stdin 发送 READ、COMMAND、EXIT；worker 保持常驻以复用 DLL/串口状态。
  std::string line;
  while (std::getline(std::cin, line)) {
    if (line == "EXIT") {
      break;
    }
    if (line == "READ" || line == "READPOS") {
      // READ 另读夹持状态与力矩；READPOS 只读位置，供遥操作采集保持读数频率。
      std::string message;
      const auto started = jodell::steadyNowUs();
      const bool ok = driver.readPositionMm(side, &message, line == "READ");
      const auto finished = jodell::steadyNowUs();
      auto sample = driver.lastDllSample(side);
      sample.monotonicUs = started + (finished - started) / 2;
      const auto positions = driver.positionMm();
      writeResponse(ok, positions[sideIndex], message, sample);
      continue;
    }
    const auto parts = splitTabs(line);
    if (parts.size() == 4 && parts[0] == "COMMAND") {
      // COMMAND 参数已经由父进程生成，这里只做范围夹紧，避免异常输入传给 vendor DLL。
      const double targetMm = std::strtod(parts[1].c_str(), nullptr);
      const int speed = std::clamp(static_cast<int>(std::strtol(parts[2].c_str(), nullptr, 10)), 1, 255);
      const int torque = std::clamp(static_cast<int>(std::strtol(parts[3].c_str(), nullptr, 10)), 1, 255);
      std::string message;
      const bool ok = driver.commandTarget(side, targetMm, speed, torque, &message, false);
      const auto positions = driver.positionMm();
      // DLL 命令路径不读反馈，样本标为无效，HAL 不会把它计为一次采样。
      jodell::GripperFeedbackSample sample;
      sample.transport = "dll";
      writeResponse(ok, positions[sideIndex], message, sample);
      continue;
    }
    writeResponse(false, -1.0, "unsupported command", jodell::GripperFeedbackSample{});
  }
  return 0;
}
