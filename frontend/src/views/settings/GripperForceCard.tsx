/*
 * Jodell 夹爪力感知卡：gCU 电流曲线、接触状态、夹持力设定与标定，以及 worker 读取方式和采样统计。
 * 先看：GripperForceCard → useCurrentHistory。
 */
import { Activity } from 'lucide-react'
import { useState } from 'react'
import { GripperCurrentChart, JodellOfficialChart } from '../../components/Charts'
import type { JodellCapture } from './useJodellCapture'
import { UiField, UiNumber, UiSelect, UiSwitch, UiTag, UiText } from '../../components/ui'
import { hardwareSideForOperatorSide, operatorSideLabel, type RobotSide } from '../../data'
import {
  currentAboveIdle,
  estimateHoldForceN,
  gapMmFromRaw,
  gripperObjectLabels,
  gripperObjectState,
  gripperObjectTone,
  gripperSenseHealth,
  matchingCalibration,
  transportLabel,
} from '../../gripperForce'
import type { AppConfig, GripperFeedbackSample, GripperStatus } from '../../types'
import { HardwareConfigCard, MetricBox } from './shared'

const HISTORY_LIMIT = 300

/** 按 seq 累积最近的有效电流读数；同一读数只记一次，seq 回退（HAL 重启）时清空。
 *  在渲染期间按新 seq 调整状态（React 推荐的“随 props 调整状态”写法），lastSeq 守卫避免重复更新。 */
function useCurrentHistory(sample: GripperFeedbackSample | null | undefined) {
  const [state, setState] = useState<{ points: { seq: number; value: number; position: number }[]; lastSeq?: number }>({ points: [] })
  const seq = sample?.seq
  const value = sample?.currentValid ? sample.currentRaw : null
  if (value === null && state.points.length) {
    setState({ points: [] })
  } else if (seq !== undefined && value !== null && seq !== state.lastSeq) {
    const base = state.lastSeq !== undefined && seq < state.lastSeq ? [] : state.points
    const position = sample?.positionValid ? sample.positionRaw : Number.NaN
    setState({ points: [...base, { seq, value, position }].slice(-HISTORY_LIMIT), lastSeq: seq })
  }
  return state.points
}

function faultText(fault: number | undefined) {
  if (fault === undefined || fault < 0) return '—'
  return fault === 0 ? '无' : `0x${fault.toString(16).toUpperCase().padStart(2, '0')}`
}

