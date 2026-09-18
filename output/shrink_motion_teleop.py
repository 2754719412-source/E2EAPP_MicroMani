from pathlib import Path
p = Path(r'D:\E2EAPP_MicroMani\frontend\src\views\SettingsView.tsx')
lines = p.read_text(encoding='utf-8').splitlines(keepends=True)

def find_start(prefix):
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            return i
    raise SystemExit(f'not found: {prefix}')

# delete from bottom to top
teleop = find_start('function TeleopHandCard({')
teleop_end = find_start('function manualAxisUnit(')
motion = find_start('function MotionCard({')
motion_end = find_start('function CameraCard({')
rot = find_start('function RotationWorkLimitPanel({')
rot_end = motion  # MotionCard follows
axis = find_start('function AxisMappingTable({')
axis_end = rot

print('teleop', teleop+1, teleop_end+1)
print('motion', motion+1, motion_end+1)
print('rot', rot+1, rot_end+1)
print('axis', axis+1, axis_end+1)

del lines[teleop:teleop_end]
del lines[motion:motion_end]
del lines[rot:rot_end]
del lines[axis:axis_end]

text = ''.join(lines)
# add imports after GripperCards import
needle = "import { GripperCard, ManualGripperControl } from './settings/GripperCards'\n"
add = (
    "import { MotionCard } from './settings/MotionCards'\n"
    "import { TeleopHandCard } from './settings/TeleopHandCard'\n"
)
if needle not in text:
    raise SystemExit('needle missing')
text = text.replace(needle, needle + add, 1)
p.write_text(text, encoding='utf-8')
print('new lines', len(text.splitlines()))
