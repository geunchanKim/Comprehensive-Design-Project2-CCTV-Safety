// 화면이 쓰는 데이터 모양. 서버 dashboard snapshot 계약을 camelCase로 옮긴 것. 좌표는 미터, 월드 바닥 좌표(X 오른쪽, Y 위쪽).
// 백엔드 응답(snake_case)은 http 소스에서 이 모양으로 바꿔서 넘긴다. 명세: docs/specs/frontend-api.md

export interface Vec2 {
  x: number
  y: number
}

export interface Rect {
  x: number
  y: number
  w: number
  h: number
}

export type Level = 'safe' | 'warning' | 'danger'

// 구역 상태 = 그 구역 경고 중 가장 심각한 것. 카메라가 끊기면 offline(감시 불가)
export type AreaStatus = 'ok' | 'warning' | 'danger' | 'offline'

// 지도 범위. 서버 snapshot의 map.bounds와 같고, 월드 바닥 좌표(world_xy_m)를 그대로 쓴다
export interface MapBounds {
  xMin: number
  xMax: number
  yMin: number
  yMax: number
}

// 지금은 blocks만 그린다. 도면 이미지는 이미지가 덮는 월드 범위를 같이 받아 아래에 깐다
export type Background =
  | { kind: 'blocks' }
  | { kind: 'image'; url: string; bounds: MapBounds }

// 서버 risk-zones 형식. vertices는 바닥 [X,Y] 꼭짓점 (첫 점 반복 없음)
export interface Zone {
  zoneId: string
  name: string
  vertices: Vec2[]
  warningDistanceM: number
  enabled: boolean
}

export interface AreaConfig {
  areaId: string
  name: string
  coordinateFrameId: string
  bounds: MapBounds
  background: Background
  zones: Zone[]
}

// yawDeg는 지도 좌표 +X에서 반시계 방향, fovDeg는 수평 시야
export interface Camera {
  cameraId: string
  position: Vec2
  yawDeg: number
  fovDeg: number
  online: boolean | null
  lastFrameAtMs: number | null
}

export type ClassShape = 'circle' | 'wide' | 'square'

// 사람은 항상 보호 대상. 나머지는 설정에서 켠 클래스만 내려온다
export interface ClassInfo {
  cls: string
  label: string
  shape: ClassShape
  protected?: boolean
}

// unknown은 미판단. 안전으로 표시하지 않는다
export interface VestState {
  status: 'wearing' | 'not_wearing' | 'unknown'
  confidence: number | null
  observedAtMs: number | null
}

export interface ZoneState {
  zoneId: string
  status: 'outside' | 'warning' | 'intrusion' | 'unknown'
  distanceM: number | null
}

export interface TrackedObject {
  objectId: number
  cls: string
  world: Vec2
  velocity: Vec2 | null
  // 카메라별 track ID. 1개뿐이면 한 카메라로만 추정한 위치
  cameraTracks: Record<string, number>
  vest: VestState
  zoneStates: ZoneState[]
  // 서버는 보내지 않는다. 데이터 소스가 최근 snapshot 위치를 쌓아 채운다 (오래된 것부터)
  trail: Vec2[]
}

// 위험 3종(충돌·위험 구역·안전조끼) + 카메라 끊김 같은 시스템 경고
export type AlertKind = 'collision' | 'zone' | 'vest' | 'system'

export interface Alert {
  alertId: string
  areaId: string
  kind: AlertKind
  level: 'warning' | 'danger'
  object1Id?: number
  object2Id?: number
  zoneId?: string
  distanceM?: number
  ttcS?: number
  contact?: Vec2
  message?: string
  startedAtMs: number
  acknowledged: boolean
}

export interface AreaSummary {
  areaId: string
  name: string
  rect: Rect
  status: AreaStatus
  people: number | null
  cameras: { online: number; total: number }
}

export interface AreaSnapshot {
  config: AreaConfig
  classes: ClassInfo[]
  objects: TrackedObject[]
  alerts: Alert[]
  // false인 판단은 결과가 비어 있어도 안전이 아니라 미판단
  evaluated: { collision: boolean; zone: boolean; vest: boolean }
  capturedAtMs: number
  staleAfterMs: number
}
