import { useEffect } from 'react'
import { operatorSideForHardwareSide, operatorSideLabel } from '../data'
import { useOriginContinuity } from '../stores/originContinuity'
import { UiButton } from './ui'

export function OriginContinuityDialog() {
  const question = useOriginContinuity((s) => s.question)
  useEffect(() => () => useOriginContinuity.getState().question?.answer(false), [])
  if (!question) return null
  const arm = operatorSideLabel(operatorSideForHardwareSide(question.side))
  return (
    <div className="ui-modal-mask" onKeyDown={(e) => { if (e.key === 'Escape') question.answer(false) }}>
      <section className="ui-modal" role="dialog" aria-labelledby="origin-continuity-title">
        <header className="ui-modal-head" id="origin-continuity-title">{arm}：电脑重启过吗？</header>
        <div className="ui-modal-body">
          <p>HAL 已重启。自上次确认这只臂的坐标以来，电脑是否重启过，或控制卡是否断电、清零过？</p>
          <p>若有或不确定，请重新建参考。只有确认计数未变，才沿用已保存的坐标并移动到工作原点。</p>
        </div>
        <footer className="ui-modal-actions">
          <UiButton autoFocus onClick={() => question.answer(false)}>重启过或不确定，不移动</UiButton>
          <UiButton variant="primary" onClick={() => question.answer(true)}>未重启且计数未变，回工作原点</UiButton>
        </footer>
      </section>
    </div>
  )
}
