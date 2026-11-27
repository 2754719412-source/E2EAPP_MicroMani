/*
 * 阅读导航 01｜入口与界面
 * 职责：用 Canvas 绘制历史遥测曲线；输入来自状态仓库的采样历史。
 * 先看：HistoryProps → LiveLineChart → JointChart → AxisGroupChart → ForceChart。
 * 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。
 */
import { memo, useEffect, useMemo, useRef } from 'react'
import type { JodellRow } from '../views/settings/useJodellCapture'
import { axisHues, axisNames, forceChannels } from '../data'
import { recentForceHistory } from '../forceDisplay'
import type { TelemetrySample } from '../types'

const axisText = '#7a8b9c'
const gridColor = '#e5e9f0'
const axisFont = '11px ui-monospace, Consolas, monospace'
const lineColor = '#d9e0e8'
// 曲线配色避开状态色（红、橙、绿），这些颜色只用于正常/注意/风险。
// X/Y/Z 与 Roll/Pitch/Yaw、Fx/Fy/Fz 与 Mx/My/Mz 按轴共用色相；力矩用虚线与力区分。
const palette = [...axisHues, '#6d4fc2', '#3d5a80', '#8a5a9e', '#5e7d8c', '#7a8b9c']
const referenceColor = '#7a8b9c'
const semanticAxes = ['X', 'Y', 'Z', 'Roll', 'Pitch', 'Yaw']

interface HistoryProps {
  history: TelemetrySample[]
  height?: number
}

interface SeriesSpec {
  name: string
  color: string
  values: number[]
  dashed?: boolean
}

interface LiveLineChartProps {
  series: SeriesSpec[]
  times?: number[]
  height?: number
  yUnit?: string
  yMin?: number
  yMax?: number
  showXLabels?: boolean
  testId?: string
  dataAttrs?: Record<string, string>
}

