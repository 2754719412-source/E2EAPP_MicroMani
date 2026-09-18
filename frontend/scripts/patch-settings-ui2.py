# -*- coding: utf-8 -*-
from pathlib import Path
import re

p = Path(r"D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx")
t = p.read_text(encoding="utf-8")

# Multiline / remaining Button open tags
t = t.replace('<Button\n', '<UiButton\n')
t = t.replace('<Button\r\n', '<UiButton\n')
# already closed with </UiButton> hopefully; any leftover </Button> none

# Typography remaining
t = t.replace(
    "<Typography.Text type={previousRestoreReady ? 'secondary' : 'danger'}>",
    "<UiTag tone={previousRestoreReady ? 'muted' : 'error'}>",
)
t = t.replace(
    '<Typography.Text type="secondary" style={{ fontSize: 12 }}>',
    '<UiText secondary style={{ fontSize: 12 }}>',
)
t = t.replace('</Typography.Text>', '</UiText>')

# Space.Compact -> UiSpace
t = t.replace('<Space.Compact block>', '<UiSpace wrap>')
t = t.replace('<Space.Compact>', '<UiSpace wrap>')
t = t.replace('</Space.Compact>', '</UiSpace>')
t = t.replace('<Space size={8} wrap>', '<UiSpace size={8} wrap>')
t = t.replace('<Space size={6}>', '<UiSpace size={6}>')
t = t.replace('</Space>', '</UiSpace>')

# Form.Item with template label
t = re.sub(r'<Form\.Item\s+label=\{`([^`]+)`\}>', r'<UiField label={`\1`}>', t)
t = t.replace('<Form.Item label="曝光 / 增益" className="camera-tuning-span">', '<UiField label="曝光 / 增益" className="camera-tuning-span">')
t = t.replace('</Form.Item>', '</UiField>')

# Switch remaining simple
t = re.sub(
    r'<Switch\s+checked=\{([^}]+)\}\s+onChange=\{([^}]+)\}\s*/>',
    r'<UiSwitch checked={\1} onChange={\2} />',
    t,
)
t = t.replace('<Switch checked=', '<UiSwitch checked=')

# Slider
t = t.replace('<Slider ', '<UiSlider ')
t = t.replace('/>', '/>')

# Select already partially done
t = t.replace('<Select\n', '<UiSelect\n')
t = t.replace('<Select ', '<UiSelect ')

# Radio.Group + Button -> simple select-like segmented using native
# Leave Radio for next pass after typecheck

p.write_text(t, encoding="utf-8")
print("Button", t.count('<Button'))
print("Space", t.count('<Space'))
print("Typography", t.count('Typography'))
print("Form", t.count('<Form'))
print("Switch", t.count('<Switch'))
print("Slider", t.count('<Slider'))
print("Select", t.count('<Select'))
print("InputNumber", t.count('InputNumber'))
