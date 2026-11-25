"""
보호구(안전모·안전조끼) 판별 공통 규칙. YOLO·torch 없이 돈다 (CI에서 테스트)

방식: 사람 탐지 → 사람 영역 자르기 → 잘라 낸 영역에서 보호구 4종 탐지 → 사람마다 상태 결정
결정 문서: docs/specs/ppe-dataset.md

보호구 모델 클래스 (잘라 낸 사람 영역 안에서 찾는다)
  0 helmet      안전모 씀
  1 no_helmet   안전모 안 씀 (머리가 보이는데 안전모가 없음)
  2 vest        조끼 입음
  3 no_vest     조끼 안 입음 (몸통이 보이는데 조끼가 없음)

사람마다 상태는 대시보드 VestState와 같은 값을 쓴다: wearing / not_wearing / unknown
"""

PPE_NAMES = ["helmet", "no_helmet", "vest", "no_vest"]
ITEMS = {"helmet": (0, 1), "vest": (2, 3)}  # 항목: (씀 클래스, 안 씀 클래스)

# Construction-PPE data.yaml 클래스 번호 → 보호구 모델 클래스 번호
SOURCE_PERSON = 5
SOURCE_TO_PPE = {0: 0, 6: 1, 2: 2, 11: 3}

# 사람 상자를 넓혀 자르는 비율 (상자 크기 기준). 안전모가 머리 위로 튀어나오므로 위쪽을 더 넓힌다
MARGIN_X = 0.10
MARGIN_TOP = 0.15
MARGIN_BOTTOM = 0.05


def yolo_to_xyxy(cx, cy, w, h, img_w, img_h):
    """YOLO 정규화 상자 → 픽셀 x1, y1, x2, y2"""
    return ((cx - w / 2) * img_w, (cy - h / 2) * img_h, (cx + w / 2) * img_w, (cy + h / 2) * img_h)


def expand_box(box, img_w, img_h):
    """사람 상자를 여유 있게 넓히고 화면 안으로 자른 정수 상자"""
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    return (max(0, int(x1 - bw * MARGIN_X)), max(0, int(y1 - bh * MARGIN_TOP)),
            min(img_w, int(round(x2 + bw * MARGIN_X))), min(img_h, int(round(y2 + bh * MARGIN_BOTTOM))))


def area(box):
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def intersection(a, b):
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def crop_labels(crop, ppe_boxes, min_visible=0.5):
    """
    잘라 낸 영역 안에 보이는 보호구 상자를 YOLO 정규화 라벨로 바꾼다
    ppe_boxes: [(보호구 클래스, (x1, y1, x2, y2)), ...] 원본 픽셀 좌표
    상자 넓이의 min_visible 이상이 영역 안에 있을 때만 넣고, 영역 밖은 잘라 낸다.
    옆 사람 보호구도 보이면 넣는다 (보이는데 라벨이 없으면 모델이 헷갈린다)
    """
    cx1, cy1, cx2, cy2 = crop
    cw, ch = cx2 - cx1, cy2 - cy1
    labels = []
    for cls, box in ppe_boxes:
        if area(box) <= 0 or intersection(crop, box) / area(box) < min_visible:
            continue
        x1, y1 = max(box[0], cx1) - cx1, max(box[1], cy1) - cy1
        x2, y2 = min(box[2], cx2) - cx1, min(box[3], cy2) - cy1
        labels.append((cls, (x1 + x2) / 2 / cw, (y1 + y2) / 2 / ch, (x2 - x1) / cw, (y2 - y1) / ch))
    return labels


def person_truth(person_index, persons, ppe_boxes, min_owned=0.5):
    """
    평가용 사람별 정답. 보호구 상자를 가장 많이 겹치는 사람 한 명에게만 준다
    같은 사람에게 씀·안 씀이 둘 다 붙거나 아무것도 없으면 unknown
    """
    found = {item: set() for item in ITEMS}
    for cls, box in ppe_boxes:
        if area(box) <= 0:
            continue
        overlaps = [intersection(p, box) / area(box) for p in persons]
        best = max(range(len(persons)), key=lambda i: overlaps[i])
        if best != person_index or overlaps[best] < min_owned:
            continue
        for item, (yes, no) in ITEMS.items():
            if cls == yes:
                found[item].add("wearing")
            elif cls == no:
                found[item].add("not_wearing")
    return {item: states.pop() if len(states) == 1 else "unknown" for item, states in found.items()}


def decide_state(detections, conf_min=0.4):
    """
    잘라 낸 사람 영역의 보호구 탐지 → 사람 한 명의 상태
    detections: [(클래스, conf, cx, cy, w, h)] 영역 기준 정규화 좌표
    - 옆 사람 것이 섞이지 않도록 좌우 가장자리 10%에 중심이 있는 상자는 버린다
    - 안전모는 영역 위쪽 절반에 중심이 있는 상자만 본다
    - 항목마다 conf가 가장 높은 상자로 정하고, conf_min 미만이거나 없으면 unknown (fail-safe는 서버가 정함)
    """
    state = {}
    for item, (yes, no) in ITEMS.items():
        best = None
        for cls, conf, cx, cy, _w, _h in detections:
            if cls not in (yes, no) or conf < conf_min or not 0.1 <= cx <= 0.9:
                continue
            if item == "helmet" and cy > 0.5:
                continue
            if best is None or conf > best[1]:
                best = (cls, conf)
        if best is None:
            state[item] = {"status": "unknown", "confidence": None}
        else:
            state[item] = {"status": "wearing" if best[0] == yes else "not_wearing", "confidence": round(best[1], 3)}
    return state