/** 轻量多序列折线图：直接在 Canvas 上绘制，避免 ECharts 在高频更新时的重渲染成本。 */
function LiveLineChart({
  series,
  times,
  height = 120,
  yUnit,
  yMin,
  yMax,
  showXLabels = false,
  testId = 'live-chart',
  dataAttrs,
}: LiveLineChartProps) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  const bounds = useMemo(() => {
    let min = Number.POSITIVE_INFINITY
    let max = Number.NEGATIVE_INFINITY
    for (const item of series) {
      for (const value of item.values) {
        if (!Number.isFinite(value)) continue
        if (value < min) min = value
        if (value > max) max = value
      }
    }
    if (!Number.isFinite(min) || !Number.isFinite(max)) {
      min = -1
      max = 1
    }
    if (min === max) {
      const pad = Math.abs(min) * 0.08 || 1
      min -= pad
      max += pad
    } else {
      const pad = (max - min) * 0.08
      min -= pad
      max += pad
    }
    return {
      min: typeof yMin === 'number' ? yMin : min,
      max: typeof yMax === 'number' ? yMax : max,
    }
  }, [series, yMin, yMax])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const draw = () => {
      const width = canvas.clientWidth
      const cssHeight = canvas.clientHeight
      if (!width || !cssHeight) return
      const dpr = window.devicePixelRatio || 1
      canvas.width = Math.max(1, Math.floor(width * dpr))
      canvas.height = Math.max(1, Math.floor(cssHeight * dpr))
      const ctx = canvas.getContext('2d')
      if (!ctx) return
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.clearRect(0, 0, width, cssHeight)

      const { min, max } = bounds
      const range = max - min || 1
      const yTicks = 4
      const tickLabels = Array.from({ length: yTicks + 1 }, (_, i) => {
        const value = min + range * (i / yTicks)
        return Math.abs(value) >= 10 ? value.toFixed(0) : value.toFixed(1)
      })
      ctx.font = axisFont
      // 左边距按最宽刻度留出，单位单独占顶部一行，避免与最上方刻度重叠。
      const labelWidth = Math.max(...tickLabels.map((label) => ctx.measureText(label).width))
      const padLeft = Math.max(28, Math.ceil(labelWidth) + 8)
      const padRight = 8
      const padTop = yUnit ? 20 : 6
      const padBottom = showXLabels ? 18 : 6
      const plotW = Math.max(1, width - padLeft - padRight)
      const plotH = Math.max(1, cssHeight - padTop - padBottom)

      // grid + y labels
      ctx.strokeStyle = gridColor
      ctx.lineWidth = 1
      ctx.fillStyle = axisText
      ctx.textAlign = 'right'
      ctx.textBaseline = 'middle'
      for (let i = 0; i <= yTicks; i += 1) {
        const y = padTop + plotH * (1 - i / yTicks)
        ctx.beginPath()
        ctx.moveTo(padLeft, y)
        ctx.lineTo(padLeft + plotW, y)
        ctx.stroke()
        ctx.fillText(tickLabels[i], padLeft - 4, y)
      }

      // x axis line
      ctx.strokeStyle = lineColor
      ctx.beginPath()
      ctx.moveTo(padLeft, padTop + plotH)
      ctx.lineTo(padLeft + plotW, padTop + plotH)
      ctx.stroke()

      // series
      for (const item of series) {
        const n = item.values.length
        if (n < 2) continue
        ctx.strokeStyle = item.color
        ctx.lineWidth = 1.4
        ctx.lineJoin = 'round'
        ctx.setLineDash(item.dashed ? [5, 3] : [])
        ctx.beginPath()
        let connected = false
        for (let i = 0; i < n; i += 1) {
          if (!Number.isFinite(item.values[i])) {
            connected = false
            continue
          }
          const fraction = times && times[n - 1] > times[0]
            ? (times[i] - times[0]) / (times[n - 1] - times[0]) : i / (n - 1)
          const x = padLeft + plotW * fraction
          const y = padTop + plotH * (1 - (item.values[i] - min) / range)
          if (connected) ctx.lineTo(x, y)
          else ctx.moveTo(x, y)
          connected = true
        }
        ctx.stroke()
      }
      ctx.setLineDash([])

      if (yUnit) {
        ctx.fillStyle = axisText
        ctx.font = axisFont
        ctx.textAlign = 'left'
        ctx.textBaseline = 'top'
        ctx.fillText(yUnit, 2, 2)
      }
    }

    draw()
    const ro = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(() => draw()) : null
    ro?.observe(canvas)
    return () => ro?.disconnect()
  }, [series, times, height, bounds, yUnit, showXLabels])

  return (
    <div
      data-testid={testId}
      style={{ width: '100%', height, display: 'grid', gridTemplateRows: 'auto minmax(0, 1fr)' }}
      {...dataAttrs}
    >
      <div style={{ display: 'flex', flexWrap: 'wrap', columnGap: 6, rowGap: 0, marginBottom: 2, minHeight: 14 }}>
        {series.map((item) => (
          <span
            key={item.name}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 3,
              fontSize: 10,
              color: 'var(--color-text-secondary)',
              fontWeight: 600,
            }}
          >
            <i style={item.dashed
              ? { width: 10, height: 2, background: `repeating-linear-gradient(90deg, ${item.color} 0 3px, transparent 3px 5px)`, display: 'inline-block' }
              : { width: 10, height: 2, background: item.color, display: 'inline-block' }} />
            {item.name}
          </span>
        ))}
      </div>
      <canvas ref={canvasRef} aria-label={yUnit} style={{ display: 'block', width: '100%', height: '100%', minHeight: 0, minWidth: 0 }} />
    </div>
  )
}

/** 渲染当前界面单元，并连接所需数据。 */
export const JointChart = memo(function JointChart({ history, height = 210 }: HistoryProps) {
  const series = useMemo(
    () =>
      axisNames.map((name, index) => ({
        name,
        color: palette[index % palette.length],
        values: history.map((sample) => sample.joints[index] ?? 0),
      })),
    [history],
  )
  return <LiveLineChart series={series} height={height} showXLabels />
})

/** 渲染当前界面单元，并连接所需数据。 */
export const AxisGroupChart = memo(function AxisGroupChart({
  history,
  side,
  group,
  height = 118,
}: HistoryProps & {
  side: 'left' | 'right'
  group: 'translation' | 'rotation'
}) {
  const series = useMemo(() => {
    const offset = side === 'left' ? 0 : 6
    const indexes = group === 'translation' ? [0, 1, 2] : [3, 4, 5]
    return indexes.map((axisIndex, i) => ({
      name: `${side === 'left' ? 'L' : 'R'}-${semanticAxes[axisIndex]}`,
      color: axisHues[i],
      values: history.map((sample) => sample.joints[offset + axisIndex] ?? 0),
    }))
  }, [history, side, group])
  return (
    <LiveLineChart
      series={series}
      height={height}
      yUnit={group === 'translation' ? 'µm' : '°'}
      dataAttrs={{ 'data-side': side, 'data-group': group }}
    />
  )
})

