import type { Participation } from '../types'
const dualParticipation: Participation = { version: 'appstation.participation.v1', arms: ['left', 'right'], grippers: ['left', 'right'] }
import { act, fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { DatasetReplayPanel } from './DatasetReplayPanel'
import { CommandTimeoutError, postCommand } from '../api'

vi.mock('../api', async (load) => ({ ...await load<typeof import('../api')>(), apiBase: 'http://localhost', mockMode: false, postCommand: vi.fn() }))
beforeEach(() => {
  vi.mocked(postCommand).mockReset()
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: { phase: 'idle', active: false, frame: 0, totalFrames: 0 } }) }))
})
afterEach(() => { cleanup(); vi.unstubAllGlobals() })

const timing = {
  requestedSpeed: .25, plannedDurationS: 12.4, plannedAverageSpeed: .201, minimumSpeed: .08,
  limitedFrames: 2, limitingChannels: ['右臂 Y'], gripperFeedbackLimited: true,
  profileSource: 'teleop', hardwareValidated: false,
  profile: { translationVelocityUiPerSec: 8000, rotationVelocityUiPerSec: 12, accTimeSec: .05, decTimeSec: .05 },
}

it('按选择的倍率规划并显示未验证的示教参数，改倍率需重新校验', async () => {
  vi.mocked(postCommand).mockResolvedValue({ data: { frames: 60, fps: 30, durationS: 2, timing } })
  render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="e" />)
  await waitFor(() => expect(postCommand).toHaveBeenCalledTimes(1))
  const plan = await screen.findByLabelText('回放时间规划')
  expect(postCommand).toHaveBeenCalledWith('/api/datasets/local/episodes/e/replay/inspect', { speed: .25, participation: dualParticipation })
  expect(plan).toHaveTextContent('预计 12.4 秒')
  expect(plan).toHaveTextContent('2 段延时，受限通道：右臂 Y')
  expect(plan).toHaveTextContent('当前示教配置 · 平移 8000 μm/s · 旋转 12°/s')
  expect(plan).toHaveTextContent('尚无逐轴及负载实机验收记录')
  fireEvent.click(screen.getByRole('checkbox', { name: /确认工作区/ }))
  fireEvent.click(screen.getByRole('radio', { name: '0.5 倍速' }))
  expect(screen.getByRole('button', { name: '对齐起点并真机回放' })).toBeDisabled()
  expect(screen.getByRole('checkbox', { name: /确认工作区/ })).not.toBeChecked()
  expect(screen.queryByLabelText('回放时间规划')).not.toBeInTheDocument()
})

it('跟随等待显示实际任务倍率、耗时及等待通道', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ data: {
    phase: 'following', active: true, datasetId: 'local', episodeId: 'e', frame: 2, totalFrames: 60,
    elapsedS: 1.2, effectiveSpeed: .12, feedbackWaitS: .5, waitingChannels: ['右臂 Y'], timing,
  } }) } as Response)
  render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="e" />)
  await screen.findByText('等待设备跟随')
  expect(screen.getByText(/任务已运行/)).toHaveTextContent('实际平均 0.120× · 跟随等待 0.5 秒 · 等待：右臂 Y')
  expect(screen.getByLabelText('回放时间规划')).toHaveTextContent('请求 0.25×')
  expect(screen.getByRole('button', { name: '停止真机回放' })).toBeEnabled()
})

it('不把其他片段的运行计划当成所选片段的规划', async () => {
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ data: {
    phase: 'running', active: true, datasetId: 'other', episodeId: 'old', frame: 2, totalFrames: 60, timing,
  } }) } as Response)
  render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="new" />)
  await screen.findByText('执行片段：other / old')
  expect(screen.queryByLabelText('回放时间规划')).not.toBeInTheDocument()
})

it('切换片段后迟到的校验响应不能解除新片段的门控', async () => {
  let resolve!: (value: unknown) => void
  vi.mocked(postCommand).mockReturnValueOnce(new Promise((done) => { resolve = done }) as ReturnType<typeof postCommand>)
    .mockReturnValue(new Promise(() => {}))
  const { rerender } = render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="old" />)
  await waitFor(() => expect(postCommand).toHaveBeenCalledTimes(1))
  rerender(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="new" />)
  await act(async () => resolve({ data: { frames: 60, fps: 30, durationS: 2, timing } }))
  await waitFor(() => expect(postCommand).toHaveBeenCalledTimes(2))
  expect(screen.queryByLabelText('回放时间规划')).not.toBeInTheDocument()
  expect(screen.getByRole('checkbox', { name: /确认工作区/ })).toBeDisabled()
})

