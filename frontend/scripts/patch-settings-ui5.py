# -*- coding: utf-8 -*-
from pathlib import Path
import re

p = Path(r"D:/E2EAPP_MicroMani/frontend/src/views/SettingsView.tsx")
t = p.read_text(encoding="utf-8")

# 1) snapshotMenu type
t = t.replace(
    "const snapshotMenu = (scope: ParameterSnapshotScope): MenuProps => {",
    "const snapshotMenu = (scope: ParameterSnapshotScope): { items: { key: string; label: React.ReactNode; disabled?: boolean }[]; onClick: (info: { key: string }) => void } => {",
)
t = t.replace("size=\"small\"\n                  type=\"text\"", "variant=\"text\"")

# 2) Dropdown -> details menu
t = t.replace(
    """        <Dropdown menu={snapshotMenu(snapshotScope)} trigger={['click']}>
          <UiButton icon={<RefreshCw size={15} />}>
            选择运动参数
          </UiButton>
        </Dropdown>""",
    """        <details className="ui-dropdown">
          <summary className="ui-btn"><RefreshCw size={15} />选择运动参数</summary>
          <div className="ui-dropdown-panel">
            {(snapshotMenu(snapshotScope).items).map((item) => (
              <button
                key={item.key}
                type="button"
                disabled={item.disabled}
                onClick={() => snapshotMenu(snapshotScope).onClick({ key: item.key })}
              >
                {item.label}
              </button>
            ))}
          </div>
        </details>""",
)
t = t.replace(
    """          <Dropdown menu={snapshotMenu('all')} trigger={['click']}>
            <UiButton icon={<RefreshCw size={16} />}>
              选择硬件快照
            </UiButton>
          </Dropdown>""",
    """          <details className="ui-dropdown">
            <summary className="ui-btn"><RefreshCw size={16} />选择硬件快照</summary>
            <div className="ui-dropdown-panel">
              {(snapshotMenu('all').items).map((item) => (
                <button
                  key={item.key}
                  type="button"
                  disabled={item.disabled}
                  onClick={() => snapshotMenu('all').onClick({ key: item.key })}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </details>""",
)

# 3) Radio calibration group
t = t.replace(
    """                            <div className="ui-segmented" role="radiogroup">
                              aria-label={`${operatorLabel}${axis}方向`}
                              buttonStyle="solid"
                              optionType="button"
                              value={axisSignDraft[index] ?? 1}
                              onChange={(event) => updateAxisSignDraft(index, Number(event.target.value))}
                            >
                              <Radio.Button value={1}>同向 +</Radio.Button>
                              <Radio.Button value={-1}>反向 −</Radio.Button>
                            </Radio.Group>""",
    """                            <div className="ui-segmented" role="radiogroup" aria-label={`${operatorLabel}${axis}方向`}>
                              <button
                                type="button"
                                role="radio"
                                aria-checked={(axisSignDraft[index] ?? 1) === 1}
                                className={(axisSignDraft[index] ?? 1) === 1 ? 'on' : ''}
                                onClick={() => updateAxisSignDraft(index, 1)}
                              >
                                同向 +
                              </button>
                              <button
                                type="button"
                                role="radio"
                                aria-checked={(axisSignDraft[index] ?? 1) === -1}
                                className={(axisSignDraft[index] ?? 1) === -1 ? 'on' : ''}
                                onClick={() => updateAxisSignDraft(index, -1)}
                              >
                                反向 −
                              </button>
                            </div>""",
)

# 4) Force calibration Modal
t = t.replace(
    """              <Modal
                title={`${operatorLabel} 六轴方向标定`}
                width={720}
                className="force-axis-calibration-modal"
                open={axisCalibrationOpen}
                onCancel={() => setAxisCalibrationOpen(false)}
                onOk={saveAxisCalibration}
                okText="保存标定\"""",
    """              {axisCalibrationOpen && (
              <div className="ui-modal-mask" role="presentation" onClick={() => setAxisCalibrationOpen(false)}>
                <div className="ui-modal force-axis-calibration-modal" style={{ width: 'min(720px, calc(100vw - 32px))' }} role="dialog" aria-label={`${operatorLabel} 六轴方向标定`} onClick={(event) => event.stopPropagation()}>
                <header className="ui-modal-head"><strong>{`${operatorLabel} 六轴方向标定`}</strong></header>
                <div className="ui-modal-body">""",
)
# closing of that modal - find </Modal> after calibration
t = t.replace(
    """              </Modal>
            </>
          )}
        </div>
      </div>
    </HardwareConfigCard>""",
    """                </div>
                <div className="ui-modal-actions">
                  <UiButton onClick={() => setAxisCalibrationOpen(false)}>取消</UiButton>
                  <UiButton variant="primary" onClick={saveAxisCalibration}>保存标定</UiButton>
                </div>
                </div>
              </div>
              )}
            </>
          )}
        </div>
      </div>
    </HardwareConfigCard>""",
)

