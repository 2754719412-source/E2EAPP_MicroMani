from pathlib import Path

src_path = Path(r'D:\E2EAPP_MicroMani\frontend\src\views\SettingsView.tsx')
lines = src_path.read_text(encoding='utf-8').splitlines(keepends=True)

def sl(a, b):
    return ''.join(lines[a-1:b])

# ---- camera constants + card ----
camera_body = (
    'export type CameraKey = keyof typeof cameraHardwareSpecs\n\n'
    + sl(102, 102)  # cameraOrder
    + '\n'
    + sl(112, 140)  # defaultCameraTuning + exposure/gain/resolution
    + '\n'
    + sl(200, 204)  # cameraByKey
    + '\n'
    + sl(558, 794)  # CameraCard
)
camera_header = '''/*
 * 相机设置卡；从 SettingsView 按域拆出。
 * 先看：CameraCard。
 */
import { Camera, Download, FolderOpen, Play, RefreshCw, Save } from 'lucide-react'
import { useState } from 'react'
import * as appApi from '../../api'
import { applyCameraTuning, reconnectCamera, type CameraTelemetry } from '../../api'
import { CameraPreview } from '../../components/CameraPreview'
import {
  UiButton,
  UiField,
  UiNumber,
  UiSelect,
  UiSpace,
  UiSwitch,
  UiTag,
  UiText,
} from '../../components/ui'
import { refreshCameraStream } from '../../hooks/useLiveCameraSnapshot'
import { cameraHardwareSpecs } from '../../data'
import type {
  AppConfig,
  CameraTuningProfile,
  ConnectionState,
  LogEntry,
} from '../../types'
import { HardwareConfigCard, MetricBox, type PendingComparison } from './shared'

function commandErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}

'''
Path(r'D:\E2EAPP_MicroMani\frontend\src\views\settings\CameraCard.tsx').write_text(
    camera_header + camera_body + '\nexport { CameraCard }\n', encoding='utf-8')

# ---- force ----
force_body = (
    sl(103, 110)  # forceAxisCalibration* + fallbackForceAxisSigns
    + '\n'
    + sl(282, 300)  # formatForceValue, forceState
    + '\n'
    + sl(796, 1154)  # ForceSensorCard
)
force_header = '''/*
 * 六维力传感器设置卡；从 SettingsView 按域拆出。
 * 先看：ForceSensorCard。
 */
import { Download, Waves } from 'lucide-react'
import { useState } from 'react'
import { tareForceSensor } from '../../api'
import { ForceChart } from '../../components/Charts'
import {
  UiButton,
  UiField,
  UiInput,
  UiNumber,
  UiSelect,
  UiSpace,
  UiSwitch,
  UiTag,
  UiText,
} from '../../components/ui'
import {
  armHardwareSpecs,
  forceChannels,
  forceSensorModelLabel,
  hardwareSideForOperatorSide,
  nano17Spec,
  operatorSideLabel,
  semanticAxes,
  type RobotSide,
} from '../../data'
import { useTelemetryStore } from '../../stores/telemetry'
import type {
  AppConfig,
  LogEntry,
  TelemetryFrame,
} from '../../types'
import { HardwareConfigCard, MetricBox } from './shared'

'''
Path(r'D:\E2EAPP_MicroMani\frontend\src\views\settings\ForceSensorCard.tsx').write_text(
    force_header + force_body + '\nexport { ForceSensorCard }\n', encoding='utf-8')

# ---- manual ----
manual_body = (
    sl(83, 85)  # TRANSLATION constants
    + '\n'
    + sl(206, 281)  # soft limit helpers through displayAxisLimitForTelemetry
    + '\n'
    + sl(340, 346)  # manualAxisOrder + speedModeOptions
    + '\n'
    + sl(1394, 1847)  # manual helpers + panels
)
manual_header = '''/*
 * 手动点动 / 夹爪 / 动作回放面板；从 SettingsView 按域拆出。
 * 先看：ManualControlPanel → ManualArmControl → ManualReplayPanel。
 */
import {
  Pause,
  Play,
  PlugZap,
  RotateCcw,
  ShieldAlert,
  Square,
  Trash2,
} from 'lucide-react'
import {
  UiButton,
  UiField,
  UiNumber,
  UiSelect,
  UiSlider,
  UiSpace,
  UiTag,
  UiText,
  UiTitle,
} from '../../components/ui'
import { useMotionEnable } from '../../hooks/useMotionEnable'
import {
  armHardwareSpecs,
  hardwareSideForOperatorSide,
  operatorSideForHardwareSide,
  operatorSideLabel,
  type RobotSide,
} from '../../data'
import { manualAxisStepLimitFromPulse, manualAxisStepLimitPulse } from '../../manualMotionLimits'
import { manualMaxVelocity } from '../../manualSpeed'
import { mockMode, stopMotionSide } from '../../api'
import type {
  AppConfig,
  ArmSoftLimitConfig,
  LogEntry,
  ManualControlAction,
  ManualControlAxis,
  ManualControlMemory,
  ManualControlState,
  ManualGripperCommand,
  ManualSpeedMode,
  RotationWorkLimitSideConfig,
} from '../../types'
import { MetricBox, type PendingComparison } from './shared'
import { ManualGripperControl } from './GripperCards'

'''
Path(r'D:\E2EAPP_MicroMani\frontend\src\views\settings\ManualControlPanel.tsx').write_text(
    manual_header + manual_body + '\nexport { ManualControlPanel }\n', encoding='utf-8')

# export functions
for name, path in [
    ('CameraCard', 'CameraCard.tsx'),
    ('ForceSensorCard', 'ForceSensorCard.tsx'),
    ('ManualControlPanel', 'ManualControlPanel.tsx'),
    ('ManualArmControl', 'ManualControlPanel.tsx'),
    ('ManualMemoryRow', 'ManualControlPanel.tsx'),
    ('ManualReplayPanel', 'ManualControlPanel.tsx'),
]:
    p = Path(r'D:\E2EAPP_MicroMani\frontend\src\views\settings') / path
    t = p.read_text(encoding='utf-8')
    t = t.replace(f'function {name}(', f'export function {name}(', 1)
    p.write_text(t, encoding='utf-8')

print('camera', len(Path(r'D:\\E2EAPP_MicroMani\\frontend\\src\\views\\settings\\CameraCard.tsx').read_text(encoding='utf-8').splitlines()))
print('force', len(Path(r'D:\\E2EAPP_MicroMani\\frontend\\src\\views\\settings\\ForceSensorCard.tsx').read_text(encoding='utf-8').splitlines()))
print('manual', len(Path(r'D:\\E2EAPP_MicroMani\\frontend\\src\\views\\settings\\ManualControlPanel.tsx').read_text(encoding='utf-8').splitlines()))