describe('DatasetReplayPanel', () => {
  it('requires validation and explicit motion confirmation before start', async () => {
    vi.mocked(postCommand).mockResolvedValueOnce({ data: { frames: 30, fps: 30, durationS: 1 } })
      .mockResolvedValueOnce({ data: { phase: 'loading', active: true, frame: 0, totalFrames: 30 } })
    render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="episode_000001" />)
    const start = screen.getByRole('button', { name: '对齐起点并真机回放' })
    expect(start).toBeDisabled()
    await screen.findByText('30 帧 · 30 Hz · 1.0 秒')
    expect(start).toBeDisabled()
    fireEvent.click(screen.getByRole('checkbox', { name: /确认工作区/ }))
    fireEvent.click(start)
    await waitFor(() => expect(postCommand).toHaveBeenLastCalledWith(
      '/api/datasets/local/episodes/episode_000001/replay/start', { speed: .25, confirmMotion: true, participation: dualParticipation }))
    expect(screen.getByRole('button', { name: '停止真机回放' })).toBeEnabled()
  })

  it('shows validation rejection without allowing motion', async () => {
    vi.mocked(postCommand).mockRejectedValueOnce(new Error('原点不一致'))
    render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="episode" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('原点不一致')
    const start = screen.getByRole('button', { name: '对齐起点并真机回放' })
    expect(start).toBeDisabled()
    vi.mocked(postCommand).mockResolvedValueOnce({ data: { frames: 30, fps: 30, durationS: 1 } })
    fireEvent.click(screen.getByRole('button', { name: '重新校验回放数据' }))
    await screen.findByText('30 帧 · 30 Hz · 1.0 秒')
    expect(start).toBeDisabled()
  })

  it('collapses technical errors behind a readable message', async () => {
    const detail = `REPLAY_REJECTED: ${'dataset path /'.repeat(30)} Parquet magic bytes not found in footer`
    vi.mocked(postCommand).mockRejectedValueOnce(new Error(detail))
    render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="episode" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('数据文件无法读取，请检查 Parquet 文件是否完整。')
    const details = screen.getByText('查看错误详情').closest('details')!
    expect(details).not.toHaveAttribute('open')
    expect(details).toHaveTextContent(detail)
    expect(screen.getByRole('button', { name: '对齐起点并真机回放' })).toBeDisabled()
  })

  it('sends the selected speed and locks speed controls during replay', async () => {
    vi.mocked(postCommand).mockResolvedValueOnce({ data: { frames: 30, fps: 30, durationS: 1 } })
      .mockResolvedValueOnce({ data: { phase: 'running', active: true, frame: 1, totalFrames: 30 } })
    render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="episode" />)
    fireEvent.click(screen.getByRole('radio', { name: '0.5 倍速' }))
    await screen.findByText('30 帧 · 30 Hz · 1.0 秒')
    fireEvent.click(screen.getByRole('checkbox', { name: /确认工作区/ }))
    fireEvent.click(screen.getByRole('button', { name: '对齐起点并真机回放' }))
    await waitFor(() => expect(postCommand).toHaveBeenLastCalledWith(
      '/api/datasets/local/episodes/episode/replay/start', { speed: .5, confirmMotion: true, participation: dualParticipation }))
    expect(screen.getByRole('radio', { name: '0.5 倍速' })).toBeDisabled()
  })

  it.each([
    ['stopping', 'controlled', '正在等待参与机械臂停轴反馈'],
    ['stopped', 'controlled', '已确认参与机械臂静止'],
    ['failed', 'emergency', '已请求硬件急停'],
  ])('显示后端回报的停车状态 %s/%s', async (phase, stopMode, message) => {
    vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ data: {
      phase, stopMode, active: phase === 'stopping', frame: 1, totalFrames: 30,
    } }) } as Response)
    render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="e" />)
    expect(await screen.findByRole('status')).toHaveTextContent(message)
    expect(postCommand).not.toHaveBeenCalled()
  })

  it('can stop an active replay belonging to another selected episode', async () => {
    vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ data: {
      phase: 'running', active: true, frame: 2, totalFrames: 30, datasetId: 'other', episodeId: 'old',
    } }) } as Response)
    vi.mocked(postCommand).mockResolvedValue({ data: { phase: 'stopped', active: false, frame: 2, totalFrames: 30 } })
    render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="new" />)
    await waitFor(() => expect(screen.getByRole('button', { name: '停止真机回放' })).toBeEnabled())
    fireEvent.click(screen.getByRole('button', { name: '停止真机回放' }))
    await waitFor(() => expect(postCommand).toHaveBeenCalledWith('/api/replay/stop', {}))
  })

  it.each([
    ['stopped', 'controlled', '已确认参与机械臂静止。'],
    ['failed', 'emergency', '停轴被控制卡拒绝'],
  ])('停止请求先超时，按实际运行片段的 %s 反馈更新提示', async (phase, stopMode, message) => {
    const running = { datasetId: 'other', episodeId: 'old', phase: 'running', active: true, frame: 2, totalFrames: 30 }
    let data = { ...running, stopMode: '', error: '' }
    vi.mocked(fetch).mockImplementation(async () => ({ ok: true, json: async () => ({ data }) }) as Response)
    vi.mocked(postCommand).mockRejectedValueOnce(new CommandTimeoutError('请求超时，执行结果未知'))
    render(<DatasetReplayPanel datasetId="local" episodeId="new" />)
    await screen.findByText('执行片段：other / old')
    fireEvent.click(screen.getByRole('button', { name: '停止真机回放' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('尚未确认停车')
    data = { ...data, phase, stopMode, active: false, error: phase === 'failed' ? message : '' }
    await screen.findByText(phase === 'failed' ? '失败' : '已停止')
    if (phase === 'failed') expect(screen.getByRole('alert')).toHaveTextContent(message)
    else expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText(message, { selector: phase === 'failed' ? 'strong' : 'p' })).toBeVisible()
    expect(postCommand).toHaveBeenCalledTimes(1)
  })

  it('停车已被轮询确认时，迟到的请求超时不覆盖最终状态', async () => {
    const running = { datasetId: 'local', episodeId: 'e', phase: 'running', active: true, frame: 2, totalFrames: 30 }
    let data = { ...running, stopMode: '' }
    vi.mocked(fetch).mockImplementation(async () => ({ ok: true, json: async () => ({ data }) }) as Response)
    let rejectStop!: (error: Error) => void
    vi.mocked(postCommand).mockImplementationOnce(() => new Promise((_, reject) => { rejectStop = reject }))
    render(<DatasetReplayPanel datasetId="local" episodeId="e" />)
    await screen.findByText('回放中')
    fireEvent.click(screen.getByRole('button', { name: '停止真机回放' }))
    data = { ...data, phase: 'stopped', stopMode: 'controlled', active: false }
    await screen.findByText('已确认参与机械臂静止。')
    await act(async () => rejectStop(new CommandTimeoutError('请求超时，执行结果未知')))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(postCommand).toHaveBeenCalledTimes(1)
  })

  it('停止请求超时而回放仍在运行时提示再次停止，回放结束后提示清除', async () => {
    let data = { runId: 'run', datasetId: 'local', episodeId: 'e', phase: 'running', active: true, frame: 2, totalFrames: 30 }
    vi.mocked(fetch).mockImplementation(async () => ({ ok: true, json: async () => ({ data }) }) as Response)
    vi.mocked(postCommand).mockRejectedValueOnce(new CommandTimeoutError('请求超时，执行结果未知'))
    render(<DatasetReplayPanel datasetId="local" episodeId="e" />)
    await screen.findByText('回放中')
    fireEvent.click(screen.getByRole('button', { name: '停止真机回放' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('请再次点击停止')
    expect(screen.getByRole('button', { name: '停止真机回放' })).toBeEnabled()
    data = { ...data, phase: 'completed', active: false, frame: 30 }
    await screen.findByText('已完成')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it.each(['success', 'timeout'])('同一片段已再次运行，上一轮停止请求迟到的 %s 应答不覆盖新状态', async (outcome) => {
    const first = { runId: 'first', datasetId: 'local', episodeId: 'e', phase: 'running', active: true, frame: 2, totalFrames: 30 }
    let data = first
    vi.mocked(fetch).mockImplementation(async () => ({ ok: true, json: async () => ({ data }) }) as Response)
    let finish!: () => void
    vi.mocked(postCommand).mockImplementationOnce(() => new Promise((resolve, reject) => {
      finish = () => outcome === 'timeout' ? reject(new CommandTimeoutError('超时'))
        : resolve({ data: { ...first, phase: 'stopped', active: false, stopMode: 'controlled' } })
    }))
    render(<DatasetReplayPanel datasetId="local" episodeId="e" />)
    await screen.findByText('回放中')
    const stop = screen.getByRole('button', { name: '停止真机回放' })
    fireEvent.click(stop)
    data = { ...first, runId: 'second', phase: 'following' }
    await screen.findByText('等待设备跟随')
    await act(async () => finish())
    expect(stop).toBeEnabled()
    expect(screen.getByText('等待设备跟随')).toBeVisible()
    expect(screen.queryByText(/已确认参与机械臂静止/)).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})

it('requires explicit legacy selection and resets validation after changing devices', async () => {
  vi.mocked(postCommand).mockResolvedValue({ data: { frames: 30, fps: 30, durationS: 1 } })
  render(<DatasetReplayPanel datasetId="legacy" episodeId="episode" />)
  await screen.findByText('待命')
  expect(postCommand).not.toHaveBeenCalled()
  fireEvent.click(screen.getByRole('checkbox', { name: '左臂' }))
  await screen.findByText('30 帧 · 30 Hz · 1.0 秒')
  expect(postCommand).toHaveBeenLastCalledWith('/api/datasets/legacy/episodes/episode/replay/inspect', {
    speed: .25, participation: { version: 'appstation.participation.v1', arms: ['left'], grippers: [] },
  })
  fireEvent.click(screen.getByRole('checkbox', { name: /确认工作区/ }))
  expect(screen.getByRole('button', { name: '对齐起点并真机回放' })).toBeEnabled()
  fireEvent.click(screen.getByRole('checkbox', { name: '左夹爪参与' }))
  expect(screen.getByRole('button', { name: '对齐起点并真机回放' })).toBeDisabled()
  expect(screen.getByRole('checkbox', { name: /确认工作区/ })).not.toBeChecked()
})


it('对齐超时直接展开未到位通道，不被长错误提示折叠', async () => {
  const detail = '目标位置对齐超时（30 秒，起点对齐）；以下参与通道未到位：\n'
    + '操作者右臂（硬件left）X：目标 100 μm，实际 75 μm，误差 25 μm，允许 10 μm\n'
    + '操作者右夹爪（硬件left）开口：目标 5 mm，实际 4 mm，误差 1 mm，允许 0.2 mm'
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: {
    phase: 'failed', active: false, frame: 0, totalFrames: 661, error: detail,
  } }) }))
  render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="episode" />)
  const alert = await screen.findByRole('alert')
  expect(alert.querySelector('details')).toHaveAttribute('open')
  expect(alert.querySelector('pre')).toHaveTextContent('误差 25 μm，允许 10 μm')
  expect(alert.querySelector('pre')).toHaveTextContent('右夹爪')
  expect(vi.mocked(postCommand).mock.calls.every(([path]) => path.endsWith('/inspect'))).toBe(true)
})

it('运行超限直接展开故障帧、目标反馈和采样时间', async () => {
  const detail = '实际位置偏离回放目标，已停止（跟踪偏差超限）\n'
    + '比较目标：第 48 帧 action；准备下发第 49 帧\n'
    + '操作者右臂（硬件left）Roll [超限]：目标 2.4516 °，实际 1.1 °，误差 1.3516 °，允许 1 °；反馈时间 2026-09-21T15:30:14.920+08:00'
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => ({ data: {
    phase: 'failed', active: false, frame: 48, totalFrames: 983, error: detail,
  } }) }))
  render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="episode" />)
  const alert = await screen.findByRole('alert')
  expect(alert.querySelector('details')).toHaveAttribute('open')
  expect(alert.querySelector('strong')).toHaveTextContent(detail.split('\n')[0])
  expect(alert.querySelector('pre')).toHaveTextContent('第 48 帧 action；准备下发第 49 帧')
  expect(alert.querySelector('pre')).toHaveTextContent('误差 1.3516 °，允许 1 °')
  expect(alert.querySelector('pre')).toHaveTextContent('反馈时间 2026-09-21T15:30:14.920+08:00')
  expect(vi.mocked(postCommand).mock.calls.every(([path]) => path.endsWith('/inspect'))).toBe(true)
})

