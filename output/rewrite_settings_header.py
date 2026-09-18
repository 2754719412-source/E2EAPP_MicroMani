from pathlib import Path
p = Path(r'D:\E2EAPP_MicroMani\frontend\src\views\SettingsView.tsx')
text = p.read_text(encoding='utf-8')
lines = text.splitlines(keepends=True)

# find start of forceAxisCalibrationGroups (keep from there)
idx = next(i for i, l in enumerate(lines) if l.startswith('const forceAxisCalibrationGroups'))

header = '''/*
 * 阅读导航 01｜入口与界面
 * 职责：设置页壳层；硬件卡按域拆到 settings/ 子模块。
 * 先看：SettingsView → settings/*Cards。
 */
import { UiButton, UiField, UiInput, UiNumber, UiSelect, UiSpace, UiSwitch, UiTabs, UiTag, UiText, UiTitle } from '../components/ui'
import {
  AlertTriangle,
  Camera,
  FolderOpen,
  Network,
  Play,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldAlert,
  Square,
  Trash2,
  Usb,
} from 'lucide-react'
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { useLocation } from 'react-router-dom'
import { ActionCompareModal, type ActionCompareItem } from '../components/ActionCompareModal'
import * as appApi from '../api'
import {
  reconnectHal,
  fetchMotionOrigin,
  type MotionPreviousRestoreStatus,
} from '../api'
import {
  cameraHardwareSpecs,
  forceChannels,
  forceSensorModelLabel,
  hardwareSideForOperatorSide,
  operatorSideForHardwareSide,
  operatorSideLabel,
  semanticAxes,
  type RobotSide,
} from '../data'
import { numberArrayEqual, teleopHandFrameEqual, teleopHandFrameSlice, useFrameField } from '../stores/frameSelectors'
import { GripperCard } from './settings/GripperCards'
import { MotionCard } from './settings/MotionCards'
import { TeleopHandCard } from './settings/TeleopHandCard'
import { CameraCard, type CameraKey } from './settings/CameraCard'
import { ForceSensorCard } from './settings/ForceSensorCard'
import { ManualControlPanel } from './settings/ManualControlPanel'
import { useTelemetryStore } from '../stores/telemetry'
import type {
  AppConfig,
  ConnectionState,
  LogEntry,
  ParameterSnapshotScope,
  RotationWorkLimitSideConfig,
} from '../types'

const TRANSLATION_SOFT_LIMIT_DISABLED_MIN = -1000000000
const TRANSLATION_SOFT_LIMIT_DISABLED_MAX = 1000000000

const sideOrder: RobotSide[] = ['left', 'right']
const cameraOrder: CameraKey[] = ['global', 'wrist_left', 'wrist_right']
const forceAxisCalibrationAxes = semanticAxes.map((axis, index) => ({ axis, channel: forceChannels[index], index }))

'''
# drop unused const blocks after forceAxisCalibrationAxes if they exist in remainder
rest = ''.join(lines[idx:])
# remove unused camera/force constants that are now only in settings modules
import re
for pat in [
    r'const fallbackForceAxisSigns: Record<RobotSide, number\[\]> = \{.*?\n\}\n',
    r'const defaultCameraTuning: Record<CameraKey, CameraTuningProfile> = \{.*?\n\}\n',
    r'const cameraExposureMin = .*\n',
    r'const cameraExposureMax = .*\n',
    r'const cameraGainMin = .*\n',
    r'const cameraGainMax = .*\n',
    r'const previewResolutionOptions = \[.*?\n\] as const\n',
]:
    rest, n = re.subn(pat, '', rest, count=1, flags=re.S)
    print('drop', pat[:30], n)

# drop unused functions
for name in ['formatSoftLimitValue', 'displayAxisLimitForTelemetry', 'formatForceValue', 'forceState', 'displaySoftLimitValue']:
    rest, n = re.subn(
        rf'(?:/\*\*[^*]*\*/\n)*function {name}\([^)]*\)[^{{]*\{{.*?\n\}}\n',
        '',
        rest,
        count=1,
        flags=re.S,
    )
    print('dropfn', name, n)

rest = re.sub(r'const manualAxisOrder: ManualControlAxis\[\] = \[.*?\]\n', '', rest, count=1)
rest = re.sub(r'const speedModeOptions: \{ value: ManualSpeedMode; label: string \}\[\] = \[.*?\n\]\n', '', rest, count=1, flags=re.S)

p.write_text(header + rest, encoding='utf-8')
print('lines', len((header+rest).splitlines()))