# 5) Snapshot Modal
t = t.replace(
    """      <Modal
        title={snapshotDraft ? snapshotModalTitle(snapshotDraft.scope) : '保存参数快照'}
        open={Boolean(snapshotDraft)}
        onCancel={() => setSnapshotDraft(null)}
        onOk={commitSnapshot}
        okText="保存"
        cancelText="取消"
        okButtonProps={{ disabled: !snapshotDraft?.name.trim() }}
      >
        <div className="ui-form">
          <UiField label="快照名称">
            <UiInput               autoFocus
              value={snapshotDraft?.name ?? ''}
              onChange={(event) => setSnapshotDraft((current) => current ? { ...current, name: event.target.value } : current)}
              onPressEnter={commitSnapshot}
            />
          </UiField>
        </div>
      </Modal>""",
    """      {snapshotDraft && (
        <div className="ui-modal-mask" role="presentation" onClick={() => setSnapshotDraft(null)}>
          <div className="ui-modal" role="dialog" aria-label="保存参数快照" onClick={(event) => event.stopPropagation()}>
            <header className="ui-modal-head">
              <strong>{snapshotModalTitle(snapshotDraft.scope)}</strong>
            </header>
            <div className="ui-modal-body">
              <div className="ui-form">
                <UiField label="快照名称">
                  <input
                    className="ui-input"
                    autoFocus
                    value={snapshotDraft?.name ?? ''}
                    onChange={(event) => setSnapshotDraft((current) => current ? { ...current, name: event.target.value } : current)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') commitSnapshot()
                    }}
                  />
                </UiField>
              </div>
            </div>
            <div className="ui-modal-actions">
              <UiButton onClick={() => setSnapshotDraft(null)}>取消</UiButton>
              <UiButton variant="primary" disabled={!snapshotDraft?.name.trim()} onClick={commitSnapshot}>保存</UiButton>
            </div>
          </div>
        </div>
      )}""",
)

# 6) Tabs -> UiTabs + explicit children
# Replace <Tabs ... items={[ ... ]} /> structure:
# Change opening
t = t.replace(
    """      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          {
            key: 'system',
            label: '系统连接',
            children: activeTab === 'system' ? (""",
    """      <UiTabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          { key: 'system', label: '系统连接' },
          { key: 'force', label: '安全与力觉' },
          { key: 'motion', label: '运动控制' },
          { key: 'teleop', label: '遥操作' },
          { key: 'vision', label: '视觉' },
        ]}
      />
      {activeTab === 'system' ? (""",
)

# Fix subsequent item wrappers - these will be typecheck cleaned next
t = t.replace(
    """              </section>
            ) : null,
          },
          {
            key: 'force',
            label: '安全与力觉',
            children: activeTab === 'force' ? (""",
    """              </section>
            ) : null}
      {activeTab === 'force' ? (""",
)
t = t.replace(
    """              </section>
            ) : null,
          },
          {
            key: 'motion',
            label: '运动控制',
            children: activeTab === 'motion' ? (""",
    """              </section>
            ) : null}
      {activeTab === 'motion' ? (""",
)
t = t.replace(
    """              </section>
            ) : null,
          },
          {
            key: 'teleop',
            label: '遥操作',
            children: activeTab === 'teleop' ? (""",
    """              </section>
            ) : null}
      {activeTab === 'teleop' ? (""",
)
t = t.replace(
    """              </section>
            ) : null,
          },
          {
            key: 'vision',
            label: '视觉',
            children: activeTab === 'vision' ? (""",
    """              </section>
            ) : null}
      {activeTab === 'vision' ? (""",
)
t = t.replace(
    """              </section>
            ) : null,
          },
        ]}
      />""",
    """              </section>
            ) : null}""",
)

p.write_text(t, encoding="utf-8")
print("Dropdown", t.count("<Dropdown"))
print("Tabs", t.count("<Tabs"))
print("Modal", t.count("<Modal"))
print("Radio", t.count("Radio."))
print("MenuProps", t.count("MenuProps"))
