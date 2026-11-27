import { useState } from 'react'
import { mockMode, runHkvlStartupSelfCheck } from '../api'
import { useTelemetryStore } from '../stores/telemetry'
import { forceSelfCheckBlockReason } from '../utils/controlSafety'
import { UiButton, UiTag } from './ui'

const stateLabels: Record<string, string> = {
  not_required: '无需自检', waiting_sensors: '等待传感器', checking_stability: '检查静稳性',
  taring: '双侧同步去皮', validating: '验证残差', ready: '自检通过，新零点已生效', failed: '自检失败',
}

/** 自检不运动、不触发急停，也不自动解除已有锁存；传感器卸载必须由操作者明确确认。 */
export function ForceStartupSelfCheck() {
  const calibration = useTelemetryStore((state) => state.frame.forceStatus?.calibration)
  const blocker = useTelemetryStore((state) => forceSelfCheckBlockReason(state, !mockMode))
  const injectLog = useTelemetryStore((state) => state.injectLog)
  const [confirmOpen, setConfirmOpen] = useState(false)
  const [unloaded, setUnloaded] = useState(false)
  const [pending, setPending] = useState(false)
  const [message, setMessage] = useState('')
  const state = calibration?.state ?? 'waiting_sensors'
  const busy = pending || ['checking_stability', 'taring', 'validating'].includes(state)
  const start = async () => {
    if (!unloaded || busy || blocker) return
    setConfirmOpen(false)
    setUnloaded(false)
    setPending(true)
    setMessage('')
    try {
      await runHkvlStartupSelfCheck()
      setMessage('自检请求已完成，新零点以下方 HAL 状态为准；若此前处于急停锁存，仍需手动确认安全态。')
      injectLog('INFO', 'HKVL 双侧去皮自检请求已完成，新零点以 HAL 状态为准', '[FORCE]')
    } catch (error) {
      const reason = `HKVL 双侧去皮自检失败：${String(error)}`
      setMessage(reason)
      injectLog('ERROR', reason, '[FORCE]')
    } finally {
      setPending(false)
    }
  }

  return (
    <section className="gripper-config-section" aria-label="HKVL 启动力觉自检">
      <div className="hardware-subtitle-row"><b>HKVL 启动力觉自检</b><span>双侧同步去皮 · 静稳性与残差验证</span></div>
      <p>先停止遥操作、回放和运动（轴使能可保持），释放双侧传感器外载后执行自检。去皮本身不会触发急停；若此前已处于急停锁存，仍需点击“确认安全态”。</p>
      <UiTag tone={state === 'failed' ? 'error' : state === 'ready' ? 'success' : 'warning'}>
        {stateLabels[state] ?? state} · {Number(calibration?.progress ?? 0).toFixed(0)}%
      </UiTag>
      {calibration?.reason && <p role="status">{calibration.reason}</p>}
      {calibration?.completedAtUnixMs ? <p>完成时间：{new Date(calibration.completedAtUnixMs).toLocaleString()}</p> : null}
      <UiButton disabled={Boolean(blocker) || busy} loading={pending} title={blocker ?? undefined}
        onClick={() => { setUnloaded(false); setConfirmOpen(true) }}>
        双侧去皮自检
      </UiButton>
      {blocker && <p role="status">{blocker}</p>}
      {message && <p role="status">{message}</p>}
      {confirmOpen && (
        <div className="ui-modal-mask" role="presentation" onClick={() => setConfirmOpen(false)}>
          <div className="ui-modal" role="dialog" aria-label="确认双侧传感器卸载" onClick={(event) => event.stopPropagation()}>
            <header className="ui-modal-head"><strong>确认双侧传感器卸载</strong></header>
            <div className="ui-modal-body">
              <p>请先移除接触力和外加载荷，保持双侧传感器静止。去皮会修改零点；有载荷时执行会把载荷计入零点。</p>
              <label className="ui-checkbox"><input type="checkbox" checked={unloaded} onChange={(event) => setUnloaded(event.target.checked)} />我已确认双侧传感器卸载并保持静止</label>
            </div>
            <div className="ui-modal-actions">
              <UiButton onClick={() => setConfirmOpen(false)}>取消</UiButton>
              <UiButton variant="primary" disabled={!unloaded || busy || Boolean(blocker)} onClick={() => void start()}>开始双侧自检</UiButton>
            </div>
          </div>
        </div>
      )}
    </section>
  )
}
