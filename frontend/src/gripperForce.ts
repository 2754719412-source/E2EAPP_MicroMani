/*
 * 阅读导航 02｜前端契约与状态
 * 职责：Jodell 夹爪力感知的显示逻辑：gOBJ/状态文字、标定是否匹配当前接线、由稳态 gCU 估算夹持力、读数健康度。
 * 先看：gripperObjectState → matchingCalibration → estimateHoldForceN → gripperSenseHealth。
 * 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。
 */
import type { AppConfig, GripperFeedbackSample, GripperForceCalibration, GripperSideStatus } from './types'

export type HardwareSide = 'left' | 'right'
export type GripperObjectState = 'moving' | 'contact_opening' | 'contact_closing' | 'arrived' | 'idle' | 'unknown'

/** 手册 6.3.1：gOBJ 只在 gGTO=1 时有效；gGTO=0 时只说明手指不在执行到位命令。 */
export function gripperObjectState(sample: GripperFeedbackSample | null | undefined): GripperObjectState {
  if (!sample || !sample.statusValid) return 'unknown'
  if (sample.gGTO !== 1) return 'idle'
  if (sample.gOBJ === 0) return 'moving'
  if (sample.gOBJ === 1) return 'contact_opening'
  if (sample.gOBJ === 2) return 'contact_closing'
  return 'arrived'
}

export const gripperObjectLabels: Record<GripperObjectState, string> = {
  moving: '运动中',
  contact_opening: '张开时碰到物体',
  contact_closing: '闭合时夹到物体',
  arrived: '到位，未检测到物体',
  // gGTO=0 时 gOBJ 无效，只显示空闲。
  idle: '空闲',
  unknown: '状态未知',
}

export function gripperObjectTone(state: GripperObjectState): 'ok' | 'warn' | 'neutral' {
  if (state === 'contact_closing' || state === 'contact_opening') return 'warn'
  if (state === 'unknown') return 'neutral'
  return 'ok'
}

/** 标定只对记录时的端口/从站有效，换线或换夹爪后不得沿用（与 backend/core/gripper_force.py 一致）。 */
export function matchingCalibration(config: AppConfig, side: HardwareSide): GripperForceCalibration | null {
  const gripper = config.gripper
  const calibration = gripper.forceCalibration?.[side] ?? null
  if (!calibration || calibration.version !== 1 || !(calibration.rfcToForceN?.slope > 0)) return null
  const port = side === 'left' ? gripper.leftPort : gripper.rightPort
  const slaveId = side === 'left' ? gripper.leftSlaveId : gripper.rightSlaveId
  if (String(calibration.port).toUpperCase() !== String(port).toUpperCase()) return null
  if (Number(calibration.slaveId) !== Number(slaveId)) return null
  return calibration
}

/** 读数电流是否越过标定得到的空载阈值；未标定时返回 null（不判电流大小）。 */
export function currentAboveIdle(sample: GripperFeedbackSample | null | undefined, calibration: GripperForceCalibration | null) {
  if (!sample?.currentValid || !calibration) return null
  return sample.currentRaw > calibration.baseline.contactThresholdRaw
}

/**
 * 稳态夹持时由 gCU 估算夹持力：先按 gCU = a·rFC + b 反推等效 rFC，再按 N = c·rFC + d 换算。
 * 只在已接触（gOBJ 报告接触或电流越过空载阈值）且有匹配标定时给出；结果限制在标定的力范围内。
 */
export function estimateHoldForceN(
  sample: GripperFeedbackSample | null | undefined,
  calibration: GripperForceCalibration | null,
): number | null {
  if (!sample?.currentValid || !calibration) return null
  const contact = gripperObjectState(sample) === 'contact_closing' || currentAboveIdle(sample, calibration) === true
  if (!contact) return null
  const hold = calibration.holdCurrentRaw
  if (!(Math.abs(hold.slope) > 1e-9)) return null
  const fit = calibration.rfcToForceN
  const rfc = Math.min(Math.max((sample.currentRaw - hold.intercept) / hold.slope, fit.rfcMin), fit.rfcMax)
  const force = fit.slope * rfc + fit.intercept
  return Number.isFinite(force) ? Math.max(0, force) : null
}

export function gapMmFromRaw(positionRaw: number, strokeMm: number) {
  return strokeMm * (1 - Math.min(Math.max(positionRaw, 0), 255) / 255)
}

export type GripperSenseHealth = 'ok' | 'warn' | 'error' | 'pending'

/** 读数健康度：无结构化读数为待确认；故障或读数无效为异常；电流不可用（DLL 只读位置）为警告。 */
export function gripperSenseHealth(sideStatus: GripperSideStatus | undefined): GripperSenseHealth {
  const sample = sideStatus?.sample
  if (!sample) return 'pending'
  if (sample.fault) return 'error'
  if (!sample.positionValid) return 'error'
  if (!sample.currentValid || !sample.statusValid) return 'warn'
  return 'ok'
}

export function transportLabel(transport: string | undefined) {
  if (transport === 'modbus') return 'Modbus 直连'
  if (transport === 'dll') return 'Vendor DLL'
  return '未知'
}
