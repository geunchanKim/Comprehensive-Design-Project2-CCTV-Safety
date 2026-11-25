import { useOutletContext } from 'react-router'
import type { Alert, AreaSummary } from '../api/types'

// AppShell이 하위 화면에 내려주는 공통 상태
export interface ShellContext {
  nowMs: number
  areas: AreaSummary[]
  alerts: Alert[]
  acknowledge: (alertId: string, action: string | null) => Promise<void>
}

export const useShell = () => useOutletContext<ShellContext>()
