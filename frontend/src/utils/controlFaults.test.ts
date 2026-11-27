import { expect, it, vi } from 'vitest'
import { installControlFaultHandlers } from './controlFaults'

it('只放行不携带脚本异常的两种完整 ResizeObserver 通知', () => {
  const report = vi.fn()
  const remove = installControlFaultHandlers(report)
  const message = 'ResizeObserver loop completed with undelivered notifications.'
  try {
    window.dispatchEvent(new ErrorEvent('error', { message }))
    window.dispatchEvent(new ErrorEvent('error', { message: 'ResizeObserver loop limit exceeded' }))
    expect(report).not.toHaveBeenCalled()
    window.dispatchEvent(new ErrorEvent('error', { message, error: new Error(message) }))
    window.dispatchEvent(new ErrorEvent('error', { message: `${message} other fault` }))
    const rejection = Object.assign(new Event('unhandledrejection'), { reason: message })
    window.dispatchEvent(rejection)
    expect(report).toHaveBeenCalledTimes(3)
  } finally { remove() }
})

it('脚本错误与未处理拒绝只上报提示且注明未撤销控制，卸载后监听对称释放', () => {
  const report = vi.fn()
  const remove = installControlFaultHandlers(report)
  window.dispatchEvent(new ErrorEvent('error', { message: '脚本异常' }))
  const rejection = new Event('unhandledrejection')
  Object.defineProperty(rejection, 'reason', { value: new Error('异步异常') })
  window.dispatchEvent(rejection)
  expect(report).toHaveBeenCalledTimes(2)
  expect(report.mock.calls[0][0]).toContain('脚本异常')
  expect(report.mock.calls[0][0]).toContain('未撤销控制')
  expect(report.mock.calls[1][0]).toContain('异步异常')
  remove()
  window.dispatchEvent(new ErrorEvent('error', { message: '已卸载' }))
  window.dispatchEvent(rejection)
  expect(report).toHaveBeenCalledTimes(2)
})
