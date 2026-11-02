import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, expect, it, vi } from 'vitest'

afterEach(() => { cleanup(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); vi.resetModules() })

it.each([false, true])('用户选择是否沿用计数：%s', async (accept) => {
  vi.stubEnv('MODE', 'development')
  const { OriginContinuityDialog } = await import('./OriginContinuityDialog')
  const api = await import('../api')
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({
    detail: { code: 'CONFIRM_ORIGIN_CONTINUITY', confirmation: 'bound-to-this-return' },
  }), { status: 409 })).mockResolvedValueOnce(new Response('{"ok":true}'))
  vi.stubGlobal('fetch', fetcher)
  render(<MemoryRouter><OriginContinuityDialog /></MemoryRouter>)
  const result = api.returnMotionOriginSide('left').catch((error: Error) => error.message)
  await screen.findByRole('dialog')
  expect(screen.getByRole('dialog')).toHaveTextContent('右臂')
  await expect(api.returnMotionOriginSide('right')).rejects.toThrow('已有回原点操作')
  expect(fetcher).toHaveBeenCalledTimes(1)
  fireEvent.click(screen.getByRole('button', { name: accept ? /未重启.*回工作原点/ : /重启过或不确定/ }))
  if (accept) {
    await expect(result).resolves.toEqual({ ok: true })
    expect(fetcher.mock.calls[1][0]).toMatch(/left\/return_origin$/)
    expect(JSON.parse(fetcher.mock.calls[1][1].body)).toEqual({ confirmUnchangedCounts: 'bound-to-this-return' })
  } else {
    await expect(result).resolves.toMatch(/已取消/)
    expect(fetcher).toHaveBeenCalledTimes(1)
  }
})
