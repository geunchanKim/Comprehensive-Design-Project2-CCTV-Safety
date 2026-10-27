# ai/

엣지(탐지·추적·전송), 캘리브레이션, 성능 평가 코드. 모든 명령은 `ai/` 폴더에서 실행한다.

## 폴더 구조

```
ai/
├── edge/                    실제 파이프라인
│   ├── realtime.py            카메라 2대 수신 → 프레임 짝짓기(수신 시각 50ms) → 녹화·탐지·서버 전송
│   ├── detector.py            YOLO11n(COCO) 탐지 + 카메라별 ByteTrack 추적
│   ├── feet.py                발 위치: YOLO11n-pose 두 발목 중점 (신뢰도 낮으면 박스 하단)
│   ├── bundle.py              서버로 보낼 탐지 묶음 만들기
│   ├── camera_source.py       RTSP·웹캠·영상 입력
│   ├── unity_reader.py        Unity·녹화 폴더 읽기 → 탐지 → 서버 전송
│   ├── unity_calibration.py   Unity cameras.json → K, rvec, tvec
│   └── server_client.py       서버 전송 (실패 기록, 응답 저장)
├── calibration/             카메라 캘리브레이션
│   ├── capture_charuco.py, calibrate_camera.py   ChArUco 렌즈 캘리브레이션
│   ├── calibrate_grid.py, build_calibration.py   장소 캘리브레이션
│   ├── register_calibration.py, recompute_sessions.py  서버 등록·조건별 재계산
│   ├── results/               cam1·cam2 렌즈 값 (ChArUco)
│   └── output/                장소별 캘리브레이션. 논문 최종은 calib-classroom-1014-2x2b.json
├── eval/                    성능 평가
│   ├── run_experiment.py      pack을 서버에 다시 보내 조건별 비교표 만들기
│   ├── real_pack.py           실측 정지 프레임 pack 만들기
│   ├── eval_position.py       추정 위치 vs 정답 오차
│   ├── eval_detection.py      탐지 성능
│   └── packs/                 저장한 탐지 묶음 (real-* = 실측 15개, s1~s4 = Unity)
├── scripts/, train.py, configs/   자체 학습 데이터·모델 (최종 실험은 COCO 원본 사용)
├── tests/                   단위 테스트
├── tools/                   테스트 보조 도구
├── datasets/                (git 제외) 자체 학습 데이터
└── runs/                    (git 제외) 녹화·결과. 구성은 runs/README.md
```

## 논문 실험 다시 돌리기 (실측 2×2)

```bash
# 1. 녹화 → 탐지 (YOLO, 오래 걸림)
python edge/unity_reader.py runs/real/classroom/s1/t1 --dry-run

# 2. 탐지 + 정답 + 캘리브레이션 → pack
python eval/real_pack.py --edge runs/edge/classroom-1014-s1-t1-v5 \
    --gt runs/gt/classroom-1014-v2/diy-1014-s1-t1/frames.jsonl \
    --calib calibration/output/calib-classroom-1014-2x2b.json --name real-s1-t1 --force

# 3. 네 조건 채점 (기준 방법, 렌즈 캘리브레이션, 매칭 알고리즘, 두 방법 결합)
python eval/run_experiment.py run --server http://<서버>:32130 --packs real-s1-t1 --label real-2x2-v4

# 4. 조건 간 통계 검정 (논문 Ⅳ장의 Wilcoxon·TOST p값)
python eval/compare_conditions.py runs/experiments/real-2x2-v4

# 5. 검출 예시 그림 (팩 이름, 프레임 쌍 번호 → runs/figures/)
python eval/draw_detections.py real-s10-t1 604
```

## 규칙

- 녹화는 `runs/real/`, 탐지 결과는 `runs/edge/`, 실험 결과는 `runs/experiments/`에 둔다
- 서버는 같은 session_id를 다시 받지 않는다 (409)
- 메시지 양식: `docs/specs/message-spec.md`
