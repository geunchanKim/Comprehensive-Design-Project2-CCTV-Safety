"""
실시간 녹화: 카메라 두 대 영상을 받아 "같은 순간" 프레임끼리 짝지어 저장한다.

저장 형식은 Unity 폴더와 같다. 그래서 녹화한 폴더를 unity_reader.py에 그대로 넣어 탐지·서버 전송을 할 수 있다.
  runs/real/<이름>-<시각>/
    cam1/000001.jpg, cam2/000001.jpg   짝지은 프레임 (같은 번호 = 같은 순간)
    frames.jsonl                       짝마다 한 줄: frame, ts, objects(빈 목록), cam1·cam2 시각, dt_ms
    stamps.jsonl                       받은 프레임 전부의 시각 (짝 못 지은 것 포함, 끊김·지연 분석용)
    meta.json                          소스, 해상도, 짝 기준, 결과 수

짝 맞추기
  - 노트북이 받은 시각(recv_ms) 기준으로, 두 카메라에서 가장 오래된 프레임끼리 비교한다.
  - 차이가 --tol-ms 이내면 짝으로 저장한다. 아니면 더 오래된 쪽은 짝이 올 수 없으니 버린다.
  - 기본 50ms. 짝마다 실제 차이(dt_ms)를 적어 두므로, 나중에 17·33·50ms 기준별로 다시 골라 평가할 수 있다.
  - --cam2-offset-ms: 깜빡임 동기화로 잰 cam2 지연을 빼고 비교한다 (재기 전에는 0).

실행 (ai/ 폴더에서)
  python edge/realtime.py --cam1 0 --cam2 ~/Downloads/CCTVTEST.mp4 --seconds 20 --show   # 웹캠 + 영상으로 연습
  python edge/realtime.py --cam1 tapo:192.168.0.10 --cam2 tapo:192.168.0.11 --name s1-walk --show
  끝내기: --seconds 가 지나거나, 미리보기 창에서 q, 또는 Ctrl+C

녹화 후 탐지·전송 (실제 카메라는 정답 좌표가 없으므로 탐지만, 캘리브레이션은 백엔드가 등록)
  python edge/unity_reader.py runs/real/<폴더> --server http://... --only detections --calib none
"""

import argparse
import json
import statistics
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2

from camera_source import CameraSource

AI_DIR = Path(__file__).resolve().parent.parent           # ai/
OUT_ROOT = AI_DIR / "runs" / "real"
CAMERAS = ("cam1", "cam2")


class Recorder:
    def __init__(self, out_dir: Path, tol_ms: float, cam2_offset_ms: float, jpeg_quality: int):
        self.out_dir = out_dir
        self.tol_ms = tol_ms
        self.offset = {"cam1": 0.0, "cam2": cam2_offset_ms}
        self.params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
        self.waiting = {cam: deque() for cam in CAMERAS}
        self.pairs = 0
        self.unpaired = {cam: 0 for cam in CAMERAS}
        self.dts = []
        for cam in CAMERAS:
            (out_dir / cam).mkdir(parents=True, exist_ok=True)
        self.frames_file = open(out_dir / "frames.jsonl", "w", encoding="utf-8")
        self.stamps_file = open(out_dir / "stamps.jsonl", "w", encoding="utf-8")

    def _t(self, f) -> float:
        return f.recv_ms - self.offset[f.camera]

    def _stamp(self, f, frame_no):
        self.stamps_file.write(json.dumps({"camera": f.camera, "seq": f.seq, "pts_ms": round(f.pts_ms, 1),
                                           "recv_ms": f.recv_ms, "frame": frame_no}) + "\n")

    def add(self, f):
        self.waiting[f.camera].append(f)
        self._match()

    def _drop(self, cam):
        self._stamp(self.waiting[cam].popleft(), None)
        self.unpaired[cam] += 1

    def _match(self):
        """가장 가까운 프레임끼리 짝짓는다.
        오래된 쪽 바로 다음 프레임이 상대와 더 가까우면, 오래된 쪽을 버리고 다음 것과 짝짓는다.
        다음 프레임이 아직 안 왔으면 올 때까지 기다린다 (최대 한 프레임 늦어짐)."""
        a, b = self.waiting["cam1"], self.waiting["cam2"]
        while a and b:
            dt = self._t(b[0]) - self._t(a[0])
            if dt > self.tol_ms:               # cam1이 너무 오래됨 → 짝이 될 cam2가 더는 안 옴
                self._drop("cam1")
                continue
            if dt < -self.tol_ms:
                self._drop("cam2")
                continue
            older, other = (a, b) if dt > 0 else (b, a)
            if dt != 0:
                if len(older) < 2:
                    break                      # 더 가까운 다음 프레임이 올 수 있으니 기다림
                if abs(self._t(other[0]) - self._t(older[1])) < abs(dt):
                    self._drop(older[0].camera)
                    continue
            self._save(a.popleft(), b.popleft(), dt)

    def _save(self, f1, f2, dt):
        self.pairs += 1
        n = self.pairs
        cv2.imwrite(str(self.out_dir / "cam1" / f"{n:06d}.jpg"), f1.image, self.params)
        cv2.imwrite(str(self.out_dir / "cam2" / f"{n:06d}.jpg"), f2.image, self.params)
        row = {"frame": n, "ts": f1.recv_ms, "objects": [], "dt_ms": round(dt, 1)}
        for f in (f1, f2):
            row[f.camera] = {"seq": f.seq, "pts_ms": round(f.pts_ms, 1), "recv_ms": f.recv_ms}
            self._stamp(f, n)
        self.frames_file.write(json.dumps(row) + "\n")
        self.dts.append(abs(dt))

    def close(self):
        for cam in CAMERAS:                    # 끝날 때 짝 없이 남은 것도 기록
            while self.waiting[cam]:
                self._stamp(self.waiting[cam].popleft(), None)
                self.unpaired[cam] += 1
        self.frames_file.close()
        self.stamps_file.close()

    def status(self) -> str:
        dt = f"{statistics.median(self.dts):.0f}ms" if self.dts else "-"
        return f"짝 {self.pairs} | 짝 못 지음 cam1 {self.unpaired['cam1']}, cam2 {self.unpaired['cam2']} | 시각 차이 중간값 {dt}"


