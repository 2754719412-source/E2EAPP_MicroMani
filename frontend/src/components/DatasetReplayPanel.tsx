import type { Participation } from '../types'
import { ParticipationSelector } from './ParticipationSelector'
import { useEffect, useRef, useState } from 'react'
import { AlertCircle, Play, RotateCcw, ShieldCheck, Square } from 'lucide-react'
import { apiBase, CommandTimeoutError, mockMode, postCommand } from '../api'
import { UiButton, UiTag, UiTitle } from './ui'

type ReplayTiming = {
  requestedSpeed: number
  plannedDurationS: number
  plannedAverageSpeed: number
  minimumSpeed: number
  limitedFrames: number
  limitingChannels: string[]
  gripperFeedbackLimited: boolean
  profileSource: string
  hardwareValidated: boolean
  profile: { translationVelocityUiPerSec: number; rotationVelocityUiPerSec: number; accTimeSec: number; decTimeSec: number }
}
type ReplayStatus = {
  active: boolean
  runId?: string
  stopMode?: 'controlled' | 'emergency'
  phase: string
  frame: number
  totalFrames: number
  datasetId?: string
  episodeId?: string
  error?: string
  warning?: string
  timing?: ReplayTiming
  elapsedS?: number
  effectiveSpeed?: number
  feedbackWaitS?: number
  waitingChannels?: string[]
}
const phaseLabels: Record<string, string> = {
  idle: '待命', loading: '校验中', aligning: '起点对齐中', running: '回放中',
  stopping: '正在停止', settling: '等待末帧到位', completed: '已完成', stopped: '已停止', failed: '失败',
  following: '等待设备跟随',
}

export function DatasetReplayPanel({ datasetId, episodeId, recordedParticipation }: { datasetId: string; episodeId: string; recordedParticipation?: Participation | null }) {
  return <DatasetReplayPanelContent key={JSON.stringify([datasetId, episodeId, recordedParticipation])} datasetId={datasetId} episodeId={episodeId} recordedParticipation={recordedParticipation} />
}

