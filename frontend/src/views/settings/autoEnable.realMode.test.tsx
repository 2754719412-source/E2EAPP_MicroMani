import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as api from '../../api'
import { defaultConfig } from '../../data'
import { initialControlLease } from '../../stores/controlLease'
import { initialMotionCommand } from '../../stores/motionCommands'
import { useTelemetryStore } from '../../stores/telemetry'
import type { TelemetryFrame } from '../../types'
import { initialControlSafety } from '../../utils/controlSafety'
import { ManualArmControl } from './ManualControlPanel'
import { TeleopHandCard } from './TeleopHandCard'

// 真实模式组件测试：使能走真实的命令通道与遥测确认，不替换 ensureMotionEnabled。
const apiMode = vi.hoisted(() => ({ mock: false }))
vi.mock('../../api', async (importOriginal) => ({
  ...await importOriginal<typeof import('../../api')>(),
  get mockMode() { return apiMode.mock },
}))

class MockWebSocket {
  static OPEN = 1
  static current: MockWebSocket
  readyState = 1
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: (() => void) | null = null
  onclose: ((event: CloseEvent) => void) | null = null
  constructor() { MockWebSocket.current = this }
  send() {}
  close() { this.readyState = 3; this.onclose?.({ code: 1000 } as CloseEvent) }
  message(type: string, data: unknown) { this.onmessage?.({ data: JSON.stringify({ type, data }) } as MessageEvent) }
}

const initialState = useTelemetryStore.getState()
const initialFrame = structuredClone(initialState.frame)
let timestamp = 0
const sideAxes = (left: boolean, right: boolean) => ({ left: Array<boolean>(6).fill(left), right: Array<boolean>(6).fill(right) })

async function emit(patch: Partial<TelemetryFrame> = {}) {
  await act(async () => {
    MockWebSocket.current.message('telemetry', {
      ...useTelemetryStore.getState().frame, timestamp: ++timestamp, halOk: true, wsOk: true,
      motionAxisEnabled: sideAxes(false, false),
      forceStatus: { safety: { latched: false, canAcknowledge: true } },
      teleopHands: initialFrame.teleopHands.map((hand) => ({ ...hand, physicalConnected: true })),
      ...patch,
    })
    await vi.advanceTimersByTimeAsync(100)
  })
}

async function liveBackend() {
  await act(async () => {
    useTelemetryStore.getState().startBackend()
    await vi.advanceTimersByTimeAsync(0)
    MockWebSocket.current.onopen?.()
    MockWebSocket.current.message('control_lease', { sessionId: 'auto-enable-ui', status: 'active', renewalOwner: 'backend' })
  })
  await emit()
}

beforeEach(() => {
  apiMode.mock = false
  vi.useFakeTimers()
  vi.setSystemTime(200_000)
  timestamp = Date.now()
  window.sessionStorage.clear()
  vi.stubGlobal('WebSocket', MockWebSocket)
  vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(new Response('{}', { status: 503 }))))
  const config = structuredClone(defaultConfig)
  config.motion.origin = { ...config.motion.origin, valid: true, leftValid: true, rightValid: true }
  useTelemetryStore.setState({
    ...initialState,
    config,
    frame: { ...structuredClone(initialFrame), timestamp },
    logs: [],
    motionCommand: { left: initialMotionCommand(), right: initialMotionCommand() },
    motionEnableOnlyAfterEmergency: { left: false, right: false },
    controlSafety: initialControlSafety(),
    controlLease: initialControlLease(true),
    telemetryLink: { state: 'connecting', lastFrameReceivedAt: null },
  }, true)
})

afterEach(() => {
  cleanup()
  useTelemetryStore.getState().stopBackend()
  useTelemetryStore.setState(initialState, true)
  vi.clearAllTimers()
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  window.sessionStorage.clear()
})

function renderTeleopCard() {
  const injectLog = vi.fn()
  const updateConfig = vi.fn()
  const state = useTelemetryStore.getState()
  render(<TeleopHandCard
    side="left" config={state.config} frame={state.frame} focusHash=""
    updateConfig={updateConfig} injectLog={injectLog}
    pendingReturnOriginSide={null} setPendingReturnOriginSide={vi.fn().mockReturnValue(true)}
  />)
  return { injectLog, updateConfig }
}

describe('真实模式：连接主手前随动使能', () => {
  it('先使能目标硬件臂，遥测确认后才发连接', async () => {
    const enable = vi.spyOn(api, 'enableMotionSide').mockResolvedValue({ ok: true })
    const connect = vi.spyOn(api, 'connectTeleopHand').mockResolvedValue({ data: { connected: true } })
    await liveBackend()
    const { updateConfig } = renderTeleopCard()
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '连接主手' })) })

    // 默认交换通道：操作者左主手驱动硬件右臂。
    expect(enable).toHaveBeenCalledExactlyOnceWith('right')
    expect(connect).not.toHaveBeenCalled()
    await emit({ motionAxisEnabled: sideAxes(false, true) })
    expect(connect).toHaveBeenCalledExactlyOnceWith('left')
    expect(updateConfig).toHaveBeenCalled()
  })

  it('3 秒内未获使能确认则不连接，按钮恢复可用', async () => {
    vi.spyOn(api, 'enableMotionSide').mockResolvedValue({ ok: true })
    const connect = vi.spyOn(api, 'connectTeleopHand').mockResolvedValue({ data: { connected: true } })
    await liveBackend()
    const { injectLog } = renderTeleopCard()
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: '连接主手' })) })
    for (let i = 0; i < 35; i++) await emit()
    await emit({ motionAxisEnabled: sideAxes(false, true) })

    expect(connect).not.toHaveBeenCalled()
    expect(injectLog).toHaveBeenCalledWith('WARNING', expect.stringMatching(/主手连接未发送：.*3 秒内/), '[HAL]')
    expect(screen.getByRole('button', { name: '连接主手' })).toBeEnabled()
  })
})

describe('真实模式：手动卡点动提示', () => {
  function renderManualCard() {
    const state = useTelemetryStore.getState()
    render(<ManualArmControl
      side="right" positions={state.frame.jointPositions} config={state.config} manualControl={state.manualControl}
      nowMs={Date.now()} selectManualAxis={vi.fn()} setManualAxisStep={vi.fn()} setManualSpeedMode={vi.fn()}
      issueManualAxisMove={vi.fn()} triggerEmergencyStop={vi.fn()} injectLog={vi.fn()}
    />)
  }

  it('急停后首次点击只使能时，点动提示如实说明', async () => {
    await liveBackend()
    await act(async () => { useTelemetryStore.setState({ motionEnableOnlyAfterEmergency: { left: true, right: false } }) })
    // 操作者右臂对应硬件左臂。
    renderManualCard()
    const jog = screen.getByRole('button', { name: /^\+/ })
    expect(jog).toBeEnabled()
    expect(jog).toHaveAttribute('title', '急停后首次点击只完成使能，确认后再次点击执行点动')
    await act(async () => { useTelemetryStore.setState({ motionEnableOnlyAfterEmergency: { left: false, right: false } }) })
    expect(jog).toHaveAttribute('title', '未使能：点击后先自动使能本侧，确认后执行点动')
    expect(screen.getByRole('button', { name: '断使能' })).toBeEnabled()
  })
})
