from pathlib import Path
src = Path(r'D:\E2EAPP_MicroMani\frontend\src\views\SettingsView.tsx').read_text(encoding='utf-8')
lines = src.splitlines(keepends=True)
# 1-indexed line ranges from earlier analysis
gripper = ''.join(lines[1843:2103])  # function GripperCard ... closing }
manual = ''.join(lines[2987:3086])   # function ManualGripperControl ... closing }
header = '''/*
 * 夹爪设置卡与手动夹爪控制；从 SettingsView 按域拆出。
 * 展示语义：请求启停 / 命令进度 / 反馈健康 三者分离。
 */
import { Hand, PlugZap, RotateCcw, Square } from 'lucide-react'
import type { ReactNode } from 'react'
import { UiButton, UiField, UiInput, UiNumber, UiSlider, UiSpace, UiSwitch, UiTag, UiText, UiTitle } from '../../components/ui'
import { useGripperDisplay } from '../../hooks/useGripperDisplay'
import {
  armHardwareSpecs,
  hardwareSideForOperatorSide,
  operatorSideLabel,
  type RobotSide,
} from '../../data'
import type {
  AppConfig,
  ConnectionState,
  LogEntry,
  ManualGripperCommand,
} from '../../types'
import {
  commandLog,
  formatGripperPosition,
  HardwareConfigCard,
  MetricBox,
  safeGripperPosition,
  type GripperPortHint,
  type InlineStatusTone,
  type PendingComparison,
} from './shared'

'''
out = header + gripper + '\n' + manual + '\n'
Path(r'D:\E2EAPP_MicroMani\frontend\src\views\settings\GripperCards.tsx').write_text(out, encoding='utf-8')
print('lines', len(out.splitlines()))
print('starts', out.splitlines()[20][:60] if len(out.splitlines())>20 else '')
print('has GripperCard', 'function GripperCard' in out)
print('has ManualGripper', 'function ManualGripperControl' in out)
