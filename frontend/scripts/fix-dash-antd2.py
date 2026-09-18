# -*- coding: utf-8 -*-
from pathlib import Path

# ArmOverviewPanel tags
p = Path(r"D:/E2EAPP_MicroMani/frontend/src/components/dashboard/ArmOverviewPanel.tsx")
t = p.read_text(encoding="utf-8")
t = t.replace(
    "<Tag icon={<Camera size={13} />} color={camera?.health === 'ok' ? 'success' : 'default'}>腕相机</UiTag>",
    "<UiTag tone={camera?.health === 'ok' ? 'success' : 'muted'}>腕相机</UiTag>",
)
t = t.replace(
    "<Tag icon={<Hand size={13} />} color={gripState === 'ok' ? 'success' : 'default'}>夹爪 {gripperText}</UiTag>",
    "<UiTag tone={gripState === 'ok' ? 'success' : 'muted'}>夹爪 {gripperText}</UiTag>",
)
t = t.replace(
    "<Tag icon={<Gamepad2 size={13} />} color={teleopState === 'ok' ? 'success' : 'default'}>主手</UiTag>",
    "<UiTag tone={teleopState === 'ok' ? 'success' : 'muted'}>主手</UiTag>",
)
t = t.replace('<UiProgress percent={Math.min(100, forceNorm * 28)} size="small" status=', '<UiProgress percent={Math.min(100, forceNorm * 28)} status=')
p.write_text(t, encoding="utf-8")

# ModuleStatusGrid Space
p = Path(r"D:/E2EAPP_MicroMani/frontend/src/components/dashboard/ModuleStatusGrid.tsx")
t = p.read_text(encoding="utf-8")
t = t.replace('<Space className="module-status-footer" size={6}>', '<UiSpace className="module-status-footer" size={6} wrap>')
p.write_text(t, encoding="utf-8")

# PlatformOverview
p = Path(r"D:/E2EAPP_MicroMani/frontend/src/components/dashboard/PlatformOverview.tsx")
t = p.read_text(encoding="utf-8")
t = t.replace('<Space size={8}>', '<UiSpace size={8} wrap>')
t = t.replace('<UiProgress percent={Math.round(frame.resource.cpuPct)} size="small"', '<UiProgress percent={Math.round(frame.resource.cpuPct)}')
t = t.replace('<UiProgress percent={Math.max(frame.queueDepth.left, frame.queueDepth.right)} size="small" strokeColor="#d98400"', '<UiProgress percent={Math.max(frame.queueDepth.left, frame.queueDepth.right)} status="exception"')
t = t.replace('<UiTag tone={frame.halOk ? \'processing\' : \'error\'} icon={<Wrench size={13} />}>', '<UiTag tone={frame.halOk ? \'processing\' : \'error\'}>')
t = t.replace('<UiTag tone="default" icon={<Database size={13} />}>', '<UiTag tone="muted">')
p.write_text(t, encoding="utf-8")

# ReadinessSummary
p = Path(r"D:/E2EAPP_MicroMani/frontend/src/components/dashboard/ReadinessSummary.tsx")
t = p.read_text(encoding="utf-8")
t = t.replace(
    '<Statistic title="整体就绪度" value={score} suffix="%" />',
    '<div className="readiness-score"><small>整体就绪度</small><b>{score}%</b></div>',
)
t = t.replace('<UiProgress percent={score} size="small"', '<UiProgress percent={score}')
t = t.replace('<Space className="readiness-metrics" wrap size={8}>', '<UiSpace className="readiness-metrics" wrap size={8}>')
t = t.replace('<UiTag tone={warningCount > 0 ? \'warning\' : \'success\'} icon={<AlertTriangle size={13} />}>', '<UiTag tone={warningCount > 0 ? \'warning\' : \'success\'}>')
t = t.replace('<UiTag tone="processing" icon={<Activity size={13} />}>', '<UiTag tone="processing">')
p.write_text(t, encoding="utf-8")
print("fixed")
