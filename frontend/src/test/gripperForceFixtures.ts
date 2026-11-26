// 夹爪力感知测试夹具：HAL 结构化读数与夹持力标定（硬件侧）。
import type { GripperFeedbackSample, GripperForceCalibration } from '../types'

export function sampleOf(patch: Partial<GripperFeedbackSample> = {}): GripperFeedbackSample {
  return {
    seq: 1, monotonicUs: 1, timestampSource: 'worker', transport: 'modbus',
    positionValid: true, statusValid: true, currentValid: true,
    positionRaw: 0, currentRaw: 3, gACT: 1, gGTO: 0, gSTA: 3, gOBJ: 3, fault: 0, ...patch,
  }
}

export function calibrationOf(patch: Partial<GripperForceCalibration> = {}): GripperForceCalibration {
  return {
    version: 1, port: 'COM8', slaveId: 10, reference: 'unit',
    baseline: { currentMeanRaw: 3, currentStdRaw: 1, currentMaxRaw: 5, contactThresholdRaw: 10 },
    rfcToForceN: { slope: 0.02, intercept: 1.5, rmsResidualN: 0.02, hysteresisN: 0.05, rfcMin: 40, rfcMax: 200 },
    holdCurrentRaw: { slope: 1, intercept: 0 },
    ...patch,
  }
}
