# -*- coding: utf-8 -*-
from pathlib import Path
import re

p = Path(r"D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx")
t = p.read_text(encoding="utf-8")

t = t.replace(
    "import { Button, Dropdown, Form, Input, InputNumber, Modal, Radio, Select, Slider, Space, Switch, Tabs, Tag, Typography, type MenuProps } from 'antd'\n",
    "import { UiButton, UiField, UiInput, UiNumber, UiSelect, UiSlider, UiSpace, UiSwitch, UiTabs, UiTag, UiText, UiTitle } from '../components/ui'\n",
)

# Typography
t = t.replace('<Typography.Title level={3}>', '<UiTitle level={3}>')
t = t.replace('<Typography.Title level={2}>', '<UiTitle level={2}>')
t = t.replace('</Typography.Title>', '</UiTitle>')
t = t.replace('<Typography.Text type="secondary" className=', '<UiText secondary className=')
t = t.replace('<Typography.Text type="secondary">', '<UiText secondary>')
t = t.replace('<Typography.Text type="warning">', '<UiTag tone="warning">')
t = t.replace('<Typography.Text type="danger">', '<UiTag tone="error">')
t = t.replace('<Typography.Text strong>', '<UiText strong>')
t = t.replace('<Typography.Text className=', '<UiText className=')
t = t.replace('<Typography.Text>', '<UiText>')
t = t.replace('</Typography.Text>', '</UiText>')

# Space
t = t.replace('<Space wrap size={6}>', '<UiSpace wrap size={6}>')
t = t.replace('<Space wrap className=', '<UiSpace wrap className=')
t = t.replace('<Space className=', '<UiSpace className=')
t = t.replace('<Space wrap>', '<UiSpace wrap>')
t = t.replace('<Space size={6} wrap>', '<UiSpace size={6} wrap>')
t = t.replace('<Space>', '<UiSpace>')
t = t.replace('</Space>', '</UiSpace>')

# Button
t = t.replace('<Button type="primary"', '<UiButton variant="primary"')
t = t.replace('<Button size="small"', '<UiButton')
t = t.replace('<Button danger', '<UiButton danger')
t = t.replace('<Button ', '<UiButton ')
t = t.replace('</Button>', '</UiButton>')

# Tag
t = t.replace('<Tag color=', '<UiTag tone=')
t = t.replace('<Tag>', '<UiTag>')
t = t.replace('</Tag>', '</UiTag>')

# Form.Item -> UiField (simple open/close)
t = re.sub(r'<Form\.Item\s+label=\{([^}]+)\}>', r'<UiField label={\1}>', t)
t = re.sub(r'<Form\.Item\s+label="([^"]+)"\s+tooltip="([^"]*)">', r'<UiField label="\1" tooltip="\2">', t)
t = re.sub(r'<Form\.Item\s+label="([^"]+)">', r'<UiField label="\1">', t)
t = re.sub(r'<Form\.Item\s+label=\{([^}]+)\}\s+key=\{([^}]+)\}>', r'<UiField label={\1} key={\2}>', t)
t = t.replace('</Form.Item>', '</UiField>')

# Form -> div
t = re.sub(r'<Form\s+layout="vertical"\s+className="([^"]*)">', r'<div className="\1 ui-form">', t)
t = re.sub(r'<Form\s+layout="vertical"\s+style=\{\{([^}]*)\}\}>', r'<div className="ui-form" style={{\1}}>', t)
t = t.replace('<Form layout="vertical">', '<div className="ui-form">')
t = t.replace('</Form>', '</div>')

# InputNumber -> UiNumber
t = t.replace('<InputNumber', '<UiNumber')

# Input -> UiInput (but not UiInputNumber already replaced)
t = re.sub(r'(?<!Ui)<Input\s', '<UiInput ', t)
t = re.sub(r'(?<!Ui)<Input>', '<UiInput>', t)

# Switch -> UiSwitch (drop checkedChildren/unCheckedChildren props into children if simple)
t = re.sub(
    r'<Switch\s+checked=\{([^}]+)\}\s+checkedChildren="([^"]*)"\s+unCheckedChildren="([^"]*)"\s+onChange=\{([^}]+)\}\s*/>',
    r'<UiSwitch checked={\1} checkedChildren="\2" unCheckedChildren="\3" onChange={\4} />',
    t,
)
t = t.replace('<Switch ', '<UiSwitch ')
t = t.replace('/>', '/>')  # no-op keep

# Select -> UiSelect
t = re.sub(r'(?<!Ui)<Select\s', '<UiSelect ', t)

# Slider -> UiSlider
t = t.replace('<Slider ', '<UiSlider ')

# Radio.Group / Radio.Button - leave for typecheck fixes if any remain

# Dropdown - convert to simple details/summary later if needed
# Tabs items - convert after

# MenuProps type import removed - fix snapshotMenu return type
t = t.replace('snapshotMenu: (scope: ParameterSnapshotScope) => MenuProps', 'snapshotMenu: (scope: ParameterSnapshotScope) => { items: { key: string; label: React.ReactNode }[]; onClick: (info: { key: string }) => void }')

p.write_text(t, encoding="utf-8")
print("done")
print("remaining antd", t.count("from 'antd'"))
print("Form", t.count('<Form'), t.count('Form.Item'))
print("InputNumber", t.count('InputNumber'))
print("Select", t.count('<Select'))
print("Switch", t.count('<Switch'))
print("Tabs", t.count('<Tabs'))
print("Modal", t.count('<Modal'))
print("Radio", t.count('Radio.'))
print("Dropdown", t.count('<Dropdown'))
print("Slider", t.count('<Slider'))
print("Button", t.count('<Button'))
print("Tag", t.count('<Tag'))
print("Typography", t.count('Typography'))
