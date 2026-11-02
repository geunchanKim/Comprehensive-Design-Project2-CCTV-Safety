import type { Alert, AreaConfig, AreaSummary, Camera, ClassInfo, TrackedObject, VestState, ZoneState } from '../types'

// 디자인 시안과 같은 예시 데이터. 실제 연결은 구역 A(작업장 1)만 가정한다

export const CLASSES: ClassInfo[] = [
  { cls: 'person', label: '사람', shape: 'circle', protected: true },
  { cls: 'cart', label: '카트', shape: 'wide' },
  { cls: 'chair', label: '의자', shape: 'square' },
]

export const AREAS: AreaSummary[] = [
  { areaId: 'A', name: '작업장 1', rect: { x: 2, y: 2, w: 18, h: 14 }, status: 'danger', people: 3, cameras: { online: 2, total: 2 } },
  { areaId: 'B', name: '자재 창고', rect: { x: 22, y: 2, w: 14, h: 14 }, status: 'ok', people: 2, cameras: { online: 2, total: 2 } },
  { areaId: 'C', name: '출하장', rect: { x: 38, y: 2, w: 20, h: 14 }, status: 'warning', people: 6, cameras: { online: 2, total: 2 } },
  { areaId: 'D', name: '조립 라인', rect: { x: 2, y: 18, w: 26, h: 16 }, status: 'ok', people: 8, cameras: { online: 2, total: 2 } },
  { areaId: 'E', name: '검사실', rect: { x: 30, y: 18, w: 12, h: 16 }, status: 'offline', people: null, cameras: { online: 1, total: 2 } },
  { areaId: 'F', name: '휴게실', rect: { x: 44, y: 18, w: 14, h: 16 }, status: 'ok', people: 0, cameras: { online: 2, total: 2 } },
]

// 구역 A 좌표는 서버 지도와 같은 월드 바닥 좌표 (X 오른쪽, Y 위쪽)
export const AREA_CONFIGS: Record<string, AreaConfig> = {
  A: {
    areaId: 'A',
    name: '작업장 1',
    coordinateFrameId: 'site-a',
    bounds: { xMin: 0, xMax: 9, yMin: 0, yMax: 7 },
    background: { kind: 'blocks' },
    zones: [{
      zoneId: 'z1', name: '위험 구역', warningDistanceM: 1.0, enabled: true,
      vertices: [{ x: 5.8, y: 0 }, { x: 8.4, y: 0 }, { x: 8.4, y: 1.4 }, { x: 5.8, y: 1.4 }],
    }],
  },
}

// lastFrameAtMs는 불러올 때 채운다
export const CAMERAS: Record<string, Omit<Camera, 'lastFrameAtMs'>[]> = {
  A: [
    { cameraId: 'cam1', position: { x: 0.4, y: 6.6 }, yawDeg: -45, fovDeg: 70, online: true },
    { cameraId: 'cam2', position: { x: 8.6, y: 6.6 }, yawDeg: -135, fovDeg: 70, online: true },
  ],
}

const vest = (status: VestState['status'], confidence: number | null): VestState =>
  ({ status, confidence, observedAtMs: null })
const zone = (status: ZoneState['status'], distanceM: number | null): ZoneState[] => [{ zoneId: 'z1', status, distanceM }]
const NO_PPE = vest('unknown', null)

export const OBJECTS: Record<string, TrackedObject[]> = {
  A: [
    {
      objectId: 3, cls: 'person', world: { x: 3.2, y: 3.6 }, velocity: { x: 0.9, y: -0.1 }, cameraTracks: { cam1: 10, cam2: 20 },
      vest: vest('wearing', 0.93), zoneStates: zone('outside', 3.41),
      trail: [{ x: 1.6, y: 3.1 }, { x: 2.0, y: 3.25 }, { x: 2.4, y: 3.4 }, { x: 2.8, y: 3.5 }],
    },
    {
      objectId: 21, cls: 'cart', world: { x: 3.9, y: 3.9 }, velocity: { x: -0.7, y: -0.2 }, cameraTracks: { cam1: 14, cam2: 22 },
      vest: NO_PPE, zoneStates: [],
      trail: [{ x: 5.5, y: 4.4 }, { x: 5.1, y: 4.3 }, { x: 4.7, y: 4.15 }, { x: 4.3, y: 4.05 }],
    },
    {
      objectId: 5, cls: 'person', world: { x: 6.6, y: 2.05 }, velocity: { x: 0.1, y: -0.35 }, cameraTracks: { cam1: 11, cam2: 23 },
      vest: vest('wearing', 0.9), zoneStates: zone('warning', 0.65),
      trail: [{ x: 6.2, y: 3.1 }, { x: 6.35, y: 2.75 }, { x: 6.5, y: 2.4 }],
    },
    {
      objectId: 9, cls: 'person', world: { x: 1.4, y: 1.3 }, velocity: { x: 0, y: 0 }, cameraTracks: { cam1: 12 },
      vest: vest('not_wearing', 0.82), zoneStates: zone('outside', 4.4), trail: [],
    },
    { objectId: 12, cls: 'chair', world: { x: 2.4, y: 5.0 }, velocity: null, cameraTracks: { cam1: 13, cam2: 24 }, vest: NO_PPE, zoneStates: [], trail: [] },
  ],
}

// startedAtMs는 불러올 때 현재 시각 기준으로 채운다 (sinceMs = 몇 ms 전에 시작했는지)
export const ALERTS: (Omit<Alert, 'startedAtMs'> & { sinceMs: number })[] = [
  {
    alertId: 'a-412', areaId: 'A', kind: 'collision', level: 'danger', object1Id: 3, object2Id: 21,
    distanceM: 0.76, ttcS: 1.1, contact: { x: 3.62, y: 3.75 }, sinceMs: 2400, acknowledged: false,
  },
  {
    alertId: 'a-411', areaId: 'A', kind: 'zone', level: 'warning', object1Id: 5, zoneId: 'z1',
    distanceM: 0.65, ttcS: 1.9, sinceMs: 3000, acknowledged: false,
  },
  { alertId: 'a-410', areaId: 'A', kind: 'vest', level: 'warning', object1Id: 9, sinceMs: 12000, acknowledged: false },
  {
    alertId: 'c-207', areaId: 'C', kind: 'zone', level: 'warning', object1Id: 2, zoneId: 'c-z1', message: '사람 #2 → 적재 구역',
    distanceM: 0.8, ttcS: 2.4, sinceMs: 41000, acknowledged: false,
  },
  { alertId: 'e-sys-1', areaId: 'E', kind: 'system', level: 'warning', message: 'CAM2 연결 끊김 · 감시 불가', sinceMs: 240000, acknowledged: false },
]
