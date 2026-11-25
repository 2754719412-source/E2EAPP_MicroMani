import { useState } from 'react'
import { Microscope } from 'lucide-react'
import { microscopeFps } from '../../data'
import { microscopeCandidates } from '../../api'
import { CameraPreview } from '../../components/CameraPreview'
import { UiButton, UiField, UiSelect, UiSwitch, UiTag, UiText } from '../../components/ui'
import type { AppConfig, CameraTelemetry } from '../../types'
import { HardwareConfigCard } from './shared'

export function MicroscopeCameraCard({ config, camera, updateConfig, focusHash }: {
  config: AppConfig
  camera?: CameraTelemetry
  updateConfig: (patch: Partial<AppConfig>) => void
  focusHash: string
}) {
  const [devices, setDevices] = useState<{ identity: string; name: string }[]>([])
  const [notice, setNotice] = useState('')
  const [scanning, setScanning] = useState(false)
  const enabled = Boolean(config.cameras.microscopeEnabled)
  const identity = config.cameras.microscopeIdentity ?? ''
  const options = devices.map((device) => ({ value: device.identity, label: `${device.name} · ${device.identity}` }))
  if (identity && !devices.some((device) => device.identity === identity)) {
    options.push({ value: identity, label: identity })
  }
  const scan = async () => {
    setScanning(true)
    try {
      const results = await microscopeCandidates()
      setDevices(results)
      setNotice(results.length ? '' : '未发现可绑定的显微相机')
    } catch (error) {
      setNotice(error instanceof Error ? error.message : '显微设备扫描失败')
    } finally {
      setScanning(false)
    }
  }

  return (
    <HardwareConfigCard id="camera-microscope" focusHash={focusHash} icon={<Microscope size={20} />}
      title="显微成像单元" subtitle="observation.images.microscope" state={enabled ? camera?.health ?? 'pending' : 'pending'}
      badges={<UiTag>4K · {microscopeFps} fps</UiTag>}>
      <div className="hardware-form-grid ui-form">
        <UiField label="显微设备">
          <UiSelect value={identity} options={[{ value: '', label: '选择设备' }, ...options]} disabled={enabled}
            onChange={(value) => updateConfig({ cameras: { ...config.cameras, microscopeIdentity: value } })} />
        </UiField>
        <UiField label="设备识别">
          <UiButton loading={scanning} onClick={() => void scan()}>扫描显微设备</UiButton>
        </UiField>
        <UiField label="启用显微通道">
          <UiSwitch checked={enabled} disabled={!identity} checkedChildren="启用" unCheckedChildren="关闭"
            onChange={(value) => updateConfig({ cameras: { ...config.cameras, microscopeEnabled: value } })} />
        </UiField>
      </div>
      {notice && <p role="status">{notice}</p>}
      <UiText secondary>显微相机以 3840 × 2160、{microscopeFps} fps 采集。数据集按 {microscopeFps} fps 对齐，其他三路沿用各自的采集帧率。</UiText>
      {enabled && camera && <CameraPreview camera={camera} compact resolution="3840×2160" />}
    </HardwareConfigCard>
  )
}
