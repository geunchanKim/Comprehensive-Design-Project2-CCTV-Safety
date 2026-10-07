"""
실험 자동화: 저장해 둔 탐지 묶음(pack)을 서버에 다시 보내고, 1:1 평가 후 비교표를 만든다

왜 pack인가
  - YOLO 탐지는 느리고, 서버 알고리즘을 바꿔도 탐지 결과는 그대로다
  - 엣지가 서버로 보낼 메시지를 한 번 저장해 두고 서버에만 다시 보내면,
    YOLO 없이 몇 분 안에 "서버 버전별" 결과를 같은 입력으로 비교할 수 있다
  - 이미지가 없어도 돌아가므로 연구실 서버의 GitHub runner에서도 자동 실행할 수 있다

pack 구조: ai/eval/packs/<이름>/
  meta.json               어떤 데이터·엣지 설정("edge": 모델·입력 크기·발 위치·클래스)으로 만들었는지
  calibration.json        cam1, cam2 캘리브레이션 (session_id 없이)
  detections.jsonl.gz     /detections 로 보낼 묶음 (session_id 없이)
  ground_truth.jsonl.gz   /ground-truth 로 보낼 정답 (있을 때만, --send-gt 로 전송)
  frames.jsonl.gz         Unity 정답 원본 (평가용)

명령 (ai/ 폴더에서)
  pack 만들기 — 기존 엣지 실행 결과에서 (YOLO 다시 안 돌림)
    python eval/run_experiment.py pack runs/edge/unity-classroom-03-s4-run2 --name s4 \\
        --gt runs/unity/unity-classroom-04/unity-classroom-03-s4 --note "coco 1280, foot box"
  pack 만들기 — Unity 폴더에서 (unity_reader --dry-run 으로 탐지부터)
    python eval/run_experiment.py pack runs/unity/unity-classroom-03-s1 --name s1-ankle -- --foot ankle
  실험
    python eval/run_experiment.py run --server http://121.182.60.2:32130
    python eval/run_experiment.py run --server URL --packs s1,s4 --label after-pr42 --compare runs/experiments/before
    python eval/run_experiment.py run --server URL --out ~/cctv-experiments --compare latest   (배포 후 자동 실행용)

결과: runs/experiments/<label>/  (--out 으로 상위 폴더 변경)
  meta.json      서버 /health(커밋·설정), 사용한 pack, 실행 시각
  summary.csv    pack·클래스별 지표 한 줄씩
  summary.md     설계도 + 표 (GitHub 작업 요약에 그대로 붙음), --compare 를 주면 전→후 비교
  diagram.mmd    파이프라인 설계도 (Mermaid). 직전 실험과 달라진 단계는 노란색
  <pack>/        responses_detections.jsonl, position_errors.csv, failed.jsonl
"""

import argparse
import csv
import gzip
import json
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

AI_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AI_DIR / "eval"))
from eval_position import evaluate, summarize  # noqa: E402
import pipeline_diagram  # noqa: E402

PACK_DIR = AI_DIR / "eval" / "packs"
EXP_DIR = AI_DIR / "runs" / "experiments"
REPORT_CLASSES = ("person", "chair", "suitcase", "backpack")   # 표에 넣을 클래스 (책상·카트는 COCO로 못 잡음)
COLUMNS = ["pack", "cls", "ok", "chance", "results", "mean_cm", "median_cm", "p90_cm", "max_cm",
           "mismatch_rate", "miss_rate", "id_switches", "bias_x_cm", "bias_y_cm", "mean_z_cm"]


# ---------- 파일 도우미 ----------

def read_jsonl(path: Path) -> list[dict]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def write_jsonl(path: Path, rows: list[dict]):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------- pack 만들기 ----------

def run_unity_reader(unity_dir: Path, extra: list[str]) -> Path:
    """unity_reader 를 --dry-run 으로 돌려 탐지만 저장하고, 결과 폴더를 돌려준다"""
    cmd = [sys.executable, str(AI_DIR / "edge" / "unity_reader.py"), str(unity_dir), "--dry-run", *extra]
    print("실행:", " ".join(cmd))
    out = subprocess.run(cmd, cwd=AI_DIR, capture_output=True, text=True)
    print(out.stdout[-2000:])
    if out.returncode != 0:
        raise SystemExit(out.stderr[-2000:])
    m = re.findall(r"결과: (.+)", out.stdout)
    if not m:
        raise SystemExit("unity_reader 결과 폴더를 찾지 못했어요")
    return Path(m[-1].strip())