it('shows final gripper warning alongside completed status without a failure alert', async () => {
  const warning = '末帧夹爪未到位（仅提示，不判定夹取成功或失败）：右夹爪误差 3.3 mm'
  vi.mocked(fetch).mockResolvedValue({ ok: true, json: async () => ({ data: {
    phase: 'completed', active: false, frame: 3, totalFrames: 3, datasetId: 'local', episodeId: 'e', warning,
  } }) } as Response)
  render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="e" />)
  expect(await screen.findByText(warning)).toBeInTheDocument()
  expect(screen.getByText('已完成')).toBeInTheDocument()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
})

it.each(['成功', '失败'])('改倍率后忽略旧请求迟到的%s结果', async (outcome) => {
  let finishOld!: () => void
  vi.mocked(postCommand).mockImplementationOnce(() => new Promise((resolve, reject) => {
    finishOld = () => outcome === '失败' ? reject(new Error('过期的错误'))
      : resolve({ data: { frames: 10, fps: 10, durationS: 1 } })
  })).mockResolvedValueOnce({ data: { frames: 40, fps: 10, durationS: 4, timing: { ...timing, requestedSpeed: 1 } } })
  render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="e" />)
  await waitFor(() => expect(postCommand).toHaveBeenCalledTimes(1))
  fireEvent.click(screen.getByRole('radio', { name: '1 倍速' }))
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 300)) })
  expect(postCommand).toHaveBeenCalledTimes(1)  // 旧预检未结束前不重复读取整段数据
  await act(async () => finishOld())
  await screen.findByText('40 帧 · 10 Hz · 4.0 秒')
  expect(screen.queryByText('10 帧 · 10 Hz · 1.0 秒')).not.toBeInTheDocument()
  expect(vi.mocked(postCommand).mock.calls[1][1]).toMatchObject({ speed: 1 })
  fireEvent.click(screen.getByRole('checkbox', { name: /确认工作区/ }))
  expect(screen.getByLabelText('回放时间规划')).toHaveTextContent('请求 1×')
  expect(screen.getByRole('checkbox', { name: /确认工作区/ })).toBeChecked()
  expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  expect(postCommand).toHaveBeenCalledTimes(2)
})

