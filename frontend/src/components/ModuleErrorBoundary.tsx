import { Component, type ReactNode } from 'react'
import { reportDisplayFault } from '../utils/controlFaults'

/** 壳层各区域独立降级，诊断显示异常不得卸载导航和急停入口。 */
export class ModuleErrorBoundary extends Component<{
  name: string
  children: ReactNode
  fallback?: ReactNode
}, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch(error: Error) {
    // 显示异常只降级本模块并记录，不撤销控制；急停入口在独立模块中保持可用。
    reportDisplayFault(`${this.props.name}显示异常（控制未中断）：${error.message}`)
  }

  render() {
    if (!this.state.failed) return this.props.children
    return this.props.fallback ?? (
      <div className="ui-alert ui-alert-warning" role="alert">
        {this.props.name}暂时不可用
        <button type="button" className="ui-btn ui-btn-text" onClick={() => this.setState({ failed: false })}>
          重试此模块
        </button>
      </div>
    )
  }
}
