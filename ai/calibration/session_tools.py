import re
from pathlib import Path

SESSION_RE = re.compile(r"^(diy|classroom)-\d{4}-s\d+-t\d+(-v\d+)?$")


def load_sessions(path: Path) -> list[str]:
    sessions = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")]
    invalid = [value for value in sessions if not SESSION_RE.fullmatch(value)]
    if invalid:
        raise ValueError(f"invalid session_id: {', '.join(invalid)}")
    if len(sessions) != len(set(sessions)):
        raise ValueError("session list contains duplicates")
    return sessions


def print_table(rows, headers):
    widths = [max(len(str(row[i])) for row in [headers, *rows]) for i in range(len(headers))]
    print(" | ".join(str(value).ljust(widths[i]) for i, value in enumerate(headers)))
    print("-+-".join("-" * width for width in widths))
    for row in rows:
        print(" | ".join(str(value).ljust(widths[i]) for i, value in enumerate(row)))
