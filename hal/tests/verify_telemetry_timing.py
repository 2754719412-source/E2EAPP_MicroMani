"""在 MSVC 环境中验证 DDS 循环的虚拟/真实时钟安排；不连接设备或 DDS。"""
from pathlib import Path
import subprocess
import tempfile


def main():
    source = (Path(__file__).resolve().parents[1] / "src/HalDdsControlServer.cpp").read_text(encoding="utf-8")
    live_loop = "void telemetryLoop()" + source.split("void telemetryLoop()", 1)[1].split("void emergencyLoop()", 1)[0]
    loop = live_loop
    # 仅替换时间来源和等待，执行源码中的完整循环与发布分支。
    loop = loop.replace("std::chrono::steady_clock", "TestClock")
    loop = loop.replace("std::this_thread::sleep_until", "sleepUntil")
    loop = loop.replace("preciseSleepUntil", "sleepUntil")
    wait = "void preciseSleepUntil" + source.split("void preciseSleepUntil", 1)[1].split("std::uint64_t unixMs()", 1)[0]
    harness = r'''
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <thread>
#include <vector>
#include "HighResolutionWait.h"
using appstation::hal::HighResolutionWait;
#if defined(__x86_64__) || defined(_M_X64)
#include <immintrin.h>
#endif
''' + wait + r'''
using namespace std::chrono;
struct TestClock {
  using time_point = steady_clock::time_point;
  inline static time_point current{};
  static time_point now() { return current; }
};
struct Fixture {
  bool running = true;
  microseconds firstPublishCost{};
  microseconds sleepDelay{};
  bool stopInWait = false;
  std::vector<long long> forceTimes, telemetryTimes;
  long long nowUs() { return duration_cast<microseconds>(TestClock::now().time_since_epoch()).count(); }
  void publishForceState() {
    forceTimes.push_back(nowUs());
    if (forceTimes.size() == 1) TestClock::current += firstPublishCost;
  }
  void publishTelemetry() { telemetryTimes.push_back(nowUs()); }
  void sleepUntil(TestClock::time_point target) {
    TestClock::current = (std::max)(TestClock::current, target) + sleepDelay;
    sleepDelay = microseconds(0);
    if (stopInWait || nowUs() >= 40000) running = false;
  }
''' + loop + r'''
};
// 同时运行真实时钟下的源码循环，避免虚拟等待掩盖 Windows 唤醒误差。
struct LiveFixture {
  bool running = true;
  std::vector<steady_clock::time_point> forceTimes, telemetryTimes;
  void publishForceState() {
    forceTimes.push_back(steady_clock::now());
    if (forceTimes.size() == 200) running = false;
  }
  void publishTelemetry() { telemetryTimes.push_back(steady_clock::now()); }
''' + live_loop + r'''
};
void require(bool ok, const char* message) {
  if (!ok) throw std::runtime_error(message);
}
Fixture run(microseconds cost = microseconds(0), microseconds delay = microseconds(0), bool stop = false) {
  TestClock::current = {};
  Fixture fixture;
  fixture.firstPublishCost = cost;
  fixture.sleepDelay = delay;
  fixture.stopInWait = stop;
  fixture.telemetryLoop();
  return fixture;
}
int main() {
  try {
    const auto normal = run();
    require(normal.forceTimes == std::vector<long long>{0,5000,10000,15000,20000,25000,30000,35000},
        "force publication must follow the 5 ms grid");
    require(normal.telemetryTimes == std::vector<long long>{5000,15000,25000,35000},
        "ordinary telemetry must use every second force tick");
    const auto shortWork = run(microseconds(2000));
    require(shortWork.forceTimes == normal.forceTimes && shortWork.telemetryTimes == normal.telemetryTimes,
        "publication cost must not shift subsequent deadlines");
    const auto boundary = run(microseconds(5000));
    require(boundary.forceTimes == normal.forceTimes, "an exactly on-time tick must not be skipped");
    for (const auto cost : {5001, 6000, 16000}) {
      const auto overloaded = run(microseconds(cost));
      require(overloaded.forceTimes.at(1) == (cost / 5000 + 1) * 5000,
          "overload must resume at the next future tick without catch-up publication");
      for (const auto stamp : overloaded.telemetryTimes)
        require(stamp % 10000 == 5000, "skipped ticks must preserve the ordinary telemetry phase");
    }
    const auto lateWake = run(microseconds(0), microseconds(600));
    require(lateWake.forceTimes.at(2) == 10000, "one late wake must not accumulate schedule drift");
    const auto missedWake = run(microseconds(0), microseconds(5600));
    require(missedWake.telemetryTimes.front() == 15000,
        "waking more than one tick late must skip the expired telemetry slot");
    const auto stopped = run(microseconds(0), microseconds(0), true);
    require(stopped.forceTimes.size() == 1 && stopped.telemetryTimes.empty(),
        "stop during wait must prevent another publication");
    const auto deadline = steady_clock::now() + milliseconds(5);
    preciseSleepUntil(deadline);
    require(steady_clock::now() >= deadline, "hybrid wait must not return before its deadline");
    preciseSleepUntil(deadline - milliseconds(10));
    LiveFixture live;
    live.forceTimes.reserve(200);
    live.telemetryTimes.reserve(200);
    live.telemetryLoop();
    const auto rate = [](const auto& stamps) {
      return (stamps.size() - 1) / duration<double>(stamps.back() - stamps.front()).count();
    };
    std::cout << "real_clock_force_hz=" << rate(live.forceTimes)
              << " ordinary_hz=" << rate(live.telemetryTimes) << '\n';
    require(rate(live.forceTimes) > 150 && rate(live.telemetryTimes) > 75,
        "real telemetry wait is still limited by the coarse Windows timer");
    std::cout << "PASS: 200/100 Hz division, fixed deadlines, overload, phase, late wake, stop\n";
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
'''
    with tempfile.TemporaryDirectory(prefix="hal-telemetry-timing-") as directory:
        build = Path(directory)
        cpp = build / "TelemetryTimingTests.cpp"
        cpp.write_text(harness, encoding="utf-8")
        executable = build / "TelemetryTimingTests.exe"
        subprocess.run(["cl", "/nologo", "/utf-8", "/std:c++20", "/EHsc", "/O2", str(cpp),
                        "/I", str(Path(__file__).resolve().parents[1] / "include"),
                        f"/Fe{executable}"], cwd=build, check=True)
        subprocess.run([str(executable)], cwd=build, check=True)


if __name__ == "__main__":
    main()
