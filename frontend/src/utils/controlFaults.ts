import { useTelemetryStore } from '../stores/telemetry'

/** 写入日志；日志状态本身损坏时降级到控制台，上报不能再次抛错。 */
export function reportDisplayFault(reason: string) {
  try {
    useTelemetryStore.getState().injectLog('ERROR', reason, '[SAFETY]')
  } catch (error) {
    console.error(reason, error)
  }
}

/** 未捕获脚本错误只记录提示，不撤销控制；执行侧急停、租约与力安全不依赖页面脚本。 */
export function installControlFaultHandlers(report: (reason: string) => void) {
  const onError = (event: ErrorEvent) => {
    if (event.error == null && (event.message === 'ResizeObserver loop completed with undelivered notifications.'
      || event.message === 'ResizeObserver loop limit exceeded')) return
    report(`页面脚本异常（控制未中断）：${event.message || '未知错误'}`)
  }
  const onRejection = (event: PromiseRejectionEvent) => report(`页面异步异常（控制未中断）：${String(event.reason)}`)
  window.addEventListener('error', onError)
  window.addEventListener('unhandledrejection', onRejection)
  return () => {
    window.removeEventListener('error', onError)
    window.removeEventListener('unhandledrejection', onRejection)
  }
}
