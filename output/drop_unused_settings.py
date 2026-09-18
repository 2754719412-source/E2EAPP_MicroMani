from pathlib import Path
import re
p = Path(r'D:\E2EAPP_MicroMani\frontend\src\views\SettingsView.tsx')
text = p.read_text(encoding='utf-8')
text2, n1 = re.subn(
    r'/\*\* 格式化对应数值用于界面展示。 \*/\nfunction formatPulseList\(values: number\[\]\) \{.*?\n\}\n',
    '',
    text,
    count=1,
    flags=re.S,
)
print('formatPulseList', n1)
text3, n2 = re.subn(
    r'const softLimitRows = \[.*?\n\] as const\n',
    '',
    text2,
    count=1,
    flags=re.S,
)
print('softLimitRows', n2)
p.write_text(text3, encoding='utf-8')
