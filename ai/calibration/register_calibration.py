import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from session_tools import SESSION_RE, load_sessions, print_table


def put(url, camera_id, payload):
    request = Request(f"{url.rstrip('/')}/cameras/{camera_id}/calibration",
                      data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}, method="PUT")
    try:
        with urlopen(request, timeout=15) as response:
            return response.status, "ok"
    except HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")
    except URLError as exc:
        return 0, str(exc.reason)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--calib", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--sessions", type=Path)
    group.add_argument("--session")
    parser.add_argument("--backend-url", required=True)
    args = parser.parse_args()
    sessions = load_sessions(args.sessions) if args.sessions else [args.session]
    if any(not SESSION_RE.fullmatch(value) for value in sessions):
        raise ValueError(f"invalid session_id: {args.session}")
    calibration = json.loads(args.calib.read_text(encoding="utf-8"))
    rows, failed = [], False
    for session_id in sessions:
        cells = [session_id]
        for camera_id in ("cam1", "cam2"):
            for profile in ("basic", "precise"):
                status, detail = put(args.backend_url, camera_id,
                                     {**calibration[camera_id][profile], "session_id": session_id})
                ok = status == 200
                failed |= not ok
                cells.append("OK" if ok else f"FAIL({status}: {detail[:40]})")
        rows.append(cells)
    print_table(rows, ["session", "cam1/basic", "cam1/precise", "cam2/basic", "cam2/precise"])
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
