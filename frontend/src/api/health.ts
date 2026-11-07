import { getJson } from './client'

// backend/main.py 의 GET /health 응답 (실험 설정 값들은 자주 바뀌어서 느슨하게 둔다)
export interface Health {
  status: 'ok'
  commit: string
  algorithms: Record<string, Record<string, unknown>>
  feature_codes: Record<string, string>
  [key: string]: unknown
}

// GET /health/db — DB 연결 실패 시 백엔드가 500을 돌려준다
export interface DbHealth {
  status: 'ok'
  db: 'connected'
}

export const getHealth = (signal?: AbortSignal) => getJson<Health>('/health', signal)

export const getDbHealth = (signal?: AbortSignal) => getJson<DbHealth>('/health/db', signal)
