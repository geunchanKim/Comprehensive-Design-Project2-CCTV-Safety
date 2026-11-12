import { getJson, postJson } from './client'
import type { DataSource } from './source'
import type { Alert, AreaConfig, AreaSnapshot, AreaSummary, Camera, ClassInfo, TrackedObject, Vec2 } from './types'

interface ApiArea {
  area_id?: string
  areaId?: string
  name: string
  rect?: { x: number; y: number; w: number; h: number }
  status?: AreaSummary['status']
  people?: number | null
  cameras?: { online: number; total: number }
  updated_at_ms?: number
  updatedAtMs?: number
}

interface ApiCamera {
  camera_id?: string
  cameraId?: string
  position: Vec2
  yaw_deg?: number
  yawDeg?: number
  fov_deg?: number
  fovDeg?: number
  online: boolean | null
  last_frame_at_ms?: number | null
  lastFrameAtMs?: number | null
}

interface ApiSnapshot {
  area_id?: string
  areaId?: string
  area_name?: string
  areaName?: string
  map: {
    coordinate_frame_id?: string
    coordinateFrameId?: string
    bounds: { x_min?: number; x_max?: number; y_min?: number; y_max?: number; xMin?: number; xMax?: number; yMin?: number; yMax?: number }
  }
  stale_after_ms?: number
  staleAfterMs?: number
  supported_classes?: string[]
  supportedClasses?: string[]
  objects: ApiObject[]
  zones?: ApiZone[]
  collision_evaluated?: boolean
  zone_evaluated?: boolean
  vest_evaluated?: boolean
  evaluated?: { collision: boolean; zone: boolean; vest: boolean }
  captured_at_ms?: number
  capturedAtMs?: number
}

interface ApiObject {
  object_id?: number
  objectId?: number
  cls: string
  world: Vec2
  velocity: Vec2 | null
  camera_tracks?: Record<string, number>
  cameraTracks?: Record<string, number>
  vest: ApiObjectVest
  zone_states?: ApiZoneState[]
  zoneStates?: ApiZoneState[]
}

interface ApiObjectVest {
  status: TrackedObject['vest']['status']
  confidence: number | null
  observed_at_ms?: number | null
  observedAtMs?: number | null
}

interface ApiZoneState {
  zone_id?: string
  zoneId?: string
  status: TrackedObject['zoneStates'][number]['status']
  distance_m?: number | null
  distanceM?: number | null
}

interface ApiZone {
  zone_id?: string
  zoneId?: string
  name: string
  vertices: Vec2[] | [number, number][]
  warning_distance_m?: number
  warningDistanceM?: number
  enabled: boolean
}

const value = <T>(snake: T | undefined, camel: T | undefined, fallback: T): T => snake ?? camel ?? fallback
const idOf = (item: { area_id?: string; areaId?: string }) => value(item.area_id, item.areaId, '')

const queryFor = (areaId?: string) => {
  const query = new URLSearchParams()
  if (areaId) query.set('area_id', areaId)
  return query.toString()
}

const pathWithQuery = (path: string, areaId?: string) => {
  const query = queryFor(areaId)
  return query ? `${path}?${query}` : path
}

const mapBounds = (bounds: ApiSnapshot['map']['bounds']) => ({
  xMin: value(bounds.x_min, bounds.xMin, 0),
  xMax: value(bounds.x_max, bounds.xMax, 0),
  yMin: value(bounds.y_min, bounds.yMin, 0),
  yMax: value(bounds.y_max, bounds.yMax, 0),
})

const mapCamera = (camera: ApiCamera): Camera => ({
  cameraId: value(camera.camera_id, camera.cameraId, ''),
  position: camera.position,
  yawDeg: value(camera.yaw_deg, camera.yawDeg, 0),
  fovDeg: value(camera.fov_deg, camera.fovDeg, 0),
  online: camera.online,
  lastFrameAtMs: value(camera.last_frame_at_ms, camera.lastFrameAtMs, null),
})

const mapZone = (zone: ApiZone) => ({
  zoneId: value(zone.zone_id, zone.zoneId, ''),
  name: zone.name,
  vertices: zone.vertices.map((vertex) => Array.isArray(vertex) ? { x: vertex[0], y: vertex[1] } : vertex),
  warningDistanceM: value(zone.warning_distance_m, zone.warningDistanceM, 0),
  enabled: zone.enabled,
})

const mapObject = (object: ApiObject): TrackedObject => ({
  objectId: value(object.object_id, object.objectId, 0),
  cls: object.cls,
  world: object.world,
  velocity: object.velocity,
  cameraTracks: value(object.camera_tracks, object.cameraTracks, {}),
  vest: {
    status: object.vest.status,
    confidence: object.vest.confidence,
    observedAtMs: value(object.vest.observed_at_ms, object.vest.observedAtMs, null),
  },
  zoneStates: (value(object.zone_states, object.zoneStates, []) as ApiZoneState[]).map((state) => ({
    zoneId: value(state.zone_id, state.zoneId, ''),
    status: state.status,
    distanceM: value(state.distance_m, state.distanceM, null),
  })),
  trail: [],
})

