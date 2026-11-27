import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useTelemetryStore } from '../stores/telemetry'
import { ModuleErrorBoundary } from './ModuleErrorBoundary'
import { RouteErrorBoundary } from './RouteErrorBoundary'

const initialState = useTelemetryStore.getState()
afterEach(() => { cleanup(); vi.restoreAllMocks(); useTelemetryStore.setState(initialState) })

function Broken(): never {
  throw new Error('渲染失败')
}

it.each([
  ['模块', <ModuleErrorBoundary name="诊断面板"><Broken /></ModuleErrorBoundary>],
  ['页面', <RouteErrorBoundary><Broken /></RouteErrorBoundary>],
])('%s显示异常只记录日志，不关闭控制连接或撤销租约', (_label, element) => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  const stopBackend = vi.fn()
  const lease = useTelemetryStore.getState().controlLease
  useTelemetryStore.setState({ stopBackend })
  render(element)
  expect(stopBackend).not.toHaveBeenCalled()
  expect(useTelemetryStore.getState().controlLease).toBe(lease)
  const last = useTelemetryStore.getState().logs.at(-1)
  expect(last?.level).toBe('ERROR')
  expect(last?.msg).toContain('控制未中断')
})

it('页面降级后重试只重新渲染，不重启控制连接', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  const stopBackend = vi.fn()
  useTelemetryStore.setState({ stopBackend })
  render(<RouteErrorBoundary><Broken /></RouteErrorBoundary>)
  fireEvent.click(screen.getByRole('button', { name: '重试页面' }))
  expect(stopBackend).not.toHaveBeenCalled()
})
