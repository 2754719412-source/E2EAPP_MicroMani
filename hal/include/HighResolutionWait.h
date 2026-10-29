#pragma once
#include <chrono>
#include <stdexcept>
#include <thread>
#ifdef _WIN32
#include <windows.h>
#endif

namespace appstation::hal {
// 句柄只属于调用线程；不改变进程或系统的定时器精度。
class HighResolutionWait {
 public:
  HighResolutionWait() {
#ifdef _WIN32
    // CREATE_WAITABLE_TIMER_HIGH_RESOLUTION；兼容项目的 Windows 7 头文件目标。
    timer_ = CreateWaitableTimerExW(nullptr, nullptr, 0x00000002, TIMER_ALL_ACCESS);
    if (!timer_) throw std::runtime_error("cannot create high-resolution wait timer");
#endif
  }
  ~HighResolutionWait() {
#ifdef _WIN32
    CloseHandle(timer_);
#endif
  }
  HighResolutionWait(const HighResolutionWait&) = delete;
  HighResolutionWait& operator=(const HighResolutionWait&) = delete;
  void until(std::chrono::steady_clock::time_point deadline) {
#ifdef _WIN32
    // 使用相对单调时间；每次等待后复查，不能提前进入下一轮。
    for (;;) {
      const auto remaining = deadline - std::chrono::steady_clock::now();
      if (remaining <= decltype(remaining)::zero()) return;
      LARGE_INTEGER due;
      due.QuadPart = -(std::chrono::duration_cast<std::chrono::nanoseconds>(remaining).count() + 99) / 100;
      if (!SetWaitableTimer(timer_, &due, 0, nullptr, nullptr, FALSE)
          || WaitForSingleObject(timer_, INFINITE) != WAIT_OBJECT_0)
        throw std::runtime_error("high-resolution timer wait failed");
    }
#else
    std::this_thread::sleep_until(deadline);
#endif
  }
 private:
#ifdef _WIN32
  HANDLE timer_{};
#endif
};
}
