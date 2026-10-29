import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { RecordQualityReport } from '../../types'
import QualityReportModal from './QualityReportModal'

afterEach(cleanup)

const routine = [
  'late frames: 1',
  'force latency summary: samples=449 warnings=5 avg=3.752ms max=15.0ms',
  'gripper settle timeout',
  'omega stale: 1',
]

function report(warnings: string[], codes: string[]): RecordQualityReport {
  return {
    index: 28, frameCount: 449, durationS: 15, status: 'ok', maxForceLeft: 0, maxForceRight: 0.4, lateFrames: 1,
    cameraDrops: { global: 0, wristLeft: 0, wristRight: 0 }, warnings, passed: false,
    qualityAssessment: {
      recommendation: codes.length ? 'review' : 'accept',
      reasons: codes.map((code) => ({ severity: 'review' as const, code, message: code })),
    },
  }
}

function feedbackTile() {
  return screen.getByText('参与设备反馈').parentElement?.textContent ?? ''
}

it('常规延迟统计和到位超时不再把参与设备反馈标成需复核', () => {
  render(<QualityReportModal open report={report(routine, [])} onReRecord={vi.fn()} onAccept={vi.fn()} />)
  expect(feedbackTile()).toContain('正常')
})

it('后端判对齐超限时参与设备反馈提示复核', () => {
  render(<QualityReportModal open report={report(routine, ['alignment_exceeded'])} onReRecord={vi.fn()} onAccept={vi.fn()} />)
  expect(feedbackTile()).toContain('需复核')
})

it('组帧拒绝等关键失效仍标异常', () => {
  render(<QualityReportModal open report={report([...routine, 'frame assembler recovered: 参与采集设备反馈无效'], [])} onReRecord={vi.fn()} onAccept={vi.fn()} />)
  expect(feedbackTile()).toContain('异常')
})

it('组帧延迟与相机帧率分别解释，29.2 FPS 不显示为低帧率', () => {
  const value = { ...report([], []), maxSkewMs: 75.081, cameraMinFps: { global: 29.2 } }
  render(<QualityReportModal open report={value} onReRecord={vi.fn()} onAccept={vi.fn()} />)
  const timing = screen.getByText('最大组帧延迟').parentElement?.textContent ?? ''
  expect(timing).toContain('75.1ms')
  expect(timing).toContain('计划组帧时刻')
  expect(timing).not.toContain('FPS')
  const camera = screen.getByText('相机异常率').parentElement?.textContent ?? ''
  expect(camera).toContain('最低 29.2 FPS（正常）')
})

it('相机帧率低于25时说明需复核，缺少帧率时不显示无穷值', () => {
  const { rerender } = render(<QualityReportModal open
    report={{ ...report([], []), cameraMinFps: { global: 24.9 } }} onReRecord={vi.fn()} onAccept={vi.fn()} />)
  expect(screen.getByText('相机异常率').parentElement?.textContent).toContain('最低 24.9 FPS（低于25，需复核）')
  rerender(<QualityReportModal open report={{ ...report([], []), cameraMinFps: {} }}
    onReRecord={vi.fn()} onAccept={vi.fn()} />)
  const camera = screen.getByText('相机异常率').parentElement?.textContent ?? ''
  expect(camera).not.toContain('Infinity')
  expect(camera).toContain('帧率未提供')
})
