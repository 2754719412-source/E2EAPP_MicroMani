import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import * as api from '../api'
import { useTelemetryStore } from '../stores/telemetry'
import { acknowledgeControlSafetyBlockReason, canAcknowledgeControlSafety, initialControlSafety } from '../utils/controlSafety'
import { ForceStartupSelfCheck } from './ForceStartupSelfCheck'
import { GlobalEmergencyStopButton } from './GlobalEmergencyStopButton'

const initialState = useTelemetryStore.getState()
beforeEach(() => {
  useTelemetryStore.setState({
    controlSafety: { ...initialControlSafety(), emergencyRequested: true },
    controlLease: { required: false, status: 'active', sessionId: null, expiresAt: 0, reason: '' },
    telemetryLink: { state: 'live', lastFrameReceivedAt: Date.now() },
    frame: { ...initialState.frame, timestamp: Date.now(), recording: false, halOk: true, wsOk: true,
      forceStatus: { source: 'hkvl_serial', calibration: { state: 'waiting_sensors', progress: 0 }, safety: { latched: true, canAcknowledge: false, acknowledgeBlocker: '请先自检' } },
    },
  })
})
afterEach(() => { cleanup(); vi.restoreAllMocks(); useTelemetryStore.setState(initialState) })

it('锁存下先明确确认双侧卸载，再执行自检；请求成功不会自动 ACK', async () => {
  const run = vi.spyOn(api, 'runHkvlStartupSelfCheck').mockResolvedValue({ ok: true })
  const ack = vi.spyOn(api, 'acknowledgeSafety')
  render(<><ForceStartupSelfCheck /><GlobalEmergencyStopButton /></>)
  expect(screen.getByRole('button', { name: '确认安全态' })).toBeDisabled()
  fireEvent.click(screen.getByRole('button', { name: '双侧去皮自检' }))
  expect(run).not.toHaveBeenCalled()
  expect(screen.getByRole('button', { name: '开始双侧自检' })).toBeDisabled()
  fireEvent.click(screen.getByRole('checkbox', { name: '我已确认双侧传感器卸载并保持静止' }))
  await act(async () => fireEvent.click(screen.getByRole('button', { name: '开始双侧自检' })))
  expect(run).toHaveBeenCalledOnce()
  expect(ack).not.toHaveBeenCalled()
  expect(useTelemetryStore.getState().frame.forceStatus?.safety?.latched).toBe(true)
  expect(screen.getByRole('button', { name: '确认安全态' })).toBeDisabled()
  act(() => useTelemetryStore.setState((state) => ({ frame: { ...state.frame, forceStatus: {
    source: 'hkvl_serial', calibration: { state: 'ready_for_ack', progress: 100 }, safety: { latched: true, canAcknowledge: true },
  } } })))
  expect(screen.getByText('自检通过，待人工确认 · 100%')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: '确认安全态' })).toBeEnabled()
})

it('确认按钮直接显示 HAL 报告的操作者侧阻塞原因，条件满足后说明伺服状态', () => {
  useTelemetryStore.setState((state) => ({ frame: { ...state.frame, forceStatus: {
    source: 'hkvl_serial', safety: { latched: true, canAcknowledge: false, acknowledgeBlocker: 'left force sensor is above warning threshold' },
  } } }))
  render(<GlobalEmergencyStopButton />)
  const button = screen.getByRole('button', { name: '确认安全态' })
  expect(button).toHaveAccessibleDescription('右臂（硬件左侧通道）力读数超出警告范围，请检查末端受力')
  expect(button).toBeDisabled()
  act(() => useTelemetryStore.setState((state) => ({ frame: { ...state.frame, forceStatus: {
    source: 'hkvl_serial', safety: { latched: true, canAcknowledge: true },
  } } })))
  expect(button).toBeEnabled()
  expect(button).toHaveAccessibleDescription(/伺服保持断开/)
})

it.each([
  ['both sensors must remain healthy and below warning thresholds for 500 ms', '连续 500 ms'],
  ['right force sample is stale', '左臂（硬件右侧通道）力样本已过期'],
  ['startup force self-check is not complete', '请先完成启动力觉自检'],
  ['未识别的硬件诊断', '未识别的硬件诊断'],
])('按 HAL 反馈显示阻塞原因 %s', (blocker, message) => {
  const state = useTelemetryStore.getState()
  const snapshot = { ...state, frame: { ...state.frame, forceStatus: { ...state.frame.forceStatus,
    safety: { latched: true, canAcknowledge: false, acknowledgeBlocker: blocker },
  } } }
  expect(acknowledgeControlSafetyBlockReason(snapshot)).toContain(message)
  expect(canAcknowledgeControlSafety(snapshot)).toBe(false)
})

it('发送中、租约过期和陈旧遥测优先于力锁存提示，保留本地急停恢复路径', () => {
  const state = useTelemetryStore.getState()
  const pending = { ...state, controlSafety: { ...state.controlSafety, emergencyPending: true } }
  const stale = { ...state, telemetryLink: { ...state.telemetryLink, lastFrameReceivedAt: null } }
  const expired = { ...stale, controlLease: { ...state.controlLease, required: true, status: 'expired' as const, reason: '租约过期' } }
  for (const [snapshot, reason] of [[pending, '急停发送'], [expired, '租约过期'], [stale, '新鲜']] as const) {
    expect(canAcknowledgeControlSafety(snapshot)).toBe(false)
    expect(acknowledgeControlSafetyBlockReason(snapshot)).toContain(reason)
  }
  const clear = { ...state, frame: { ...state.frame, forceStatus: undefined } }
  expect(canAcknowledgeControlSafety(clear)).toBe(true)
  expect(canAcknowledgeControlSafety({ ...clear, controlSafety: initialControlSafety() })).toBe(false)
})

it('取消卸载确认不发送命令，失败原因由 HAL 遥测显示', () => {
  const run = vi.spyOn(api, 'runHkvlStartupSelfCheck')
  useTelemetryStore.setState((state) => ({ frame: { ...state.frame, forceStatus: {
    ...state.frame.forceStatus, calibration: { state: 'failed', progress: 30, reason: 'left sensor is unstable' },
  } } }))
  render(<ForceStartupSelfCheck />)
  expect(screen.getByText('left sensor is unstable')).toBeInTheDocument()
  fireEvent.click(screen.getByRole('button', { name: '双侧去皮自检' }))
  fireEvent.click(screen.getByRole('button', { name: '取消' }))
  expect(run).not.toHaveBeenCalled()
})

it('控制租约过期仍阻止锁存期间自检', () => {
  useTelemetryStore.setState({ controlLease: { required: true, status: 'expired', sessionId: 'old', expiresAt: 0, reason: '租约过期' } })
  render(<ForceStartupSelfCheck />)
  expect(screen.getByRole('button', { name: '双侧去皮自检' })).toBeDisabled()
})
