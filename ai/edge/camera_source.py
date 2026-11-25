"""
카메라 연결: 웹캠, 영상 파일, RTSP(Tapo)를 같은 방식으로 열고 프레임마다 시각을 붙인다.

소스 쓰는 법 (--source 또는 CameraSource(source))
  0, 1                 노트북 웹캠 번호
  video.mp4            영상 파일 (실제 카메라처럼 원래 속도로 흘려보냄)
  runs/real/.../cam1   realtime.py 로 녹화한 사진 폴더. 녹화 때 기록한 시각(상위 폴더 frames.jsonl)대로
                       실제 카메라처럼 흘려보냄. cam1·cam2 폴더를 같이 주면 두 카메라 시각 차이도 그대로
  tapo:192.168.0.10    Tapo 카메라. 계정 아이디·비밀번호는 실행할 때 입력 (코드·파일에 남기지 않음)
  rtsp://...           RTSP 주소를 그대로 (테스트용 가짜 카메라 등)

프레임마다 붙는 시각 (Frame)
  seq      이 카메라에서 받은 순서 (0부터)
  pts_ms   카메라(영상)가 붙인 시각. 영상 안의 시간이라 카메라마다 기준점이 다름
  recv_ms  노트북이 프레임을 받은 시각 (epoch ms). 두 카메라 짝 맞추기의 기준
  두 값을 따로 저장해 두면, 나중에 깜빡임 동기화로 카메라별 지연·시계 차이를 잴 수 있다.

동작
  - 카메라마다 읽기 스레드 하나가 쉬지 않고 프레임을 받아 큐에 넣는다.
    (RTSP는 안 읽고 두면 카메라 쪽 버퍼가 쌓여 영상이 점점 늦어진다)
  - 큐가 가득 차면 가장 오래된 프레임을 버리고 dropped 로 센다.
  - 웹캠·RTSP가 끊기면 최대 reconnect_limit 번 다시 연결한다. 파일·녹화 폴더는 끝나면 멈춘다.

단독 실행 (ai/ 폴더에서): 연결 확인과 fps·시각 점검
  python edge/camera_source.py --source 0 --seconds 10 --show
  python edge/camera_source.py --source 0 --source ~/Downloads/CCTVTEST.mp4 --seconds 10
  python edge/camera_source.py --source tapo:192.168.0.10 --seconds 10
"""

import argparse
import json
import getpass
import os
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

import cv2

# RTSP를 TCP로 받는다 (UDP는 와이파이에서 패킷이 빠져 화면이 깨짐). cv2.VideoCapture 전에 설정해야 함
os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")

TAPO_PORT = 554
TAPO_STREAM = "stream1"      # 고화질. 앱 화질 설정이 "최고 화질"이어야 1080p

_credentials = None          # 실행 중 한 번만 입력받아 모든 Tapo 카메라에 씀 (파일에 저장하지 않음)


@dataclass
class Frame:
    camera: str
    seq: int
    pts_ms: float
    recv_ms: int
    image: object            # numpy 배열 (BGR)


def ask_credentials():
    global _credentials
    if _credentials is None:
        user = input("Tapo 카메라 계정 아이디: ").strip()
        password = getpass.getpass("Tapo 카메라 계정 비밀번호: ")
        _credentials = (user, password)
    return _credentials


def resolve(source: str):
    """소스 문자열 → (cv2에 넘길 값, 화면에 보일 이름, 종류). 화면 이름에는 비밀번호를 넣지 않는다"""
    source = str(source)
    if source.isdigit():
        return int(source), f"webcam{source}", "webcam"
    if source.startswith("tapo:"):
        ip = source[len("tapo:"):]
        user, password = ask_credentials()
        url = f"rtsp://{quote(user, safe='')}:{quote(password, safe='')}@{ip}:{TAPO_PORT}/{TAPO_STREAM}"
        return url, f"rtsp://{ip}:{TAPO_PORT}/{TAPO_STREAM}", "rtsp"
    if source.startswith("rtsp://"):
        shown = source.split("@")[-1] if "@" in source else source[len("rtsp://"):]
        return source, f"rtsp://{shown}", "rtsp"
    path = Path(source).expanduser()
    if not path.exists():
        raise SystemExit(f"영상 파일이 없어요: {path}")
    if path.is_dir():
        if not (path.parent / "frames.jsonl").exists():
            raise SystemExit(f"녹화 폴더 위에 frames.jsonl 이 없어요: {path.parent}")
        return str(path), f"{path.parent.name}/{path.name}", "folder"
    return str(path), path.name, "file"


