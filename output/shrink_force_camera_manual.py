from pathlib import Path
p = Path(r'D:\E2EAPP_MicroMani\frontend\src\views\SettingsView.tsx')
lines = p.read_text(encoding='utf-8').splitlines(keepends=True)

def find_start(prefix):
    for i, line in enumerate(lines):
        if line.startswith(prefix):
            return i
    raise SystemExit(f'not found {prefix}')

manual_panel = find_start('function ManualControlPanel({')
# delete manual helpers + panels from manualAxisUnit through end of ManualControlPanel
manual_helpers = find_start('function manualAxisUnit(')
settings = find_start('export function SettingsView(')
force = find_start('function ForceSensorCard({')
pico = find_start('function PicoVisionCard({')
camera = find_start('function CameraCard({')
force2 = find_start('function ForceSensorCard({')

print('manual_helpers', manual_helpers+1, settings+1)
print('force', force+1, pico+1)
print('camera', camera+1, force+1)

del lines[manual_helpers:settings]
del lines[force:pico]
del lines[camera:force]

text = ''.join(lines)
needle = "import { TeleopHandCard } from './settings/TeleopHandCard'\n"
add = (
    "import { CameraCard } from './settings/CameraCard'\n"
    "import { ForceSensorCard } from './settings/ForceSensorCard'\n"
    "import { ManualControlPanel } from './settings/ManualControlPanel'\n"
)
if needle not in text:
    raise SystemExit('needle missing')
text = text.replace(needle, needle + add, 1)
p.write_text(text, encoding='utf-8')
print('new lines', len(text.splitlines()))
