# Frontend

CCTV Safety 프로젝트의 웹 프론트엔드입니다. Vite + React + TypeScript 기반입니다.

## 실행

```bash
cd frontend
npm install
npm run dev       # 개발 서버 (HMR)
```

## 스크립트

| 명령 | 설명 |
| --- | --- |
| `npm run dev` | 개발 서버 실행 |
| `npm run build` | 타입 체크 후 프로덕션 빌드 (`dist/`) |
| `npm run preview` | 빌드 결과 미리보기 |
| `npm run lint` | Oxlint 검사 |

## 구조

지금은 백엔드에 관제용 API가 없어서 **mock 데이터**로 화면을 그립니다. 필요한 API는 [docs/specs/frontend-api.md](../docs/specs/frontend-api.md)에 정리했고, API가 생기면 `src/api/source.ts`의 `dataSource`만 HTTP 구현으로 바꾸면 됩니다.

```
src/
  api/
    types.ts        화면이 쓰는 데이터 모양 (좌표는 미터)
    source.ts       DataSource 인터페이스와 현재 구현 선택
    mock/           예시 데이터와 mock 구현
  components/
    AppShell.tsx    사이드바 + 위험 팝업, 구역 목록·경고 polling
    FloorPlan.tsx   탑다운 평면도 (SVG, viewBox = 미터)
    DangerAlertModal.tsx  위험(danger) 팝업, 확인해야 닫힘
  pages/
    AreaPage.tsx    구역 관제 화면 (/areas/:areaId)
  hooks/            usePolling, useShell
  lib/safety.ts     경고 문구·시간 표시 같은 공통 함수
```

전체 현황(`/`), 이벤트 기록(`/events`), 설정(`/settings`)은 아직 자리만 있습니다.
