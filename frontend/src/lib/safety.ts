import type { Alert, AlertKind, ClassInfo, Level, TrackedObject, Vec2, Zone } from '../api/types'

export const LEVEL_TEXT: Record<Alert['level'], string> = { warning: '주의', danger: '위험' }

export const KIND_TEXT: Record<AlertKind, string> = {
  collision: '충돌',
  zone: '위험 구역 접근·진입',
  vest: '안전조끼 미착용',
  system: '시스템',
}

const RANK: Record<Level, number> = { safe: 0, warning: 1, danger: 2 }

export const objectName = (obj: TrackedObject | undefined, classes: ClassInfo[]) => {
  if (!obj) return '알 수 없음'
  const label = classes.find((c) => c.cls === obj.cls)?.label ?? obj.cls
  return `${label} #${obj.objectId}`
}

// 객체마다 걸려 있는 경고 중 가장 심각한 단계
export function levelByObject(alerts: Alert[]): Map<number, Level> {
  const levels = new Map<number, Level>()
  const bump = (id: number | undefined, level: Level) => {
    if (id === undefined) return
    if (RANK[level] > RANK[levels.get(id) ?? 'safe']) levels.set(id, level)
  }
  for (const a of alerts) {
    bump(a.object1Id, a.level)
    bump(a.object2Id, a.level)
  }
  return levels
}

// 사람에서 가장 가까운 구역 경계점 (구역 경고 연결선 끝점)
export function nearestPointOnPolygon(p: Vec2, vertices: Vec2[]): Vec2 {
  let best = vertices[0]
  let bestDist = Infinity
  vertices.forEach((a, i) => {
    const b = vertices[(i + 1) % vertices.length]
    const dx = b.x - a.x
    const dy = b.y - a.y
    const t = Math.min(1, Math.max(0, ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy)))
    const q = { x: a.x + t * dx, y: a.y + t * dy }
    const d = Math.hypot(p.x - q.x, p.y - q.y)
    if (d < bestDist) {
      best = q
      bestDist = d
    }
  })
  return best
}

export function alertTitle(alert: Alert, objects: TrackedObject[], zones: Zone[], classes: ClassInfo[]) {
  const find = (id?: number) => objects.find((o) => o.objectId === id)
  const who = objectName(find(alert.object1Id), classes)
  switch (alert.kind) {
    case 'collision':
      return `${who} ↔ ${objectName(find(alert.object2Id), classes)}`
    case 'zone':
      return `${who} → ${zones.find((z) => z.zoneId === alert.zoneId)?.name ?? '위험 구역'}`
    case 'vest':
      return `${who} · 안전조끼 미착용`
    case 'system':
      return alert.message ?? '시스템 경고'
  }
}

export const formatSince = (ms: number) => {
  const s = Math.max(0, ms) / 1000
  if (s < 60) return `${s.toFixed(1)}초째`
  return `${Math.floor(s / 60)}분째`
}

export const formatClock = (ms: number) =>
  new Date(ms).toLocaleTimeString('ko-KR', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
