# -*- coding: utf-8 -*-
from pathlib import Path
import re

p = Path(r"D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx")
lines = p.read_text(encoding="utf-8").splitlines(True)

def replace_range(start_1, end_1, new_text):
    """start/end are 1-based inclusive line numbers."""
    global lines
    lines[start_1 - 1:end_1] = [new_text if new_text.endswith("\n") else new_text + "\n"]

# UiButton type= -> variant=
text = "".join(lines)
text = text.replace("type={active ? 'primary' : 'default'}", "variant={active ? 'primary' : 'default'}")
text = text.replace("type={gripperEnabled ? 'default' : 'primary'}", "variant={gripperEnabled ? 'default' : 'primary'}")
lines = text.splitlines(True)

# Switch blocks - find and replace by scanning
text = "".join(lines)
text = re.sub(
    r"<Switch\s+checked=\{([^}]+)\}\s+checkedChildren=\"([^\"]*)\"\s+unCheckedChildren=\"([^\"]*)\"\s+onChange=\{([^}]+)\}\s+/>",
    r"<UiSwitch checked={\1} checkedChildren=\"\2\" unCheckedChildren=\"\3\" onChange={\4} />",
    text,
    flags=re.S,
)
text = re.sub(
    r"<Switch\s+checked=\{([^}]+)\}\s+checkedChildren=\"([^\"]*)\"\s+unCheckedChildren=\"([^\"]*)\"\s+onChange=\{([^}]+)\}\s*\n\s*/>",
    r"<UiSwitch checked={\1} checkedChildren=\"\2\" unCheckedChildren=\"\3\" onChange={\4} />",
    text,
    flags=re.S,
)
# fallback: line-based Switch open tags
text = text.replace("<Switch\n", "<UiSwitch\n")
text = text.replace("<Slider\n", "<UiSlider\n")
text = text.replace("<Switch checked=", "<UiSwitch checked=")
text = text.replace("<Slider min=", "<UiSlider min=")
text = text.replace("<Slider className=", "<UiSlider className=")
# Slider props use value/onChange already

# Radio.Group -> segmented using UiSelect-like native buttons
text = text.replace(
    """<Radio.Group
""",
    """<div className="ui-segmented" role="radiogroup">
""",
)
# We'll handle Radio.Button lines manually after

p.write_text(text, encoding="utf-8")
print("Switch", text.count("<Switch"))
print("Slider", text.count("<Slider"))