function DatasetReplayPanelContent({ datasetId, episodeId, recordedParticipation }: { datasetId: string; episodeId: string; recordedParticipation?: Participation | null }) {
  const [selected, setSelected] = useState<Participation>(recordedParticipation ?? { version: 'appstation.participation.v1', arms: [], grippers: [] })
  const [status, setStatus] = useState<ReplayStatus | null>(null)
  const [inspection, setInspection] = useState<{
    key: string; summary?: string; timing?: ReplayTiming; error?: string
  } | null>(null)
  const [attempt, setAttempt] = useState(0)
  const generation = useRef(0)
  const statusRevision = useRef(0)
  const commandSequence = useRef(0)
  const [confirmed, setConfirmed] = useState(false)
  const [speed, setSpeed] = useState('0.25')
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  const [stopRequest, setStopRequest] = useState<{ target: ReplayStatus; error: string } | null>(null)
  const [connection, setConnection] = useState<'connecting' | 'online' | 'offline'>('connecting')
  const connected = connection === 'online'
  const canInspect = connected && !mockMode && !pending && !status?.active && selected.arms.length > 0
  const replayPath = `/api/datasets/${encodeURIComponent(datasetId)}/episodes/${encodeURIComponent(episodeId)}/replay`
  const key = JSON.stringify([datasetId, episodeId, selected, speed])
  const current = canInspect && inspection?.key === key ? inspection : null
  const verified = Boolean(current?.summary)
  const resetInspection = () => {
    generation.current += 1
    setInspection(null)
    setConfirmed(false)
  }
  useEffect(() => {
    if (mockMode) return
    let disposed = false
    let timer: ReturnType<typeof setTimeout>
    const poll = async () => {
      const revision = statusRevision.current
      try {
        const response = await fetch(`${apiBase}/api/replay/status`, { signal: AbortSignal.timeout(3000) })
        if (!response.ok) throw new Error('无法获取回放状态')
        const payload = await response.json() as { data: ReplayStatus }
        if (!disposed && revision === statusRevision.current) {
          statusRevision.current += 1
          setStatus(payload.data)
          setConnection('online')
          setStopRequest((request) => request && !payload.data.stopMode
            && request.target.runId === payload.data.runId && request.target.datasetId === payload.data.datasetId
            && request.target.episodeId === payload.data.episodeId ? request : null)
          if (payload.data.active) resetInspection()
        }
      } catch {
        if (!disposed) {
          setConnection('offline')
          resetInspection()
        }
      } finally {
        if (!disposed) timer = setTimeout(poll, 500)
      }
    }
    void poll()
    return () => { disposed = true; clearTimeout(timer) }
  }, [])
  useEffect(() => {
    if (!canInspect) return
    let disposed = false
    const requestGeneration = generation.current
    const inspect = async () => {
      try {
        const { data } = await postCommand(`${replayPath}/inspect`, { participation: selected, speed: Number(speed) }) as {
          data: { frames: number; fps: number; durationS: number; timing?: ReplayTiming }
        }
        if (!disposed && requestGeneration === generation.current) {
          setInspection({ key, summary: `${data.frames} 帧 · ${data.fps} Hz · ${data.durationS.toFixed(1)} 秒`, timing: data.timing })
        }
      } catch (cause) {
        if (!disposed && requestGeneration === generation.current)
          setInspection({ key, error: cause instanceof Error ? cause.message || '回放数据校验失败' : '回放数据校验失败' })
      }
    }
    const timer = setTimeout(() => void inspect(), 200)
    return () => { disposed = true; clearTimeout(timer) }
  }, [canInspect, replayPath, selected, speed, key, attempt])

  const run = async (operation: 'start' | 'stop') => {
    if (operation === 'start' && !(verified && confirmed)) return
    const revision = statusRevision.current
    const command = ++commandSequence.current
    resetInspection()
    setPending(true)
    setError('')
    const stop = operation === 'stop' && status ? { target: status, error: '' } : null
    setStopRequest(stop)
    try {
      const result = await (operation === 'stop' ? postCommand('/api/replay/stop', {})
        : postCommand(`${replayPath}/start`, { participation: selected, speed: Number(speed), confirmMotion: true })) as { data: ReplayStatus }
      // 命令返回期间若已收到更新的状态，继续以轮询为准。
      if (command === commandSequence.current && revision === statusRevision.current) {
        statusRevision.current += 1
        setStatus(result.data)
      }
    } catch (cause) {
      if (command !== commandSequence.current) return
      if (stop) {
        const message = cause instanceof CommandTimeoutError ? '停止请求超时，尚未确认停车，正在核对设备反馈。'
          : cause instanceof Error ? cause.message : '回放停止请求失败'
        setStopRequest((request) => request === stop ? { ...stop, error: message } : request)
      } else {
        setError(cause instanceof Error ? cause.message : '回放操作失败')
      }
    } finally {
      if (command === commandSequence.current) setPending(false)
    }
  }
  const errorDetail = connection === 'offline' ? '回放状态连接中断，请核验设备状态' : error || status?.error || stopRequest?.error || current?.error || ''
  const diagnosticError = errorDetail.startsWith('目标位置对齐超时') || errorDetail.startsWith('实际位置偏离回放目标') || errorDetail.startsWith('回放跟随等待超时')
  const errorMessage = diagnosticError ? errorDetail.split('\n')[0] : errorDetail.includes('Parquet magic bytes')
    ? '数据文件无法读取，请检查 Parquet 文件是否完整。'
    : errorDetail.length > 120 ? '回放操作未完成，请展开详情查看原因。' : errorDetail
  const progress = status?.totalFrames ? Math.min(100, Math.max(0, status.frame / status.totalFrames * 100)) : 0
  const timing = status?.active ? (status.datasetId === datasetId && status.episodeId === episodeId ? status.timing : null) : current?.timing
  return (
    <section className="panel-surface dataset-replay" aria-label="示教数据真机回放测试">
      <header className="dataset-replay-header">
        <span className="dataset-replay-icon"><RotateCcw size={20} aria-hidden="true" /></span>
        <div className="dataset-replay-heading">
          <UiTitle level={3}>示教数据真机回放测试</UiTitle>
          <p>对齐录制起点，再按帧执行参与臂与夹爪动作</p>
        </div>
        <UiTag tone={!connected ? 'muted' : status?.phase === 'failed' ? 'error' : status?.active ? 'processing' : status?.phase === 'completed' ? 'success' : 'default'}>
          {!connected ? '未连接' : status ? phaseLabels[status.phase] ?? status.phase : '待命'}
        </UiTag>
      </header>
      <ParticipationSelector value={selected} disabled={Boolean(recordedParticipation) || pending || status?.active} onChange={(value) => { setSelected(value); resetInspection() }} />
      {!recordedParticipation && <p>此片段未记录参与侧，请明确选择参与臂与夹爪后校验。未选设备不会接收回放动作。</p>}
      <div className="dataset-replay-toolbar">
        <div className="dataset-replay-actions">
          {current?.error && <UiButton onClick={() => { resetInspection(); setAttempt((value) => value + 1) }}>重新校验回放数据</UiButton>}
          <UiButton variant="primary" icon={<Play size={15} aria-hidden="true" />} disabled={!verified || !confirmed} onClick={() => void run('start')}>对齐起点并真机回放</UiButton>
          <UiButton danger icon={<Square size={14} aria-hidden="true" />} disabled={!status?.active} onClick={() => void run('stop')}>停止真机回放</UiButton>
        </div>
        <fieldset className="dataset-replay-speed" disabled={pending || status?.active}>
          <legend>回放倍率</legend>
          <div>
            {['0.1', '0.25', '0.5', '1'].map((value) => (
              <label key={value}>
                <input type="radio" name={`replay-speed-${datasetId}-${episodeId}`} aria-label={`${value} 倍速`} value={value} checked={speed === value} onChange={() => { setSpeed(value); resetInspection() }} />
                <span>{value}×</span>
              </label>
            ))}
          </div>
        </fieldset>
      </div>
      {timing && <div className="dataset-replay-timing" aria-label="回放时间规划">
        <p>请求 {timing.requestedSpeed}× · 计划平均 {timing.plannedAverageSpeed.toFixed(3)}× · 最慢段 {timing.minimumSpeed.toFixed(3)}× · 预计 {timing.plannedDurationS.toFixed(1)} 秒</p>
        <p>{timing.limitedFrames ? `${timing.limitedFrames} 段延时，受限通道：${timing.limitingChannels.join('、')}` : '轨迹无需额外延时'}。预计时长不含起点对齐、通信与反馈等待{timing.gripperFeedbackLimited ? '；夹爪耗时以实际反馈为准' : ''}。</p>
        <p>参数来源：{timing.profileSource === 'teleop' ? '当前示教配置' : timing.profileSource} · 平移 {timing.profile.translationVelocityUiPerSec} μm/s · 旋转 {timing.profile.rotationVelocityUiPerSec}°/s · 加/减速 {timing.profile.accTimeSec}/{timing.profile.decTimeSec} 秒。{!timing.hardwareValidated && '尚无逐轴及负载实机验收记录。'}</p>
      </div>}
      <label className={`dataset-replay-confirm${confirmed ? ' is-confirmed' : ''}`}>
        <input type="checkbox" checked={confirmed} disabled={!verified} onChange={(event) => setConfirmed(event.target.checked)} />
        <span><strong>确认工作区可安全运动</strong><span>请先停止示教、录制和策略运行；勾选后允许所选臂与夹爪移动到录制起点并回放。</span></span>
      </label>
      <div className="dataset-replay-status">
        <span>{pending ? '正在处理请求…' : verified ? '数据校验通过' : canInspect && !current ? '正在校验回放数据…' : '回放进度'}{current?.summary && <span className="dataset-replay-summary">{current.summary}</span>}</span>
        <span className="dataset-replay-frames">{status?.frame ?? 0}<span> / {status?.totalFrames ?? 0} 帧</span></span>
      </div>
      <progress className="dataset-replay-progress" aria-label="真机回放进度" max={100} value={progress} />
      {status?.active && <p className="dataset-replay-episode">执行片段：{status.datasetId} / {status.episodeId}</p>}
      {status?.elapsedS != null && <p className="dataset-replay-episode">任务已运行 {status.elapsedS.toFixed(1)} 秒 · 实际平均 {(status.effectiveSpeed ?? 0).toFixed(3)}× · 跟随等待 {(status.feedbackWaitS ?? 0).toFixed(1)} 秒{status.phase === 'following' && status.waitingChannels?.length ? ` · 等待：${status.waitingChannels.join('、')}` : ''}</p>}
      {current?.error && current.error !== errorDetail && <p className="dataset-replay-episode" role="status">回放预检失败：{current.error}</p>}
      {status?.stopMode && <p className="dataset-replay-episode" role="status">
        {status.stopMode === 'emergency' ? '已请求硬件急停，请核对设备安全反馈。'
          : status.phase === 'stopped' ? '已确认参与机械臂静止。' : '正在等待参与机械臂停轴反馈…'}
      </p>}
      {status?.warning && <p className="dataset-replay-episode" role="status">{status.warning}</p>}
      {errorDetail && <div className="dataset-replay-error" role="alert">
        <AlertCircle size={17} aria-hidden="true" />
        <div><strong>{errorMessage}</strong><details open={diagnosticError}><summary>查看错误详情</summary><pre>{errorDetail}</pre></details></div>
      </div>}
      <p className="dataset-replay-footnote"><ShieldCheck size={15} aria-hidden="true" /><span>纯机械臂回放在 HAL 支持时可受控停轴。夹爪参与、执行故障、下发结果未知或无法确认停车时会请求硬件急停。</span></p>
    </section>
  )
}
