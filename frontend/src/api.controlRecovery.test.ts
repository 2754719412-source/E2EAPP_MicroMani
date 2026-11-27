import { afterEach, expect, it, vi } from 'vitest'
import { motionSideReturnOriginReady } from './motionReturnReady'

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules() })

it('配置保存将 HAL 拒绝方向标定的具体原因传给设置卡', async () => {
  vi.resetModules()
  vi.stubEnv('MODE', 'development')
  const detail = { code: 'HAL_REJECTED', message: 'force configuration requires all axes stopped and servos disabled' }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail }), { status: 409 })))
  const { putConfig } = await import('./api')
  const { defaultConfig } = await import('./data')
  await expect(putConfig(defaultConfig)).rejects.toThrow(detail.message)
})

it('请求超时结束等待但不撤销控制会话；Abort 不表示服务端动作已取消', async () => {
  vi.resetModules()
  vi.stubEnv('MODE', 'development')
  vi.useFakeTimers()
  const fetcher = vi.fn(() => new Promise<Response>(() => undefined))
  vi.stubGlobal('fetch', fetcher)
  const api = await import('./api')
  api.installControlSessionProvider(() => 'owner')
  const pending = api.enableMotionSide('left')
  const rejected = expect(pending).rejects.toThrow('执行结果未知')
  await vi.advanceTimersByTimeAsync(10_001)
  await rejected
  await expect(pending).rejects.toBeInstanceOf(api.CommandTimeoutError)
  expect(fetcher).toHaveBeenCalledOnce()
  const options = (fetcher.mock.calls[0] as unknown as [string, RequestInit])[1]
  expect(options.signal?.aborted).toBe(true)
  expect(options.headers).toMatchObject({ 'X-Control-Session': 'owner' })
})

it('两个页面的回原点请求在共享 API 边界互斥', async () => {
  vi.resetModules()
  vi.stubEnv('MODE', 'development')
  let finish!: (value: Response) => void
  const fetcher = vi.fn(() => new Promise<Response>((resolve) => { finish = resolve }))
  vi.stubGlobal('fetch', fetcher)
  const api = await import('./api')
  const first = api.returnMotionOriginSide('left')
  await expect(api.returnMotionOriginSide('right')).rejects.toThrow('已有回原点操作')
  expect(fetcher).toHaveBeenCalledOnce()
  finish(new Response(JSON.stringify({ ok: true })))
  await first
})

it('原点修改经过门闩，右侧 Yaw 未知不能以聚合使能代替', async () => {
  const api = await import('./api')
  api.installControlCommandGuard(() => '未确认控制租约')
  await expect(api.postCommand('/motion/origin/restore_previous')).rejects.toThrow('未确认控制租约')
  await expect(api.postCommand('/motion/left/origin/capture')).rejects.toThrow('未确认控制租约')
  expect(motionSideReturnOriginReady('right', { left: true, right: true }, {
    left: Array(6).fill(true), right: [true, true, true, true, true, null],
  })).toBe(false)
})

it('真机回放开始经过控制门闩，停止始终允许发送', async () => {
  vi.resetModules()
  vi.stubEnv('MODE', 'development')
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })))
  vi.stubGlobal('fetch', fetcher)
  const api = await import('./api')
  api.installControlCommandGuard(() => '未确认控制租约')
  await expect(api.postCommand('/api/datasets/local/episodes/episode_000001/replay/start', { confirmMotion: true })).rejects.toThrow('未确认控制租约')
  expect(fetcher).not.toHaveBeenCalled()
  await api.postCommand('/api/replay/stop', {})
  expect(fetcher).toHaveBeenCalledOnce()
})

it('策略 Dry-Run 可读取计划，真实发送必须经过控制门闩', async () => {
  vi.resetModules()
  vi.stubEnv('MODE', 'development')
  const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ ok: true })))
  vi.stubGlobal('fetch', fetcher)
  const api = await import('./api')
  api.installControlCommandGuard(() => '未确认控制租约')
  await api.postCommand('/api/policy/action', { action: Array(14).fill(0), dryRun: true })
  expect(fetcher).toHaveBeenCalledOnce()
  await expect(api.postCommand('/api/policy/action', { action: Array(14).fill(0), dryRun: false }))
    .rejects.toThrow('未确认控制租约')
  expect(fetcher).toHaveBeenCalledOnce()
})
