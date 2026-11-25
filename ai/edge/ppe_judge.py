"""
엣지 보호구 판별: 사람 탐지마다 사람 영역을 잘라 보호구 모델(ai/ppe)로 안전모·조끼 상태를 붙인다.

순서: 사람 탐지·추적(detector.py) → 판별할 사람 고르기 → 사람 영역 자르기(학습과 같은 expand_box)
      → 보호구 4종 탐지(한 번에 묶어서) → 사람마다 상태(ppe_common.decide_state) → 탐지에 vest·helmet 붙임

매 프레임 모든 사람을 판별하지 않는다
  - 추적 ID마다 --ppe-interval-ms(기본 500ms)가 지나야 다시 판별한다
  - 한 프레임에 최대 --ppe-max-people(기본 4)명만. 오래 판별 안 한 사람(처음 본 사람)부터
  - 추적 ID가 없거나 사람 높이가 MIN_PERSON_HEIGHT 미만이면 판별하지 않는다 (학습 데이터에서도 뺀 크기)

서버 계약 (해민 feat/server-ppe-status, docs/specs/ppe-state.md)
  사람 탐지에 선택 필드로 붙인다. 판별한 프레임에만 붙이고, 판별 안 한 프레임은 필드를 뺀다
    "vest":   {"status": "wearing" | "not_wearing" | "unknown", "confidence": 0~1 | null, "observed_at_ms": ts}
    "helmet": {...같은 형식}
  - observed_at_ms 는 판별한 프레임의 ts (frame.ts 와 같은 시계, frame.ts 이하)
  - 판별했지만 애매하면 unknown + confidence null
  - 서버는 3번 연속 같은 결과면 확정하고 마지막 결과를 3초 유지 → 판별 간격은 1초 이하로 둔다
"""

import sys
import time
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent.parent           # ai/
sys.path.insert(0, str(AI_DIR / "ppe"))

from ppe_common import ITEMS, decide_state, expand_box  # noqa: E402

DEFAULT_WEIGHTS = AI_DIR / "runs" / "ppe_v1" / "weights" / "best.pt"
MIN_PERSON_HEIGHT = 48          # ppe/build_crops.py 와 같은 값 (원본 픽셀)
SERVER_HOLD_MS = 3000           # 서버가 마지막 결과를 유지하는 시간


class PpeSchedule:
    """추적 ID마다 마지막 판별 시각을 기억하고, 이번 프레임에 판별할 사람을 고른다"""

    def __init__(self, interval_ms: float = 500, max_per_frame: int = 4, forget_ms: float = 10_000):
        if interval_ms <= 0 or interval_ms >= SERVER_HOLD_MS:
            raise ValueError(f"판별 간격은 0보다 크고 서버 유지 시간({SERVER_HOLD_MS}ms)보다 짧아야 해요: {interval_ms}")
        if max_per_frame < 1:
            raise ValueError(f"한 프레임 최대 인원은 1 이상이어야 해요: {max_per_frame}")
        self.interval_ms = interval_ms
        self.max_per_frame = max_per_frame
        self.forget_ms = forget_ms
        self.last = {}              # track_id → 마지막 판별 ts

    def pick(self, detections: list[dict], ts_ms: int) -> list[int]:
        """판별할 탐지 번호. 처음 본 사람 → 오래 판별 안 한 사람 순"""
        due = []
        for i, d in enumerate(detections):
            tid = d.get("track_id")
            if d.get("cls") != "person" or tid is None or d["bbox"][3] - d["bbox"][1] < MIN_PERSON_HEIGHT:
                continue
            last = self.last.get(tid)
            if last is None or ts_ms - last >= self.interval_ms or ts_ms < last:   # 시각이 뒤로 가면(재생 다시 시작) 다시 판별
                due.append((-1 if last is None else last, i))
        due.sort()
        return [i for _, i in due[:self.max_per_frame]]

    def mark(self, track_ids, ts_ms: int):
        for tid in track_ids:
            self.last[tid] = ts_ms
        # 오래 안 보인 ID는 잊는다 (메모리가 계속 늘지 않게)
        self.last = {tid: t for tid, t in self.last.items() if ts_ms - t < self.forget_ms and t <= ts_ms}


def crop_person(frame, bbox):
    """사람 상자를 학습 때와 같은 비율로 넓혀 자른다 (원본 해상도)"""
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = expand_box(bbox, w, h)
    return frame[y1:y2, x1:x2]


