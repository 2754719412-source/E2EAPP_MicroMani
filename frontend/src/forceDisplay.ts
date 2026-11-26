import type { AppConfig, ForceStatus, TelemetryFrame, TelemetryLinkStatus, TelemetrySample } from './types'
import { telemetryStaleAfterMs } from './hardwareStatus'

/** HKVL 输出物理量，NI-DAQ 关闭标定后保留电压。优先采用帧报告的数据源。 */
export function isForceVoltage(config: AppConfig['force'], status?: ForceStatus) {
  if ((status?.source ?? config.source) !== 'nidaq') return false
  return typeof status?.sampleVoltage === 'boolean' ? status.sampleVoltage : !config.calibrationEnabled
}

export function forceSampleReady(status: ForceStatus | undefined, side: 'left' | 'right') {
  return status?.sides?.[side]?.healthy === true && (status.source !== 'nidaq' || status.sampleVoltage !== null)
}

/** 力觉断流或切换量纲后，只绘制和导出本段连续样本。 */
export function recentForceHistory(history: TelemetrySample[], voltage: boolean, side: 'left' | 'right') {
  const lastBreak = history.findLastIndex((sample) => Boolean(sample.forceVoltage) !== voltage || sample.forceHealthy?.[side] === false)
  return lastBreak < 0 ? history : history.slice(lastBreak + 1)
}

export function formatForceReadout(value: number, axis: number, voltage: boolean) {
  return voltage ? value.toFixed(3) : (value * 1000).toFixed(axis < 3 ? 0 : 1)
}

export function forceChannelLimits(safety: AppConfig['safety'], axis: number) {
  if (axis < 2) return { warn: safety.fxyWarnN, stop: safety.fxyStopN }
  if (axis === 2) return { warn: safety.fzWarnN, stop: safety.fzStopN }
  return { warn: safety.momentWarnNm, stop: safety.momentStopNm }
}

export function forceChannelLevel(value: number, limits: ReturnType<typeof forceChannelLimits>) {
  if (!(limits.stop > limits.warn && limits.warn > 0) || !Number.isFinite(value)) return 'pending'
  if (Math.abs(value) >= limits.stop) return 'error'
  return Math.abs(value) >= limits.warn ? 'warn' : 'ok'
}

type ForceTelemetry = { frame: TelemetryFrame; telemetryLink: TelemetryLinkStatus }

export function forceFeedbackLive(state: ForceTelemetry) {
  const { frame, telemetryLink } = state
  return frame.halOk && frame.wsOk && telemetryLink.state === 'live' && telemetryLink.lastFrameReceivedAt !== null
    && Date.now() - telemetryLink.lastFrameReceivedAt <= telemetryStaleAfterMs
}

export function reportedForceDanger(state: ForceTelemetry & { config: AppConfig }) {
  const status = state.frame.forceStatus
  if (!forceFeedbackLive(state) || !forceSampleReady(status, 'left') || !forceSampleReady(status, 'right')
    || typeof status?.safety?.latched !== 'boolean' || isForceVoltage(state.config.force, status)) return null
  return Number.isFinite(state.frame.dangerIndex) ? state.frame.dangerIndex : null
}
