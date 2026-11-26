import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { defaultConfig } from '../../data'
import { calibrationOf, sampleOf } from '../../test/gripperForceFixtures'
import type { AppConfig, GripperStatus } from '../../types'
import { GripperForceCard } from './GripperForceCard'

afterEach(cleanup)

function statusWith(sample: ReturnType<typeof sampleOf> | null): GripperStatus {
  // 操作者左 = 硬件右
  return {
    command: { torque: 100, transport: 'modbus', sampleIntervalMs: 10 },
    sides: { right: { sample, sampleStats: { samples: 120, spanMs: 1190, effectiveHz: 99.9, maxGapMs: 14.2 } } },
  }
}

function renderCard(config: AppConfig, status: GripperStatus) {
  const updateConfig = vi.fn()
  const view = render(
    <GripperForceCard side="left" config={config} updateConfig={updateConfig} focusHash="" gripperStatus={status} />,
  )
  return { updateConfig, view, card: within(document.getElementById('force-gripper-left')!) }
}

describe('Jodell 夹爪力感知卡', () => {
  it('显示硬件右侧的读数和采样统计；未标定时不换算牛顿，力限制开关不可开启', () => {
    const config = structuredClone(defaultConfig)
    config.gripper.rightEnabled = true
    const { card } = renderCard(config, statusWith(sampleOf({ currentRaw: 200, gGTO: 1, gOBJ: 2, positionRaw: 128 })))
    const readings = card.getByLabelText('左臂夹爪当前读数')
    expect(readings).toHaveTextContent('gCU 电流原码200')
    expect(card.getByTestId('gripper-current-chart')).toHaveTextContent('位置原码')
    expect(card.getByTestId('gripper-current-chart')).toHaveTextContent('gCU 电流原码')
    expect(readings).toHaveTextContent('闭合时夹到物体')
    expect(readings).not.toHaveTextContent('估算夹持力')
    expect(card.getByText('99.9 Hz')).toBeInTheDocument()
    expect(card.getByText('14.2 ms')).toBeInTheDocument()
    expect(card.queryByText('命令力限制 N')).not.toBeInTheDocument()
    const head = document.querySelector('#force-gripper-left .hardware-config-card-head') as HTMLElement
    expect(within(head).getByText('未标定')).toBeInTheDocument()
    expect(readings).toHaveTextContent('空载阈值未标定')
    expect(card.getByRole('checkbox', { name: '按标定换算力限制' })).toBeDisabled()
  })

  it('有匹配标定时估算夹持力并给出 rFC 对应的牛顿值', () => {
    const config = structuredClone(defaultConfig)
    config.gripper.rightEnabled = true
    config.gripper.forceCalibration = {
      applyCommandForceLimit: false, left: null, right: calibrationOf({ port: 'COM9', slaveId: 9 }),
    }
    const { card } = renderCard(config, statusWith(sampleOf({ currentRaw: 100, gGTO: 1, gOBJ: 2 })))
    expect(card.getByLabelText('左臂夹爪当前读数')).toHaveTextContent('估算夹持力3.50 N')
    expect(card.getByText('约 3.50 N')).toBeInTheDocument()
    expect(card.getByRole('checkbox', { name: '按标定换算力限制' })).not.toBeDisabled()
  })

  it('电流曲线按 seq 累积，同一读数只画一次，seq 回退时清空', () => {
    const config = structuredClone(defaultConfig)
    const { view } = renderCard(config, statusWith(sampleOf({ seq: 1, currentRaw: 10 })))
    const points = () => screen.getByTestId('gripper-current-chart').getAttribute('data-points')
    expect(points()).toBe('1')
    const rerender = (seq: number) => view.rerender(
      <GripperForceCard side="left" config={config} updateConfig={vi.fn()} focusHash=""
        gripperStatus={statusWith(sampleOf({ seq, currentRaw: 10 + seq }))} />,
    )
    rerender(1)
    expect(points()).toBe('1')
    rerender(2)
    rerender(3)
    expect(points()).toBe('3')
    rerender(1)
    expect(points()).toBe('1')
  })

  it('DLL 读取时提示电流不可用；切换读取方式写入配置', () => {
    const config = structuredClone(defaultConfig)
    const status = statusWith(sampleOf({ currentValid: false, statusValid: false, transport: 'dll' }))
    status.command = { torque: 1, transport: 'dll', sampleIntervalMs: 33.3 }
    const { card, updateConfig } = renderCard(config, status)
    expect(card.getByText(/Vendor DLL 遥操作只读位置/)).toBeInTheDocument()
    expect(card.getByLabelText('左臂夹爪当前读数')).toHaveTextContent('gCU 电流原码不可用')
    fireEvent.change(card.getByLabelText('左臂夹爪读取方式'), { target: { value: 'modbus' } })
    expect(updateConfig).toHaveBeenCalledWith({ gripper: expect.objectContaining({ workerTransport: 'modbus' }) })
  })
})

