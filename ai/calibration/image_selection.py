from pathlib import Path

import cv2


def image_paths(images_dir: Path, best: int | None = None) -> list[Path]:
    paths = sorted(images_dir.glob("*.png")) + sorted(images_dir.glob("*.jpg"))
    if not paths:
        raise ValueError(f"no calibration images found: {images_dir}")
    if best is None:
        return paths
    if best < 1:
        raise ValueError("--best must be at least 1")
    scored = []
    for path in paths:
        gray = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if gray is not None:
            scored.append((float(cv2.Laplacian(gray, cv2.CV_64F).var()), path))
    return [path for _, path in sorted(scored, reverse=True)[:best]]
