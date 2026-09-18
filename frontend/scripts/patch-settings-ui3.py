# -*- coding: utf-8 -*-
from pathlib import Path
import re

p = Path(r"D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx")
t = p.read_text(encoding="utf-8")

# Multiline Switch
t = re.sub(
    r'<Switch\s*\n(\s*)checked=\{([^}]+)\}\s*\n\s*checkedChildren="([^"]*)"\s*\n\s*unCheckedChildren="([^"]*)"\s*\n\s*onChange=\{([^}]+)\}\s*\n\s*/>',
    r'<UiSwitch checked={\2} checkedChildren="\3" unCheckedChildren="\4" onChange={\5} />',
    t,
)

# Multiline Slider
t = re.sub(
    r'<Slider\s*\n(\s*)min=\{([^}]+)\}\s*\n\s*max=\{([^}]+)\}\s*\n\s*step=\{([^}]+)\}\s*\n\s*value=\{([^}]+)\}\s*\n\s*onChange=\{([^}]+)\}\s*\n\s*/>',
    r'<UiSlider min={\2} max={\3} step={\4} value={\5} onChange={\6} />',
    t,
)

# UiText className type="secondary" leftover
t = t.replace('<UiText className="camera-tuning-control-label" type="secondary">', '<UiText secondary className="camera-tuning-control-label">')

p.write_text(t, encoding="utf-8")
print("Switch leftover", t.count('<Switch'))
print("Slider leftover", t.count('<Slider'))
print("type=\"secondary\"", t.count('type="secondary"'))
