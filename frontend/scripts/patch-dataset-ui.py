# -*- coding: utf-8 -*-
from pathlib import Path
import re

p = Path(r"D:/E2EAPP_MicroMani/frontend/src/views/DatasetView.tsx")
t = p.read_text(encoding="utf-8")

t = t.replace(
    "import { Button, Card, Checkbox, Empty, Form, Input, Modal, Popconfirm, Progress, Segmented, Slider, Space, Switch, Tag, Typography } from 'antd'\n",
    "import { UiButton, UiCard, UiProgress, UiSegmented, UiSpace, UiTag, UiText, UiTitle } from '../components/ui'\n",
)

# status tags
t = t.replace(
    """function statusTag(status: EpisodeStatus) {
  if (status === 'valid') return <Tag color="success">有效</Tag>
  if (status === 'invalid') return <Tag color="error">无效</Tag>
  return <Tag color="warning">待复核</Tag>
}""",
    """function statusTag(status: EpisodeStatus) {
  if (status === 'valid') return <UiTag tone="success">有效</UiTag>
  if (status === 'invalid') return <UiTag tone="error">无效</UiTag>
  return <UiTag tone="warning">待复核</UiTag>
}""",
)

# Typography
t = t.replace('<Typography.Title level={2}>', '<UiTitle level={2}>')
t = t.replace('<Typography.Title level={3}>', '<UiTitle level={3}>')
t = t.replace('</Typography.Title>', '</UiTitle>')
t = t.replace('<Typography.Text type="secondary">', '<UiText secondary>')
t = t.replace('<Typography.Text type="warning">', '<UiTag tone="warning">')
t = t.replace('</Typography.Text>', '</UiText>')

# Space
t = t.replace('<Space wrap>', '<UiSpace wrap>')
t = t.replace('<Space>', '<UiSpace>')
t = t.replace('</Space>', '</UiSpace>')

# Button -> UiButton with simple prop mapping
t = t.replace('<Button type="primary"', '<UiButton variant="primary"')
t = t.replace('<Button size="small"', '<UiButton')
t = t.replace('<Button danger', '<UiButton danger')
t = t.replace('<Button ', '<UiButton ')
t = t.replace('</Button>', '</UiButton>')

# Popconfirm delete -> confirm on click
t = t.replace(
    """              <Popconfirm title="删除该数据集？" okText="删除" cancelText="取消" onConfirm={() => deleteDataset(selectedDataset.id)}>
                <UiButton danger icon={<Trash2 size={14} />}>删除</UiButton>
              </Popconfirm>""",
    """              <UiButton
                danger
                icon={<Trash2 size={14} />}
                onClick={() => {
                  if (window.confirm('删除该数据集？')) deleteDataset(selectedDataset.id)
                }}
              >
                删除
              </UiButton>""",
)
t = t.replace(
    """                  <Popconfirm title="删除该条数据？" okText="删除" cancelText="取消" onConfirm={() => deleteEpisode(selectedEpisode.id)}>
                    <UiButton danger icon={<Trash2 size={14} />}>删除本条</UiButton>
                  </Popconfirm>""",
    """                  <UiButton
                    danger
                    icon={<Trash2 size={14} />}
                    onClick={() => {
                      if (window.confirm('删除该条数据？')) deleteEpisode(selectedEpisode.id)
                    }}
                  >
                    删除本条
                  </UiButton>""",
)

