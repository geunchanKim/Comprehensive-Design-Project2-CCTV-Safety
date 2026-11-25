import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router'
import { dataSource } from '../api/source'
import type { Alert, AreaSnapshot, AreaSummary, Camera } from '../api/types'
import { alertTitle, formatClock, KIND_TEXT } from '../lib/safety'
import FloorPlan from './FloorPlan'

// 미확인 위험이 이 시간 넘게 남아 있으면 안전관리자에게 상위 알림 (백엔드 구현 예정)
const ESCALATE_AFTER_MS = 30_000

interface Props {
  alerts: Alert[]
  areas: AreaSummary[]
  nowMs: number
  onAcknowledge: (alertId: string, action: string | null) => Promise<void>
}

// 위험(danger) 발생 시 모든 화면 위에 뜨고, 확인해야만 닫힌다. 주의는 여기 뜨지 않는다
export default function DangerAlertModal({ alerts, areas, nowMs, onAcknowledge }: Props) {
  const pending = alerts.filter((a) => a.level === 'danger' && !a.acknowledged).sort((a, b) => a.startedAtMs - b.startedAtMs)
  const alert = pending[0]
  if (!alert) return null
  // 경고가 바뀌면 key로 새로 마운트해서 이전 경고의 평면도·조치 선택이 남지 않게 한다
  return (
    <DangerAlert key={alert.alertId} alert={alert} moreCount={pending.length - 1}
      area={areas.find((a) => a.areaId === alert.areaId)} nowMs={nowMs} onAcknowledge={onAcknowledge} />
  )
}

interface AlertProps {
  alert: Alert
  moreCount: number
  area: AreaSummary | undefined
  nowMs: number
  onAcknowledge: Props['onAcknowledge']
}

function DangerAlert({ alert, moreCount, area, nowMs, onAcknowledge }: AlertProps) {
  const [snapshot, setSnapshot] = useState<AreaSnapshot | null>(null)
  const [cameras, setCameras] = useState<Camera[]>([])
  const [action, setAction] = useState('')
  const [busy, setBusy] = useState(false)
  // 구역으로 이동하면 팝업을 오른쪽 아래로 접는다. 확인 전까지는 사라지지 않는다
  const [docked, setDocked] = useState(false)
  const confirmRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    const ctrl = new AbortController()
    dataSource.getAreaSnapshot(alert.areaId, ctrl.signal).then(setSnapshot).catch(() => {})
    dataSource.listCameras(alert.areaId, ctrl.signal).then(setCameras).catch(() => {})
    confirmRef.current?.focus()
    return () => ctrl.abort()
  }, [alert.areaId])

  const remainingS = Math.ceil((ESCALATE_AFTER_MS - (nowMs - alert.startedAtMs)) / 1000)
  const title = snapshot ? alertTitle(alert, snapshot.objects, snapshot.config.zones, snapshot.classes) : KIND_TEXT[alert.kind]

  const confirm = async () => {
    setBusy(true)
    try {
      await onAcknowledge(alert.alertId, action || null)
    } finally {
      setBusy(false)
    }
  }

  if (docked) {
    return (
      <aside className="danger-dock" role="alert" aria-label="확인 대기 중인 위험">
        <span className="level-tag level-tag--danger">위험</span>
        <span className="grow">
          <b>{title}</b>
          <span className="muted small"> · {area?.name ?? alert.areaId}{moreCount > 0 ? ` 외 ${moreCount}건` : ''}</span>
        </span>
        <button type="button" className="btn" onClick={() => setDocked(false)}>자세히</button>
        <button type="button" className="btn btn--danger" onClick={confirm} disabled={busy}>확인</button>
      </aside>
    )
  }

  return (
    <div className="modal-backdrop">
      <section className="danger-modal" role="alertdialog" aria-modal="true" aria-labelledby="danger-title">
        <header className="danger-modal__bar">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" />
            <path d="M12 9v4M12 17h.01" />
          </svg>
          <strong>위험 발생</strong>
          <span>{area ? `${area.areaId} ${area.name}` : alert.areaId}</span>
          {moreCount > 0 && <span className="danger-modal__more">외 {moreCount}건</span>}
          <span className="mono danger-modal__time">{formatClock(alert.startedAtMs)}</span>
        </header>

        <div className="danger-modal__body">
          <div>
            <h2 id="danger-title">{title}</h2>
            <span className="muted">{KIND_TEXT[alert.kind]}</span>
          </div>
          <dl className="stat-grid">
            <div><dt>거리</dt><dd className="mono danger-text">{alert.distanceM !== undefined ? `${alert.distanceM.toFixed(2)} m` : '—'}</dd></div>
            <div><dt>예상 접촉</dt><dd className="mono danger-text">{alert.ttcS !== undefined ? `${alert.ttcS.toFixed(1)} s` : '—'}</dd></div>
            <div><dt>지속</dt><dd className="mono">{((nowMs - alert.startedAtMs) / 1000).toFixed(1)} s</dd></div>
          </dl>

          <figure className="danger-modal__snapshot">
            <figcaption className="muted small">발생 순간 평면도{area ? ` · ${area.name}` : ''}</figcaption>
            {snapshot ? (
              <FloorPlan compact label={`${area?.name ?? ''} 평면도, ${title}`} config={snapshot.config} cameras={cameras}
                classes={snapshot.classes} objects={snapshot.objects} alerts={[alert]}
                layers={{ trail: false, fov: false, zones: true }} />
            ) : (
              <div className="placeholder-box">평면도 불러오는 중…</div>
            )}
          </figure>

          <p className="escalation">
            {remainingS > 0
              ? <>경고음 재생 중 · <b className="mono">{remainingS}초</b> 안에 확인하지 않으면 안전관리자에게 알림</>
              : <>안전관리자에게 알림을 보냈습니다</>}
          </p>

          <label className="field">
            조치 (선택)
            <select value={action} onChange={(e) => setAction(e.target.value)}>
              <option value="">선택 안 함</option>
              <option value="radio">현장 무전으로 지시</option>
              <option value="dispatch">현장 담당자 출동</option>
              <option value="false-positive">오탐 (위험 아님)</option>
            </select>
          </label>

          <div className="btn-row">
            <Link to={`/areas/${alert.areaId}`} className="btn btn--large" onClick={() => setDocked(true)}>구역으로 이동</Link>
            <button ref={confirmRef} type="button" className="btn btn--large btn--danger" onClick={confirm} disabled={busy}>확인</button>
          </div>
          <p className="muted small center">확인한 사람과 시각이 이벤트 기록에 남습니다 · 위험이 끝나도 확인 전까지 닫히지 않습니다</p>
        </div>
      </section>
    </div>
  )
}
