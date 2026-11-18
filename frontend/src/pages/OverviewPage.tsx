import { Link } from 'react-router'
import type { AreaStatus } from '../api/types'
import { useShell } from '../hooks/useShell'

const STATUS_TEXT: Record<AreaStatus, string> = {
  danger: '위험',
  warning: '주의',
  offline: '감시 불가',
  ok: '정상',
}

export default function OverviewPage() {
  const { areas, alerts } = useShell()
  const dangerCount = areas.filter((area) => area.status === 'danger').length
  const warningCount = areas.filter((area) => area.status === 'warning').length
  const offlineCount = areas.filter((area) => area.status === 'offline').length
  const peopleCount = areas.reduce((total, area) => total + (area.people ?? 0), 0)

  return (
    <div className="page">
      <header className="topbar">
        <div className="grow">
          <span className="muted small">현장 안전 관제</span>
          <h1>전체 현황</h1>
        </div>
        <span className="chip">활성 경고 <b className="mono">{alerts.length}</b></span>
      </header>

      {areas.length === 0 ? (
        <p className="page-message">구역 현황을 불러오는 중…</p>
      ) : (
        <>
          <section className="kpis" aria-label="전체 현황 요약">
            <div className="kpi"><span className="muted small">관제 구역</span><span className="kpi__value mono">{areas.length}<small> 곳</small></span></div>
            <div className="kpi"><span className="muted small">현재 인원</span><span className="kpi__value mono">{peopleCount}<small> 명</small></span></div>
            <div className="kpi kpi--danger"><span className="muted small">위험 구역</span><span className="kpi__value mono danger-text">{dangerCount}</span></div>
            <div className="kpi"><span className="muted small">주의 · 감시 불가</span><span className="kpi__value mono warning-text">{warningCount + offlineCount}</span></div>
          </section>

          <section aria-label="구역별 현황" className="overview-grid">
            {areas.map((area) => (
              <Link className={`overview-card overview-card--${area.status}`} key={area.areaId} to={`/areas/${area.areaId}`}>
                <div className="card__head">
                  <span className={`status-dot status-dot--${area.status}`} aria-hidden="true" />
                  <h2 className="grow">{area.areaId} {area.name}</h2>
                  <strong className={`status-text--${area.status}`}>{STATUS_TEXT[area.status]}</strong>
                </div>
                <div className="overview-card__details">
                  <span>인원 <b>{area.people === null ? '—' : `${area.people}명`}</b></span>
                  <span>카메라 <b>{area.cameras.online}/{area.cameras.total}</b></span>
                </div>
                <span className="muted small">구역 관제로 이동 →</span>
              </Link>
            ))}
          </section>
        </>
      )}
    </div>
  )
}
