"""
v2 데이터셋에 COCO val2017 원본 이미지 일부(person, chair 포함)를 추가하는 스크립트

자동 라벨링(pseudo_label_coco.py)만으로는 chair/person 박스가 부족해서,
사람이 직접 검수한 COCO 라벨이 붙은 사진을 섞어 v2 모델이 COCO 수준의
person/chair 인식력을 유지하도록 한다.

- 라벨 zip(약 46MB)만 받고, 필요한 이미지만 골라서 개별 다운로드 (전체 780MB 받지 않음)
- 다운로드한 원본은 datasets/raw/coco/ 에 캐시 (다시 돌려도 재다운로드 안 함)
- person(COCO 0) -> 2, chair(COCO 56) -> 3 만 남기고 나머지 COCO 클래스는 버림

실행 순서 (ai/ 폴더에서)
  python scripts/pseudo_label_coco.py      # merged_v2 새로 생성 (기존 merged_v2 삭제됨)
  python scripts/add_coco_subset.py        # 그 위에 COCO 사진 추가
"""

import argparse
import random
import shutil
import urllib.request
import zipfile
from collections import Counter
from pathlib import Path

AI_DIR = Path(__file__).resolve().parent.parent          # ai/
DST_DIR = AI_DIR / "datasets" / "merged_v2"
CACHE_DIR = AI_DIR / "datasets" / "raw" / "coco"
LABELS_ZIP = CACHE_DIR / "coco2017labels.zip"
IMG_CACHE = CACHE_DIR / "val2017"

LABELS_URL = "https://github.com/ultralytics/assets/releases/download/v0.0.0/coco2017labels.zip"
IMG_URL = "http://images.cocodataset.org/val2017/{stem}.jpg"
ZIP_PREFIX = "coco/labels/val2017/"

NAMES = ["cart", "desk", "person", "chair"]
COCO_TO_NEW = {0: 2, 56: 3}   # person, chair
PREFIX = "coco_"              # merged_v2 안에서 COCO 사진 구분용 파일명 접두어


def download(url: str, out: Path):
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".part")
    urllib.request.urlretrieve(url, tmp)
    tmp.rename(out)


def load_coco_labels() -> dict[str, list[str]]:
    """val2017 라벨을 {파일stem: [라벨 줄...]} 로 읽기 (zip 안에서 바로)"""
    if not LABELS_ZIP.exists():
        print(f"COCO 라벨 다운로드 중 (약 46MB)... {LABELS_URL}")
        download(LABELS_URL, LABELS_ZIP)

    labels = {}
    with zipfile.ZipFile(LABELS_ZIP) as z:
        for name in z.namelist():
            if name.startswith(ZIP_PREFIX) and name.endswith(".txt"):
                text = z.read(name).decode("utf-8")
                labels[Path(name).stem] = [l.strip() for l in text.splitlines() if l.strip()]
    return labels


def convert(lines: list[str]) -> list[str]:
    """COCO 라벨 중 person/chair만 남기고 새 클래스 id로 변환"""
    out = []
    for line in lines:
        parts = line.split()
        coco_id = int(parts[0])
        if coco_id in COCO_TO_NEW and len(parts) == 5:
            out.append(" ".join([str(COCO_TO_NEW[coco_id])] + parts[1:]))
    return out


def select(labels: dict, n_chair: int, n_person: int, seed: int) -> list[str]:
    """의자가 있는 사진 n_chair장 + 사람만 있는(의자 없는) 사진 n_person장 고르기"""
    chair_imgs, person_only = [], []
    for stem, lines in labels.items():
        ids = {int(l.split()[0]) for l in lines}
        if 56 in ids:
            chair_imgs.append(stem)
        elif 0 in ids:
            person_only.append(stem)

    rng = random.Random(seed)
    chair_imgs.sort()
    person_only.sort()
    picked = rng.sample(chair_imgs, min(n_chair, len(chair_imgs)))
    picked += rng.sample(person_only, min(n_person, len(person_only)))
    print(f"후보: 의자 사진 {len(chair_imgs)}장, 사람만 있는 사진 {len(person_only)}장")
    print(f"선택: 의자 사진 {min(n_chair, len(chair_imgs))}장 + 사람 사진 {min(n_person, len(person_only))}장")
    rng.shuffle(picked)
    return picked


def count_all() -> dict:
    counter = Counter()
    for split_dir in sorted((DST_DIR / "labels").iterdir()):
        for f in split_dir.glob("*.txt"):
            for line in f.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    counter[(split_dir.name, NAMES[int(line.split()[0])])] += 1
    return counter


def main(n_chair: int, n_person: int, valid_ratio: float, seed: int):
    if not (DST_DIR / "images" / "train").exists():
        raise SystemExit("merged_v2가 없어요. 먼저 python scripts/pseudo_label_coco.py 실행")

    # 이전에 넣은 COCO 사진이 있으면 지우고 다시 넣음 (중복 방지)
    for p in DST_DIR.glob(f"*/*/{PREFIX}*"):
        p.unlink()

    labels = load_coco_labels()
    picked = select(labels, n_chair, n_person, seed)
    n_valid = int(len(picked) * valid_ratio)
    split_of = {stem: ("valid" if i < n_valid else "train") for i, stem in enumerate(picked)}

    failed = []
    for i, stem in enumerate(picked, 1):
        cached = IMG_CACHE / f"{stem}.jpg"
        if not cached.exists():
            try:
                download(IMG_URL.format(stem=stem), cached)
            except Exception as e:  # 네트워크 오류 등은 건너뛰고 끝에 보고
                failed.append((stem, str(e)))
                continue

        split = split_of[stem]
        img_dir = DST_DIR / "images" / split
        lbl_dir = DST_DIR / "labels" / split
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)

        shutil.copy2(cached, img_dir / f"{PREFIX}{stem}.jpg")
        (lbl_dir / f"{PREFIX}{stem}.txt").write_text("\n".join(convert(labels[stem])) + "\n", encoding="utf-8")

        if i % 50 == 0 or i == len(picked):
            print(f"  {i}/{len(picked)}")

    if failed:
        print(f"\n다운로드 실패 {len(failed)}장 (다시 실행하면 이어서 받음): 예) {failed[0]}")

    counter = count_all()
    splits = sorted({s for s, _ in counter})
    print("\n클래스별 박스 개수 (COCO 추가 후)")
    print(f"{'split':<7}" + "".join(f"{n:>8}" for n in NAMES))
    for split in splits:
        print(f"{split:<7}" + "".join(f"{counter[(split, n)]:>8}" for n in NAMES))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    # 의자 사진에 사람도 많이 찍혀 있어서 기본값은 의자 사진 200장만 (cart/desk 대비 클래스 균형 고려)
    parser.add_argument("--chair", type=int, default=200, help="의자가 포함된 COCO 사진 수")
    parser.add_argument("--person", type=int, default=0, help="사람만 있는(의자 없는) COCO 사진 수")
    parser.add_argument("--valid_ratio", type=float, default=0.2)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    main(args.chair, args.person, args.valid_ratio, args.seed)