import { afterEach, expect, it, vi } from 'vitest'

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules() })

it('正限位参考超过十秒仍等待原请求，并拒绝重复定位', async () => {
  vi.resetModules(); vi.stubEnv('MODE', 'development'); vi.useFakeTimers()
  let finish!: (response: Response) => void
  const fetcher = vi.fn(() => new Promise<Response>((resolve) => { finish = resolve }))
  vi.stubGlobal('fetch', fetcher)
  const api = await import('./api')
  api.installControlSessionProvider(() => 'owner')
  const revoke = vi.fn(); api.installControlCommandTimeoutHandler(revoke)
  const pending = api.referencePositiveLimitSide('left', ['X', 'Y'])
  const result = pending.then((value) => ({ value }), (error: unknown) => ({ error }))
  await vi.advanceTimersByTimeAsync(35_000)
  expect(revoke).not.toHaveBeenCalled()
  await expect(api.referencePositiveLimitSide('left', ['Y'])).rejects.toThrow('已有回原点操作')
  await expect(api.returnHardwareReferenceSide('left', ['Z'])).rejects.toThrow('已有回原点操作')
  expect(fetcher).toHaveBeenCalledOnce()
  finish(new Response(JSON.stringify({ ok: true })))
  await expect(result).resolves.toEqual({ value: { ok: true } })
})

it('正限位参考达到长超时仍撤权，且不会自动重发', async () => {
  vi.resetModules(); vi.stubEnv('MODE', 'development'); vi.useFakeTimers()
  const fetcher = vi.fn(() => new Promise<Response>(() => undefined)); vi.stubGlobal('fetch', fetcher)
  const api = await import('./api'); api.installControlSessionProvider(() => 'owner')
  const revoke = vi.fn(); api.installControlCommandTimeoutHandler(revoke)
  const failed = expect(api.referencePositiveLimitSide('left', ['Y'])).rejects.toThrow('执行结果未知')
  await vi.advanceTimersByTimeAsync(79_999)
  expect(revoke).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(2); await failed
  expect(revoke).toHaveBeenCalledOnce(); expect(fetcher).toHaveBeenCalledOnce()
})


it('正限位参考同样遵守急停和连接状态拦截', async () => {
  vi.resetModules(); vi.stubEnv('MODE', 'development')
  const fetcher = vi.fn(); vi.stubGlobal('fetch', fetcher)
  const api = await import('./api')
  api.installControlCommandGuard(() => '急停未解除')
  await expect(api.referencePositiveLimitSide('left', ['X'])).rejects.toThrow('急停未解除')
  expect(fetcher).not.toHaveBeenCalled()
})
