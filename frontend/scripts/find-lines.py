# -*- coding: utf-8 -*-
from pathlib import Path
t = Path(r"D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx").read_text(encoding="utf-8")
for i, line in enumerate(t.splitlines(), 1):
    if 'type="primary"' in line or "type=\"default\"" in line or 'readOnly' in line or 'disabled: true' in line or 'dmc_get_position' in line:
        print(i, line.strip()[:160])
