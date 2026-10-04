# ai/

엣지(탐지·전송)와 성능 측정 코드. 모든 명령은 `ai/` 폴더에서 실행한다.

## 폴더 구조

```
ai/
├── edge/                    실제 파이프라인
│   ├── detector.py            YOLO v2 탐지 + 카메라별 ByteTrack 추적
│   ├── unity_reader.py        Unity 폴더 읽기 → 캘리브레이션 등록 → 탐지·정답 서버 전송
│   ├── unity_calibration.py   cameras.json → K, rvec, tvec 계산·검증
│   └── server_client.py       서버 전송 (실패 기록, 서버 응답 저장)
├── eval/                    성능 측정
│   └── eval_position.py       서버 3D 좌표 vs 정답 좌표 오차
├── tools/                   테스트 보조 도구
│   └── make_fake_unity_run.py 영상·웹캠으로 Unity 형식 가짜 폴더 만들기
└── runs/                    (git 제외) 데이터와 결과
    ├── unity/<장면>/          입력: Unity 출력 폴더 (cam1/, cam2/, frames.jsonl, cameras.json)
    ├── edge/<장면>-runN/      결과: 전송 기록, 서버 응답, 오차표
    └── train_v1/, train_v2/   YOLO 학습 결과
```

## 자주 쓰는 명령

```bash
# 캘리브레이션 계산 + 검증
python edge/unity_calibration.py runs/unity/unity-classroom-02 --check

# 서버로 전송 (run 번호는 자동 증가)
python edge/unity_reader.py runs/unity/unity-classroom-02 --server http://121.182.60.2:32130

# 서버 없이 시험
python edge/unity_reader.py runs/unity/unity-classroom-02 --dry-run --save-every 1

# 서버 3D 좌표 오차 측정
python eval/eval_position.py runs/edge/unity-classroom-02-run3
```

## 결과 폴더 (`runs/edge/<장면>-runN/`)

| 파일 | 내용 |
|---|---|
| `sent_calibration.jsonl` | 등록한 캘리브레이션 |
| `sent_detections.jsonl` | 보낸 탐지 결과 |
| `sent_ground-truth.jsonl` | 보낸 정답 좌표 |
| `responses_detections.jsonl` | 서버 응답 (매칭, 3D 좌표) |
| `failed.jsonl` | 실패한 요청 (상태 코드 + 응답) |
| `position_errors.csv` | `eval_position.py` 결과 |
| `vis/` | 박스를 그린 이미지 (`--save-every`) |

## 규칙

- 입력은 `runs/unity/`, 결과는 `runs/edge/`에만 둔다
- 같은 장면을 다시 보내면 `-runN`이 늘어난다. 서버는 같은 session_id를 다시 받지 않는다 (409)
- 메시지 양식: `docs/specs/message-spec.md`
