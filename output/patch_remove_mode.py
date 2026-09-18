from pathlib import Path
p = Path(r'D:\E2EAPP_MicroMani\frontend\src\stores\telemetry.ts')
t = p.read_text(encoding='utf-8')
replacements = [
    ("  selectedMode: 'Record' | 'Auto' | 'Manual'\n", ''),
    ("  setMode: (mode: 'Record' | 'Auto' | 'Manual') => void\n", ''),
    ("  selectedMode: 'Record',\n", ''),
    ("  setMode: (mode) => set({ selectedMode: mode }),\n", ''),
]
for a, b in replacements:
    if a not in t:
        print('MISSING', repr(a[:60]))
    else:
        t = t.replace(a, b, 1)
        print('ok', repr(a[:50]))
p.write_text(t, encoding='utf-8')
print('done')
