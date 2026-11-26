import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it } from 'vitest'
import { useTelemetryStore } from '../../stores/telemetry'
import type { TelemetrySample } from '../../types'
import RecordTelemetryPanel from './RecordTelemetryPanel'
import SafetyMonitorCard from './SafetyMonitorCard'

const initial = useTelemetryStore.getState()
const sides = { left: { healthy: true }, right: { healthy: true } }

function sample(fx: number, voltage = false): TelemetrySample {
  return { time: 1, joints: Array(12).fill(0), forceLeft: [fx, 0, 0, 0, 0, 0], forceRight: [0, 0, 0, 0, 0, 0],
    danger: 0, queueLeft: 0, queueRight: 0, forceVoltage: voltage }
}

beforeEach(() => {
  useTelemetryStore.setState({
    telemetryLink: { state: 'live', lastFrameReceivedAt: Date.now() },
    frame: { ...initial.frame, wsOk: true, halOk: true, forceLeft: [1, 0, 5, 0.005, 0, 0], dangerIndex: 0.167,
      forceStatus: { source: 'hkvl_serial', sides, safety: { latched: false } } },
  })
})

afterEach(() => { cleanup(); useTelemetryStore.setState(initial, true) })

it('显示分通道单位，5 N 仅在达到配置阈值时着色，锁存采用遥测反馈', () => {
  const { container } = render(<><RecordTelemetryPanel /><SafetyMonitorCard /></>)
  const arm = container.querySelector('.record-arm-monitor')!
  expect(arm.querySelectorAll('.record-force-meter')[2]).toHaveTextContent('Fz · N+5.00')
  expect(arm.querySelectorAll('.record-force-meter')[2]).toHaveClass('record-force-meter-warn')
  expect(arm.querySelectorAll('.record-force-meter')[3]).toHaveTextContent('Mx · N·m+0.005')
  expect(screen.getByText('0.167')).toBeInTheDocument()
  expect(screen.getByText('未锁存')).toBeInTheDocument()
  act(() => useTelemetryStore.setState((state) => ({ frame: { ...state.frame,
    forceStatus: { ...state.frame.forceStatus, sides: { ...sides, left: { healthy: false } } } } })))
  expect(arm.querySelector('.record-force-meter b')).toHaveTextContent('—')
  expect(container.querySelector('.record-safety-values')).toHaveTextContent('遥测危险指数 不可用')
  expect(screen.getByText('0.00 N')).toBeInTheDocument()
})

it('采样单位优先于设置，切换单位和恢复连接后仅绘制连续有效样本', () => {
  useTelemetryStore.setState((state) => ({
    config: { ...state.config, force: { ...state.config.force, source: 'nidaq', calibrationEnabled: true } },
    frame: { ...state.frame, forceStatus: { source: 'nidaq', sampleVoltage: true, sides, safety: { latched: false } } },
    history: [sample(9), sample(1, true), { ...sample(2, true), forceHealthy: { left: false, right: true } }, sample(3, true)],
  }))
  const { container } = render(<><RecordTelemetryPanel /><SafetyMonitorCard /></>)
  const chart = container.querySelector('.record-force-chart [data-fx]')!
  expect(chart).toHaveAttribute('data-fx', '[3]')
  expect(container.querySelector('.record-force-meter')).toHaveTextContent('Fx · V+1.000')
  expect(container.querySelector('.record-force-meter-warn')).toBeNull()
  expect(container.querySelector('.record-safety-values')).toHaveTextContent('遥测危险指数 不可用')
  act(() => useTelemetryStore.setState((state) => ({ history: [...state.history, sample(0.002)],
    frame: { ...state.frame, forceStatus: { ...state.frame.forceStatus, sampleVoltage: false } } })))
  expect(chart).toHaveAttribute('data-fx', '[2]')
  expect(container.querySelector('.record-force-meter')).toHaveTextContent('Fx · N+1.00')
})
