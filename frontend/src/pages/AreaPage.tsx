import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { dataSource } from '../api/source'
import type { AreaSnapshot, ClassInfo } from '../api/types'
import AlertCard from '../components/AlertCard'
import { useShell } from '../hooks/useShell'
import FloorPlan, { type FloorPlanLayers } from '../components/FloorPlan'
import { usePolling } from '../hooks/usePolling'
import { alertTitle, formatClock, objectName } from '../lib/safety'

const LAYER_LABELS: [keyof FloorPlanLayers, string][] = [['trail', '이동 궤적'], ['fov', '카메라 시야'], ['zones', '구역']]
const MATCHING_TEXT = { epipolar: 'epipolar (2대)', 'ground-plane': '바닥 평면 추정', 'single-camera': '한 카메라' }

// 구역이 바뀌면 key로 다시 마운트해서 이전 구역 데이터가 남지 않게 한다
export default function AreaPage() {
  const { areaId = 'A' } = useParams()
  return <AreaView key={areaId} areaId={areaId} />
}

function AreaView({ areaId }: { areaId: string }) {
  const { nowMs, areas, acknowledge } = useShell()
  const [snapshot, refresh] = usePolling((signal) => dataSource.getAreaSnapshot(areaId, signal), 1000)
  const [layers, setLayers] = useState<FloorPlanLayers>({ trail: true, fov: true, zones: true })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const summary = areas.find((a) => a.areaId === areaId)

  if (snapshot.state === 'loading') return <p className="page-message">불러오는 중…</p>
  if (snapshot.state === 'error') return <p className="page-message">구역 데이터를 불러오지 못했습니다: {snapshot.detail}</p>

  const { config, cameras, classes, objects, alerts } = snapshot.data
  const titleOf = (a: AreaSnapshot['alerts'][number]) => alertTitle(a, objects, config.zones, classes)
  const sorted = [...alerts].sort((a, b) => (a.level === b.level ? a.startedAtMs - b.startedAtMs : a.level === 'danger' ? -1 : 1))
  const danger = sorted.find((a) => a.level === 'danger')
  const people = objects.filter((o) => o.cls === 'person')
  const others = objects.filter((o) => o.cls !== 'person')
  const selected = objects.find((o) => o.objectId === (selectedId ?? people[0]?.objectId))

  const ack = async (alertId: string) => {
    await acknowledge(alertId, null)
    refresh()
  }

  return (
    <div className="page">
      <header className="topbar">
        <div className="grow">
          <nav aria-label="경로" className="muted small"><Link to="/">전체 현황</Link> › 구역 {areaId}</nav>
          <h1>{config.name}</h1>
        </div>
        <div className="chip-row">
          {cameras.map((c) => (
            <span key={c.cameraId} className="chip">
              <span className={`status-dot status-dot--${c.online ? 'ok' : 'offline'}`} aria-hidden="true" />
              {c.cameraId.toUpperCase()} {c.online ? `${c.fps ?? '-'}fps` : '끊김'}
            </span>
          ))}
          <span className="mono clock">{formatClock(nowMs)}</span>
        </div>
      </header>

      {danger && (
        <div className="risk-banner" role="status">
          <span className="danger-text"><b>위험</b></span>
          <span className="grow">{titleOf(danger)} · 거리 <b className="mono">{danger.distanceM?.toFixed(2)} m</b> · 예상 접촉 <b className="mono">{danger.ttcS?.toFixed(1)} s</b></span>
          <button type="button" className="btn btn--ghost" onClick={() => setSelectedId(danger.object1Id ?? null)}>위치 보기</button>
        </div>
      )}

      <section className="kpis" aria-label="구역 요약">
        <div className="kpi"><span className="muted small">현재 인원</span><span className="kpi__value mono">{people.length}<small> 명</small></span></div>
        <div className="kpi">
          <span className="muted small">추적 중인 객체</span>
          <span className="kpi__value mono">{others.length}<small> 개</small></span>
          <span className="muted small">{countByClass(others.map((o) => o.cls), classes)}</span>
        </div>
        <div className="kpi"><span className="muted small">주의</span><span className="kpi__value mono warning-text">{alerts.filter((a) => a.level === 'warning').length}</span></div>
        <div className="kpi kpi--danger"><span className="muted small">위험</span><span className="kpi__value mono danger-text">{alerts.filter((a) => a.level === 'danger').length}</span></div>
      </section>

      <div className="content-row">
        <section className="card grow-wide" aria-label="평면도">
          <div className="card__head">
            <h2 className="grow">구역 평면도 <span className="muted mono small">{config.size.w.toFixed(1)} × {config.size.h.toFixed(1)} m</span></h2>
            {LAYER_LABELS.map(([key, text]) => (
              <button key={key} type="button" className="toggle" aria-pressed={layers[key]}
                onClick={() => setLayers((l) => ({ ...l, [key]: !l[key] }))}>{text}</button>
            ))}
          </div>
          <FloorPlan label={`${config.name} 평면도`} config={config} cameras={cameras} classes={classes} objects={objects}
            alerts={alerts} layers={layers} selectedId={selected?.objectId ?? null} onSelect={setSelectedId} />
          <Legend classes={classes} />
        </section>

        <aside className="side-panel">
          <section className="card" aria-label="이 구역 경고">
            <h2>이 구역 경고 <span className="muted mono">{alerts.length}</span></h2>
            {sorted.length === 0 && <p className="muted small">진행 중인 경고가 없습니다.</p>}
            {sorted.map((a) => (
              <AlertCard key={a.alertId} alert={a} title={titleOf(a)} nowMs={nowMs}
                onLocate={a.object1Id !== undefined ? () => setSelectedId(a.object1Id ?? null) : undefined}
                onAcknowledge={() => ack(a.alertId)} />
            ))}
          </section>

          {selected && (
            <section className="card" aria-label="선택 객체">
              <h2>{objectName(selected, classes)} <span className="muted small">선택됨</span></h2>
              <dl className="detail-list">
                <dt>위치 (x, y)</dt><dd className="mono">{selected.world.x.toFixed(2)}, {selected.world.y.toFixed(2)} m</dd>
                <dt>속도</dt><dd className="mono">{selected.velocity ? `${Math.hypot(selected.velocity.x, selected.velocity.y).toFixed(2)} m/s` : '—'}</dd>
                <dt>매칭 방식</dt><dd className="mono">{MATCHING_TEXT[selected.matchingMethod]}</dd>
                {selected.ppe && (
                  <><dt>PPE</dt><dd>안전모 {selected.ppe.helmet ? '○' : '✕'} · 조끼 {selected.ppe.vest ? '○' : '✕'}</dd></>
                )}
              </dl>
              {/* 카메라별 bbox 크롭은 영상 전달 경로가 생기면 붙인다 */}
              <div className="snap-row">
                {cameras.map((c) => <div key={c.cameraId} className="placeholder-box">{c.cameraId.toUpperCase()} 스냅샷</div>)}
              </div>
            </section>
          )}
        </aside>
      </div>
      {summary?.status === 'offline' && <p className="page-message">카메라가 끊겨 이 구역은 감시 불가 상태입니다.</p>}
    </div>
  )
}

function countByClass(list: string[], classes: ClassInfo[]) {
  const counts = new Map<string, number>()
  for (const cls of list) counts.set(cls, (counts.get(cls) ?? 0) + 1)
  return [...counts].map(([cls, n]) => `${classes.find((c) => c.cls === cls)?.label ?? cls} ${n}`).join(' · ')
}

function Legend({ classes }: { classes: ClassInfo[] }) {
  return (
    <ul className="legend" aria-label="범례">
      {classes.map((c) => (
        <li key={c.cls}><span className={`legend__shape legend__shape--${c.shape} ${c.protected ? 'legend__shape--protected' : ''}`} />{c.label}</li>
      ))}
      <li><span className="legend__shape legend__shape--single" />한 카메라만 봄 (추정 오차)</li>
      <li><span className="legend__line legend__line--warning" />주의</li>
      <li><span className="legend__line legend__line--danger" />위험</li>
      <li><span className="legend__zone" />위험 구역</li>
      <li><span className="legend__ppe">PPE</span>안전모·조끼 미착용</li>
    </ul>
  )
}
