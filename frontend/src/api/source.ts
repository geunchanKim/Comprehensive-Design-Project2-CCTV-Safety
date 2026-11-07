import { mockSource } from './mock/mockSource'
import type { Alert, AreaSnapshot, AreaSummary } from './types'

// 화면은 이 인터페이스만 본다. 지금은 mock 하나뿐이고,
// 백엔드 읽기 API가 생기면 http 구현을 추가해 VITE_DATA_SOURCE로 고른다
export interface DataSource {
  listAreas(signal?: AbortSignal): Promise<AreaSummary[]>
  getAreaSnapshot(areaId: string, signal?: AbortSignal): Promise<AreaSnapshot>
  // 모든 구역의 진행 중 경고 (위험 팝업·전체 현황용)
  listActiveAlerts(signal?: AbortSignal): Promise<Alert[]>
  acknowledgeAlert(alertId: string, action: string | null): Promise<void>
}

export const dataSource: DataSource = mockSource
