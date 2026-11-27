import { afterEach, expect, it, vi } from 'vitest'
import * as api from '../api'
import { defaultConfig } from '../data'
import type { AppConfig } from '../types'
import { useTelemetryStore as store } from './telemetry'

const initial = store.getState()
afterEach(() => { store.setState(initial, true); vi.restoreAllMocks() })

const halRejected = () => Object.assign(new Error('HAL refused: servos enabled'), { status: 409, code: 'HAL_REJECTED' })
const settingsBusy = () => Object.assign(new Error('已有配置正在应用，请稍后重试'), { status: 409 })

async function rejectStopThreshold(error: () => Error) {
  vi.spyOn(api, 'mockMode', 'get').mockReturnValue(false)
  const bodies: AppConfig[] = []
  vi.spyOn(api, 'putConfig').mockImplementation(async (config) => {
    bodies.push(structuredClone(config))
    if (bodies.length === 1) throw error()
    return structuredClone(config)
  })
  store.setState({ config: structuredClone(defaultConfig), logs: [] })
  store.getState().updateConfig({ safety: { ...store.getState().config.safety, fzStopN: 1 } })
  await vi.waitFor(() => expect(store.getState().logs.some((log) => log.level === 'ERROR')).toBe(true))
  await new Promise((resolve) => setTimeout(resolve, 0))  // 等队列排空
  expect(store.getState().configSaveError).toBeTruthy()
  return bodies
}

it('后端明确拒绝后再改无关字段，保存不携带被拒值，界面恢复为生效值', async () => {
  const bodies = await rejectStopThreshold(halRejected)
  store.getState().updateConfig({ storage: { ...store.getState().config.storage, datasetRoot: 'D:/unrelated' } })
  await vi.waitFor(() => expect(bodies).toHaveLength(2))
  expect(bodies[1].safety.fzStopN).toBe(defaultConfig.safety.fzStopN)
  expect(bodies[1].storage.datasetRoot).toBe('D:/unrelated')
  await vi.waitFor(() => expect(store.getState().config.safety.fzStopN).toBe(defaultConfig.safety.fzStopN))
  expect(store.getState().configSaveError).toBeNull()
})

it('被拒后继续修改同一字段，以新输入为准', async () => {
  const bodies = await rejectStopThreshold(halRejected)
  store.getState().updateConfig({ safety: { ...store.getState().config.safety, fzStopN: 15 } })
  await vi.waitFor(() => expect(bodies).toHaveLength(2))
  expect(bodies[1].safety.fzStopN).toBe(15)
})

it('写锁冲突等暂时失败，下一次保存仍携带该值重试', async () => {
  const bodies = await rejectStopThreshold(settingsBusy)
  store.getState().updateConfig({ storage: { ...store.getState().config.storage, datasetRoot: 'D:/unrelated' } })
  await vi.waitFor(() => expect(bodies).toHaveLength(2))
  expect(bodies[1].safety.fzStopN).toBe(1)
})
