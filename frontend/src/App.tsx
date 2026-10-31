import { useEffect, useState } from 'react'
import { getDbHealth, getHealth } from './api/health'

type Status = { state: 'loading' } | { state: 'ok'; detail: string } | { state: 'error'; detail: string }

const errorText = (e: unknown) => (e instanceof Error ? e.message : String(e))

function App() {
  const [server, setServer] = useState<Status>({ state: 'loading' })
  const [db, setDb] = useState<Status>({ state: 'loading' })

  useEffect(() => {
    const ctrl = new AbortController()
    getHealth(ctrl.signal)
      .then((h) => setServer({ state: 'ok', detail: `commit ${h.commit}` }))
      .catch((e) => !ctrl.signal.aborted && setServer({ state: 'error', detail: errorText(e) }))
    getDbHealth(ctrl.signal)
      .then((h) => setDb({ state: 'ok', detail: h.db }))
      .catch((e) => !ctrl.signal.aborted && setDb({ state: 'error', detail: errorText(e) }))
    return () => ctrl.abort()
  }, [])

  return (
    <main>
      <h1>CCTV Safety</h1>
      <p>backend: {server.state}{server.state !== 'loading' && ` (${server.detail})`}</p>
      <p>db: {db.state}{db.state !== 'loading' && ` (${db.detail})`}</p>
    </main>
  )
}

export default App