describe('设置页接入', () => {
  it('#force-gripper-left 进入力传感器页并显示夹爪力感知卡', async () => {
    const { act } = await import('@testing-library/react')
    const { MemoryRouter } = await import('react-router-dom')
    const { SettingsView } = await import('../SettingsView')
    render(<MemoryRouter initialEntries={['/settings#force-gripper-left']}><SettingsView /></MemoryRouter>)
    await act(async () => { await Promise.resolve() })
    expect(document.getElementById('force-gripper-left')).not.toBeNull()
    expect(document.getElementById('force-gripper-right')).not.toBeNull()
    expect(screen.getByText('夹爪力感知')).toBeInTheDocument()
    expect(document.getElementById('force-gripper-left')).toBeVisible()
    expect(document.getElementById('force-gripper-right')).toBeVisible()
  })
})

it('COM9 官方采集与 COM8 的 HAL 电流同时显示，各自标注单位与端口', () => {
  const capture = { port: 'COM9', slaveId: 9, file: 'EPG.csv', sampledAt: Date.now(), live: true,
    samples: [['16:36:59.975', 242, 116, 0] as [string, number, number, number]] }
  const status = { sides: { left: { sample: sampleOf({ currentRaw: 37 }) } } }
  render(<>{(['left', 'right'] as const).map(side => <GripperForceCard key={side} side={side}
    gripperStatus={status} config={defaultConfig} updateConfig={vi.fn()} focusHash="" capture={capture} />)}</>)
  const left = within(document.getElementById('force-gripper-left')!)
  const right = within(document.getElementById('force-gripper-right')!)
  expect(left.getByTestId('jodell-official-chart')).toBeVisible()
  expect(left.getByLabelText('左臂夹爪当前读数')).toHaveTextContent('gCU 电流原码116')
  expect(right.queryByTestId('jodell-official-chart')).toBeNull()
  expect(right.getByLabelText('右臂夹爪当前读数')).toHaveTextContent('gCU 电流原码37')
  expect(left.getByLabelText('左臂夹爪当前读数')).toHaveTextContent('未标定')
  expect(right.getByLabelText('右臂夹爪当前读数')).toHaveTextContent('未标定')
})

it('两侧独立显示 HAL 电流，断样侧不把旧曲线或历史文件当作实时反馈', () => {
  const capture = { port: 'COM9', slaveId: 9, file: 'old.csv', sampledAt: 1, live: false,
    samples: [['17:00:00.000', 9, 173, 0] as [string, number, number, number]] }
  const config = structuredClone(defaultConfig)
  config.gripper.forceCalibration = { applyCommandForceLimit: false, left: calibrationOf(), right: null }
  const cards = (seq: number, valid: boolean) => (['left', 'right'] as const).map(side => (
    <GripperForceCard key={side} side={side} config={config} updateConfig={vi.fn()} focusHash="" capture={capture}
      gripperStatus={{ sides: { left: { sample: sampleOf({ seq, currentRaw: 100 }) },
        right: { sample: sampleOf({ seq, currentRaw: 0, currentValid: valid }) } } }} />
  ))
  const view = render(<>{cards(1, true)}</>)
  const left = within(document.getElementById('force-gripper-left')!)
  const right = within(document.getElementById('force-gripper-right')!)
  expect(left.getByLabelText('左臂夹爪当前读数')).toHaveTextContent('gCU 电流原码0')
  expect(right.getByLabelText('右臂夹爪当前读数')).toHaveTextContent('估算夹持力3.50 N')
  view.rerender(<>{cards(2, false)}</>)
  expect(left.getByLabelText('左臂夹爪当前读数')).toHaveTextContent('gCU 电流原码不可用')
  expect(left.getByTestId('gripper-current-chart')).toHaveAttribute('data-points', '0')
  expect(left.queryByText('估算夹持力')).not.toBeInTheDocument()
  expect(right.getByTestId('gripper-current-chart')).toHaveAttribute('data-points', '2')
  view.rerender(<>{cards(3, true)}</>)
  expect(left.getByTestId('gripper-current-chart')).toHaveAttribute('data-points', '1')
})
