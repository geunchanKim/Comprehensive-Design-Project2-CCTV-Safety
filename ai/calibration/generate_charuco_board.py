import cv2
import numpy as np
from PIL import Image

from config import (
    A4_HEIGHT_MM,
    A4_WIDTH_MM,
    CHARUCO_BOARD_DIR,
    CHARUCO_DICTIONARY_ID,
    CHARUCO_MARKER_LENGTH_M,
    CHARUCO_SQUARE_LENGTH_M,
    CHARUCO_SQUARES_X,
    CHARUCO_SQUARES_Y,
    DPI,
)


def mm_to_px(length_mm: float) -> int:
    return round(length_mm / 25.4 * DPI)


def main() -> None:
    CHARUCO_BOARD_DIR.mkdir(parents=True, exist_ok=True)

    dictionary = cv2.aruco.getPredefinedDictionary(
        CHARUCO_DICTIONARY_ID
    )

    board = cv2.aruco.CharucoBoard(
        (CHARUCO_SQUARES_X, CHARUCO_SQUARES_Y),
        CHARUCO_SQUARE_LENGTH_M,
        CHARUCO_MARKER_LENGTH_M,
        dictionary,
    )

    board_width_mm = (
        CHARUCO_SQUARES_X
        * CHARUCO_SQUARE_LENGTH_M
        * 1000
    )
    board_height_mm = (
        CHARUCO_SQUARES_Y
        * CHARUCO_SQUARE_LENGTH_M
        * 1000
    )

    board_width_px = mm_to_px(board_width_mm)
    board_height_px = mm_to_px(board_height_mm)

    board_image = board.generateImage(
        (board_width_px, board_height_px),
        marginSize=0,
        borderBits=1,
    )

    page_width_px = mm_to_px(A4_WIDTH_MM)
    page_height_px = mm_to_px(A4_HEIGHT_MM)

    page = np.full(
        (page_height_px, page_width_px),
        255,
        dtype=np.uint8,
    )

    start_x = (page_width_px - board_width_px) // 2
    start_y = (page_height_px - board_height_px) // 2

    if start_x < 0 or start_y < 0:
        raise ValueError("ChArUco 보드가 A4보다 큽니다.")

    page[
        start_y : start_y + board_height_px,
        start_x : start_x + board_width_px,
    ] = board_image

    output_path = (
        CHARUCO_BOARD_DIR
        / "charuco_5x7_dict5x5_100_A4.png"
    )

    Image.fromarray(page).save(
        output_path,
        dpi=(DPI, DPI),
    )

    print("ChArUco 보드 생성 완료")
    print(f"파일: {output_path}")
    print(
        f"보드 크기: "
        f"{board_width_mm:.1f} × {board_height_mm:.1f} mm"
    )
    print(
        f"한 칸: "
        f"{CHARUCO_SQUARE_LENGTH_M * 1000:.1f} mm"
    )
    print(
        f"내부 마커: "
        f"{CHARUCO_MARKER_LENGTH_M * 1000:.1f} mm"
    )
    print("딕셔너리: DICT_5X5_100")


if __name__ == "__main__":
    main()