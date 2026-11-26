#pragma once

#include <array>

namespace appstation::hal {

inline constexpr const char* kHalVersion = "hal-real/0.2";
// 双侧 Tare 稳定性/残差验证、校准状态和 ACK 门控由 ForceControlRuntime 实现。
// ControlLeaseState 与 DDS 紧急通道实现后端续租及执行侧失效保护。
inline constexpr std::array<const char*, 9> kHalCapabilities{{"force_calibration_state_v1", "control_lease_v1", "replay_absolute_target_v1", "record_participation_v1", "record_start_hold_v1", "policy_gripper_feedback_v1", "work_origin_instance_guard_v1", "home_preserve_counts_v1", "replay_controlled_stop_v1"}};

}  // namespace appstation::hal
