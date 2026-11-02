// 화면이 쓰는 데이터 모양. 좌표는 모두 미터, 원점은 평면도 좌상단.
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

// 지금은 blocks만 그린다. 도면 이미지는 축척(m/px)과 원점을 같이 받아 아래에 깐다
export type Background =
  | { kind: 'blocks' }
  | { kind: 'image'; url: string; metersPerPixel: number; origin: Vec2 }

export interface Zone {
  zoneId: string
  kind: 'restricted'
  label: string
  rect: Rect
}

export interface AreaConfig {
  areaId: string
  name: string
  size: { w: number; h: number }
  background: Background
  zones: Zone[]
}

export interface Camera {
  cameraId: string
  position: Vec2
  yawDeg: number
  fovDeg: number
  online: boolean
  fps: number | null
}

export type ClassShape = 'circle' | 'wide' | 'square'

// 사람은 항상 보호 대상. 나머지는 설정에서 켠 클래스만 내려온다
export interface ClassInfo {
  cls: string
  label: string
  shape: ClassShape
  protected?: boolean
}

export type MatchingMethod = 'epipolar' | 'ground-plane' | 'single-camera'

export interface TrackedObject {
  objectId: number
  cls: string
  world: Vec2
  velocity: Vec2 | null
  matchingMethod: MatchingMethod
  trail: Vec2[]
  ppe?: { helmet: boolean; vest: boolean }
}

// 위험 3종(충돌·위험 구역·PPE) + 카메라 끊김 같은 시스템 경고
export type AlertKind = 'collision' | 'zone' | 'ppe' | 'system'

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
  cameras: Camera[]
  classes: ClassInfo[]
  objects: TrackedObject[]
  alerts: Alert[]
  capturedAtMs: number
}