interface ApiAlert {
  alert_id?: string
  alertId?: string
  area_id?: string
  areaId?: string
  kind: Alert['kind']
  level: Alert['level']
  object1_id?: number
  object1Id?: number
  object2_id?: number
  object2Id?: number
  zone_id?: string
  zoneId?: string
  distance_m?: number
  distanceM?: number
  ttc_s?: number
  ttcS?: number
  contact?: Vec2
  message?: string
  started_at_ms?: number
  startedAtMs?: number
  acknowledged: boolean
  action?: string | null
}

const mapAlert = (alert: ApiAlert): Alert => ({
  alertId: value(alert.alert_id, alert.alertId, ''),
  areaId: value(alert.area_id, alert.areaId, ''),
  kind: alert.kind,
  level: alert.level,
  object1Id: value(alert.object1_id, alert.object1Id, undefined),
  object2Id: value(alert.object2_id, alert.object2Id, undefined),
  zoneId: value(alert.zone_id, alert.zoneId, undefined),
  distanceM: value(alert.distance_m, alert.distanceM, undefined),
  ttcS: value(alert.ttc_s, alert.ttcS, undefined),
  contact: alert.contact,
  message: alert.message,
  startedAtMs: value(alert.started_at_ms, alert.startedAtMs, 0),
  acknowledged: alert.acknowledged,
})

const classInfo = (cls: string): ClassInfo => ({
  cls,
  label: cls,
  shape: cls === 'person' ? 'circle' : cls === 'cart' ? 'wide' : 'square',
  protected: cls === 'person',
})

const mapSnapshot = (snapshot: ApiSnapshot, cameras: Camera[]): AreaSnapshot => {
  const areaId = value(snapshot.area_id, snapshot.areaId, '')
  const bounds = mapBounds(snapshot.map.bounds)
  const classes = value(snapshot.supported_classes, snapshot.supportedClasses, []).map(classInfo)
  const zones = (snapshot.zones ?? []).map(mapZone)

  const config: AreaConfig = {
    areaId,
    name: value(snapshot.area_name, snapshot.areaName, areaId),
    coordinateFrameId: value(snapshot.map.coordinate_frame_id, snapshot.map.coordinateFrameId, ''),
    bounds,
    background: { kind: 'blocks' },
    zones,
  }

  return {
    config,
    cameras,
    classes,
    objects: snapshot.objects.map(mapObject),
    alerts: [],
    evaluated: snapshot.evaluated ?? {
      collision: snapshot.collision_evaluated ?? false,
      zone: snapshot.zone_evaluated ?? false,
      vest: snapshot.vest_evaluated ?? false,
    },
    capturedAtMs: value(snapshot.captured_at_ms, snapshot.capturedAtMs, 0),
    staleAfterMs: value(snapshot.stale_after_ms, snapshot.staleAfterMs, 1000),
  }
}

const mapArea = (area: ApiArea): AreaSummary => {
  const areaId = idOf(area)
  return {
    areaId,
    name: area.name,
    rect: area.rect ?? { x: 0, y: 0, w: 0, h: 0 },
    status: area.status ?? 'offline',
    people: area.people ?? null,
    cameras: area.cameras ?? { online: 0, total: 0 },
  }
}

const areasFrom = (response: ApiArea[] | { areas: ApiArea[] }) =>
  (Array.isArray(response) ? response : response.areas).map(mapArea)

const httpSource: DataSource = {
  async listAreas(signal) {
    return areasFrom(await getJson<ApiArea[] | { areas: ApiArea[] }>('/dashboard/areas', signal))
  },

  async getAreaSnapshot(areaId, signal) {
    const [snapshot, cameras] = await Promise.all([
      getJson<ApiSnapshot>(pathWithQuery('/dashboard/snapshot', areaId), signal),
      getJson<ApiCamera[]>(pathWithQuery('/dashboard/cameras', areaId), signal),
    ])
    return mapSnapshot(snapshot, cameras.map(mapCamera))
  },

  async listActiveAlerts(signal) {
    const response = await getJson<ApiAlert[] | { alerts: ApiAlert[] }>('/dashboard/alerts', signal)
    return (Array.isArray(response) ? response : response.alerts).map(mapAlert)
  },

  acknowledgeAlert(alertId, action) {
    return postJson(`/alerts/${encodeURIComponent(alertId)}/ack`, { action })
  },
}

export default httpSource