_REPLAY_STARTS: dict[str, float] = {}
_REPLAY_LOCK = threading.Lock()


def _replay_start(recording: Path, lead_s: float = 0.3) -> float:
    """같은 녹화 폴더를 처음 시작한 카메라가 정한 출발 시각(epoch 초)을 나머지 카메라도 쓴다"""
    with _REPLAY_LOCK:
        key = str(recording.resolve())
        if key not in _REPLAY_STARTS:
            _REPLAY_STARTS[key] = time.time() + lead_s
        return _REPLAY_STARTS[key]


def load_recording(folder: Path) -> tuple[list[tuple[Path, int, float, int]], int]:
    """녹화 폴더(cam1 등) → ([(사진, 카메라 seq, pts_ms, 받은 시각)], 기준 시각).
    기준 시각은 첫 짝에서 두 카메라 중 먼저 받은 시각이라, cam1·cam2 를 따로 열어도 같은 시간축으로 재생된다"""
    rows = [json.loads(line) for line in (folder.parent / "frames.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()]
    cam = folder.name
    items = []
    for row in rows:
        info = row.get(cam)
        image = folder / f"{row['frame']:06d}.jpg"
        if info is None or not image.exists():
            continue
        items.append((image, int(info["seq"]), float(info["pts_ms"]), int(info["recv_ms"])))
    if not items:
        raise SystemExit(f"재생할 사진이 없어요: {folder}")
    first = rows[0]
    base = min(int(first[c]["recv_ms"]) for c in ("cam1", "cam2") if c in first)
    return items, base


class CameraSource:
    def __init__(self, source, name: str | None = None, queue_size: int = 64,
                 reconnect_limit: int = 5, reconnect_wait: float = 2.0,
                 requested_size: tuple[int, int] | None = None):
        self.target, self.shown, self.kind = resolve(source)
        self.name = name or self.shown
        self.reconnect_limit = reconnect_limit
        self.reconnect_wait = reconnect_wait
        self.requested_size = requested_size
        self.frames: queue.Queue[Frame] = queue.Queue(maxsize=queue_size)
        self.received = 0
        self.dropped = 0
        self.reconnects = 0
        self.size = None                 # (w, h)
        self.fps = None                  # 소스가 알려준 fps (RTSP·웹캠은 부정확할 수 있음)
        self.error = None
        self._cap = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"cam-{self.name}", daemon=True)

    # ---- 열기 / 닫기 ----
    def _open(self) -> bool:
        if self.kind == "folder":
            self._recording, self._base_ms = load_recording(Path(self.target))
            image = cv2.imread(str(self._recording[0][0]))
            if image is None:
                return False
            self.size = (image.shape[1], image.shape[0])
            span = (self._recording[-1][3] - self._recording[0][3]) / 1000
            self.fps = (len(self._recording) - 1) / span if span > 0 else None
            return True
        cap = cv2.VideoCapture(self.target)
        if self.requested_size:
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.requested_size[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.requested_size[1])
        if not cap.isOpened():
            cap.release()
            return False
        self._cap = cap
        self.size = (int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        self.fps = cap.get(cv2.CAP_PROP_FPS) or None
        return True

    def start(self):
        if not self._open():
            raise SystemExit(f"[{self.name}] 열 수 없어요: {self.shown}")
        print(f"[{self.name}] 연결: {self.shown} | {self.size[0]}x{self.size[1]} | 소스 fps {f'{self.fps:.1f}' if self.fps else '?'}")
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3)
        if self._cap is not None:
            self._cap.release()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()

    @property
    def alive(self) -> bool:
        return self._thread.is_alive() or not self.frames.empty()

    # ---- 프레임 받기 ----
    def get(self, timeout: float = 1.0) -> Frame | None:
        """다음 프레임. timeout 동안 없으면 None"""
        try:
            return self.frames.get(timeout=timeout)
        except queue.Empty:
            return None

    def _push(self, frame: Frame):
        while True:
            try:
                self.frames.put_nowait(frame)
                return
            except queue.Full:
                try:
                    self.frames.get_nowait()     # 가장 오래된 것 버림
                    self.dropped += 1
                except queue.Empty:
                    pass

    def _reconnect(self) -> bool:
        self._cap.release()
        while self.reconnects < self.reconnect_limit and not self._stop.is_set():
            self.reconnects += 1
            print(f"[{self.name}] 끊김 → 다시 연결 {self.reconnects}/{self.reconnect_limit}")
            time.sleep(self.reconnect_wait)
            if self._open():
                return True
        return False

    def _run_folder(self):
        """녹화 폴더: 기록한 받은 시각 간격 그대로 사진을 흘려보낸다.
        - 같은 녹화의 cam1·cam2 는 같은 출발 시각을 써서, 늦게 연 카메라가 밀리지 않게 한다
        - 사진은 정해진 시각 전에 미리 읽어 두고, 그 시각이 되면 바로 넘긴다 (읽는 시간만큼 밀리지 않게)"""
        start_s = _replay_start(Path(self.target).parent)
        for image_path, seq, pts_ms, recorded_ms in self._recording:
            if self._stop.is_set():
                break
            image = cv2.imread(str(image_path))
            if image is None:
                continue
            wait = start_s + (recorded_ms - self._base_ms) / 1000 - time.time()
            if wait > 0:
                time.sleep(wait)
            self._push(Frame(self.name, seq, pts_ms, int(time.time() * 1000), image))
            self.received += 1

    def _run(self):
        if self.kind == "folder":
            self._run_folder()
            return
        seq = 0
        start_wall = time.perf_counter()
        while not self._stop.is_set():
            ok, image = self._cap.read()
            recv_ms = int(time.time() * 1000)
            if not ok:
                if self.kind == "file":
                    break                         # 영상 끝
                if self._reconnect():
                    continue
                self.error = "다시 연결 실패"
                print(f"[{self.name}] 다시 연결 {self.reconnect_limit}번 실패, 멈춤")
                break
            pts_ms = self._cap.get(cv2.CAP_PROP_POS_MSEC)
            if self.kind == "file":
                # 파일은 실제 카메라처럼 영상 시간에 맞춰 흘려보낸다
                wait = pts_ms / 1000 - (time.perf_counter() - start_wall)
                if wait > 0:
                    time.sleep(wait)
                recv_ms = int(time.time() * 1000)
            self._push(Frame(self.name, seq, pts_ms, recv_ms, image))
            self.received += 1
            seq += 1


def main():
    parser = argparse.ArgumentParser(description="카메라 연결 확인: fps, 시각, 끊김 점검")
    parser.add_argument("--source", action="append", required=True,
                        help="웹캠 번호, 영상 파일, tapo:IP, rtsp://... (여러 번 쓰면 여러 대)")
    parser.add_argument("--seconds", type=float, default=10)
    parser.add_argument("--show", action="store_true", help="화면 표시 (q로 종료)")
    args = parser.parse_args()

    cams = [CameraSource(s, name=f"cam{i + 1}").start() for i, s in enumerate(args.source)]
    last = {c.name: None for c in cams}
    first_recv = {}
    t_end = time.time() + args.seconds
    try:
        while time.time() < t_end and any(c.alive for c in cams):
            for cam in cams:
                f = cam.get(timeout=0.01)
                if f is None:
                    continue
                first_recv.setdefault(cam.name, f)
                last[cam.name] = f
                if args.show:
                    cv2.imshow(cam.name, f.image)
            if args.show and cv2.waitKey(1) & 0xFF == ord("q"):
                break
    finally:
        for cam in cams:
            cam.stop()
        if args.show:
            cv2.destroyAllWindows()

    print("\n결과")
    for cam in cams:
        f0, f1 = first_recv.get(cam.name), last[cam.name]
        if f0 is None or f1 is f0:
            print(f"  {cam.name}: 받은 프레임 없음 ({cam.error or '확인 필요'})")
            continue
        span = (f1.recv_ms - f0.recv_ms) / 1000
        pts_span = (f1.pts_ms - f0.pts_ms) / 1000
        print(f"  {cam.name}: {cam.received}장 | 받은 fps {(f1.seq - f0.seq) / span:.1f} | "
              f"버림 {cam.dropped} | 재연결 {cam.reconnects} | "
              f"영상 시간 {pts_span:.2f}s / 받은 시간 {span:.2f}s")


if __name__ == "__main__":
    main()
