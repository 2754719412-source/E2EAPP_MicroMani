import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import type { TelemetryFrame } from '../types'

// 真实模式（HTTP 与 WS 均为离线替身）：验证点动前随动使能只在遥测确认后放行一次位移。
let store: typeof import('./telemetry').useTelemetryStore
let time = 0
type FetchStub = (url: string, init?: RequestInit) => Promise<Response>
let fetchSpy: Mock<FetchStub>
let enableResponse: () => Promise<Response>

class Socket {
  static OPEN = 1
  static instances: Socket[] = []
  readyState = 1
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: ((event: { code: number }) => void) | null = null
  send = vi.fn()
  close = vi.fn(() => { this.readyState = 3; this.onclose?.({ code: 1000 }) })
  url?: string
  constructor(url?: string) { this.url = url; Socket.instances.push(this) }
  emit(type: string, data: unknown) { this.onmessage?.({ data: JSON.stringify({ type, data }) }) }
}

const ok = () => Promise.resolve(new Response(JSON.stringify({ ok: true, data: {} }), { status: 200 }))
const axes = (value: boolean) => ({ left: Array<boolean>(6).fill(value), right: Array<boolean>(6).fill(value) })

async function live(socket: Socket, patch: Partial<TelemetryFrame> = {}) {
  socket.emit('telemetry', { ...store.getState().frame, wsOk: true, halOk: true, timestamp: Date.now(),
    motionAxisEnabled: axes(false), forceStatus: { safety: { latched: false, canAcknowledge: true } }, ...patch })
  await vi.advanceTimersByTimeAsync(100)
}
const commands = () => fetchSpy.mock.calls.map(([url]) => new URL(String(url)).pathname).filter((path) => /\/api\/motion\//.test(path))
const warnings = () => store.getState().logs.filter((log) => log.level === 'WARNING').map((log) => log.msg)

const latched = (value: boolean) => ({ forceStatus: { safety: { latched: value, canAcknowledge: true } } })

/** 走真实路径：遥测锁存进入急停，安全确认后等到新的未锁存反馈解除，伺服保持断开。 */
async function emergencyThenAcknowledge(socket: Socket) {
  await live(socket, latched(true))
  expect(store.getState().controlSafety.emergencyRequested).toBe(true)
  store.getState().acknowledgeSafety()
  await vi.advanceTimersByTimeAsync(0)
  await live(socket, latched(false))
  await live(socket, latched(false))
  expect(store.getState().controlSafety.emergencyRequested).toBe(false)
}

async function connectedSocket() {
  store.getState().startBackend()
  const socket = Socket.instances.at(-1)!
  await live(socket)
  socket.emit('control_lease', { sessionId: 's1', status: 'active', renewalOwner: 'backend' })
  return socket
}

beforeEach(async () => {
  vi.resetModules()
  vi.useFakeTimers()
  vi.stubEnv('MODE', 'development')
  time = 0
  vi.spyOn(performance, 'now').mockImplementation(() => time)
  window.sessionStorage.clear()
  Socket.instances = []
  vi.stubGlobal('WebSocket', Socket)
  enableResponse = ok
  fetchSpy = vi.fn<FetchStub>((url) => {
    const path = new URL(String(url)).pathname
    if (path.endsWith('/enable_all')) return enableResponse()
    if (path === '/api/motion/manual_axis_move' || path.endsWith('/disable_all') || path.endsWith('/safety/acknowledge')) return ok()
    return Promise.resolve(new Response('{}', { status: 503 }))
  })
  vi.stubGlobal('fetch', fetchSpy)
  store = (await import('./telemetry')).useTelemetryStore
})

afterEach(() => {
  store.getState().stopBackend()
  vi.clearAllTimers(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllEnvs(); vi.unstubAllGlobals()
  window.sessionStorage.clear()
})

describe('点动前随动使能', () => {
  it('未使能时先发使能，遥测确认后只补发一次点动', async () => {
    const socket = await connectedSocket()
    store.getState().issueManualAxisMove('left', 'X', 1)
    store.getState().issueManualAxisMove('left', 'X', 1)
    await vi.advanceTimersByTimeAsync(0)
    expect(commands()).toEqual(['/api/motion/left/enable_all'])

    await live(socket)
    expect(commands()).toEqual(['/api/motion/left/enable_all'])
    await live(socket, { motionAxisEnabled: axes(true) })
    expect(commands()).toEqual(['/api/motion/left/enable_all', '/api/motion/manual_axis_move'])
    await vi.advanceTimersByTimeAsync(20_000)
    expect(commands()).toEqual(['/api/motion/left/enable_all', '/api/motion/manual_axis_move'])
  })

  it('已使能时直接点动，不重复发送使能', async () => {
    const socket = await connectedSocket()
    await live(socket, { motionAxisEnabled: axes(true) })
    await expect(store.getState().ensureMotionEnabled('left')).resolves.toBeNull()
    store.getState().issueManualAxisMove('left', 'X', 1)
    expect(commands()).toEqual(['/api/motion/manual_axis_move'])
  })

  it('后端拒绝使能时不发点动', async () => {
    enableResponse = () => Promise.resolve(new Response(JSON.stringify({ ok: false, message: 'driver fault' }), { status: 200 }))
    await connectedSocket()
    store.getState().issueManualAxisMove('left', 'X', 1)
    await vi.advanceTimersByTimeAsync(0)
    expect(commands()).toEqual(['/api/motion/left/enable_all'])
    expect(warnings().some((msg) => msg.includes('点动未发送') && msg.includes('driver fault'))).toBe(true)
  })

  it('等待确认期间安全锁存则撤销使能意图，不发点动', async () => {
    const socket = await connectedSocket()
    store.getState().issueManualAxisMove('left', 'X', 1)
    await vi.advanceTimersByTimeAsync(0)
    await live(socket, { forceStatus: { safety: { latched: true, canAcknowledge: false } } })
    await live(socket, { motionAxisEnabled: axes(true), forceStatus: { safety: { latched: true, canAcknowledge: false } } })
    expect(commands()).toEqual(['/api/motion/left/enable_all'])
    expect(warnings().some((msg) => msg.includes('点动未发送'))).toBe(true)
  })

  it('使能未在动作窗口内获确认时放弃点动，迟到的反馈也不补发', async () => {
    const socket = await connectedSocket()
    store.getState().issueManualAxisMove('left', 'X', 1)
    await vi.advanceTimersByTimeAsync(0)
    for (let i = 0; i < 60; i++) { time += 100; await live(socket) }
    await live(socket, { motionAxisEnabled: axes(true) })
    expect(commands()).toEqual(['/api/motion/left/enable_all'])
    expect(warnings().some((msg) => msg.includes('点动未发送') && msg.includes('3 秒内'))).toBe(true)
  })

  it('使能排在挂起的旧请求之后：超过动作窗口只保留使能，点动需重新点击', async () => {
    let finishDisable!: (response: Response) => void
    const base = fetchSpy.getMockImplementation()!
    fetchSpy.mockImplementation((url) => String(url).endsWith('/disable_all')
      ? new Promise<Response>((resolve) => { finishDisable = resolve })
      : base(url))
    const socket = await connectedSocket()
    store.getState().setMotionEnabled('left', false)
    await vi.advanceTimersByTimeAsync(0)
    store.getState().issueManualAxisMove('left', 'X', 1)
    for (let i = 0; i < 90; i++) { time += 100; await live(socket) }
    finishDisable(new Response(JSON.stringify({ ok: true }), { status: 200 }))
    await vi.advanceTimersByTimeAsync(0)
    await live(socket)
    await live(socket, { motionAxisEnabled: axes(true) })
    // 旧请求返回后排队的使能照常发出，但点击已过窗口，不在操作员离手后补发位移。
    expect(commands()).toEqual(['/api/motion/left/disable_all', '/api/motion/left/enable_all'])
    store.getState().issueManualAxisMove('left', 'X', 1)
    expect(commands().at(-1)).toBe('/api/motion/manual_axis_move')
  })

  it('补发点动沿用点击时的步长与速度档，等待期间修改不生效', async () => {
    const socket = await connectedSocket()
    store.getState().setManualAxisStep('um', 100)
    store.getState().setManualSpeedMode('fine')
    store.getState().issueManualAxisMove('left', 'X', 1)
    await vi.advanceTimersByTimeAsync(0)
    store.getState().setManualAxisStep('um', 4000)
    store.getState().setManualSpeedMode('coarse')
    await live(socket, { motionAxisEnabled: axes(true) })
    const call = fetchSpy.mock.calls.find(([url]) => String(url).endsWith('/api/motion/manual_axis_move'))
    expect(JSON.parse(String(call?.[1]?.body))).toMatchObject({ side: 'left', axis: 'X', step: 100, speedMode: 'fine' })
  })

  it('等待期间界面订阅抛错不会让该侧点动永久失效', async () => {
    const socket = await connectedSocket()
    const unsubscribe = store.subscribe(() => { throw new Error('显示故障') })
    expect(() => store.getState().issueManualAxisMove('left', 'X', 1)).toThrow('显示故障')
    unsubscribe()
    await vi.advanceTimersByTimeAsync(5_000)
    await live(socket)
    store.getState().issueManualAxisMove('left', 'X', 1)
    await vi.advanceTimersByTimeAsync(0)
    await live(socket, { motionAxisEnabled: axes(true) })
    expect(commands().at(-1)).toBe('/api/motion/manual_axis_move')
  })

  it('真实锁存→确认解除后：首次点击只使能，再次点击才点动', async () => {
    const socket = await connectedSocket()
    await emergencyThenAcknowledge(socket)
    expect(store.getState().motionEnableOnlyAfterEmergency).toEqual({ left: true, right: true })

    store.getState().issueManualAxisMove('left', 'X', 1)
    await vi.advanceTimersByTimeAsync(0)
    // 只有左侧获确认使能；右侧仍断开，其“首次只使能”要求保留。
    await live(socket, { motionAxisEnabled: { left: Array<boolean>(6).fill(true), right: Array<boolean>(6).fill(false) } })
    expect(commands().filter((path) => path !== '/api/motion/safety/acknowledge')).toEqual(['/api/motion/left/enable_all'])
    expect(store.getState().motionEnableOnlyAfterEmergency).toEqual({ left: false, right: true })

    store.getState().issueManualAxisMove('left', 'X', 1)
    expect(commands().at(-1)).toBe('/api/motion/manual_axis_move')
  })

  it('刷新页面后仍保留急停后“首次只使能”的要求', async () => {
    const socket = await connectedSocket()
    await emergencyThenAcknowledge(socket)
    store.getState().stopBackend()
    vi.resetModules()
    store = (await import('./telemetry')).useTelemetryStore
    expect(store.getState().controlSafety.emergencyRequested).toBe(false)
    expect(store.getState().motionEnableOnlyAfterEmergency).toEqual({ left: true, right: true })

    const reloaded = await connectedSocket()
    const before = commands().length
    store.getState().issueManualAxisMove('right', 'X', 1)
    await vi.advanceTimersByTimeAsync(0)
    await live(reloaded, { motionAxisEnabled: axes(true) })
    expect(commands().slice(before)).toEqual(['/api/motion/right/enable_all'])
  })

  it('等待使能确认期间点断使能：点动取消，迟到的使能反馈也不补发', async () => {
    const socket = await connectedSocket()
    store.getState().issueManualAxisMove('left', 'X', 1)
    await vi.advanceTimersByTimeAsync(0)
    store.getState().setMotionEnabled('left', false)
    await vi.advanceTimersByTimeAsync(0)
    await live(socket, { motionAxisEnabled: axes(true) })
    expect(commands()).toEqual(['/api/motion/left/enable_all', '/api/motion/left/disable_all'])
    expect(warnings().some((msg) => msg.includes('点动未发送'))).toBe(true)
  })

  it('急停后首次点击只完成使能，再次点击才点动；之后恢复一键操作', async () => {
    const socket = await connectedSocket()
    const { autoEnableEnableOnlyReason } = await import('./telemetry')
    store.setState((state) => ({ controlSafety: { ...state.controlSafety, generation: state.controlSafety.generation + 1, emergencyRequested: true } }))
    store.setState((state) => ({ controlSafety: { ...state.controlSafety, emergencyRequested: false } }))
    await live(socket)

    store.getState().issueManualAxisMove('left', 'X', 1)
    await vi.advanceTimersByTimeAsync(0)
    await live(socket, { motionAxisEnabled: axes(true) })
    expect(commands()).toEqual(['/api/motion/left/enable_all'])
    expect(warnings().some((msg) => msg.includes(autoEnableEnableOnlyReason))).toBe(true)

    store.getState().issueManualAxisMove('left', 'X', 1)
    expect(commands()).toEqual(['/api/motion/left/enable_all', '/api/motion/manual_axis_move'])

    // 该侧急停后已确认使能，之后断使能再点动恢复为一键使能并执行。
    await vi.advanceTimersByTimeAsync(5_000)
    await live(socket)
    store.getState().issueManualAxisMove('left', 'Y', 1)
    await vi.advanceTimersByTimeAsync(0)
    await live(socket, { motionAxisEnabled: axes(true) })
    expect(commands()).toEqual([
      '/api/motion/left/enable_all', '/api/motion/manual_axis_move',
      '/api/motion/left/enable_all', '/api/motion/manual_axis_move',
    ])
  })
})
