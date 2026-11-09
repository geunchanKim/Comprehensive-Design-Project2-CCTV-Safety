import { NavLink } from 'react-router'
import type { AreaStatus, AreaSummary } from '../api/types'

const STATUS_NOTE: Record<AreaStatus, string> = { danger: '위험', warning: '주의', offline: '감시 불가', ok: '' }

export default function Sidebar({ areas }: { areas: AreaSummary[] }) {
  return (
    <nav className="sidebar" aria-label="주 메뉴">
      <div className="brand">
        <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--accent)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6l8-3z" />
          <circle cx="12" cy="11" r="2.5" />
        </svg>
        <div>
          <div className="brand__name">CCTV Safety</div>
          <div className="muted small">현장 안전 관제</div>
        </div>
      </div>
      <NavLink to="/" end className="nav-link">전체 현황</NavLink>
      <NavLink to="/events" className="nav-link">이벤트 기록</NavLink>
      <NavLink to="/settings" className="nav-link">사업장·구역 설정</NavLink>

      <span className="sidebar__section muted small">구역</span>
      {areas.map((a) => (
        <NavLink key={a.areaId} to={`/areas/${a.areaId}`} className="nav-link nav-link--area">
          <span className={`status-dot status-dot--${a.status}`} aria-hidden="true" />
          <span className="grow">{a.areaId} {a.name}</span>
          <span className={`small status-text--${a.status}`}>{STATUS_NOTE[a.status]}</span>
        </NavLink>
      ))}
    </nav>
  )
}
