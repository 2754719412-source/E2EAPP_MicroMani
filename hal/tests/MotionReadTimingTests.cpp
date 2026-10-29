// 使用 SDK 函数替身验证计时和抢锁诊断；不加载 DLL 或连接控制卡。
#define APPSTATION_ENABLE_VENDOR_SDKS 1
#include "../src/LTDMCDriver.cpp"
#include <future>
#include <iostream>

namespace appstation::hal {
struct MotionExecutorTestAccess {
  static void initialize(LTDMCDriver& driver) { driver.initialized_ = true; }
  static auto hold(LTDMCDriver& driver) { return std::unique_lock(driver.mutex_); }
  static const MotionTiming& timing(const LTDMCDriver& driver) { return driver.timing_; }
};
}
using namespace appstation::hal;
using namespace std::chrono_literals;

namespace {
void require(bool value, const char* message) {
  if (!value) throw std::runtime_error(message);
}
void delay() {
  const auto end = std::chrono::steady_clock::now() + 50us;
  while (std::chrono::steady_clock::now() < end) std::this_thread::yield();
}
long __stdcall position(unsigned short card, unsigned short axis) { delay(); return card * 100 + axis; }
short __stdcall enabled(unsigned short, unsigned short) { delay(); return 1; }
short __stdcall done(unsigned short, unsigned short) { delay(); return 1; }
}

int main() {
  try {
    LTDMCDriver driver;
    MotionExecutorTestAccess::initialize(driver);
    dmcGetPosition = position;
    dmcReadSevonPin = enabled;
    dmcCheckDone = done;
    const auto first = driver.readState();
    const auto& timing = MotionExecutorTestAccess::timing(driver);
    require(!first.sampleCached && first.readTimestampMs > 0, "fresh sample semantics changed");
    require(first.axes[0].pulse == 100 && first.axes[6].pulse == 2, "card/axis mapping changed");
    for (int card = 0; card < 2; ++card) {
      const auto& calls = timing.cards[card].readCalls;
      require(calls[0].count == 6 && calls[2].count == 6, "each card must count 6 position/done reads");
      require(calls[1].count == (card == 1 ? 6 : 0), "unreadable servo feedback must not call SDK");
      require(calls[0].totalNs >= 300000 && calls[0].maxNs >= 50000, "per-call duration was lost");
      require(timing.cards[card].scan.totalNs >= calls[0].totalNs + calls[1].totalNs + calls[2].totalNs,
          "card scan must contain all of its SDK calls");
    }
    require(timing.fullRead.totalNs >= timing.cards[0].scan.totalNs + timing.cards[1].scan.totalNs,
        "full read must contain both cards");
    {
      auto lock = MotionExecutorTestAccess::hold(driver);
      auto read = std::async(std::launch::async, [&]() { return driver.readState(); });
      const bool ready = read.wait_for(100ms) == std::future_status::ready;
      // 即使发生阻塞回归，也先解锁，确保测试能够报告失败而非卡住。
      lock.unlock();
      const auto cached = read.get();
      require(ready, "contended read blocked behind the command mutex");
      require(cached.sampleCached && cached.readTimestampMs == first.readTimestampMs,
          "contended read must retain the real read timestamp");
    }
    require(timing.busyReturns == 1 && timing.readAttempt.count == 2 && timing.fullRead.count == 1,
        "cached read was incorrectly counted as a controller scan");
    const auto json = driver.timingJson();
    require(json.find("\"busyReturns\":1") != std::string::npos
        && json.find("\"dmc_get_position\":{\"count\":6") != std::string::npos,
        "read-only diagnostics omitted measured counters");
    require(timing.fullRead.count == 1 && !driver.estopActive(), "diagnostic query changed driver state");
    dmcReadSevonPin = nullptr;
    driver.readState();
    require(timing.fullRead.count == 2 && timing.cards[1].readCalls[1].count == 6,
        "missing optional export was counted as a call");
    std::cout << "MotionReadTimingTests passed (per-card calls, durations, contention, timestamps, query)\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
