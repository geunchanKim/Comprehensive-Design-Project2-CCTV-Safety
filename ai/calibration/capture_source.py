"""Shared calibration-camera adapter backed by edge.camera_source.CameraSource."""
import sys
from pathlib import Path

EDGE_DIR = Path(__file__).resolve().parents[1] / "edge"
if str(EDGE_DIR) not in sys.path:
    sys.path.insert(0, str(EDGE_DIR))

from camera_source import CameraSource  # noqa: E402
from config import CAMERA_HEIGHT, CAMERA_INDEX, CAMERA_WIDTH  # noqa: E402


def add_camera_args(parser):
    parser.add_argument("--camera-ip", help="Tapo 등 RTSP 카메라 IP 주소")
    parser.add_argument("--max-reconnects", type=int, default=5)


def open_camera(args, camera_id: str) -> CameraSource:
    source = f"tapo:{args.camera_ip}" if args.camera_ip else str(CAMERA_INDEX)
    return CameraSource(source, name=camera_id, queue_size=1,
                        reconnect_limit=args.max_reconnects,
                        requested_size=(CAMERA_WIDTH, CAMERA_HEIGHT)).start()


def next_image(camera: CameraSource):
    while camera.alive:
        frame = camera.get(timeout=1.0)
        if frame is not None:
            return frame.image
    raise RuntimeError(f"카메라 프레임 수신 실패: {camera.error or '연결 종료'}")
