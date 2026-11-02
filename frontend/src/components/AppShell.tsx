import { useEffect, useState } from 'react'
import { Outlet } from 'react-router'
import { dataSource } from '../api/source'
import { usePolling } from '../hooks/usePolling'
import type { ShellContext } from '../hooks/useShell'
import DangerAlertModal from './DangerAlertModal'
import Sidebar from './Sidebar'

// 모든 화면 공통: 사이드바(구역 목록) + 위험 팝업. 경고는 1초마다 다시 불러온다
export default function AppShell() {
  const [areas] = usePolling((signal) => dataSource.listAreas(signal), 5000)
  const [alerts, refreshAlerts] = usePolling((signal) => dataSource.listActiveAlerts(signal), 1000)
  const [nowMs, setNowMs] = useState(() => Date.now())

  useEffect(() => {
    const timer = setInterval(() => setNowMs(Date.now()), 500)
    return () => clearInterval(timer)
  }, [])

  const acknowledge = async (alertId: string, action: string | null) => {
    await dataSource.acknowledgeAlert(alertId, action)
    refreshAlerts()
  }

  const ctx: ShellContext = {
    nowMs,
    areas: areas.state === 'ok' ? areas.data : [],
    alerts: alerts.state === 'ok' ? alerts.data : [],
    acknowledge,
  }

  return (
    <div className="shell">
      <Sidebar areas={ctx.areas} />
      <main className="main">
        <Outlet context={ctx} />
      </main>
      <DangerAlertModal alerts={ctx.alerts} areas={ctx.areas} nowMs={nowMs} onAcknowledge={acknowledge} />
    </div>
  )
}
