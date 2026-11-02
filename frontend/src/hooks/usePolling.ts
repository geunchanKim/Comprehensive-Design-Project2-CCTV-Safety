import { useCallback, useEffect, useRef, useState } from 'react'

export type PollState<T> =
  | { state: 'loading' }
  | { state: 'ok'; data: T }
  | { state: 'error'; detail: string }

// 실시간 화면용: intervalMs마다 다시 불러온다. 첫 로드 이후 실패는 마지막 데이터를 유지한다.
// 나중에 SSE로 바꾸더라도 이 훅만 갈아끼우면 된다
export function usePolling<T>(fetcher: (signal: AbortSignal) => Promise<T>, intervalMs: number) {
  const [result, setResult] = useState<PollState<T>>({ state: 'loading' })
  const fetcherRef = useRef(fetcher)
  useEffect(() => {
    fetcherRef.current = fetcher
  })
  const [tick, setTick] = useState(0)

  useEffect(() => {
    const ctrl = new AbortController()
    fetcherRef.current(ctrl.signal)
      .then((data) => setResult({ state: 'ok', data }))
      .catch((e: unknown) => {
        if (ctrl.signal.aborted) return
        setResult((prev) => (prev.state === 'ok' ? prev : { state: 'error', detail: e instanceof Error ? e.message : String(e) }))
      })
    const timer = setTimeout(() => setTick((t) => t + 1), intervalMs)
    return () => {
      ctrl.abort()
      clearTimeout(timer)
    }
  }, [tick, intervalMs])

  const refresh = useCallback(() => setTick((t) => t + 1), [])
  return [result, refresh] as const
}
