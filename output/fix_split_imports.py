from pathlib import Path
import re

base = Path(r'D:\E2EAPP_MicroMani\frontend\src\views\settings')

# strip trailing re-export lines
for name in ['CameraCard.tsx', 'ForceSensorCard.tsx', 'ManualControlPanel.tsx']:
    p = base / name
    t = p.read_text(encoding='utf-8')
    t2, n = re.subn(rf'/\*\* 渲染当前界面单元，并连接所需数据。 \*/\n\nexport \{{ {name[:-4]} \}}\n?', '', t)
    if n == 0:
        t2, n = re.subn(rf'\nexport \{{ {name[:-4]} \}}\n', '\n', t)
    print(name, 'strip', n)
    p.write_text(t2, encoding='utf-8')

# ForceSensorCard imports
p = base / 'ForceSensorCard.tsx'
t = p.read_text(encoding='utf-8')
t = t.replace(
    "import { Download, Waves } from 'lucide-react'\n",
    "import { Crosshair, Download, RotateCcw, Waves } from 'lucide-react'\n",
    1,
)
t = t.replace(
    "import { HardwareConfigCard, MetricBox } from './shared'\n",
    "import { HardwareConfigCard, MetricBox, commandLog } from './shared'\n",
    1,
)
t = t.replace('  forceSensorModelLabel,\n', '', 1)
p.write_text(t, encoding='utf-8')

# ManualControlPanel imports
p = base / 'ManualControlPanel.tsx'
t = p.read_text(encoding='utf-8')
t = t.replace(
    "import {\n  Pause,\n  Play,\n  PlugZap,\n  RotateCcw,\n  ShieldAlert,\n  Square,\n  Trash2,\n} from 'lucide-react'\n",
    "import {\n  Activity,\n  Pause,\n  Play,\n  PlugZap,\n  Save,\n  ShieldAlert,\n  Square,\n  Trash2,\n} from 'lucide-react'\nimport { useState } from 'react'\n",
    1,
)
t = t.replace(
    "import {\n  UiButton,\n  UiField,\n  UiNumber,\n  UiSelect,\n  UiSlider,\n  UiSpace,\n  UiTag,\n  UiText,\n  UiTitle,\n} from '../../components/ui'\n",
    "import {\n  UiButton,\n  UiField,\n  UiInput,\n  UiNumber,\n  UiSelect,\n  UiSpace,\n  UiTag,\n  UiText,\n  UiTitle,\n} from '../../components/ui'\n",
    1,
)
# add missing helpers after imports
anchor = "import { ManualGripperControl } from './GripperCards'\n"
extra = """
const sideOrder: RobotSide[] = ['left', 'right']

const defaultRotationWorkLimits: RotationWorkLimitSideConfig = {
  roll: { min: -100, max: 100 },
  pitch: { min: -100, max: 100 },
  yaw: { min: -7, max: 7 },
}

function commandErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error)
}
"""
if anchor in t and 'const sideOrder' not in t:
    t = t.replace(anchor, anchor + extra, 1)
p.write_text(t, encoding='utf-8')
print('fixed force+manual imports')
