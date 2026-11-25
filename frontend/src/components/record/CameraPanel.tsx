/*
 * 阅读导航 01｜入口与界面
 * 职责：组织录制页面的全局与双腕相机区域，复用相机预览组件。
 * 先看：CameraSlotProps → CameraSlot → CameraPanel。
 * 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。
 */
import { useRef } from 'react'
import { Maximize2, Microscope } from 'lucide-react'
import { Link } from 'react-router-dom'
import { microscopeFps } from '../../data'
import { useLiveCameraSnapshot } from '../../hooks/useLiveCameraSnapshot'
import { useTelemetryStore } from '../../stores/telemetry'
import type { AppConfig, CameraTelemetry } from '../../types'
import { UiCard, UiTag } from '../ui'

const cameraSpecs = {
  global: { label: '全局', title: '全局相机', model: 'IMX335' },
  wrist_left: { label: '左腕', title: '左腕相机', model: 'IMX335' },
  wrist_right: { label: '右腕', title: '右腕相机', model: 'IMX335' },
  microscope: { label: '显微', title: '显微相机', model: '4K UHD' },
} as const
/** 计算对应的业务值或展示值。 */
const cameraResolution = (config: AppConfig, kind: keyof typeof cameraSpecs) => {
  if (kind === 'microscope') return '3840×2160'
  if (kind === 'global') return config.cameras.globalResolution ?? config.cameras.previewResolution
  if (kind === 'wrist_left') return config.cameras.wristLeftResolution ?? config.cameras.previewResolution
  return config.cameras.wristRightResolution ?? config.cameras.previewResolution
}
/** 计算对应的业务值或展示值。 */
const getFpsColor = (hz: number) => {
  if (hz >= 25) return '#52c41a'
  if (hz >= 20) return '#E65100'
  return '#cf1322'
}

interface CameraSlotProps {
  kind: keyof typeof cameraSpecs
  camera: CameraTelemetry | undefined
  resolution: string
}
/** 渲染当前界面单元，并连接所需数据。 */
function CameraSlot({ kind, camera, resolution }: CameraSlotProps) {
  const slot = useRef<HTMLDivElement>(null)
  const spec = cameraSpecs[kind]
  const fps = camera?.fps ?? 0
  const { liveImageEnabled, previewHealth, snapshotUrl, handleLoad, handleError } = useLiveCameraSnapshot(kind, camera?.health)

  return (
    <div ref={slot} className={`record-camera-slot record-camera-${kind}`}>
      {liveImageEnabled && snapshotUrl && previewHealth !== 'warn' ? (
        <img
          className="record-camera-image"
          data-testid={`record-camera-image-${kind}`}
          src={snapshotUrl}
          alt={`${spec.title} live frame`}
          onLoad={handleLoad}
          onError={handleError}
        />
      ) : (
        <div className={`record-camera-placeholder record-camera-placeholder-${kind}`}>
          <div className="record-camera-placeholder-copy">
            <div>{spec.model}</div>
            <small>{camera ? '等待画面' : '无信号'}</small>
          </div>
        </div>
      )}

      {kind === 'microscope' && liveImageEnabled && snapshotUrl && previewHealth === 'ok' && document.fullscreenEnabled && (
        <button className="microscope-fullscreen" aria-label="切换显微画面全屏"
          onClick={() => void (document.fullscreenElement ? document.exitFullscreen() : slot.current?.requestFullscreen())?.catch(() => {})}>
          <Maximize2 size={15} />
        </button>
      )}
      <div className="record-camera-label">{spec.label}</div>
      <div className="record-camera-fps" style={{ color: getFpsColor(kind === 'microscope' ? fps * 30 / microscopeFps : fps) }}>
        {fps.toFixed(1)} Hz
      </div>
      <div className="record-camera-resolution">{resolution}</div>
    </div>
  )
}
/** 渲染当前界面单元，并连接所需数据。 */
export default function CameraPanel() {
  const cameras = useTelemetryStore((s) => s.frame.cameras)
  const config = useTelemetryStore((s) => s.config)
  const roles = Object.keys(cameraSpecs) as (keyof typeof cameraSpecs)[]

  return (
    <UiCard title="相机预览" bodyStyle={{ padding: 6 }} style={{ flexShrink: 0 }}>
      <div className="record-camera-layout">
        {roles.map((kind) => {
          const microscope = kind === 'microscope'
          const resolution = cameraResolution(config, kind)
          const camera = cameras.find((item) => item.key === kind)
          return (
            <div className="record-camera-panel" key={kind}>
              <div className="record-camera-meta-row">
                <span>{cameraSpecs[kind].title}</span>
                <UiTag>{microscope ? `4K · ${microscopeFps} fps` : resolution}</UiTag>
              </div>
              {microscope && !config.cameras.microscopeEnabled ? (
                <div className="record-camera-slot record-camera-microscope record-microscope-reserved">
                  <Microscope size={24} aria-hidden="true" />
                  <strong>显微通道待接入</strong>
                  <span>3840 × 2160 · {microscopeFps} fps</span>
                  <Link to="/settings#camera-microscope">配置显微相机</Link>
                </div>
              ) : <CameraSlot kind={kind} camera={camera} resolution={resolution} />}
            </div>
          )
        })}
      </div>
    </UiCard>
  )
}
