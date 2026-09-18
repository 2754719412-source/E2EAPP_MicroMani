from pathlib import Path

src_path = Path(r'D:\E2EAPP_MicroMani\frontend\src\views\SettingsView.tsx')
lines = src_path.read_text(encoding='utf-8').splitlines(keepends=True)

def slice_lines(start_1, end_1_inclusive):
    return ''.join(lines[start_1 - 1:end_1_inclusive])

# Motion domain: helpers + AxisMappingTable + RotationWorkLimitPanel + MotionCard
# helpers 182-335 (commandErrorMessage through displayAxisLimitForTelemetry)
# AxisMappingTable 624-759, RotationWorkLimitPanel 760-869, MotionCard 871-1228
motion_body = (
    slice_lines(182, 190) + '\n'  # commandErrorMessage, originDriftFromError start
    + slice_lines(186, 221) + '\n'  # originDrift.. formatWorkOriginPosition
    + slice_lines(253, 335) + '\n'  # formatAxisValue through displayAxisLimitForTelemetry
    + slice_lines(624, 1228)
)

# cleaner: take 182-221 and 253-335 and 624-1228
motion_body = slice_lines(182, 221) + '\n' + slice_lines(253, 335) + '\n' + slice_lines(624, 1228)

motion_header = '''/*
 * 运动控制卡 + 轴映射 + 旋转工作限；从 SettingsView 按域拆出。
 * 先看：MotionCard → AxisMappingTable → RotationWorkLimitPanel。
 */
import { Crosshair, PlugZap, RefreshCw, ShieldAlert, Usb } from 'lucide-react'
import type { ReactNode } from 'react'
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
import { useMotionEnable } from '../../hooks/useMotionEnable'
import {
  armHardwareSpecs,
  hardwareSideForOperatorSide,
  motionCardModelByNo,
  operatorSideLabel,
  type RobotSide,
} from '../../data'
import type { MotionPreviousRestoreStatus } from '../../api'
import type {
  AppConfig,
  ArmMotionProfile,
  ArmSoftLimitConfig,
  ConnectionState,
  LogEntry,
  MotionOriginConfig,
  ParameterSnapshotScope,
  RotationWorkLimitSideConfig,
} from '../../types'
import { HardwareConfigCard, MetricBox, type PendingComparison } from './shared'

const TRANSLATION_SOFT_LIMIT_DISABLED_MIN = -1000000000
const TRANSLATION_SOFT_LIMIT_DISABLED_MAX = 1000000000

'''

motion_out = motion_header + motion_body + '\nexport { MotionCard }\n'
# export the functions we need
motion_out = motion_out.replace('function MotionCard({', 'export function MotionCard({', 1)
Path(r'D:\E2EAPP_MicroMani\frontend\src\views\settings\MotionCards.tsx').write_text(motion_out, encoding='utf-8')

# Teleop: physicalText 249-251, inlineToneFromState 238-243, TeleopHandCard 2065-2475
teleop_body = slice_lines(238, 252) + '\n' + slice_lines(2065, 2475)
teleop_header = '''/*
 * Omega.7 主手设置卡；从 SettingsView 按域拆出。
 * 先看：TeleopHandCard。
 */
import {
  Gamepad2,
  PlugZap,
  RotateCcw,
} from 'lucide-react'
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
  hardwareSideForOperatorSide,
  operatorSideForHardwareSide,
  operatorSideLabel,
  type RobotSide,
} from '../../data'
import { motionSideReturnOriginReady } from '../../motionReturnReady'
import type { TeleopHandFrameSlice } from '../../stores/frameSelectors'
import type {
  AppConfig,
  ConnectionState,
  LogEntry,
} from '../../types'
import { HardwareConfigCard, MetricBox, type InlineStatusTone } from './shared'

'''
teleop_out = teleop_header + teleop_body + '\n'
teleop_out = teleop_out.replace('function TeleopHandCard({', 'export function TeleopHandCard({', 1)
Path(r'D:\E2EAPP_MicroMani\frontend\src\views\settings\TeleopHandCard.tsx').write_text(teleop_out, encoding='utf-8')

print('motion lines', len(motion_out.splitlines()))
print('teleop lines', len(teleop_out.splitlines()))
print('motion has MotionCard', 'export function MotionCard' in motion_out)
print('teleop has TeleopHandCard', 'export function TeleopHandCard' in teleop_out)
