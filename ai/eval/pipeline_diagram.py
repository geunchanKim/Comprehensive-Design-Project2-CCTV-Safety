"""
실험 한 번의 파이프라인 설계도(Mermaid)를 만든다

  데이터 → 엣지 → 짝 찾기 → 위치 계산 → 결과
  - 칸 안에는 그 실험 때의 설정값을 적는다
      엣지: pack 의 meta.json "edge" (unity_reader 가 남긴 edge_config.json)
      서버: 실험 시작 때 받은 /health 응답 (서버에 설정이 추가되면 그대로 칸에 나타난다)
      결과: summary 지표 (발 위치 종류별 사람 평균, 의자 평균)
  - 직전 실험과 값이 달라진 칸은 노란색으로 칠하고 "전 → 후"를 적는다

run_experiment.py 가 summary.md 맨 위에 붙이고 diagram.mmd 로도 저장한다.
"""

POSITION_NAMES = {"triangulate": "삼각측량", "plane": "바닥 평면 교점"}
FOOT_NAMES = {"ankle": "발목", "box": "박스 아래"}
HEALTH_USED = {"status", "commit", "max_epipolar_error_px", "box_foot_z_min", "box_foot_z_max",
               "ankle_foot_z_min", "ankle_foot_z_max", "bbox_position_method"}


def _join(values) -> str:
    vals = []
    for v in values:
        v = ", ".join(map(str, v)) if isinstance(v, (list, tuple)) else str(v)
        if v not in vals:
            vals.append(v)
    return " / ".join(vals) if vals else "?"


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def describe(meta: dict, rows: list[dict]) -> dict:
    """실험 하나를 {칸: [(항목, 값), ...]} 으로 정리한다"""
    packs = meta.get("pack_runs", {})
    edges = {name: (p.get("edge") or {}) for name, p in packs.items()}
    h = meta.get("health", {})

    data = [("pack", ", ".join(sorted({n.replace("-ankle", "") for n in meta.get("packs", packs)}))),
            ("개수", f"{len(meta.get('packs', packs))}개")]

    edge = [("모델", _join(e.get("model", "?") for e in edges.values())),
            ("입력 크기", _join(e.get("imgsz", "?") for e in edges.values())),
            ("발 위치", _join(FOOT_NAMES.get(e.get("foot"), e.get("foot", "?")) for e in edges.values())),
            ("클래스", _join(e.get("classes", "?") for e in edges.values()))]

    match = [("에피폴라 기준", f"{h['max_epipolar_error_px']:g}px" if "max_epipolar_error_px" in h else "?")]
    if "box_foot_z_min" in h:
        match.append(("박스 높이 범위", f"{h['box_foot_z_min']:g}~{h['box_foot_z_max']:g}m"))
    if "ankle_foot_z_min" in h:
        match.append(("발목 높이 범위", f"{h['ankle_foot_z_min']:g}~{h['ankle_foot_z_max']:g}m"))
    for k in sorted(set(h) - HEALTH_USED):             # 서버에 새로 생긴 설정은 그대로 보여 준다
        match.append((k, str(h[k])))

    position = [("발목 쌍", "삼각측량")]
    if "bbox_position_method" in h:
        position.append(("박스 쌍", POSITION_NAMES.get(h["bbox_position_method"], h["bbox_position_method"])))
    else:
        position.append(("박스 쌍", "삼각측량"))

    result = []
    for foot in ("ankle", "box"):
        rs = [r for r in rows if r["cls"] == "person" and edges.get(r["pack"], {}).get("foot") == foot]
        if not rs:
            continue
        name = FOOT_NAMES[foot]
        mean = _mean(r["mean_cm"] for r in rs)
        mism = _mean(r["mismatch_rate"] for r in rs)
        ok, chance = sum(r["ok"] for r in rs), sum(r["chance"] for r in rs)
        result += [(f"사람 평균 ({name})", f"{mean:.1f}cm" if mean is not None else "-"),
                   (f"오매칭 ({name})", f"{mism * 100:.1f}%" if mism is not None else "-"),
                   (f"맞음 ({name})", f"{ok / chance * 100:.0f}%" if chance else "-")]
    chair = _mean(r["mean_cm"] for r in rows if r["cls"] == "chair")
    if chair is not None:
        result.append(("의자 평균", f"{chair:.1f}cm"))

    return {"data": ("데이터", data), "edge": ("엣지 탐지", edge), "match": ("서버 짝 찾기", match),
            "position": ("위치 계산", position), "result": ("결과 (pack 평균)", result)}


def _label(title: str, items: list, before: dict | None) -> tuple[str, bool]:
    old = dict(before[1]) if before else {}
    lines, changed = [f"<b>{title}</b>"], False
    for k, v in items:
        if k in old and old[k] != v:
            lines.append(f"{k}: {old[k]} → <b>{v}</b>")
            changed = True
        elif before and k not in old:                  # 직전 실험에 없던 설정이 새로 생김
            lines.append(f"<b>{k}: {v}</b> (새로)")
            changed = True
        else:
            lines.append(f"{k}: {v}")
    return "<br/>".join(lines).replace('"', "'"), changed


def mermaid(now: dict, before: dict | None = None) -> str:
    out = ["flowchart LR"]
    changed = []
    for key, (title, items) in now.items():
        text, ch = _label(title, items, (before or {}).get(key))
        out.append(f'  {key}["{text}"]')
        if ch:
            changed.append(key)
    out.append("  data --> edge --> match --> position --> result")
    out.append("  classDef changed fill:#fde68a,stroke:#b45309,color:#111")
    if changed:
        out.append(f"  class {','.join(changed)} changed")
    return "\n".join(out) + "\n"


def markdown(now: dict, before: dict | None, commit: str, before_label: str | None) -> str:
    head = f"### 파이프라인 설계도 (서버 `{commit}`)\n\n"
    if before_label:
        head += f"노란 칸 = 직전 실험(`{before_label}`)과 달라진 단계, 굵은 글씨 = 바뀐 값\n\n"
    return head + "```mermaid\n" + mermaid(now, before) + "```\n\n"
