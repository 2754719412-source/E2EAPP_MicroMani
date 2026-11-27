import { Component, type ReactNode } from 'react'
import { UiButton, UiText, UiTitle } from './ui'
import { controlLeaseBlockReason } from '../stores/controlLease'
import { useTelemetryStore } from '../stores/telemetry'
import { reportDisplayFault } from '../utils/controlFaults'

/** 按实际租约与观察模式说明控制状态；页面异常本身不撤销控制，但连接可能因其他原因已不可用。 */
function ControlStateNote() {
  const lease = useTelemetryStore((state) => state.controlLease)
  const observer = useTelemetryStore((state) => state.observerMode)
  const blocker = controlLeaseBlockReason(lease)
  const status = observer
    ? '当前为观察模式，本页不持有控制权。'
    : blocker ? `页面异常未撤销控制，但当前控制不可用：${blocker}。` : '页面异常未撤销控制，控制会话仍有效。'
  return <UiText secondary>{status}可从侧栏查看其他页面，或重试本页；顶部全局急停按钮保持显示。</UiText>
}

/** 隔离业务页加载和渲染失败，让导航、遥测与全局急停继续挂载。 */
export class RouteErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error) {
    reportDisplayFault(`页面显示异常（未撤销控制）：${error.message}`)
  }

  render() {
    if (!this.state.failed) return this.props.children

    return (
      <section className="panel-surface view-stack" role="alert">
        <UiTitle level={2}>页面暂时无法显示</UiTitle>
        <ControlStateNote />
        <div>
          <UiButton variant="primary" onClick={() => this.setState({ failed: false })}>
            重试页面
          </UiButton>
        </div>
      </section>
    )
  }
}
