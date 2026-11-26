import { expect, it, vi } from 'vitest'
import { installControlFaultHandlers } from './controlFaults'

it('只放行不携带脚本异常的两种完整 ResizeObserver 通知', () => {
  const revoke = vi.fn()
  const remove = installControlFaultHandlers(revoke)
  const message = 'ResizeObserver loop completed with undelivered notifications.'
  try {
    window.dispatchEvent(new ErrorEvent('error', { message }))
    window.dispatchEvent(new ErrorEvent('error', { message: 'ResizeObserver loop limit exceeded' }))
    expect(revoke).not.toHaveBeenCalled()
    window.dispatchEvent(new ErrorEvent('error', { message, error: new Error(message) }))
    window.dispatchEvent(new ErrorEvent('error', { message: `${message} other fault` }))
    const rejection = Object.assign(new Event('unhandledrejection'), { reason: message })
    window.dispatchEvent(rejection)
    expect(revoke).toHaveBeenCalledTimes(3)
  } finally { remove() }
})

it('脚本错误与未处理拒绝撤销控制，卸载后监听对称释放', () => {
  const revoke = vi.fn()
  const remove = installControlFaultHandlers(revoke)
  window.dispatchEvent(new ErrorEvent('error', { message: '脚本异常' }))
  const rejection = new Event('unhandledrejection')
  Object.defineProperty(rejection, 'reason', { value: new Error('异步异常') })
  window.dispatchEvent(rejection)
  expect(revoke).toHaveBeenCalledTimes(2)
  expect(revoke.mock.calls[0][0]).toContain('脚本异常')
  expect(revoke.mock.calls[1][0]).toContain('异步异常')
  remove()
  window.dispatchEvent(new ErrorEvent('error', { message: '已卸载' }))
  window.dispatchEvent(rejection)
  expect(revoke).toHaveBeenCalledTimes(2)
})
