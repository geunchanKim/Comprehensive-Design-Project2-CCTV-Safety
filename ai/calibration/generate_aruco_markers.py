import cv2
import numpy as np
from PIL import Image

from config import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    ARUCO_DICTIONARY_ID,
    ARUCO_MARKER_DIR,
    ARUCO_MARKER_IDS,
    ARUCO_MARKER_LENGTH_M,
    DPI,
)



def mm_to_px(length_mm: float) -> int:
    return round(length_mm / 25.4 * DPI)


def main() -> None:
    ARUCO_MARKER_DIR.mkdir(parents=True, exist_ok=True)

    dictionary = cv2.aruco.getPredefinedDictionary(
        ARUCO_DICTIONARY_ID
    )

    marker_size_mm = ARUCO_MARKER_LENGTH_M * 1000
    marker_size_px = mm_to_px(marker_size_mm)

    page_width_px = mm_to_px(A4_WIDTH_MM)
    page_height_px = mm_to_px(A4_HEIGHT_MM)

    for marker_id in ARUCO_MARKER_IDS:
        marker_image = cv2.aruco.generateImageMarker(
            dictionary,
            marker_id,
            marker_size_px,
            borderBits=1,
        )

        page = np.full(
            (page_height_px, page_width_px),
            255,
            dtype=np.uint8,
        )

        start_x = (page_width_px - marker_size_px) // 2
        start_y = (page_height_px - marker_size_px) // 2

        page[
            start_y : start_y + marker_size_px,
            start_x : start_x + marker_size_px,
        ] = marker_image

        output_path = (
            ARUCO_MARKER_DIR
            / (
                f"aruco_dict4x4_50_"
                f"id_{marker_id:02d}_"
                f"{int(marker_size_mm)}mm_A4.png"
            )
        )

        Image.fromarray(page).save(
            output_path,
            dpi=(DPI, DPI),
        )

        print(f"생성: {output_path}")

    print()
    print("ArUco 마커 생성 완료")
    print("딕셔너리: DICT_4X4_50")
    print(f"마커 ID: {ARUCO_MARKER_IDS}")
    print(f"마커 크기: {marker_size_mm:.1f} mm")


if __name__ == "__main__":
    main()