it('预检超时提示未发送运动命令', async () => {
  vi.mocked(postCommand).mockRejectedValueOnce(new CommandTimeoutError('请求超时，执行结果未知；请重新连接核验，禁止自动重发运动'))
  render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="e" />)
  expect(await screen.findByRole('alert')).toHaveTextContent('回放预检超时，未发送任何运动命令')
  expect(screen.queryByText(/禁止自动重发运动/)).not.toBeInTheDocument()
})

it('状态连接中断撤销确认，恢复后重新预检', async () => {
  vi.mocked(postCommand).mockResolvedValue({ data: { frames: 30, fps: 30, durationS: 1 } })
  render(<DatasetReplayPanel recordedParticipation={dualParticipation} datasetId="local" episodeId="e" />)
  await screen.findByText('30 帧 · 30 Hz · 1.0 秒')
  const confirmation = screen.getByRole('checkbox', { name: /确认工作区/ })
  fireEvent.click(confirmation)
  vi.mocked(fetch).mockRejectedValueOnce(new Error('断线'))
  expect(await screen.findByRole('alert')).toHaveTextContent('连接中断')
  expect(confirmation).not.toBeChecked()
  expect(confirmation).toBeDisabled()
  await waitFor(() => expect(confirmation).toBeEnabled(), { timeout: 2000 })
  expect(confirmation).not.toBeChecked()
  expect(postCommand).toHaveBeenCalledTimes(2)
})
