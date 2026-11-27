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
  expect(last?.msg).toContain('未撤销控制')
})

it('页面降级后重试只重新渲染，不重启控制连接', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  const stopBackend = vi.fn()
  useTelemetryStore.setState({ stopBackend })
  render(<RouteErrorBoundary><Broken /></RouteErrorBoundary>)
  fireEvent.click(screen.getByRole('button', { name: '重试页面' }))
  expect(stopBackend).not.toHaveBeenCalled()
})


it.each([
  ['有效租约', { required: true, status: 'active', sessionId: 's', expiresAt: null, reason: '' }, false, '控制会话仍有效'],
  ['租约过期', { required: true, status: 'expired', sessionId: null, expiresAt: 0, reason: '连接断开，控制租约已撤销' }, false, '当前控制不可用：连接断开'],
  ['观察模式', { required: true, status: 'pending', sessionId: null, expiresAt: 0, reason: '' }, true, '观察模式'],
] as const)('页面错误提示按实际控制状态显示：%s', (_label, controlLease, observerMode, expected) => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  useTelemetryStore.setState({ controlLease: { ...controlLease }, observerMode })
  render(<RouteErrorBoundary><Broken /></RouteErrorBoundary>)
  expect(screen.getByRole('alert')).toHaveTextContent(expected)
  if (expected !== '控制会话仍有效') expect(screen.getByRole('alert')).not.toHaveTextContent('控制会话仍有效')
})
