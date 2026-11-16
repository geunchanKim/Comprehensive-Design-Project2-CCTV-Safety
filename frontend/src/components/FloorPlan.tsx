import type { KeyboardEvent } from 'react'
import type { Alert, AreaConfig, Camera, ClassInfo, ClassShape, TrackedObject, Vec2 } from '../api/types'
import { levelByObject, nearestPointOnPolygon, objectName } from '../lib/safety'

export interface FloorPlanLayers {
  trail: boolean
  fov: boolean
  zones: boolean
}

interface Props {
  config: AreaConfig
  cameras: Camera[]
  classes: ClassInfo[]
  objects: TrackedObject[]
  alerts: Alert[]
  layers?: FloorPlanLayers
  selectedId?: number | null
  onSelect?: (objectId: number) => void
  // 위험 팝업 스냅샷처럼 작게 그릴 때: 카메라 라벨·축척 생략
  compact?: boolean
  label: string
}

const ALL_LAYERS: FloorPlanLayers = { trail: true, fov: true, zones: true }
const LEVEL_COLOR = { safe: 'var(--text)', warning: 'var(--warning)', danger: 'var(--danger)' }
const ARROW_SECONDS = 0.8

// 구역 평면도. 월드 좌표(m)를 SVG 좌표로 옮겨 그리고, 표식 크기만 화면 기준(px)으로 환산한다.
// 월드 Y는 위쪽, SVG y는 아래쪽이라 toPlan에서 뒤집는다. 범위 밖 객체는 SVG 경계에서 잘린다
export default function FloorPlan({
  config, cameras, classes, objects, alerts, layers = ALL_LAYERS, selectedId, onSelect, compact = false, label,
}: Props) {
  const { xMin, xMax, yMin, yMax } = config.bounds
  const w = xMax - xMin
  const h = yMax - yMin
  const toPlan = (v: Vec2): Vec2 => ({ x: v.x - xMin, y: yMax - v.y })
  // 평면도 긴 변을 약 900px로 보고 1px이 몇 m인지
  const px = Math.max(w, h) / 900
  const levels = levelByObject(alerts)
  const byId = new Map(objects.map((o) => [o.objectId, o]))
  const shapeOf = (cls: string): ClassShape => classes.find((c) => c.cls === cls)?.shape ?? 'square'
  const coneLength = Math.hypot(w, h)
  const zones = config.zones.filter((z) => z.enabled)

  const riskLines = alerts.flatMap((a) => {
    const from = a.object1Id !== undefined ? byId.get(a.object1Id) : undefined
    if (!from) return []
    let to
    if (a.kind === 'collision' && a.object2Id !== undefined) to = byId.get(a.object2Id)?.world
    if (a.kind === 'zone') {
      const zone = zones.find((z) => z.zoneId === a.zoneId)
      if (zone) to = nearestPointOnPolygon(from.world, zone.vertices)
    }
    return to ? [{ alert: a, from: toPlan(from.world), to: toPlan(to) }] : []
  })

  const select = (id: number) => onSelect?.(id)
  const onKey = (e: KeyboardEvent, id: number) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      select(id)
    }
  }

  const bg = config.background
  const bgOrigin = bg.kind === 'image' ? toPlan({ x: bg.bounds.xMin, y: bg.bounds.yMax }) : null

  return (
    <svg className="floor-plan" viewBox={`0 0 ${w} ${h}`} role="group" aria-label={label} style={{ aspectRatio: `${w} / ${h}` }}>
      <defs>
        <pattern id={`grid-${config.areaId}`} width="1" height="1" patternUnits="userSpaceOnUse" x={-xMin} y={yMax}>
          <path d="M 1 0 L 0 0 0 1" fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth={px} />
        </pattern>
      </defs>
      <rect width={w} height={h} fill="var(--plan)" />
      {bg.kind === 'image' && bgOrigin && (
        <image href={bg.url} x={bgOrigin.x} y={bgOrigin.y} width={bg.bounds.xMax - bg.bounds.xMin}
          height={bg.bounds.yMax - bg.bounds.yMin} preserveAspectRatio="none" opacity={0.5} />
      )}
      <rect width={w} height={h} fill={`url(#grid-${config.areaId})`} />

      {layers.fov &&
        cameras.map((c) => {
          // 월드 각도는 반시계 방향이라 SVG에서는 y 성분 부호를 뒤집는다
          const a1 = ((c.yawDeg - c.fovDeg / 2) * Math.PI) / 180
          const a2 = ((c.yawDeg + c.fovDeg / 2) * Math.PI) / 180
          const p = toPlan(c.position)
          const points = [p, { x: p.x + coneLength * Math.cos(a1), y: p.y - coneLength * Math.sin(a1) },
            { x: p.x + coneLength * Math.cos(a2), y: p.y - coneLength * Math.sin(a2) }]
          return (
            <polygon key={`fov-${c.cameraId}`} points={points.map((q) => `${q.x},${q.y}`).join(' ')}
              fill="rgba(106,168,255,0.045)" stroke="rgba(106,168,255,0.35)" strokeWidth={1.5 * px}
              strokeDasharray={`${6 * px} ${6 * px}`} />
          )
        })}

      {layers.zones &&
        zones.map((z) => {
          const points = z.vertices.map(toPlan)
          const center = {
            x: points.reduce((sum, q) => sum + q.x, 0) / points.length,
            y: points.reduce((sum, q) => sum + q.y, 0) / points.length,
          }
          return (
            <g key={z.zoneId}>
              <polygon points={points.map((q) => `${q.x},${q.y}`).join(' ')} fill="rgba(255,90,85,0.07)"
                stroke="var(--danger-text)" strokeWidth={1.5 * px} strokeDasharray={`${5 * px} ${4 * px}`} />
              <text x={center.x} y={center.y + 4 * px} fontSize={11 * px} textAnchor="middle" fill="var(--danger-text)">{z.name}</text>
            </g>
          )
        })}

      {!compact &&
        cameras.map((c) => {
          const p = toPlan(c.position)
          return (
            <g key={`cam-${c.cameraId}`}>
              <rect x={p.x - 11 * px} y={p.y - 11 * px} width={22 * px} height={22 * px} rx={6 * px}
                fill="#1B2A40" stroke={c.online === true ? 'var(--accent)' : 'var(--muted)'} strokeWidth={px} />
              <text x={p.x} y={p.y + 4 * px} fontSize={10 * px} textAnchor="middle" fill="var(--accent)" fontFamily="var(--font-mono)">
                {c.cameraId.replace('cam', 'C')}
              </text>
            </g>
          )
        })}

      {layers.trail &&
        objects.flatMap((o) =>
          o.trail.map((world, i) => {
            const p = toPlan(world)
            return (
              <circle key={`t-${o.objectId}-${i}`} cx={p.x} cy={p.y} r={2 * px} fill="var(--muted)"
                opacity={0.15 + (0.5 * (i + 1)) / o.trail.length} />
            )
          }),
        )}

      {riskLines.map(({ alert, from, to }) => {
        const color = LEVEL_COLOR[alert.level]
        const mid = { x: (from.x + to.x) / 2, y: (from.y + to.y) / 2 }
        const text = `${alert.distanceM?.toFixed(2) ?? '-'}m · ${alert.ttcS?.toFixed(1) ?? '-'}s`
        return (
          <g key={`risk-${alert.alertId}`}>
            <line x1={from.x} y1={from.y} x2={to.x} y2={to.y} stroke={color} strokeWidth={2 * px} />
            {!compact && (
              <g transform={`translate(${mid.x} ${mid.y - 14 * px})`}>
                <rect x={-44 * px} y={-10 * px} width={88 * px} height={18 * px} rx={4 * px} fill="var(--bg)" stroke={color} strokeWidth={px} />
                <text y={3 * px} fontSize={11 * px} textAnchor="middle" fill={color} fontFamily="var(--font-mono)" fontWeight={600}>{text}</text>
              </g>
            )}
          </g>
        )
      })}

      {objects.map((o) => {
        if (!o.velocity || Math.hypot(o.velocity.x, o.velocity.y) < 0.2) return null
        const start = toPlan(o.world)
        const end = toPlan({ x: o.world.x + o.velocity.x * ARROW_SECONDS, y: o.world.y + o.velocity.y * ARROW_SECONDS })
        const angle = (Math.atan2(end.y - start.y, end.x - start.x) * 180) / Math.PI
        return (
          <g key={`v-${o.objectId}`}>
            <line x1={start.x} y1={start.y} x2={end.x} y2={end.y} stroke="var(--subtle)" strokeWidth={1.5 * px} />
            <polygon points={`0,${-4 * px} ${7 * px},0 0,${4 * px}`} fill="var(--subtle)"
              transform={`translate(${end.x} ${end.y}) rotate(${angle})`} />
          </g>
        )
      })}

      {alerts.map((a) => {
        if (!a.contact) return null
        const p = toPlan(a.contact)
        return (
          <circle key={`c-${a.alertId}`} cx={p.x} cy={p.y} r={9 * px} fill="none" stroke="var(--danger)"
            strokeWidth={1.5 * px} strokeDasharray={`${3 * px} ${3 * px}`} />
        )
      })}

      {objects.map((o) => {
        const level = levels.get(o.objectId) ?? 'safe'
        const color = LEVEL_COLOR[level]
        const person = o.cls === 'person'
        const single = Object.keys(o.cameraTracks).length < 2
        const shape = shapeOf(o.cls)
        const fill = single ? 'transparent' : person ? color : '#2A333E'
        const stroke = level === 'safe' && !person ? 'var(--muted)' : color
        const { x, y } = toPlan(o.world)
        return (
          <g key={o.objectId} className="plan-object" role={onSelect ? 'button' : undefined} tabIndex={onSelect ? 0 : undefined}
            aria-label={objectName(o, classes)} aria-pressed={onSelect ? selectedId === o.objectId : undefined}
            onClick={() => select(o.objectId)} onKeyDown={(e) => onKey(e, o.objectId)}>
            {single && <circle cx={x} cy={y} r={0.45} fill="rgba(155,166,180,0.07)" stroke="var(--muted)" strokeWidth={px} strokeDasharray={`${3 * px} ${3 * px}`} />}
            {selectedId === o.objectId && <circle cx={x} cy={y} r={14 * px} fill="none" stroke="var(--accent)" strokeWidth={2 * px} />}
            {level === 'danger' && <circle cx={x} cy={y} r={14 * px} fill="rgba(255,90,85,0.18)" />}
            {shape === 'circle' && <circle cx={x} cy={y} r={7 * px} fill={fill} stroke={stroke} strokeWidth={2.5 * px} />}
            {shape === 'wide' && <rect x={x - 11 * px} y={y - 6.5 * px} width={22 * px} height={13 * px} rx={3 * px} fill={fill} stroke={stroke} strokeWidth={2.5 * px} />}
            {shape === 'square' && <rect x={x - 6 * px} y={y - 6 * px} width={12 * px} height={12 * px} rx={3 * px} fill={fill} stroke={stroke} strokeWidth={2.5 * px} />}
            <text x={x + 10 * px} y={y - 12 * px} fontSize={11 * px} fill={level === 'safe' ? 'var(--muted)' : color} fontFamily="var(--font-mono)">#{o.objectId}</text>
            {o.vest.status === 'not_wearing' && (
              <g transform={`translate(${x + 10 * px} ${y + 8 * px})`}>
                <rect width={44 * px} height={16 * px} rx={4 * px} fill="var(--bg)" stroke="var(--warning)" strokeWidth={px} />
                <text x={22 * px} y={11.5 * px} fontSize={10 * px} textAnchor="middle" fill="var(--warning)" fontWeight={600}>조끼</text>
              </g>
            )}
          </g>
        )
      })}

      {!compact && (
        <g transform={`translate(${w * 0.02} ${h * 0.95})`}>
          <path d={`M0 ${-5 * px} V0 H1 V${-5 * px}`} fill="none" stroke="var(--muted)" strokeWidth={1.5 * px} />
          <text y={12 * px} fontSize={10 * px} fill="var(--muted)" fontFamily="var(--font-mono)">1 m</text>
        </g>
      )}
    </svg>
  )
}
