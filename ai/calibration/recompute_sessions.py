import argparse
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from session_tools import load_sessions, print_table


def post(url, session_id, profile, algorithm):
    query = urlencode({"profile": profile, "algorithm": algorithm})
    request = Request(f"{url.rstrip('/')}/sessions/{session_id}/recompute?{query}", data=b"", method="POST")
    try:
        with urlopen(request, timeout=120) as response:
            return response.status, "ok"
    except HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")
    except URLError as exc:
        return 0, str(exc.reason)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--backend-url", required=True)
    parser.add_argument("--algorithm", choices=("baseline", "improved", "all"), default="all")
    args = parser.parse_args()
    conditions = [("precise", "baseline")]
    if args.algorithm in {"improved", "all"}:
        conditions.extend([("basic", "improved"), ("precise", "improved")])
    if args.algorithm == "improved":
        conditions = conditions[1:]
    rows, failed = [], False
    for session_id in load_sessions(args.sessions):
        cells = [session_id]
        for profile, algorithm in conditions:
            status, detail = post(args.backend_url, session_id, profile, algorithm)
            ok = status == 200
            failed |= not ok
            cells.append("OK" if ok else f"FAIL({status}: {detail[:40]})")
        rows.append(cells)
    print_table(rows, ["session", *[f"{p}/{a}" for p, a in conditions]])
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
