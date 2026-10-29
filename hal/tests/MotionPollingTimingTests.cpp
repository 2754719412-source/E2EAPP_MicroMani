// 只注入轮询回调，不初始化 SDK 或设备；比较实际线程的唤醒间隔。
#include "MotionControlThread.h"
#include <algorithm>
#include <iostream>
#include <stdexcept>
#include <vector>

using namespace appstation::hal;
using Clock = std::chrono::steady_clock;
using namespace std::chrono_literals;

void exercise(std::chrono::microseconds work) {
  LTDMCDriver driver;
  std::vector<double> intervals;
  intervals.reserve(100);
  std::atomic_int samples{0};
  auto previous = Clock::now();
  MotionControlThread polling(driver, {}, [&]() {
    const auto now = Clock::now();
    if (samples.load() > 0 && intervals.size() < 100)
      intervals.push_back(std::chrono::duration<double, std::milli>(now - previous).count());
    previous = now;
    while (Clock::now() < now + work) std::this_thread::yield();
    samples.fetch_add(1);
  });
  polling.start(1000);
  const auto deadline = Clock::now() + 4s;
  while (samples.load() < 101 && Clock::now() < deadline) std::this_thread::sleep_for(10ms);
  polling.stop();
  if (intervals.size() != 100) throw std::runtime_error("polling did not finish 100 intervals");
  std::sort(intervals.begin(), intervals.end());
  std::cout << "work_us=" << work.count() << " p50_ms=" << intervals[50]
            << " p95_ms=" << intervals[95] << " max_ms=" << intervals.back() << '\n';
  if (intervals[50] >= (work == 0us ? 5.0 : 10.0))
    throw std::runtime_error("motion polling still waits on the coarse Windows sleep tick");
  if (work > 0us && intervals.front() < 3.0)
    throw std::runtime_error("overloaded polling lost its 1 ms opportunity for command threads");
  const auto count = samples.load();
  std::this_thread::sleep_for(20ms);
  if (samples.load() != count || polling.running())
    throw std::runtime_error("polling continued after stop");
}

int main() {
  try {
    exercise(0us);
    exercise(2000us);
    std::cout << "MotionPollingTimingTests passed (idle, overload, stop)\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