# Tag colors
t = t.replace('<Tag color="success">', '<UiTag tone="success">')
t = t.replace('<Tag color="error">', '<UiTag tone="error">')
t = t.replace('<Tag color="warning">', '<UiTag tone="warning">')
t = t.replace('<Tag color="processing">', '<UiTag tone="processing">')
t = t.replace('<Tag color={backendLoadError ? \'error\' : \'processing\'}>', '<UiTag tone={backendLoadError ? \'error\' : \'processing\'}>')
t = t.replace('<Tag color={hubMessage ? \'success\' : \'muted\'}>', '<UiTag tone="success">')
t = t.replace('<Tag color={hubPushToHub ? \'success\' : \'default\'}>', '<UiTag tone={hubPushToHub ? \'success\' : \'muted\'}>')
t = t.replace('<Tag color={dataset.status === \'待审核\' ? \'warning\' : \'processing\'}>', '<UiTag tone={dataset.status === \'待审核\' ? \'warning\' : \'processing\'}>')
t = t.replace('<Tag color={selectedEpisode.quality >= 85 ? \'success\' : \'warning\'}>', '<UiTag tone={selectedEpisode.quality >= 85 ? \'success\' : \'warning\'}>')
t = t.replace('<Tag>', '<UiTag>')
t = t.replace('</Tag>', '</UiTag>')

# Progress
t = t.replace(
    '<Progress percent={quality} size="small" showInfo={false} strokeColor={qualityTone(quality)} />',
    '<UiProgress percent={quality} status={quality >= 90 ? \'success\' : quality >= 80 ? \'active\' : \'exception\'} />',
)

# Card
t = t.replace('<Card size="small" title={title}>', '<UiCard title={title}>')
t = t.replace('</Card>', '</UiCard>')

# Empty
t = t.replace('<Empty description="请选择数据集和 episode" />', '<div className="empty">请选择数据集和 episode</div>')

# Segmented - keep value/options/onChange shape
t = t.replace('<Segmented', '<UiSegmented')

# Slider -> range input
t = re.sub(
    r'<Slider\s*\n(\s*)min=\{([^}]+)\}\s*\n\s*max=\{([^}]+)\}\s*\n\s*value=\{([^}]+)\}\s*\n\s*onChange=\{([^}]+)\}\s*\n(\s*)/>',
    r'<input type="range" className="ui-range" min={\2} max={\3} value={\4} onChange={(event) => \5(Number(event.target.value))} />',
    t,
)

# Modal footer array pattern - rewrite hub upload modal later if typecheck fails
# Switch
t = t.replace(
    '<Switch\n              checked={hubPushToHub}\n              onChange={setHubPushToHub}\n            />',
    '''<label className="ui-switch">
              <input type="checkbox" checked={hubPushToHub} onChange={(event) => setHubPushToHub(event.target.checked)} />
              <span />
            </label>''',
)

# Form layout - leave Form.Item for now if complex; remove import already done
# Replace remaining Form with div if any
if 'Form' in t.split('return (')[1][:500] if 'return (' in t else False:
    pass

# Checkbox
t = t.replace(
    '<Checkbox checked={hubPrivate} onChange={(event) => setHubPrivate(event.target.checked)}>Private</Checkbox>',
    '<label className="ui-checkbox"><input type="checkbox" checked={hubPrivate} onChange={(event) => setHubPrivate(event.target.checked)} />Private</label>',
)
t = t.replace(
    '<Checkbox checked={hubDryRun} onChange={(event) => setHubDryRun(event.target.checked)}>Dry-run</Checkbox>',
    '<label className="ui-checkbox"><input type="checkbox" checked={hubDryRun} onChange={(event) => setHubDryRun(event.target.checked)} />Dry-run</label>',
)

# Input
t = t.replace('<Input.Password', '<input type="password" className="ui-input"')
t = t.replace('<Input\n', '<input\n className="ui-input"\n')
t = t.replace('<Input ', '<input className="ui-input" ')

p.write_text(t, encoding="utf-8")
print("remaining antd tokens:", t.count('from \'antd\''), t.count('<Tag'), t.count('<Button'), t.count('<Card'), t.count('<Modal'), t.count('<Form'), t.count('<Input'), t.count('<Switch'), t.count('<Popconfirm'), t.count('<Empty'), t.count('<Segmented'), t.count('<Slider'), t.count('<Checkbox'), t.count('<Progress'), t.count('<Typography'), t.count('<Space'))