def make_pack(args, extra: list[str]):
    source = Path(args.source)
    if (source / "frames.jsonl").exists() and (source / "cam1").exists():   # Unity 폴더 → 탐지부터
        gt_dir = source
        run_dir = run_unity_reader(source, extra)
        note = args.note or f"unity_reader --dry-run {' '.join(extra)}".strip()
    else:                                                                     # 기존 엣지 결과 폴더
        if not args.gt:
            raise SystemExit("엣지 결과 폴더로 pack 을 만들 때는 --gt (Unity 정답 폴더)가 필요해요")
        gt_dir, run_dir, note = Path(args.gt), source, args.note
    for p in (run_dir / "sent_detections.jsonl", run_dir / "sent_calibration.jsonl", gt_dir / "frames.jsonl"):
        if not p.exists():
            raise SystemExit(f"파일이 없어요: {p}")

    pack = PACK_DIR / args.name
    if pack.exists() and not args.force:
        raise SystemExit(f"이미 있는 pack 이에요: {pack} (덮어쓰려면 --force)")
    pack.mkdir(parents=True, exist_ok=True)

    calib = {}
    for r in read_jsonl(run_dir / "sent_calibration.jsonl"):
        cam = r["path"].split("/")[2]                        # /cameras/cam1/calibration → cam1
        calib[cam] = {k: v for k, v in r.items() if k not in ("path", "session_id")}
    (pack / "calibration.json").write_text(json.dumps(calib, indent=2), encoding="utf-8")

    dets = [{k: v for k, v in r.items() if k != "session_id"} for r in read_jsonl(run_dir / "sent_detections.jsonl")]
    write_jsonl(pack / "detections.jsonl.gz", dets)
    if (run_dir / "sent_ground-truth.jsonl").exists():
        gts = [{k: v for k, v in r.items() if k != "session_id"} for r in read_jsonl(run_dir / "sent_ground-truth.jsonl")]
        write_jsonl(pack / "ground_truth.jsonl.gz", gts)
    write_jsonl(pack / "frames.jsonl.gz", read_jsonl(gt_dir / "frames.jsonl"))

    edge = {}
    if (run_dir / "edge_config.json").exists():            # unity_reader 가 남긴 탐지 설정
        edge = json.loads((run_dir / "edge_config.json").read_text(encoding="utf-8"))
    for item in filter(None, (args.edge or "").split(",")):  # --edge 로 직접 적은 값이 우선
        k, v = item.split("=", 1)
        edge[k.strip()] = int(v) if v.strip().isdigit() else v.strip()

    foot_src = {}
    for b in dets:
        for f in b["frames"]:
            for d in f["detections"]:
                foot_src[d.get("foot_src", "box")] = foot_src.get(d.get("foot_src", "box"), 0) + 1
    meta = {"name": args.name, "source": str(run_dir), "gt": str(gt_dir), "note": note, "edge": edge or None,
            "pairs": len(dets), "foot_src": foot_src, "created": datetime.now().isoformat(timespec="seconds")}
    (pack / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    size = sum(p.stat().st_size for p in pack.iterdir()) / 1e6
    print(f"pack 저장: {pack} ({len(dets)}묶음, {size:.1f}MB)")


# ---------- 실험 ----------

def replay(server: str, pack: Path, session_id: str, out: Path, send_gt: bool) -> dict:
    """pack 을 새 session_id 로 서버에 보낸다. 캘리브레이션 → (정답) → 탐지 순서"""
    out.mkdir(parents=True, exist_ok=True)
    http = requests.Session()
    failed = []
    stats = {"sent": 0, "failed": 0, "seconds": 0.0}

    for cam, body in json.loads((pack / "calibration.json").read_text(encoding="utf-8")).items():
        r = http.put(f"{server}/cameras/{cam}/calibration", json={**body, "session_id": session_id}, timeout=10)
        if not r.ok:
            raise SystemExit(f"[{pack.name}] {cam} 캘리브레이션 등록 실패 {r.status_code}: {r.text[:300]}")

    if send_gt and (pack / "ground_truth.jsonl.gz").exists():
        for g in read_jsonl(pack / "ground_truth.jsonl.gz"):
            r = http.post(f"{server}/ground-truth", json={**g, "session_id": session_id}, timeout=10)
            if not r.ok:
                failed.append({"path": "/ground-truth", "frame": g.get("frame"), "status": r.status_code, "body": r.text[:300]})

    t0 = time.perf_counter()
    with open(out / "responses_detections.jsonl", "w", encoding="utf-8") as f:
        for b in read_jsonl(pack / "detections.jsonl.gz"):
            try:
                r = http.post(f"{server}/detections", json={**b, "session_id": session_id}, timeout=30)
            except requests.RequestException as e:
                failed.append({"path": "/detections", "pair_id": b["pair_id"], "error": str(e)})
                stats["failed"] += 1
                continue
            if r.ok:
                f.write(json.dumps(r.json(), ensure_ascii=False) + "\n")
                stats["sent"] += 1
            else:
                failed.append({"path": "/detections", "pair_id": b["pair_id"], "status": r.status_code, "body": r.text[:300]})
                stats["failed"] += 1
    stats["seconds"] = round(time.perf_counter() - t0, 1)
    if failed:
        write_jsonl(out / "failed.jsonl", failed)
    return stats


def fmt(v, kind):
    if v is None:
        return "-"
    return f"{v * 100:.1f}%" if kind == "rate" else (f"{v:.1f}" if isinstance(v, float) else str(v))


def summary_markdown(rows: list[dict], meta: dict, before: dict | None) -> str:
    h = meta.get("health", {})
    lines = [f"### 실험 결과 `{meta['label']}`", "",
             f"- 서버 커밋 `{h.get('commit', '?')}` · 에피폴라 기준 {h.get('max_epipolar_error_px', '?')}px · 평가 1:1 배정, 맞음 기준 50cm",
             f"- pack: {', '.join(meta['packs'])}", ""]
    cols = [("맞음/기회", None), ("평균(cm)", "mean_cm"), ("90%(cm)", "p90_cm"),
            ("오매칭", "mismatch_rate"), ("놓침", "miss_rate"), ("ID 바뀜", "id_switches")]
    lines.append("| pack | 클래스 | " + " | ".join(c for c, _ in cols) + " |")
    lines.append("|---|---|" + "---|" * len(cols))
    for r in rows:
        b = (before or {}).get((r["pack"], r["cls"]))
        cells = []
        for name, key in cols:
            if key is None:
                now = f"{r['ok']}/{r['chance']}"
                old = f"{b['ok']}/{b['chance']}" if b else None
            else:
                kind = "rate" if key.endswith("rate") else "num"
                now = fmt(r[key], kind)
                old = fmt(b[key], kind) if b else None
            cells.append(f"{old} → **{now}**" if b and old != now else now)
        lines.append(f"| {r['pack']} | {r['cls']} | " + " | ".join(cells) + " |")
    if before is not None:
        lines += ["", f"전 → 후 비교 기준: `{meta.get('compare')}`"]
    return "\n".join(lines) + "\n"


def load_summary(exp: Path) -> dict:
    out = {}
    with open(exp / "summary.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            for k in COLUMNS[2:]:
                r[k] = None if r[k] in ("", "None") else (int(r[k]) if k in ("ok", "chance", "results", "id_switches") else float(r[k]))
            out[(r["pack"], r["cls"])] = r
    return out


def run_experiment(args):
    server = args.server.rstrip("/")
    try:
        health = requests.get(f"{server}/health", timeout=10).json()
    except (requests.RequestException, ValueError) as e:
        raise SystemExit(f"서버 {server}/health 응답 없음: {e}")

    names = args.packs.split(",") if args.packs else sorted(p.name for p in PACK_DIR.iterdir() if (p / "meta.json").exists())
    packs = [PACK_DIR / n for n in names]
    for p in packs:
        if not (p / "meta.json").exists():
            raise SystemExit(f"pack 이 없어요: {p}")

    label = args.label or datetime.now().strftime("%Y%m%d-%H%M%S")
    exp_root = Path(args.out).expanduser() if args.out else EXP_DIR
    compare = None
    if args.compare == "latest":                       # 같은 폴더의 가장 최근 실험과 비교
        done = sorted((d for d in exp_root.glob("*") if (d / "summary.csv").exists()),
                      key=lambda d: (d / "summary.csv").stat().st_mtime)
        compare = done[-1] if done else None
        print(f"비교 기준: {compare or '없음 (첫 실험)'}")
    elif args.compare:
        compare = Path(args.compare).expanduser()
    exp = exp_root / label
    if exp.exists():
        raise SystemExit(f"이미 있는 실험 이름이에요: {exp}")
    stamp = datetime.now().strftime("%m%d%H%M%S")
    print(f"서버 {server} | 커밋 {health.get('commit')} | pack {', '.join(names)} | 결과 {exp}")

    rows, packs_meta = [], {}
    for p in packs:
        session_id = f"exp-{p.name}-{stamp}"
        out = exp / p.name
        stats = replay(server, p, session_id, out, args.send_gt)
        gt_dir = out / "gt"
        gt_dir.mkdir(exist_ok=True)
        write_jsonl(gt_dir / "frames.jsonl", read_jsonl(p / "frames.jsonl.gz"))
        pos_rows, visible = evaluate(out, gt_dir, args.thr)
        shutil.rmtree(gt_dir)
        with open(out / "position_errors.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=sorted({k for r in pos_rows for k in r}))
            w.writeheader()
            w.writerows(pos_rows)
        for cls, s in summarize(pos_rows, visible).items():
            if cls in REPORT_CLASSES:
                rows.append({"pack": p.name, "cls": cls, **s})
        packs_meta[p.name] = {"session_id": session_id, **stats,
                              **json.loads((p / "meta.json").read_text(encoding="utf-8"))}
        print(f"  {p.name}: 전송 {stats['sent']} · 실패 {stats['failed']} · {stats['seconds']}초")

    exp.mkdir(parents=True, exist_ok=True)
    with open(exp / "summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows([{k: r.get(k) for k in COLUMNS} for r in rows])
    meta = {"label": label, "server": server, "health": health, "packs": names, "thr_cm": args.thr,
            "compare": str(compare) if compare else None, "created": datetime.now().isoformat(timespec="seconds"), "pack_runs": packs_meta}
    (exp / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    before = load_summary(compare) if compare else None
    before_view = None
    if compare and (compare / "meta.json").exists():
        before_meta = json.loads((compare / "meta.json").read_text(encoding="utf-8"))
        before_view = pipeline_diagram.describe(before_meta, list(before.values()))
    now_view = pipeline_diagram.describe(meta, rows)
    (exp / "diagram.mmd").write_text(pipeline_diagram.mermaid(now_view, before_view), encoding="utf-8")
    md = (pipeline_diagram.markdown(now_view, before_view, health.get("commit", "?"), compare.name if compare else None)
          + summary_markdown(rows, meta, before))
    (exp / "summary.md").write_text(md, encoding="utf-8")
    print("\n" + md)
    print(f"결과: {exp}")
    if any(m["failed"] for m in packs_meta.values()):
        raise SystemExit("전송 실패가 있어요. 각 pack 폴더의 failed.jsonl 을 확인하세요")


def main():
    parser = argparse.ArgumentParser(description="탐지 pack 을 서버에 다시 보내고 1:1 평가")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("pack", help="탐지 pack 만들기")
    p.add_argument("source", help="엣지 결과 폴더(runs/edge/...) 또는 Unity 폴더(runs/unity/...)")
    p.add_argument("--name", required=True, help="pack 이름. 예: s4")
    p.add_argument("--gt", default=None, help="Unity 정답 폴더 (엣지 결과 폴더로 만들 때 필요)")
    p.add_argument("--note", default="", help="엣지 설정 메모. 예: coco 1280, foot box")
    p.add_argument("--force", action="store_true", help="같은 이름 pack 덮어쓰기")
    p.add_argument("--edge", default=None, help="엣지 설정 직접 지정. 예: model=coco,imgsz=1280,foot=box")

    r = sub.add_parser("run", help="pack 들을 서버에 보내고 평가")
    r.add_argument("--server", required=True, help="예: http://121.182.60.2:32130")
    r.add_argument("--packs", default=None, help="쉼표로 구분. 기본: ai/eval/packs 전체")
    r.add_argument("--label", default=None, help="결과 폴더 이름. 기본: 실행 시각")
    r.add_argument("--compare", default=None, help="비교할 이전 실험 폴더, 또는 latest (가장 최근 실험)")
    r.add_argument("--out", default=None, help="결과를 모을 상위 폴더. 기본: ai/runs/experiments")
    r.add_argument("--thr", type=float, default=50.0, help="맞음 기준 바닥 오차 cm")
    r.add_argument("--send-gt", action="store_true", help="정답도 서버에 보내기 (서버 DB에 남길 때)")

    args, extra = parser.parse_known_args()
    if args.cmd == "pack":
        make_pack(args, [x for x in extra if x != "--"])
    else:
        if extra:
            parser.error(f"알 수 없는 옵션: {extra}")
        run_experiment(args)


if __name__ == "__main__":
    main()