/** 渲染当前界面单元，并连接所需数据。 */
export const ForceChart = memo(function ForceChart({
  history,
  side,
  height = 220,
  voltage = false,
}: HistoryProps & { side: 'left' | 'right'; voltage?: boolean }) {
  const series = useMemo(() => {
    const scale = voltage ? 1 : 1000
    const samples = recentForceHistory(history, voltage, side)
    return forceChannels.map((name, index) => ({
      name,
      color: axisHues[index % 3],
      dashed: index >= 3,
      values: samples.map((sample) => (side === 'left' ? sample.forceLeft[index] : sample.forceRight[index]) * scale),
    }))
  }, [history, side, voltage])
  const fxJson = useMemo(() => JSON.stringify(series[0]?.values ?? []), [series])
  return (
    <LiveLineChart
      series={series}
      height={height}
      yUnit={voltage ? '未标定 · V' : '力 mN / 力矩 mN·m'}
      dataAttrs={{ 'data-side': side, 'data-fx': fxJson }}
    />
  )
})

/** 渲染当前界面单元，并连接所需数据。 */
export const QueueChart = memo(function QueueChart({ history, height = 160 }: HistoryProps) {
  const series = useMemo(
    () => [
      { name: '左臂队列', color: axisHues[0], values: history.map((sample) => sample.queueLeft) },
      { name: '右臂队列', color: axisHues[1], values: history.map((sample) => sample.queueRight) },
    ],
    [history],
  )
  return <LiveLineChart series={series} height={height} yMin={0} yMax={100} />
})

export const JodellOfficialChart = memo(function JodellOfficialChart({ rows }: { rows: JodellRow[] }) {
  const series = useMemo(() => [
    { name: '位置原码', color: '#1683d5', values: rows.map(row => row[1]) },
    { name: 'gCU 电流原码', color: '#598813', values: rows.map(row => row[2]) },
    { name: '速度原码', color: '#be7410', values: rows.map(row => row[3]) },
  ], [rows])
  const times = useMemo(() => {
    let offset = 0
    let previous = 0
    const stamps: number[] = []
    for (const [time] of rows) {
      const [h, m, s, ms] = time.split(/[:.]/).map(Number)
      const value = ((h * 60 + m) * 60 + s) * 1000 + ms
      if (previous - value > 12 * 3600 * 1000) offset += 24 * 3600 * 1000
      previous = value
      stamps.push(offset + value)
    }
    return stamps
  }, [rows])
  return <LiveLineChart series={series} times={times} height={170} yMin={0} yMax={255}
    testId="jodell-official-chart" dataAttrs={{ 'data-points': String(rows.length) }} />
})

/** 夹爪 gCU 电流原码曲线（0–255），可叠加标定得到的空载阈值参考线。 */
export const GripperCurrentChart = memo(function GripperCurrentChart({
  values,
  positions,
  thresholdRaw,
  height = 150,
  side,
}: {
  values: number[]
  positions: number[]
  thresholdRaw?: number | null
  height?: number
  side: 'left' | 'right'
}) {
  const series = useMemo(() => {
    // 固定 0–255 量程时左上角单位会与顶部刻度重叠，单位写进序列名。
    const items: SeriesSpec[] = [
      { name: '位置原码', color: '#1683d5', values: positions },
      { name: 'gCU 电流原码', color: '#598813', values },
    ]
    if (typeof thresholdRaw === 'number') {
      items.push({ name: '空载阈值', color: referenceColor, dashed: true, values: values.map(() => thresholdRaw) })
    }
    return items
  }, [values, positions, thresholdRaw])
  return (
    <LiveLineChart
      series={series}
      height={height}
      yMin={0}
      yMax={255}
      testId="gripper-current-chart"
      dataAttrs={{ 'data-side': side, 'data-points': String(values.length) }}
    />
  )
})
