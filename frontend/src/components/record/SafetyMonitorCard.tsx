import { isForceVoltage, forceFeedbackLive, forceSampleReady, reportedForceDanger } from '../../forceDisplay'
import { useTelemetryStore } from '../../stores/telemetry'
import { UiCard, UiTag } from '../ui'

/** 锁存状态与危险指数使用遥测原值；每侧的力读数独立判断可用性。 */
export default function SafetyMonitorCard() {
  const live = useTelemetryStore(forceFeedbackLive)
  const danger = useTelemetryStore(reportedForceDanger)
  const status = useTelemetryStore((state) => state.frame.forceStatus)
  const requested = useTelemetryStore((state) => state.controlSafety.emergencyRequested)
  const voltage = useTelemetryStore((state) => isForceVoltage(state.config.force, state.frame.forceStatus))
  const left = useTelemetryStore((state) => state.frame.forceLeft[2])
  const right = useTelemetryStore((state) => state.frame.forceRight[2])
  const leftReady = live && forceSampleReady(status, 'left')
  const rightReady = live && forceSampleReady(status, 'right')
  const latched = status?.safety?.latched
  const latchLabel = latched ? (live ? '安全锁存' : '上次反馈已锁存')
    : requested ? '已请求急停，等待锁存反馈' : live && latched === false ? '未锁存' : '锁存状态未知'
  const unit = voltage ? 'V' : 'N'

  return (
    <UiCard title="力觉安全监控" extra={<UiTag tone={latched ? 'error' : requested ? 'warning' : 'muted'}>{latchLabel}</UiTag>}>
      <div className="record-safety-values">
        <span>遥测危险指数 <b>{danger?.toFixed(3) ?? '不可用'}</b></span>
        <span>左臂 Fz <b>{leftReady ? `${left.toFixed(voltage ? 3 : 2)} ${unit}` : '不可用'}</b></span>
        <span>右臂 Fz <b>{rightReady ? `${right.toFixed(voltage ? 3 : 2)} ${unit}` : '不可用'}</b></span>
      </div>
    </UiCard>
  )
}
