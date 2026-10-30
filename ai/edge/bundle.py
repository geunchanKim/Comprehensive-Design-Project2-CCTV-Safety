"""
서버로 보내는 탐지 묶음 만들기 (엣지 ↔ 서버 계약)

unity_reader.py(폴더 재생)와 realtime.py(실시간 카메라)가 같이 쓴다.
서버 API가 바뀌면 여기만 고친다. 기준 문서: 실측 촬영용 캘리브레이션·session_id·API 정리 (10/12)

session_id 규칙: {site}-{MMDD}-{scenario}-t{take}[-v{n}]
  예: classroom-1014-s2-t1, diy-1014-s1-t3-v2
  - 해민이 이 이름으로 캘리브레이션(cam1·cam2 × basic·precise)을 먼저 등록한다
  - 엣지는 목록 파일(sessions/<site>-<MMDD>.txt)에 있는 이름만 쓴다
  - 같은 영상을 다시 보낼 때만 -v2, -v3 … (서버는 같은 session·pair 중복을 409로 막음)

POST /detections 묶음
  {session_id, calibration_profile: "basic", pair_id,
   max_sync_delta_ms,
   frames: [{camera_id, frame_id, ts, pts_ms, recv_ms, image_size, detections: [...]}, × 2]}
  detections: {track_id, cls, conf, bbox, foot, foot_src, ankles?}
  - ankles: 사람의 좌우 발목 {left: [x, y, conf] | null, right: [x, y, conf] | null} (feet.py)
  - calibration_profile은 항상 basic. precise는 서버 recompute로만 만든다
  - ts는 카메라마다 노트북이 받은 시각(epoch ms). 두 카메라 차이는 50ms 이내만 보낸다
"""

import re
from pathlib import Path

# 서버(ObjectClass)가 받는 클래스. 서버에 클래스가 추가되면 여기에도 추가한다
SERVER_CLASSES = {"person", "chair", "cart", "desk", "suitcase", "backpack"}
PROFILE = "basic"
MAX_SYNC_DELTA_MS = 50          # 서버 MAX_SYNC_DELTA_MS 와 같아야 함
SESSION_RE = re.compile(r"^(diy|classroom)-\d{4}-s\d+-t\d+(-v\d+)?$")


def check_session_id(session_id: str, session_list: str | None = None) -> str:
    """규칙에 맞는지, 목록 파일이 있으면 목록에 있는지 확인한다. 아니면 이유를 말하고 멈춘다"""
    if not SESSION_RE.fullmatch(session_id):
        raise SystemExit(f"session_id 규칙에 안 맞아요: {session_id}\n"
                         f"  형식: {{diy|classroom}}-{{MMDD}}-s{{시나리오}}-t{{회차}}[-v{{n}}]  예: classroom-1014-s2-t1")
    if session_list:
        names = load_session_list(session_list)
        if session_id not in names:
            raise SystemExit(f"목록에 없는 session_id예요: {session_id}\n"
                             f"  목록: {session_list} ({len(names)}개). 해민이 등록한 이름인지 확인하세요")
    return session_id


def load_session_list(path: str) -> list[str]:
    """한 줄에 session_id 하나. 빈 줄과 # 주석은 건너뜀"""
    lines = Path(path).expanduser().read_text(encoding="utf-8").splitlines()
    return [s.strip() for s in lines if s.strip() and not s.strip().startswith("#")]


def clean_detections(dets: list[dict], width: int, height: int) -> tuple[list[dict], int]:
    """서버 검증에 걸리는 탐지를 정리한다. (정리된 목록, 뺀 개수)
    - track_id가 아직 없는 탐지는 뺀다 (서버는 0 이상 정수만 받음)
    - 서버가 모르는 클래스는 뺀다 (하나라도 있으면 묶음 전체가 422)
    - bbox·foot은 이미지 안으로 자르고, 폭·높이가 1px 미만인 박스는 뺀다"""
    kept, removed = [], 0
    for d in dets:
        if d["track_id"] is None or d["track_id"] < 0 or d["cls"] not in SERVER_CLASSES:
            removed += 1
            continue
        x1, y1, x2, y2 = d["bbox"]
        x1, x2 = max(0.0, min(x1, float(width))), max(0.0, min(x2, float(width)))
        y1, y2 = max(0.0, min(y1, float(height))), max(0.0, min(y2, float(height)))
        if x2 - x1 < 1 or y2 - y1 < 1:
            removed += 1
            continue
        item = {**d, "bbox": [round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1)]}
        if d.get("foot"):
            # 서버는 0 <= foot < 크기 를 요구한다 (끝 픽셀 포함 안 됨)
            item["foot"] = _inside(d["foot"], width, height)
        if d.get("ankles"):
            item["ankles"] = {side: (_inside(p, width, height) + [p[2]] if p else None)
                              for side, p in ((s, d["ankles"].get(s)) for s in ("left", "right"))}
        kept.append(item)
    return kept, removed


def _inside(point, width: int, height: int) -> list:
    """[x, y, ...] → 이미지 안으로 자른 [x, y]"""
    return [round(max(0.0, min(point[0], width - 0.1)), 1), round(max(0.0, min(point[1], height - 0.1)), 1)]


def build_frame(camera_id: str, frame_id: int, ts: int, image_size, detections: list[dict],
                pts_ms: float | None = None, recv_ms: int | None = None) -> dict:
    frame = {"camera_id": camera_id, "frame_id": int(frame_id), "ts": int(ts),
             "image_size": [int(image_size[0]), int(image_size[1])], "detections": detections}
    if pts_ms is not None:
        frame["pts_ms"] = round(float(pts_ms), 3)
    if recv_ms is not None:
        frame["recv_ms"] = int(recv_ms)
    return frame


def build_bundle(session_id: str, pair_id: int, frames: list[dict],
                 max_sync_delta_ms: int = MAX_SYNC_DELTA_MS) -> dict:
    return {"session_id": session_id, "calibration_profile": PROFILE, "pair_id": int(pair_id),
            "max_sync_delta_ms": int(max_sync_delta_ms), "frames": frames}


def edge_config(detector) -> dict:
    """어떤 엣지 설정으로 탐지했는지 남긴다 (실험 pack·설계도에서 읽음)"""
    return {"model": detector.model_name, "imgsz": detector.imgsz, "foot": detector.foot,
            "classes": list(detector.classes), "conf": detector.conf, "class_conf": detector.class_conf,
            "tracker": detector.tracker}


def explain_failure(status, response) -> str | None:
    """서버가 거절한 이유를 사람이 바로 알 수 있게 바꾼다. 멈춰야 하는 실패면 문장, 아니면 None"""
    text = str(response)
    if status == 404 and "calibration" in text:
        return "이 session_id로 캘리브레이션이 등록되지 않았어요. 해민에게 같은 이름으로 등록됐는지 확인하세요"
    if status == 422 and "image_size" in text:
        return "해상도가 캘리브레이션과 달라요. Tapo 앱 화질을 '최고 화질'(1920x1080)로 맞추세요"
    if status == 409 and "experiment settings" in text:
        return "이 session_id는 다른 서버 설정으로 이미 처리됐어요. 새 이름(-v2)을 쓰세요"
    if status == 409:
        return "이 session_id로 이미 보낸 묶음이 있어요. 다시 보내려면 -v2 이름을 쓰세요"
    return None
