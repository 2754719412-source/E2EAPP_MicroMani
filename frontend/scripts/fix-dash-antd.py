# -*- coding: utf-8 -*-
from pathlib import Path
import re

base = Path(r"D:/E2EAPP_MicroMani/frontend/src/components/dashboard")
for name in ["ArmOverviewPanel.tsx", "ModuleStatusGrid.tsx", "PlatformOverview.tsx", "ReadinessSummary.tsx"]:
    p = base / name
    t = p.read_text(encoding="utf-8")
    t = t.replace(
        "import { Progress, Space, Tag } from 'antd'\n",
        "import { UiProgress, UiSpace, UiTag } from '../ui'\n",
    )
    t = t.replace(
        "import { Button, Progress, Space, Tag, Typography } from 'antd'\n",
        "import { UiButton, UiProgress, UiSpace, UiTag, UiText, UiTitle } from '../ui'\n",
    )
    t = t.replace(
        "import { Button, Space, Tag, Typography } from 'antd'\n",
        "import { UiButton, UiSpace, UiTag, UiText } from '../ui'\n",
    )
    t = t.replace(
        "import { Progress, Space, Statistic, Tag, Typography } from 'antd'\n",
        "import { UiProgress, UiSpace, UiTag, UiText, UiTitle } from '../ui'\n",
    )
    t = t.replace('<Typography.Title level={3}>', '<UiTitle level={3}>')
    t = t.replace('<Typography.Title level={2}>', '<UiTitle level={2}>')
    t = t.replace('</Typography.Title>', '</UiTitle>')
    t = t.replace('<Typography.Text type="secondary">', '<UiText secondary>')
    t = t.replace('<Typography.Text strong>', '<UiText strong>')
    t = t.replace('</Typography.Text>', '</UiText>')
    t = t.replace('<Space wrap>', '<UiSpace wrap>')
    t = t.replace('<Space size={6} wrap>', '<UiSpace size={6} wrap>')
    t = t.replace('<Space>', '<UiSpace>')
    t = t.replace('</Space>', '</UiSpace>')
    t = t.replace('<Button type="primary"', '<UiButton variant="primary"')
    t = t.replace('<Button size="small"', '<UiButton')
    t = t.replace('<Button danger', '<UiButton danger')
    t = t.replace('<Button ', '<UiButton ')
    t = t.replace('</Button>', '</UiButton>')
    t = t.replace('<Tag color=', '<UiTag tone=')
    t = t.replace('<Tag>', '<UiTag>')
    t = t.replace('</Tag>', '</UiTag>')
    t = t.replace('<Progress ', '<UiProgress ')
    # Statistic only in ReadinessSummary
    t = t.replace(
        "import { Statistic",
        "import { Statistic",
    )
    p.write_text(t, encoding="utf-8")
    print(name, "antd", t.count("from 'antd'"), "Statistic", t.count("Statistic"))
