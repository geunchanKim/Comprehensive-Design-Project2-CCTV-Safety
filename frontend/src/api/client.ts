// 모든 백엔드 요청은 /api 접두어로 보낸다 (vite 프록시가 백엔드로 넘김)
const API_BASE = '/api'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { signal })
  if (res.status === 204) {
    throw new ApiError(204, 'no data')
  }
  if (!res.ok) {
    throw new ApiError(res.status, `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export async function postJson(path: string, body: unknown, signal?: AbortSignal): Promise<void> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!res.ok) {
    throw new ApiError(res.status, `${res.status} ${res.statusText}`)
  }
}
