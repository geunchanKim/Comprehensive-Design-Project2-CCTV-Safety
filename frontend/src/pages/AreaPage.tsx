import { Fragment, useState } from 'react'
import { Link, useParams } from 'react-router'
import { dataSource } from '../api/source'
import type { AreaSnapshot, ClassInfo, VestState, ZoneState } from '../api/types'
import AlertCard from '../components/AlertCard'
import { useShell } from '../hooks/useShell'
import FloorPlan, { type FloorPlanLayers } from '../components/FloorPlan'
import { usePolling } from '../hooks/usePolling'
import { alertTitle, formatClock, objectName } from '../lib/safety'

const LAYER_LABELS: [keyof FloorPlanLayers, string][] = [['trail', '이동 궤적'], ['fov', '카메라 시야'], ['zones', '구역']]
const VEST_TEXT: Record<VestState['status'], string> = { wearing: '착용', not_wearing: '미착용', unknown: '미판단' }
const ZONE_TEXT: Record<ZoneState['status'], string> = { outside: '밖', warning: '접근', intrusion: '진입', unknown: '미판단' }
const EVALUATED_TEXT = { collision: '충돌', zone: '위험 구역', vest: '안전조끼' }

// 구역이 바뀌면 key로 다시 마운트해서 이전 구역 데이터가 남지 않게 한다
export default function AreaPage() {
  const { areaId = 'A' } = useParams()
  return <AreaView key={areaId} areaId={areaId} />
}

function AreaView({ areaId }: { areaId: string }) {
  const { nowMs, areas, acknowledge } = useShell()
  const [snapshot, refresh] = usePolling((signal) => dataSource.getAreaSnapshot(areaId, signal), 500)
  const [layers, setLayers] = useState<FloorPlanLayers>({ trail: true, fov: true, zones: true })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const summary = areas.find((a) => a.areaId === areaId)

  if (snapshot.state === 'loading') return <p className="page-message">불러오는 중…</p>
  if (snapshot.state === 'error') {
    const noData = snapshot.detail === 'no data' || (snapshot.detail.includes('204') && snapshot.detail.includes('No Content'))
    return <p className="page-message">{noData ? '구역 데이터가 없습니다.' : `구역 데이터를 불러오지 못했습니다: ${snapshot.detail}`}</p>
  }

  const { config, cameras, classes, objects, alerts, evaluated, capturedAtMs, staleAfterMs } = snapshot.data
  // 마지막 snapshot이 기준보다 오래되면 화면이 멈춘 것. 안전으로 보이지 않게 표시한다
  const stale = nowMs - capturedAtMs > staleAfterMs
  const notEvaluated = (Object.keys(EVALUATED_TEXT) as (keyof typeof EVALUATED_TEXT)[]).filter((k) => !evaluated[k])
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
              <span className={`status-dot status-dot--${c.online === true ? 'ok' : c.online === false ? 'offline' : 'unknown'}`} aria-hidden="true" />
              {c.cameraId.toUpperCase()} {c.online === true ? '연결' : c.online === false ? '끊김' : '상태 미확인'}
            </span>
          ))}
          {stale && <span className="chip warning-text">갱신 지연 {((nowMs - capturedAtMs) / 1000).toFixed(0)}초</span>}
          {notEvaluated.length > 0 && (
            <span className="chip muted" title="판단이 꺼져 있어 경고가 없어도 안전하다는 뜻이 아닙니다">
              미판단: {notEvaluated.map((k) => EVALUATED_TEXT[k]).join(' · ')}
            </span>
          )}
          <span className="mono clock">{formatClock(nowMs)}</span>
        </div>
      </header>

      {danger && (
        <div className="risk-banner" role="status">
          <span className="danger-text"><b>위험</b></span>
          <span className="grow">
            {titleOf(danger)}
            {danger.distanceM !== undefined && <> · 거리 <b className="mono">{danger.distanceM.toFixed(2)} m</b></>}
            {danger.ttcS !== undefined && <> · 예상 접촉 <b className="mono">{danger.ttcS.toFixed(1)} s</b></>}
          </span>
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
            <h2 className="grow">구역 평면도 <span className="muted mono small">{(config.bounds.xMax - config.bounds.xMin).toFixed(1)} × {(config.bounds.yMax - config.bounds.yMin).toFixed(1)} m</span></h2>
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
                <dt>카메라 track</dt>
                <dd className="mono">
                  {Object.entries(selected.cameraTracks).map(([cam, track]) => `${cam} #${track}`).join(' · ')}
                  {Object.keys(selected.cameraTracks).length < 2 && ' (한 카메라)'}
                </dd>
                {selected.cls === 'person' && (
                  <>
                    <dt>안전조끼</dt>
                    <dd>
                      {evaluated.vest ? VEST_TEXT[selected.vest.status] : '미판단'}
                      {evaluated.vest && selected.vest.confidence !== null && <span className="muted mono small"> {Math.round(selected.vest.confidence * 100)}%</span>}
                    </dd>
                  </>
                )}
                {selected.zoneStates.map((zs) => (
                  <Fragment key={zs.zoneId}>
                    <dt>{config.zones.find((z) => z.zoneId === zs.zoneId)?.name ?? zs.zoneId}</dt>
                    <dd>
                      {evaluated.zone ? ZONE_TEXT[zs.status] : '미판단'}
                      {evaluated.zone && zs.distanceM !== null && <span className="muted mono small"> {zs.distanceM.toFixed(2)} m</span>}
                    </dd>
                  </Fragment>
                ))}
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
      <li><span className="legend__ppe">조끼</span>안전조끼 미착용</li>
    </ul>
  )
}