def preview(f1, f2, width=640):
    def small(img):
        h, w = img.shape[:2]
        return cv2.resize(img, (width, int(h * width / w)))
    a, b = small(f1.image), small(f2.image)
    if a.shape[0] != b.shape[0]:
        b = cv2.resize(b, (b.shape[1], a.shape[0]))
    return cv2.hconcat([a, b])


def main():
    parser = argparse.ArgumentParser(description="카메라 두 대 동시 녹화 (Unity 폴더 형식)")
    parser.add_argument("--cam1", required=True, help="웹캠 번호, 영상 파일, tapo:IP, rtsp://...")
    parser.add_argument("--cam2", required=True)
    parser.add_argument("--name", default="rec", help="폴더 이름 앞부분 (예: s1-walk)")
    parser.add_argument("--out", default=str(OUT_ROOT))
    parser.add_argument("--seconds", type=float, default=0, help="녹화 시간 (0 = q나 Ctrl+C로 끝낼 때까지)")
    parser.add_argument("--tol-ms", type=float, default=50, help="짝으로 인정할 최대 시각 차이")
    parser.add_argument("--cam2-offset-ms", type=float, default=0, help="깜빡임 동기화로 잰 cam2 지연")
    parser.add_argument("--jpeg-quality", type=int, default=95)
    parser.add_argument("--show", action="store_true", help="두 카메라 미리보기 (q로 종료)")
    args = parser.parse_args()

    out_dir = Path(args.out).expanduser() / f"{args.name}-{datetime.now():%Y%m%d-%H%M%S}"
    cams = {"cam1": CameraSource(args.cam1, name="cam1"), "cam2": CameraSource(args.cam2, name="cam2")}
    for cam in cams.values():
        cam.start()
    rec = Recorder(out_dir, args.tol_ms, args.cam2_offset_ms, args.jpeg_quality)
    print(f"저장 위치: {out_dir}\n녹화 시작 (끝내기: q 또는 Ctrl+C)")

    started = time.time()
    last_print = started
    latest = {}
    try:
        while all(c.alive for c in cams.values()):
            if args.seconds and time.time() - started >= args.seconds:
                break
            for cam in cams.values():
                f = cam.get(timeout=0.005)
                if f is not None:
                    latest[f.camera] = f
                    rec.add(f)
            if args.show and len(latest) == 2:
                cv2.imshow("cam1 | cam2", preview(latest["cam1"], latest["cam2"]))
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
            if time.time() - last_print >= 5:
                print(f"  {time.time() - started:.0f}초 | {rec.status()}")
                last_print = time.time()
    except KeyboardInterrupt:
        pass
    finally:
        for cam in cams.values():
            cam.stop()
        while True:                            # 큐에 남은 프레임까지 처리
            left = [f for f in (c.get(timeout=0) for c in cams.values()) if f is not None]
            if not left:
                break
            for f in left:
                rec.add(f)
        rec.close()
        if args.show:
            cv2.destroyAllWindows()

    elapsed = time.time() - started
    meta = {
        "name": args.name, "started": datetime.fromtimestamp(started).isoformat(timespec="seconds"),
        "seconds": round(elapsed, 1), "tol_ms": args.tol_ms, "cam2_offset_ms": args.cam2_offset_ms,
        "pairs": rec.pairs, "pair_fps": round(rec.pairs / max(elapsed, 1e-9), 2),
        "dt_ms_median": round(statistics.median(rec.dts), 1) if rec.dts else None,
        "dt_ms_max": round(max(rec.dts), 1) if rec.dts else None,
        "cameras": {name: {"source": c.shown, "kind": c.kind, "size": c.size, "fps": c.fps,
                           "received": c.received, "queue_dropped": c.dropped, "reconnects": c.reconnects,
                           "unpaired": rec.unpaired[name], "error": c.error} for name, c in cams.items()},
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n녹화 끝: {elapsed:.1f}초 | {rec.status()} | 짝 {meta['pair_fps']} fps")
    for name, c in cams.items():
        print(f"  {name}: 받음 {c.received} | 큐에서 버림 {c.dropped} | 재연결 {c.reconnects} | {c.size}")
    print(f"저장 위치: {out_dir}")


if __name__ == "__main__":
    main()
