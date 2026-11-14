import httpSource from './httpSource'
import type { Alert, AreaSnapshot, AreaSummary, Camera } from './types'

// 화면은 이 인터페이스만 본다.
export interface DataSource {
  listAreas(signal?: AbortSignal): Promise<AreaSummary[]>
  getAreaSnapshot(areaId: string, signal?: AbortSignal): Promise<AreaSnapshot>
  // 카메라 연결 상태는 snapshot과 따로 조회한다. snapshot이 없을 때(204)도 연결 상태는 보여야 한다
  listCameras(areaId: string, signal?: AbortSignal): Promise<Camera[]>
  // 모든 구역의 진행 중 경고 (위험 팝업·전체 현황용)
  listActiveAlerts(signal?: AbortSignal): Promise<Alert[]>
  acknowledgeAlert(alertId: string, action: string | null): Promise<void>
}

export const dataSource: DataSource = httpSource
