from pathlib import Path

import cv2


BASE_DIR = Path(__file__).resolve().parent

BOARDS_DIR = BASE_DIR / "boards"
CHARUCO_BOARD_DIR = BOARDS_DIR / "charuco"
ARUCO_MARKER_DIR = BOARDS_DIR / "aruco"

CAPTURES_DIR = BASE_DIR / "captures"
OUTPUT_DIR = BASE_DIR / "output"


# ─────────────────────────────────────────────
# ChArUco: 카메라 내부 캘리브레이션용
# ─────────────────────────────────────────────

CHARUCO_DICTIONARY_ID = cv2.aruco.DICT_5X5_100

CHARUCO_SQUARES_X = 5
CHARUCO_SQUARES_Y = 7

# 최초 생성 규격
CHARUCO_SQUARE_LENGTH_M = 0.035
CHARUCO_MARKER_LENGTH_M = 0.025


# ─────────────────────────────────────────────
# 개별 ArUco: 바닥·벽 공간 기준점용
# ─────────────────────────────────────────────

ARUCO_DICTIONARY_ID = cv2.aruco.DICT_4X4_50

# 생성할 마커 ID
ARUCO_MARKER_IDS = list(range(8))

# 실제 출력 규격: 180 × 180mm (검은 마커 영역 기준)
ARUCO_MARKER_LENGTH_M = 0.180


# ─────────────────────────────────────────────
# 출력 및 카메라 설정
# ─────────────────────────────────────────────

DPI = 300

A4_WIDTH_MM = 210
A4_HEIGHT_MM = 297

CAMERA_INDEX = 0
CAMERA_WIDTH = 1920
CAMERA_HEIGHT = 1080
