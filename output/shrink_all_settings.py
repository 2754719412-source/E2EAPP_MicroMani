from pathlib import Path

p = Path(r'D:\E2EAPP_MicroMani\frontend\src\views\SettingsView.tsx')
lines = p.read_text(encoding='utf-8').splitlines(keepends=True)

def find_start(prefix):
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            return i
    raise SystemExit(f'not found {prefix}')

# delete blocks bottom-to-top by function start markers
# after each delete, line indices for earlier blocks remain valid

def del_range(start_prefix, end_prefix):
    global lines
    s = find_start(start_prefix)
    e = find_start(end_prefix)
    if e <= s:
        raise SystemExit(f'bad range {start_prefix} {end_prefix} {s} {e}')
    print(f'del {start_prefix} [{s+1}:{e}]')
    del lines[s:e]

# 1. Manual helpers+panels through SettingsView export
del_range('function manualAxisUnit(', 'export function SettingsView(')
# 2. TeleopHandCard through manualAxisUnit (already deleted manual - so Teleop ends at what was after it)
# After deleting manual, teleop is followed by export SettingsView if Teleop was last card
# Order in file: ... Force, Pico, Storage, Teleop, manual helpers, Manual*, SettingsView
# After step 1: ... Force, Pico, Storage, Teleop, SettingsView
del_range('function TeleopHandCard({', 'export function SettingsView(')
# 3. ForceSensorCard through PicoVisionCard
del_range('function ForceSensorCard({', 'function PicoVisionCard({')
# 4. CameraCard through ForceSensorCard
del_range('function CameraCard({', 'function ForceSensorCard({')
# 5. MotionCard through CameraCard
del_range('function MotionCard({', 'function CameraCard({')
# 6. RotationWorkLimitPanel through MotionCard
del_range('function RotationWorkLimitPanel({', 'function MotionCard({')
# 7. AxisMappingTable through RotationWorkLimitPanel
del_range('function AxisMappingTable({', 'function RotationWorkLimitPanel({')
# 8. GripperCard through PicoVisionCard (gripper was before pico in original? check)
# Original: GripperCard, PicoVisionCard - wait original was Gripper then Pico
# After previous: Hal, Safety, Pico, Storage, SettingsView
# Gripper was between Force and Pico originally. After force delete: Hal, Safety, Gripper?, Pico, Storage
# Original order: Camera, Force, Gripper, Pico, Storage, Teleop
# After camera+force: Hal, Safety, Gripper, Pico, Storage, Teleop, Settings
# GripperCard - check if still present
if any(l.startswith('function GripperCard(') for l in lines):
    del_range('function GripperCard({', 'function PicoVisionCard({')

text = ''.join(lines)
# insert imports after last import line from '../types' or similar
marker = "} from '../types'\n"
if marker not in text:
    raise SystemExit('types import missing')
text = text.replace(
    marker,
    marker
    + "import { GripperCard } from './settings/GripperCards'\n"
    + "import { MotionCard } from './settings/MotionCards'\n"
    + "import { TeleopHandCard } from './settings/TeleopHandCard'\n"
    + "import { CameraCard, type CameraKey } from './settings/CameraCard'\n"
    + "import { ForceSensorCard } from './settings/ForceSensorCard'\n"
    + "import { ManualControlPanel } from './settings/ManualControlPanel'\n",
    1,
)
p.write_text(text, encoding='utf-8')
print('final lines', len(text.splitlines()))
