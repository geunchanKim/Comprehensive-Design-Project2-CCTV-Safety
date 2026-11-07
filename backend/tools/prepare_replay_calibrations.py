"""Prepare camera/profile registration payloads for explicitly named replay sessions."""
import argparse
import json
from pathlib import Path
from urllib.parse import quote

from ai.calibration.session_tools import SESSION_RE, load_sessions
from backend.schemas import CameraCalibrationIn


def prepare(calibration, sessions):
    if not sessions or len(sessions) != len(set(sessions)):
        raise ValueError("provide distinct session names")
    plan = []
    for session in sessions:
        if not SESSION_RE.fullmatch(session):
            raise ValueError(f"invalid replay session name: {session}")
        if set(calibration) != {"cam1", "cam2"}:
            raise ValueError("calibration must contain cam1 and cam2")
        for camera_id, profiles in calibration.items():
            if set(profiles) != {"basic", "precise"}:
                raise ValueError("each camera must contain basic and precise profiles")
            for profile, data in profiles.items():
                if data.get("calibration_profile", profile) != profile:
                    raise ValueError("calibration profile key and payload disagree")
                body = CameraCalibrationIn.model_validate({
                    **data, "session_id": session, "calibration_profile": profile,
                })
                plan.append({"path": f"/cameras/{quote(camera_id, safe='')}/calibration",
                             "body": body.model_dump(mode="json")})
    return plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--session", action="append")
    group.add_argument("--sessions", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    try:
        sessions = load_sessions(args.sessions) if args.sessions else args.session
        plan = prepare(json.loads(args.calibration.read_text(encoding="utf-8")), sessions)
        # Exclusive create: never overwrite another run's prepared plan.
        with args.out.open("x", encoding="utf-8") as target:
            json.dump(plan, target, ensure_ascii=False, indent=2)
        print(f"Prepared {len(plan)} registrations: {args.out}")
        print("Offline only: use ai/calibration/register_calibration.py for registration")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