def judge_people(frame, detections: list[dict], ts_ms: int, schedule: PpeSchedule, predict, conf_min: float = 0.4):
    """
    고른 사람에게 vest·helmet 을 붙인다 (detections 를 직접 바꿈). 판별한 인원 수를 돌려준다
    predict(crops) → 사람마다 [(클래스, conf, cx, cy, w, h)] 목록 (영역 기준 정규화 좌표)
    """
    picked = schedule.pick(detections, ts_ms)
    if not picked:
        return 0
    results = predict([crop_person(frame, detections[i]["bbox"]) for i in picked])
    for i, boxes in zip(picked, results):
        state = decide_state(boxes, conf_min)
        for item in ITEMS:      # 서버 필드 이름이 항목 이름과 같다 (helmet, vest)
            detections[i][item] = {**state[item], "observed_at_ms": int(ts_ms)}
    schedule.mark([detections[i]["track_id"] for i in picked], ts_ms)
    return len(picked)


class PpeJudge:
    """카메라 한 대용 보호구 판별기. 추적 ID가 카메라마다 다르므로 카메라마다 하나씩 만든다"""

    def __init__(self, weights=DEFAULT_WEIGHTS, interval_ms: float = 500, max_per_frame: int = 4,
                 conf_min: float = 0.4, imgsz: int = 320, device: str | None = None):
        weights = Path(weights).expanduser()
        if not weights.exists():
            raise FileNotFoundError(f"보호구 모델이 없어요: {weights}\n"
                                    f"  ppe/train_ppe.py 로 학습하거나 --ppe-weights 로 경로를 주세요")
        from ultralytics import YOLO                     # torch는 판별기를 만들 때만 불러옴 (테스트는 YOLO 없이)
        from detector import get_device
        self.model = YOLO(str(weights))
        self.weights = weights
        self.schedule = PpeSchedule(interval_ms, max_per_frame)
        self.conf_min = conf_min
        self.imgsz = imgsz
        self.device = device or get_device()
        self.last_ms = 0.0          # 마지막 호출에서 걸린 시간
        self.last_people = 0        # 마지막 호출에서 판별한 인원

    def _predict(self, crops):
        results = self.model.predict(crops, imgsz=self.imgsz, conf=self.conf_min, device=self.device, verbose=False)
        return [[(int(c), float(p), *map(float, b))
                 for c, p, b in zip(r.boxes.cls, r.boxes.conf, r.boxes.xywhn)] for r in results]

    def __call__(self, frame, detections: list[dict], ts_ms: int) -> list[dict]:
        t0 = time.perf_counter()
        self.last_people = judge_people(frame, detections, ts_ms, self.schedule, self._predict, self.conf_min)
        self.last_ms = round((time.perf_counter() - t0) * 1000, 1)
        return detections

    def config(self) -> dict:
        return {"weights": str(self.weights), "interval_ms": self.schedule.interval_ms,
                "max_per_frame": self.schedule.max_per_frame, "conf_min": self.conf_min, "imgsz": self.imgsz}


def add_ppe_args(parser):
    """realtime.py·unity_reader.py 공통 옵션"""
    group = parser.add_argument_group("보호구 판별")
    group.add_argument("--ppe", action="store_true", help="사람마다 안전모·조끼 판별 결과(helmet·vest)를 붙여 보냄")
    group.add_argument("--ppe-weights", default=str(DEFAULT_WEIGHTS), help="보호구 모델 (기본 runs/ppe_v1)")
    group.add_argument("--ppe-interval-ms", type=float, default=500, help="같은 사람을 다시 판별하는 간격 (서버 유지 3초보다 짧게)")
    group.add_argument("--ppe-max-people", type=int, default=4, help="한 프레임에 판별할 최대 인원")
    group.add_argument("--ppe-conf", type=float, default=0.4, help="이보다 낮은 보호구 탐지는 무시 (없으면 unknown)")
    return group


def make_judges(args, cameras) -> dict:
    """--ppe 면 카메라마다 판별기, 아니면 빈 dict"""
    if not args.ppe:
        return {}
    return {cam: PpeJudge(args.ppe_weights, args.ppe_interval_ms, args.ppe_max_people, args.ppe_conf)
            for cam in cameras}
