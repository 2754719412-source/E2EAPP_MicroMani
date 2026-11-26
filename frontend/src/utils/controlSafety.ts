import { hardwareChannelLabel, operatorSideForHardwareSide, operatorSideLabel } from '../data'
import { motionTelemetryIsLive } from '../stores/motionCommands'
import type { TelemetryFrame, TelemetryLinkStatus } from '../types'
import { controlLeaseBlockReason, type ControlLeaseState } from '../stores/controlLease'

export interface ControlSafetyState {
  generation: number
  emergencyRequested: boolean
  emergencyPending: boolean
  emergencyError: string | null
  acknowledging: boolean
  acknowledgeAfterFrame: number | null
}

export const initialControlSafety = (): ControlSafetyState => ({
  generation: 0, emergencyRequested: false, emergencyPending: false,
  emergencyError: null, acknowledging: false, acknowledgeAfterFrame: null,
})

interface SafetySnapshot {
  frame: TelemetryFrame
  telemetryLink: TelemetryLinkStatus
  controlSafety: ControlSafetyState
  controlLease: ControlLeaseState
}

/** 急停意图独立于显示数值；只能通过显式确认及后续安全反馈释放。 */
export function controlSafetyBlockReason(state: SafetySnapshot, requireLive = true): string | null {
  if (state.controlSafety.emergencyRequested || state.controlSafety.acknowledging) return '急停保护尚未确认解除'
  if (state.frame.forceStatus?.safety?.latched) return state.frame.forceStatus.safety.reason || '硬件安全联锁已锁存'
  const leaseReason = controlLeaseBlockReason(state.controlLease)
  if (leaseReason) return leaseReason
  if (requireLive && !motionTelemetryIsLive(state.frame, state.telemetryLink)) return '缺少新鲜的硬件遥测，禁止启动运动'
  return null
}

const acknowledgeMessages: Record<string, string> = {
  'startup force self-check is not complete': '请先完成启动力觉自检',
  'both sensors must remain healthy and below warning thresholds for 500 ms': '等待双侧力传感器连续 500 ms 健康且低于警告阈值',
  'force worker failed; reconfigure before acknowledgement': '力觉采集故障，请重新配置后再确认',
  'force emergency-stop callback failed; diagnose and reconfigure before acknowledgement': '力觉急停回调失败，请排查并重新配置后再确认',
}

function forceAcknowledgeReason(reason?: string): string {
  if (!reason) return '等待 HAL 确认力安全条件已满足'
  for (const side of ['left', 'right'] as const) {
    const label = `${operatorSideLabel(operatorSideForHardwareSide(side))}（${hardwareChannelLabel(side)}）`
    if (reason === `${side} force sensor is above warning threshold`) return `${label}力读数超出警告范围，请检查末端受力`
    if (reason === `${side} force sample is stale`) return `${label}力样本已过期`
    if (reason === `${side} force sensor is not healthy`) return `${label}力传感器状态异常`
  }
  return Object.hasOwn(acknowledgeMessages, reason) ? acknowledgeMessages[reason] : reason
}

export function acknowledgeControlSafetyBlockReason(state: SafetySnapshot): string | null {
  if (state.controlSafety.emergencyPending) return '等待急停发送完成'
  if (state.controlSafety.acknowledging) return '等待硬件返回安全态确认结果'
  const leaseReason = controlLeaseBlockReason(state.controlLease)
  if (leaseReason) return leaseReason
  if (!motionTelemetryIsLive(state.frame, state.telemetryLink)) return '等待新鲜的硬件遥测'
  const force = state.frame.forceStatus
  if ((force?.source === 'hkvl_serial' || force?.safety?.latched) && force.safety?.canAcknowledge !== true)
    return forceAcknowledgeReason(force.safety?.acknowledgeBlocker)
  // 无锁存时仍可请求 HAL 核验此前发送失败的本地急停意图。
  return force?.safety?.latched || state.controlSafety.emergencyRequested ? null : '当前没有待确认的急停'
}

export function canAcknowledgeControlSafety(state: SafetySnapshot): boolean {
  return acknowledgeControlSafetyBlockReason(state) === null
}

/** 无运动的 HKVL 自检允许已锁存，仍要求有效租约和新鲜反馈。 */
export function forceSelfCheckBlockReason(state: SafetySnapshot, requireLive = true): string | null {
  if (state.controlSafety.emergencyPending || state.controlSafety.acknowledging) return '等待当前安全操作完成'
  if (state.controlSafety.emergencyError) return '急停尚未确认，请先重新急停并检查反馈'
  const leaseReason = controlLeaseBlockReason(state.controlLease)
  if (leaseReason) return leaseReason
  if (requireLive && !motionTelemetryIsLive(state.frame, state.telemetryLink)) return '缺少新鲜的硬件遥测，无法执行自检'
  if (state.frame.recording) return '请先停止录制再执行力觉自检'
  return null
}
