import { describe, expect, it } from 'vitest'
import { defaultConfig } from './data'
import {
  currentAboveIdle,
  estimateHoldForceN,
  gripperObjectState,
  gripperSenseHealth,
  matchingCalibration,
} from './gripperForce'
import { calibrationOf, sampleOf } from './test/gripperForceFixtures'
import type { AppConfig, GripperForceCalibration } from './types'

function configWith(calibration: GripperForceCalibration | null): AppConfig {
  const config = structuredClone(defaultConfig)
  config.gripper.forceCalibration = { applyCommandForceLimit: false, left: calibration, right: null }
  return config
}

describe('夹爪力感知显示逻辑', () => {
  it('gOBJ 只在 gGTO=1 时解读', () => {
    expect(gripperObjectState(sampleOf({ gGTO: 1, gOBJ: 2 }))).toBe('contact_closing')
    expect(gripperObjectState(sampleOf({ gGTO: 0, gOBJ: 2 }))).toBe('idle')
    expect(gripperObjectState(sampleOf({ statusValid: false }))).toBe('unknown')
    expect(gripperObjectState(null)).toBe('unknown')
  })

  it('标定只在端口和从站与当前接线一致时生效', () => {
    expect(matchingCalibration(configWith(calibrationOf()), 'left')).not.toBeNull()
    expect(matchingCalibration(configWith(calibrationOf({ port: 'COM3' })), 'left')).toBeNull()
    expect(matchingCalibration(configWith(calibrationOf({ slaveId: 9 })), 'left')).toBeNull()
    expect(matchingCalibration(configWith(null), 'left')).toBeNull()
  })

  it('只在接触时按标定估算夹持力，并限制在标定范围内', () => {
    const calibration = calibrationOf()
    expect(estimateHoldForceN(sampleOf({ currentRaw: 3 }), calibration)).toBeNull()
    expect(estimateHoldForceN(sampleOf({ currentRaw: 100 }), calibration)).toBeCloseTo(3.5)
    expect(estimateHoldForceN(sampleOf({ currentRaw: 254 }), calibration)).toBeCloseTo(0.02 * 200 + 1.5)
    expect(estimateHoldForceN(sampleOf({ currentRaw: 100 }), null)).toBeNull()
    expect(estimateHoldForceN(sampleOf({ currentRaw: 100, currentValid: false }), calibration)).toBeNull()
    expect(currentAboveIdle(sampleOf({ currentRaw: 11 }), calibration)).toBe(true)
    expect(currentAboveIdle(sampleOf({ currentRaw: 11 }), null)).toBeNull()
  })

  it('读数健康度区分无读数、故障与电流不可用', () => {
    expect(gripperSenseHealth(undefined)).toBe('pending')
    expect(gripperSenseHealth({ sample: sampleOf({ fault: 0x0b }) })).toBe('error')
    expect(gripperSenseHealth({ sample: sampleOf({ currentValid: false }) })).toBe('warn')
    expect(gripperSenseHealth({ sample: sampleOf() })).toBe('ok')
  })
})
