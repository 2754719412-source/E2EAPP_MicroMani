/*
 * 阅读导航 01｜入口与界面
 * 职责：装配录制页面：相机、控制、遥测、预检查、质量报告和历史记录。
 * 先看：RecordPage。
 * 全局阅读顺序与关联文件：docs/CODE_READING_GUIDE.md；逐文件目录：docs/SOURCE_INDEX.md。
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import CameraPanel from '../components/record/CameraPanel'
import EpisodeControlPanel from '../components/record/EpisodeControlPanel'
import EpisodeHistoryCard from '../components/record/EpisodeHistoryCard'
import HardwareStatusCard from '../components/record/HardwareStatusCard'
import KalmanFilterCard from '../components/record/KalmanFilterCard'
import PreCheckModal from '../components/record/PreCheckModal'
import QualityReportModal from '../components/record/QualityReportModal'
import RecordTelemetryPanel from '../components/record/RecordTelemetryPanel'
import SafetyMonitorCard from '../components/record/SafetyMonitorCard'
import { useTelemetryStore } from '../stores/telemetry'
const recordActionKeys: Readonly<Record<string, string | undefined>> = {
  ' ': 'advance', ArrowRight: 'advance', ArrowLeft: 'discard', Escape: 'finish',
}

/** 渲染当前界面单元，并连接所需数据。 */
export default function RecordPage() {
  const pageRef = useRef<HTMLDivElement>(null)
  const [preCheckVisible, setPreCheckVisible] = useState(false)

  const latestReport = useTelemetryStore((s) => s.recordSession.latestQualityReport)
  const datasetName = useTelemetryStore((s) => s.recordSession.datasetName)
  const task = useTelemetryStore((s) => s.recordSession.task)
  const startRecordSession = useTelemetryStore((s) => s.startRecordSession)
  const toggleRecordClutch = useTelemetryStore((s) => s.toggleRecordClutch)
  const setRecordSpeedMode = useTelemetryStore((s) => s.setRecordSpeedMode)
  const homeRecordArms = useTelemetryStore((s) => s.homeRecordArms)
  const acceptRecordQualityReport = useTelemetryStore((s) => s.acceptRecordQualityReport)
  const rejectRecordQualityReport = useTelemetryStore((s) => s.rejectRecordQualityReport)

  const handleCreateSession = useCallback(() => startRecordSession(datasetName, task), [datasetName, task, startRecordSession])

  useEffect(() => {
    let controlAlone = false
    const cancelControl = () => { controlAlone = false }
    const acceptsShortcut = (e: KeyboardEvent) => {
      if (preCheckVisible || latestReport || e.defaultPrevented || e.isComposing || pageRef.current?.querySelector('[aria-modal="true"]')) return false
      if (!(e.target instanceof Element)) return true
      if (e.target instanceof HTMLElement && e.target.isContentEditable) return false
      return !e.target.closest('button, a, input, textarea, select, [role="button"], [role="dialog"], [role="separator"]')
    }
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key !== 'Control') cancelControl()
      if (e.repeat || !acceptsShortcut(e) || e.metaKey || e.altKey || (e.shiftKey && e.key !== 'R')) return
      if (e.key === 'Control') {
        controlAlone = true
        return
      }
      if (e.ctrlKey) return

      // 快捷键激活当前可用的按钮，沿用按钮的复位检查及夹爪确认。
      const action = recordActionKeys[e.key]
      if (action) {
        const button = pageRef.current?.querySelector<HTMLButtonElement>(`button[data-record-action="${action}"]`)
        if (button && !button.disabled) {
          e.preventDefault()
          button.click()
        }
        return
      }
      const phase = useTelemetryStore.getState().recordSession.phase
      switch (e.key) {
        case '1':
          setRecordSpeedMode('coarse')
          break
        case '2':
          setRecordSpeedMode('medium')
          break
        case '3':
          setRecordSpeedMode('fine')
          break

        case 'r':
        case 'R':
          if (phase === 'idle' || phase === 'resetting') homeRecordArms()
          break

        default:
          break
      }
    }

    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.key !== 'Control') return
      if (controlAlone && acceptsShortcut(e)) toggleRecordClutch()
      cancelControl()
    }
    window.addEventListener('keydown', handleKeyDown)
    window.addEventListener('keyup', handleKeyUp)
    window.addEventListener('pointerdown', cancelControl)
    window.addEventListener('blur', cancelControl)
    return () => {
      window.removeEventListener('keydown', handleKeyDown)
      window.removeEventListener('keyup', handleKeyUp)
      window.removeEventListener('pointerdown', cancelControl)
      window.removeEventListener('blur', cancelControl)
    }
  }, [
    preCheckVisible,
    latestReport,
    homeRecordArms,
    setRecordSpeedMode,
    toggleRecordClutch,
  ])

  return (
    <div className="record-page" ref={pageRef}>
      <div className="record-page-layout">
        <div className="record-page-main">
          <CameraPanel />
          <RecordTelemetryPanel />
          <EpisodeControlPanel onStartSession={() => setPreCheckVisible(true)} />
        </div>

        <div className="record-page-side">
          <SafetyMonitorCard />
          <HardwareStatusCard />
          <EpisodeHistoryCard />
          <KalmanFilterCard />
        </div>
      </div>

      <PreCheckModal
        open={preCheckVisible}
        onConfirm={() => {
          setPreCheckVisible(false)
          handleCreateSession()
        }}
        onCancel={() => setPreCheckVisible(false)}
      />
      <QualityReportModal
        open={Boolean(latestReport)}
        report={latestReport}
        onReRecord={rejectRecordQualityReport}
        onAccept={acceptRecordQualityReport}
      />
    </div>
  )
}
