import { Component, type ReactNode } from 'react'
import { UiButton, UiText, UiTitle } from './ui'
import { reportDisplayFault } from '../utils/controlFaults'

/** 隔离业务页加载和渲染失败，让导航、遥测与全局急停继续挂载。 */
export class RouteErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error) {
    reportDisplayFault(`页面显示异常（控制未中断）：${error.message}`)
  }

  render() {
    if (!this.state.failed) return this.props.children

    return (
      <section className="panel-surface view-stack" role="alert">
        <UiTitle level={2}>页面暂时无法显示</UiTitle>
        <UiText secondary>控制连接未中断，全局急停仍可使用。可从侧栏查看其他页面，或重试本页。</UiText>
        <div>
          <UiButton variant="primary" onClick={() => this.setState({ failed: false })}>
            重试页面
          </UiButton>
        </div>
      </section>
    )
  }
}
