import { act, cleanup, fireEvent, render, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter } from 'react-router-dom'
import * as api from '../../src/api'
import { defaultConfig } from '../../src/data'
import { useTelemetryStore } from '../../src/stores/telemetry'
import { SettingsView } from '../../src/views/SettingsView'

const initialFrame = structuredClone(useTelemetryStore.getState().frame)
beforeEach(() => {
  vi.spyOn(api, 'fetchMotionOrigin').mockResolvedValue({ ok: true, data: { origin: defaultConfig.motion.origin } })
  useTelemetryStore.setState({ config: structuredClone(defaultConfig), frame: structuredClone(initialFrame), history: [] })
})
afterEach(() => { cleanup(); vi.restoreAllMocks() })
async function show(hash: string) {
  await act(async () => { render(<MemoryRouter initialEntries={['/settings#' + hash]}><SettingsView /></MemoryRouter>) })
}

describe('只读审查：设置迁移可观察行为', () => {
  it('力觉卡数值应与操作者侧对应的硬件侧一致', async () => {
    useTelemetryStore.setState((state) => ({ frame: { ...state.frame, forceLeft: [0.014, 0, 0, 0, 0, 0], forceRight: [1.527, 0, 0, 0, 0, 0] } }))
    await show('force-left')
    const fx = document.querySelector('#force-left .force-current-grid span')!
    expect(fx.textContent).toContain('1527 mN')
  })
  it('回原点 HTTP 待完成期间应拦截重复与另一侧请求', async () => {
    const returnOrigin = vi.spyOn(api, 'returnMotionOriginSide').mockImplementation(() => new Promise(() => {}))
    useTelemetryStore.setState((state) => ({ frame: { ...state.frame, motionEnabled: { left: true, right: true }, motionAxisEnabled: { left: Array(6).fill(true), right: Array(6).fill(true) } } }))
    await show('teleop-left')
    const left = within(document.querySelector('#teleop-left')!).getByRole('button', { name: '回工作原点' })
    const right = within(document.querySelector('#teleop-right')!).getByRole('button', { name: '回工作原点' })
    fireEvent.click(left)
    fireEvent.click(left)
    fireEvent.click(right)
    expect(returnOrigin).toHaveBeenCalledTimes(1)
  })
  it('系统连接应保留数据存储与录制 FPS 设置', async () => {
    await show('storage')
    expect(document.querySelector('#storage')).not.toBeNull()
  })
  it('既有 PICO teleop hash 应挂载目标卡片', async () => {
    await show('teleop')
    expect(document.querySelector('#teleop')).not.toBeNull()
  })
})

it('应用配置应重新提交界面当前配置而不是只发送 HAL 重连', async () => {
  const apply = vi.spyOn(api, 'applyConfig').mockResolvedValue({ ok: true })
  const reconnect = vi.spyOn(api, 'reconnectHal').mockResolvedValue({ ok: true })
  useTelemetryStore.setState((state) => ({ config: { ...state.config, safety: { ...state.config.safety, fxyStopN: 9 } } }))
  await show('safety')
  await act(async () => { fireEvent.click(within(document.body).getByRole('button', { name: '应用配置' })) })
  expect.soft(reconnect).not.toHaveBeenCalled()
  expect(apply).toHaveBeenCalledWith(useTelemetryStore.getState().config)
})
