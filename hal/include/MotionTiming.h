#pragma once
#include <array>
#include <atomic>
#include <chrono>
#include <cstdint>
#include <ostream>

namespace appstation::hal {
// 累计计时只写原子计数，不在读卡/持锁线程格式化或输出日志。
// 读取端取两个时间点的差得到窗口均值；跨字段读取不是事务快照。
struct MotionTimingCounter {
  std::atomic_uint64_t count{0}, totalNs{0}, maxNs{0};
  void add(std::chrono::steady_clock::duration duration) noexcept {
    const auto ns = static_cast<std::uint64_t>(
        std::chrono::duration_cast<std::chrono::nanoseconds>(duration).count());
    totalNs.fetch_add(ns, std::memory_order_relaxed);
    auto previous = maxNs.load(std::memory_order_relaxed);
    while (previous < ns && !maxNs.compare_exchange_weak(previous, ns, std::memory_order_relaxed)) {}
    count.fetch_add(1, std::memory_order_relaxed);
  }
  void json(std::ostream& out) const {
    out << "{\"count\":" << count.load(std::memory_order_relaxed)
        << ",\"totalNs\":" << totalNs.load(std::memory_order_relaxed)
        << ",\"maxNs\":" << maxNs.load(std::memory_order_relaxed) << "}";
  }
};

class MotionTimingScope {
 public:
  explicit MotionTimingScope(MotionTimingCounter& counter)
      : counter_(counter), started_(std::chrono::steady_clock::now()) {}
  ~MotionTimingScope() { counter_.add(std::chrono::steady_clock::now() - started_); }
  MotionTimingScope(const MotionTimingScope&) = delete;
  MotionTimingScope& operator=(const MotionTimingScope&) = delete;
 private:
  MotionTimingCounter& counter_;
  std::chrono::steady_clock::time_point started_;
};

struct MotionTiming {
  MotionTimingCounter pollWork, pollWait, busyPollWait, readAttempt, fullRead;
  std::atomic_uint64_t busyReturns{0};
  struct Card {
    MotionTimingCounter scan, teleopHold;
    // 顺序：位置、使能反馈、运动完成、IO、停止原因。
    // 后两项仅遥操作读取，普通 fullRead 不调用。
    std::array<MotionTimingCounter, 3> readCalls;
    std::array<MotionTimingCounter, 5> teleopReadCalls;
  };
  std::array<Card, 2> cards;
};
}
