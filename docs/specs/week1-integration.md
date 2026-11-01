# 1주 차 담당자 회신 반영

2026-11-01 [AI 회신](https://github.com/geunchanKim/Comprehensive-Design-Project2-CCTV-Safety/issues/71)과 [Unity·대시보드 회신](https://github.com/geunchanKim/Comprehensive-Design-Project2-CCTV-Safety/issues/72)을 기준으로 서버 준비 작업을 정리한다.

## 녹화 재생과 캘리브레이션

- AI는 MacBook Pro M3 Pro/MPS, COCO yolo11n + yolo11n-pose, imgsz 1280, foot ankle로 10/14 녹화 15개를 재생한다. 전체 약 4분이며 10분 실시간 실행과 별도 조건이다.
- v6는 현 배포 서버로 엣지·RTT를 측정하고, 계측 서버 배포 이후 v7으로 같은 녹화를 반복한다. 배포일은 PR 컨펌·push·리뷰 이후 결정한다.
- 10/14와 카메라 위치가 같다는 AI 회신에 따라 `calib-classroom-1014-2x2b.json`을 후보로 사용한다. session_id만 새 이름으로 두고 cam1/cam2 × basic/precise 네 payload를 검증한다.
- 실제 등록에는 기존 `ai/calibration/register_calibration.py`를 재사용한다. 이번에 추가한 `prepare_replay_calibrations`는 오프라인 사전 검증만 하며 서버에 접속하지 않는다.

```powershell
# 저장소 루트. AI가 확정한 세션 목록을 한 줄에 하나씩 적은 파일을 사용
python -m backend.tools.prepare_replay_calibrations --calibration ai/calibration/output/calib-classroom-1014-2x2b.json --sessions ai/runs/week1-prep/sessions-v6.txt --out ai/runs/week1-prep/registration-plan-v6.json

# 등록 시점에 별도로 실행하는 기존 명령. 현재는 실행하지 않음
python ai/calibration/register_calibration.py --calib ai/calibration/output/calib-classroom-1014-2x2b.json --sessions ai/runs/week1-prep/sessions-v6.txt --backend-url http://서버주소:32130
```

전체 15개 세션 이름은 AI 확정 목록을 받아 사용하며 추측해서 생성하지 않는다. 현재 확인된 예시 `classroom-1014-s10-t1-v6/v7`에 대해서는 8개 payload 사전 검증을 완료했다. 기존 등록기는 PUT으로 값을 갱신하므로 과거 실험 이름을 재사용하지 않는다.

## Unity 입력과 지도

이번 평가는 world→(x,z,y)를 유지하며 rel로 바꾸지 않는다. 4m 격자에 0.5m씩 여유를 둔 지도 범위는 X 2.79~7.79m, Y 1.785~6.785m이다. 지도·위험구역 frame ID는 `unity-world-xzy`다. 실측 마커 좌표와는 분리한다.

| 검증 목적 | 우선 재사용할 장면 |
| --- | --- |
| 이동 위치 오차 | sc6 한 명만 이동하는 구간 또는 sc8. 다른 사람이 정지해 있어도 이동하는 사람만 채점 |
| 엇갈림·ID 유지 | sc2. 충돌 정확도 주 채점에는 사용하지 않음 |
| 사람–사람/사람–의자 위험 | sc10. 경계값 0.5m에 머무는 sc1은 주의 확인용 |
| 구역 진입·이탈 | sc6/8/9의 기존 GT로 산출 |
| 주의만 발생하는 음성 예시 | sc4 person_1 구간과 기존 외부 구간. 새 장면은 우선 요청하지 않음 |

사람–의자도 현재 계산 함수의 기본값은 주의 `<1.0m`, 위험 `<0.5m`이며 중심 바닥 좌표 간 거리다. 전체 위험 분석 플래그는 false를 유지하므로 지금 기본 배포에서 사람–의자 경고가 켜진 것은 아니다. 종류별 거리 설정·활성화는 3주 차에 진행한다. cdfg 사람–사람 경고 유지에는 해제 여유 0.1m가 있으므로 GT 거리 임계값과 히스테리시스 출력을 구분해 채점한다.

`events.json`은 계획 경로 기준이고 발목 가운데 GT와 1~2프레임 차이가 날 수 있다. 이동 위치 오차와 경고 채점에서 피벗·발목 GT를 혼합하지 않는다. 구역 정답은 GT 위치+구역 JSON에서 계산하는 방식으로 준비한다.

## sc10 실제 파일 호환성

공유 ZIP에서 이미지 2×130개의 존재, 15fps/130행 시각, 객체별 world→서버 GT 스키마, world/rel 평행이동, 카메라 payload·좌표 삼각측량 왕복, 이벤트 참조를 확인했다. 이미지 디코딩·YOLO 추론이나 경고 정확도 채점은 이 검사의 범위가 아니다.

```powershell
python -m backend.tools.check_unity_metadata ai/runs/week1-prep/unity-grid-sc10.zip --out ai/runs/week1-prep/unity-sc10-check.json
```

객체 기록 520건, 이벤트 10개, 경고 구간 정의 4개, 카메라 뒤쪽 객체 0건이다. [검증 결과 JSON](../benchmarks/2026-11-01-unity-sc10-metadata.json)에 기록했다. 좌표 왕복 최대 오차는 약 8.0e-15m였다. 발목 가운데 GT 390건 중 26건은 높이 0.15m를 넘었다. 이는 실제 탐지·서버 탈락률이 아니며, 실측 기준값 0.15m를 변경하지 않고 2주 차 위치 평가 때 확인한다.

## 담당자에게 남은 확인

- AI: 15개 정확한 세션 목록, 실행 커밋·기록 공유 위치, yolo/pose/RTT 로그 샘플. 교실 사진 일정과 조끼 준비 현황은 회신에 미기입 상태다.
- Unity/프론트: 메시지 추가 필드 반영 의견과 디자인 시안. 지도 범위·seq·stale 기준·지원 클래스는 [snapshot 명세](dashboard-stream.md)에 반영했다.
- 서버: PR 컨펌 전 push·배포하지 않는다. 전체 위험 분석 활성화와 실시간 API는 이번 준비 작업에서 앞당기지 않는다.
