from pathlib import Path
p = Path(r'D:\E2EAPP_MicroMani\frontend\src\views\SettingsView.tsx')
text = p.read_text(encoding='utf-8')
lines = text.splitlines(keepends=True)

def find_line(prefix, start=0):
    for i, line in enumerate(lines[start:], start):
        if line.startswith(prefix):
            return i
    return -1

# Remove GripperCard block (function GripperCard through its closing at line before PicoVisionCard)
g_start = find_line('function GripperCard(')
p_start = find_line('function PicoVisionCard(')
# Remove ManualGripperControl (function ManualGripperControl through ManualMemoryRow)
m_start = find_line('function ManualGripperControl(')
mm_start = find_line('function ManualMemoryRow(')
print('gripper', g_start+1, p_start+1, 'manual', m_start+1, mm_start+1)

# delete manual first (later in file)
del lines[m_start:mm_start]
del lines[g_start:p_start]

text = ''.join(lines)
# add import after useGripperDisplay import
needle = "import { useGripperDisplay } from '../hooks/useGripperDisplay'\n"
if needle not in text:
    raise SystemExit('import needle missing')
text = text.replace(
    needle,
    needle + "import { GripperCard, ManualGripperControl } from './settings/GripperCards'\n",
    1,
)
p.write_text(text, encoding='utf-8')
print('new lines', len(text.splitlines()))
