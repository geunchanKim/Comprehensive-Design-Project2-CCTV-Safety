"""
녹화 여러 개를 차례로 재생해서 실시간 속도 재기: 녹화마다 realtime.py --send 를 한 번씩 실행한다

무엇을 하나
  - runs/real/classroom/s<장면>/t<회차>/ 녹화 폴더를 찾아 이름 순서대로 하나씩 재생한다
  - 녹화마다 session_id 를 <prefix>-s<장면>-t<회차>-<버전> 으로 붙인다 (예: classroom-1014-s10-t1-v6)
  - --sessions 목록 파일을 주면 목록에 있는 이름만 실행하고, 목록에 없는 녹화는 건너뛴다고 알려 준다
  - 사진은 다시 저장하지 않는다 (--no-save). 재생 기록(frames·meta)은 runs/replay/ 에 남긴다
  - 하나가 실패하면 이유를 보여 주고 멈춘다 (서버가 캘리브레이션 없음 등으로 거절하면 나머지도 실패하므로)
  - 끝나면 timing_summary.py 로 모든 세션을 한 표로 보여 준다 (--detail 포함)
  - 실행 정보(시작·종료 시각, session_id 목록, 장비, 넘긴 설정)를 runs/replay/run-<시각>.json 에 남긴다

명령 (ai/ 폴더에서, 가상환경 켠 뒤)
  python edge/replay_all.py --version v6 --dry-run                                  # 서버 없이 엣지만
  python edge/replay_all.py --version v6 --server http://<서버>:32130 \\
      --sessions calibration/sessions/classroom-1014-v6.txt
  python edge/replay_all.py --version v6 --dry-run --only s10-t1 s6-t1              # 일부만
"""
import argparse
import json
import platform
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent.parent
FOLDER_RE = re.compile(r"^s(\d+)$")
TAKE_RE = re.compile(r"^t(\d+)$")


def find_recordings(root: Path) -> list[tuple[str, Path]]:
    """[("s10-t1", 폴더), ...] 장면·회차 숫자 순서"""
    found = []
    for scene in root.iterdir():
        m = FOLDER_RE.match(scene.name)
        if not (m and scene.is_dir()):
            continue
        for take in scene.iterdir():
            t = TAKE_RE.match(take.name)
            if t and (take / "frames.jsonl").exists() and (take / "cam1").is_dir() and (take / "cam2").is_dir():
                found.append(((int(m.group(1)), int(t.group(1))), f"{scene.name}-{take.name}", take))
    return [(name, path) for _, name, path in sorted(found)]


def load_list(path: str | None) -> set | None:
    if not path:
        return None
    lines = Path(path).expanduser().read_text(encoding="utf-8").splitlines()
    return {s.strip() for s in lines if s.strip() and not s.strip().startswith("#")}


def main():
    parser = argparse.ArgumentParser(description="녹화 여러 개를 차례로 재생해 실시간 속도 재기")
    parser.add_argument("--root", default=str(AI_DIR / "runs" / "real" / "classroom"), help="녹화 폴더 위치")
    parser.add_argument("--prefix", default="classroom-1014", help="session_id 앞부분 (장소-날짜)")
    parser.add_argument("--version", required=True, help="session_id 끝 버전 (예: v6)")
    parser.add_argument("--only", nargs="*", default=None, help="일부만 (예: s10-t1 s6-t1)")
    parser.add_argument("--sessions", default=None, help="서버에 등록된 session_id 목록 파일")
    parser.add_argument("--server", default=None)
    parser.add_argument("--dry-run", action="store_true", help="서버 없이 파일로만 저장")
    parser.add_argument("--out", default=str(AI_DIR / "runs" / "replay"), help="재생 기록(frames·meta) 위치")
    args, extra = parser.parse_known_args()     # 나머지(--imgsz 등)는 realtime.py 에 그대로 넘긴다
    if not args.dry_run and not args.server:
        raise SystemExit("--server 주소를 주거나 --dry-run 으로 실행하세요")

    recordings = find_recordings(Path(args.root).expanduser())
    if args.only:
        recordings = [(n, p) for n, p in recordings if n in set(args.only)]
    allowed = load_list(args.sessions)
    plan = []
    for name, path in recordings:
        session = f"{args.prefix}-{name}-{args.version}"
        if allowed is not None and session not in allowed:
            print(f"건너뜀 (목록에 없음): {session}")
            continue
        plan.append((session, path))
    if not plan:
        raise SystemExit("재생할 녹화가 없어요")
    print(f"재생할 녹화 {len(plan)}개: " + ", ".join(s for s, _ in plan) + "\n")

    started = datetime.now()
    info = {"started": started.isoformat(timespec="seconds"), "finished": None,
            "server": "dry-run" if args.dry_run else args.server, "sessions_file": args.sessions,
            "planned": [s for s, _ in plan], "done": [], "realtime_args": extra,
            "machine": {"platform": platform.platform(), "machine": platform.machine(),
                        "processor": platform.processor(), "python": platform.python_version()}}
    Path(args.out).mkdir(parents=True, exist_ok=True)
    info_path = Path(args.out) / f"run-{started:%Y%m%d-%H%M%S}.json"

    def save_info():
        info["finished"] = datetime.now().isoformat(timespec="seconds")
        info_path.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")

    done = info["done"]
    for i, (session, path) in enumerate(plan, start=1):
        cmd = [sys.executable, str(AI_DIR / "edge" / "realtime.py"),
               "--cam1", str(path / "cam1"), "--cam2", str(path / "cam2"),
               "--no-save", "--out", args.out, "--name", session, "--send", "--session", session]
        cmd += ["--dry-run"] if args.dry_run else ["--server", args.server]
        if args.sessions:
            cmd += ["--sessions", args.sessions]
        cmd += extra
        print(f"===== [{i}/{len(plan)}] {session} =====", flush=True)
        if subprocess.run(cmd, cwd=AI_DIR).returncode != 0:
            save_info()
            raise SystemExit(f"\n{session} 에서 멈췄어요. 위 메시지를 확인하세요 (끝난 것: {len(done)}개)")
        done.append(session)
    save_info()
    print(f"실행 정보: {info_path}")

    print("\n===== 전체 요약 =====")
    subprocess.run([sys.executable, str(AI_DIR / "eval" / "timing_summary.py"), "--detail",
                    *[str(AI_DIR / "runs" / "edge" / s) for s in done]], cwd=AI_DIR)


if __name__ == "__main__":
    main()
