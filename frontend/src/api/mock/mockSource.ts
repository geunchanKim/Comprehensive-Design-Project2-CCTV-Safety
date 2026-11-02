import type { DataSource } from '../source'
import type { Alert, AreaConfig } from '../types'
import { ALERTS, AREA_CONFIGS, AREAS, CAMERAS, CLASSES, OBJECTS } from './data'

// 불러온 시각 기준으로 경고 시작 시각을 고정해 두면 지속 시간이 실제처럼 늘어난다
const loadedAt = Date.now()
const alerts: Alert[] = ALERTS.map(({ sinceMs, ...rest }) => ({ ...rest, startedAtMs: loadedAt - sinceMs }))

const delay = <T,>(value: T, signal?: AbortSignal) =>
  new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => resolve(structuredClone(value)), 120)
    signal?.addEventListener('abort', () => {
      clearTimeout(timer)
      reject(new DOMException('aborted', 'AbortError'))
    })
  })

// 예시 데이터가 없는 구역은 크기만 맞춘 빈 평면도로 보여준다
const configOf = (areaId: string): AreaConfig => {
  const known = AREA_CONFIGS[areaId]
  if (known) return known
  const summary = AREAS.find((a) => a.areaId === areaId)
  if (!summary) throw new Error(`unknown area ${areaId}`)
  return { areaId, name: summary.name, size: { w: summary.rect.w, h: summary.rect.h }, background: { kind: 'blocks' }, zones: [] }
}

export const mockSource: DataSource = {
  listAreas: (signal) => delay(AREAS, signal),

  getAreaSnapshot: (areaId, signal) =>
    delay(
      {
        config: configOf(areaId),
        cameras: CAMERAS[areaId] ?? [],
        classes: CLASSES,
        objects: OBJECTS[areaId] ?? [],
        alerts: alerts.filter((a) => a.areaId === areaId),
        capturedAtMs: Date.now(),
      },
      signal,
    ),

  listActiveAlerts: (signal) => delay(alerts, signal),

  acknowledgeAlert: async (alertId) => {
    const alert = alerts.find((a) => a.alertId === alertId)
    if (alert) alert.acknowledged = true
  },
}