export function GripperForceCard({
  side,
  config,
  updateConfig,
  focusHash,
  gripperStatus,
  capture,
}: {
  side: RobotSide
  config: AppConfig
  updateConfig: (patch: Partial<AppConfig>) => void
  focusHash: string
  gripperStatus: GripperStatus | undefined
  capture?: JodellCapture | null
}) {
  const hardwareSide = hardwareSideForOperatorSide(side)
  const operatorLabel = operatorSideLabel(side)
  const sideStatus = gripperStatus?.sides?.[hardwareSide]
  const sample = sideStatus?.sample ?? null
  const port = hardwareSide === 'left' ? config.gripper.leftPort : config.gripper.rightPort
  const slaveId = hardwareSide === 'left' ? config.gripper.leftSlaveId : config.gripper.rightSlaveId
  const official = capture?.live && capture.port.toUpperCase() === port.toUpperCase() && capture.slaveId === slaveId
    && capture.samples.length > 0 && !sample?.currentValid ? capture : null
  const row = official?.samples[official.samples.length - 1]
  const stats = sideStatus?.sampleStats ?? null
  const command = gripperStatus?.command ?? null
  const calibration = matchingCalibration(config, hardwareSide)
  const storedCalibration = config.gripper.forceCalibration?.[hardwareSide] ?? null
  const history = useCurrentHistory(sample)
  const health = gripperSenseHealth(sideStatus)
  const objectState = gripperObjectState(sample)
  const aboveIdle = currentAboveIdle(sample, calibration)
  const holdForceN = estimateHoldForceN(sample, calibration)
  const transport = command?.transport ?? config.gripper.workerTransport ?? 'dll'
  const appliedRfc = command?.torque
  const expectedForceN = calibration && typeof appliedRfc === 'number'
    ? calibration.rfcToForceN.slope * appliedRfc + calibration.rfcToForceN.intercept
    : null
  const forceCalibration = config.gripper.forceCalibration ?? { applyCommandForceLimit: false, left: null, right: null }
  const enabledSides = (['left', 'right'] as const).filter((item) =>
    item === 'left' ? config.gripper.leftEnabled : config.gripper.rightEnabled)
  const allEnabledCalibrated = enabledSides.length > 0 && enabledSides.every((item) => matchingCalibration(config, item))
  const id = `force-gripper-${side}`

  return (
    <HardwareConfigCard
      id={id}
      focusHash={focusHash}
      icon={<Activity size={20} />}
      title={`${operatorLabel} Jodell 夹爪力感知`}
      subtitle={`${port} / ${slaveId} · ${official ? '钧舵工具采集' : transportLabel(transport)} · gCU 0–255`}
      state={official ? 'ok' : health}
      badges={<UiTag tone={calibration ? 'success' : 'warning'}>{calibration ? '已标定' : '未标定'}</UiTag>}
    >
      <div className="force-settings-layout">
        <div className="force-visual-area">
          {official ? <JodellOfficialChart rows={official.samples} /> : <GripperCurrentChart
            side={hardwareSide}
            values={history.map((item) => item.value)}
            positions={history.map((item) => item.position)}
            thresholdRaw={calibration?.baseline.contactThresholdRaw ?? null}
            height={170}
          />}
          <div className="force-current-grid force-current-grid-settings gripper-sense-grid" aria-label={`${operatorLabel}夹爪当前读数`}>
            <span>
              <b>gCU 电流原码</b>
              {row ? row[2] : sample?.currentValid ? sample.currentRaw : '不可用'}
            </span>
            {calibration && <span>
              <b>估算夹持力</b>
              {holdForceN !== null ? `${holdForceN.toFixed(2)} N` : '—'}
            </span>}
            <span>
              <b>{row ? '位置原码' : '开口'}</b>
              {row ? row[1] : sample?.positionValid ? `${gapMmFromRaw(sample.positionRaw, config.gripper.strokeMm).toFixed(2)} mm` : '—'}
            </span>
            {row ? <span><b>速度原码</b>{row[3]}</span> : <span className={`gripper-sense-object gripper-sense-object-${gripperObjectTone(objectState)}`}>
              <b>目标检测</b>
              {gripperObjectLabels[objectState]}
            </span>}
            <span>
              <b>空载阈值</b>
              {aboveIdle === null ? '未标定' : aboveIdle ? '已越过' : '未越过'}
            </span>
            <span>
              <b>故障码</b>
              {faultText(sample?.statusValid ? sample.fault : undefined)}
            </span>
          </div>
          <UiText secondary className="gripper-sense-note">
            {official && row
              ? `钧舵工具最新采样 ${row[0]} · ${official.file}`
              : transport === 'modbus'
              ? '绿色曲线是钧舵上位机的力矩反馈，取自 0x07D2 高字节。蓝色曲线是夹爪位置原码。'
              : 'Vendor DLL 遥操作只读位置，电流与目标检测不可用；切换到 Modbus 直连并完成现场验收后才有完整读数。'}
          </UiText>
        </div>
        <div className="force-settings-column">
          <div className="hardware-form-grid hardware-form-grid-compact ui-form">
            {/* 读取方式、频率和力限制换算是双侧共用的全局配置，两张卡显示同一值。 */}
            <UiField label="读取方式（双侧共用）">
              <UiSelect
                aria-label={`${operatorLabel}夹爪读取方式`}
                value={config.gripper.workerTransport ?? 'dll'}
                options={[
                  { value: 'dll', label: 'Vendor DLL（默认）' },
                  { value: 'modbus', label: 'Modbus（待验收）' },
                ]}
                onChange={(workerTransport) => updateConfig({ gripper: { ...config.gripper, workerTransport } })}
              />
            </UiField>
            <UiField label="读取频率 Hz（双侧共用）">
              <UiNumber
                aria-label={`${operatorLabel}夹爪读取频率`}
                min={1}
                max={200}
                value={config.gripper.sampleHz}
                onChange={(value) => updateConfig({ gripper: { ...config.gripper, sampleHz: Number(value ?? 30) } })}
              />
            </UiField>
            {calibration && <UiField label="命令力限制 N">
              <UiNumber disabled value={config.gripper.commandForceLimitN} />
            </UiField>}
            <UiField label="按标定换算力限制（双侧共用）">
              <UiSwitch
                aria-label="按标定换算力限制"
                checked={forceCalibration.applyCommandForceLimit}
                disabled={!allEnabledCalibrated && !forceCalibration.applyCommandForceLimit}
                checkedChildren="已启用"
                unCheckedChildren={allEnabledCalibrated ? '已关闭' : '等待标定'}
                onChange={(applyCommandForceLimit) => updateConfig({
                  gripper: { ...config.gripper, forceCalibration: { ...forceCalibration, applyCommandForceLimit } },
                })}
              />
            </UiField>
          </div>
          <div className="hardware-metric-grid">
            <MetricBox
              label="有效采样率"
              value={stats ? `${stats.effectiveHz.toFixed(1)} Hz` : '—'}
              hint={command?.sampleIntervalMs ? `设定间隔 ${command.sampleIntervalMs.toFixed(1)} ms` : undefined}
              tone={stats && stats.effectiveHz > 0 ? 'ok' : 'warn'}
            />
            <MetricBox
              label="最长断样"
              value={stats ? `${stats.maxGapMs.toFixed(1)} ms` : '—'}
              hint={stats ? `${stats.samples} 条读数` : undefined}
              tone={stats && command?.sampleIntervalMs && stats.maxGapMs > command.sampleIntervalMs * 4 ? 'warn' : 'neutral'}
            />
            <MetricBox
              label="夹持力设定"
              value={typeof appliedRfc === 'number' ? `rFC ${appliedRfc}` : '—'}
              hint={expectedForceN === null ? undefined : `约 ${expectedForceN.toFixed(2)} N`}
            />
            <MetricBox
              label="时间戳"
              value={sample?.timestampSource === 'hal_midpoint' ? 'HAL 中点' : sample ? 'worker' : '—'}
              hint={sample ? `seq ${sample.seq}` : '暂无结构化读数'}
              tone={sample?.timestampSource === 'hal_midpoint' ? 'warn' : 'neutral'}
            />
          </div>
          <details className="gripper-config-section">
            <summary>{operatorLabel}夹持力标定（硬件{hardwareSide === 'left' ? '左' : '右'} · {hardwareSide === 'left' ? config.gripper.leftPort : config.gripper.rightPort}）</summary>
            {calibration ? (
              <table className="ui-table" aria-label={`${operatorLabel}夹持力标定`}>
                <tbody>
                  <tr><th scope="row">rFC → N</th><td>{`N = ${calibration.rfcToForceN.slope.toFixed(5)}·rFC + ${calibration.rfcToForceN.intercept.toFixed(3)}`}</td></tr>
                  <tr><th scope="row">标定范围</th><td>{`rFC ${calibration.rfcToForceN.rfcMin}–${calibration.rfcToForceN.rfcMax}`}</td></tr>
                  <tr><th scope="row">残差 RMS / 回差</th><td>{`${calibration.rfcToForceN.rmsResidualN.toFixed(3)} N / ${(calibration.rfcToForceN.hysteresisN ?? 0).toFixed(3)} N`}</td></tr>
                  <tr><th scope="row">稳态 gCU</th><td>{`${calibration.holdCurrentRaw.slope.toFixed(3)}·rFC + ${calibration.holdCurrentRaw.intercept.toFixed(2)}`}</td></tr>
                  <tr><th scope="row">空载 gCU</th><td>{`均值 ${calibration.baseline.currentMeanRaw} · σ ${calibration.baseline.currentStdRaw} · 阈值 ${calibration.baseline.contactThresholdRaw}`}</td></tr>
                  <tr><th scope="row">参考测力计</th><td>{calibration.reference || '—'}</td></tr>
                </tbody>
              </table>
            ) : (
              <UiText secondary>
                {storedCalibration
                  ? `已有标定来自 ${storedCalibration.port} / slave ${storedCalibration.slaveId}，与当前接线不符，已停用。`
                  : '尚未标定：停机后按 docs/gripper-force-calibration.md 运行 scripts/calibrate_gripper_force.py。'}
              </UiText>
            )}
          </details>
        </div>
      </div>
    </HardwareConfigCard>
  )
}
