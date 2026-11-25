import type { Alert } from '../api/types'
import { formatSince, KIND_TEXT, LEVEL_TEXT } from '../lib/safety'

interface Props {
  alert: Alert
  title: string
  nowMs: number
  areaName?: string
  onLocate?: () => void
  onAcknowledge?: () => void
}

export default function AlertCard({ alert, title, nowMs, areaName, onLocate, onAcknowledge }: Props) {
  const hasMetrics = alert.distanceM !== undefined
  return (
    <article className={`alert-card alert-card--${alert.level}`}>
      <div className="alert-card__head">
        <span className={`level-tag level-tag--${alert.level}`}>{LEVEL_TEXT[alert.level]}</span>
        <span className="alert-card__title">{title}</span>
        <span className="mono muted small">{formatSince(nowMs - alert.startedAtMs)}</span>
      </div>
      <span className="muted small">
        {areaName ? `${areaName} · ` : ''}
        {KIND_TEXT[alert.kind]}
        {alert.acknowledged ? ' · 확인됨' : ''}
      </span>
      {hasMetrics && (
        <div className="alert-card__metrics mono">
          <span><span className="muted">거리 </span>{alert.distanceM?.toFixed(2)} m</span>
          {alert.ttcS !== undefined && <span><span className="muted">TTC </span>{alert.ttcS.toFixed(1)} s</span>}
        </div>
      )}
      {(onLocate || onAcknowledge) && (
        <div className="btn-row">
          {onLocate && <button type="button" className="btn btn--ghost" onClick={onLocate}>평면도에서 보기</button>}
          {onAcknowledge && !alert.acknowledged && (
            <button type="button" className="btn" onClick={onAcknowledge}>확인 처리</button>
          )}
        </div>
      )}
    </article>
  )
}
