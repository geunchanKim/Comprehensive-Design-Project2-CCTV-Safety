"""
실시간 녹화·전송: 카메라 두 대 영상을 받아 "같은 순간" 프레임끼리 짝짓고, 저장하고(기본), 탐지해서 서버로 보낸다(--send).

저장 형식은 Unity 폴더와 같다. 그래서 녹화한 폴더를 unity_reader.py에 그대로 넣어 탐지·서버 전송을 다시 할 수 있다.
  runs/real/<이름>-<시각>/
    cam1/000001.jpg, cam2/000001.jpg   짝지은 프레임 (같은 번호 = 같은 순간)
    frames.jsonl                       짝마다 한 줄: frame, ts, objects(빈 목록), cam1·cam2 시각, dt_ms
    stamps.jsonl                       받은 프레임 전부의 시각 (짝 못 지은 것 포함, 끊김·지연 분석용)
    meta.json                          소스, 해상도, 짝 기준, 결과 수, 전송 결과

짝 맞추기
  - 노트북이 받은 시각(recv_ms) 기준으로 가장 가까운 프레임끼리 짝짓는다.
  - 차이가 --tol-ms 이내만 짝으로 인정하고 같은 값을 서버 세션 설정으로 보낸다. 기본 50ms.
  - 짝마다 실제 차이(dt_ms)를 적어 두므로, 나중에 17·33·50ms 기준별로 다시 골라 평가할 수 있다.
  - --cam2-offset-ms: 깜빡임 동기화로 잰 cam2 지연을 빼고 비교한다 (재기 전에는 0).

서버 전송 (--send) — 규칙은 bundle.py
  - --session: 해민이 캘리브레이션을 등록해 둔 session_id (예: classroom-1014-s2-t1). 규칙에 안 맞으면 시작 안 함
  - --sessions: 목록 파일을 주면 목록에 있는 이름인지도 확인
  - 캘리브레이션은 등록하지 않는다 (해민 담당). 항상 calibration_profile=basic 으로 보낸다
  - 탐지가 카메라보다 느리면 밀린 짝은 건너뛰고 가장 최근 짝을 탐지한다 (저장은 모든 짝을 함)
  - 서버가 "캘리브레이션 없음(404)", "해상도 다름(422)", "중복(409)"으로 거절하면 이유를 말하고 멈춘다
  - 보낸 것·서버 응답·실패: runs/edge/<session_id>/ (sent_detections.jsonl, responses_detections.jsonl, failed.jsonl)

실행 (ai/ 폴더에서)
  python edge/realtime.py --cam1 0 --cam2 ~/Downloads/CCTVTEST.mp4 --seconds 20 --show            # 녹화만
  python edge/realtime.py --cam1 0 --cam2 ~/Downloads/CCTVTEST.mp4 --seconds 20 \\
      --send --dry-run --session classroom-1014-s1-t1                                               # 서버 없이 전송 연습
  python edge/realtime.py --cam1 tapo:192.168.0.10 --cam2 tapo:192.168.0.11 --show \\
      --send --server http://<서버>:32130 --session classroom-1014-s2-t1 --sessions sessions/classroom-1014.txt
  끝내기: --seconds 가 지나거나, 미리보기 창에서 q, 또는 Ctrl+C

녹화만 해 두고 나중에 보내기
  python edge/unity_reader.py runs/real/<폴더> --server http://... --only detections --calib none --session <session_id>
"""

import argparse
import json
import statistics
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import cv2

from bundle import MAX_SYNC_DELTA_MS, build_bundle, build_frame, check_session_id, clean_detections, edge_config, \
    explain_failure
from camera_source import CameraSource

AI_DIR = Path(__file__).resolve().parent.parent           # ai/
OUT_ROOT = AI_DIR / "runs" / "real"
SEND_ROOT = AI_DIR / "runs" / "edge"
CAMERAS = ("cam1", "cam2")
REAL_CLASSES = "person,chair,suitcase"                   # 실측 촬영 물체: 사람, 의자, 캐리어


class Recorder:
    """두 카메라 프레임을 가장 가까운 것끼리 짝짓는다. 짝이 생기면 저장하고 on_pair(번호, f1, f2, dt)를 부른다"""

    def __init__(self, out_dir: Path, tol_ms: float, cam2_offset_ms: float, jpeg_quality: int,
                 save: bool = True, on_pair=None):
        self.out_dir = out_dir
        self.tol_ms = tol_ms
        self.offset = {"cam1": 0.0, "cam2": cam2_offset_ms}
        self.params = [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality]
        self.save = save
        self.on_pair = on_pair
        self.waiting = {cam: deque() for cam in CAMERAS}
        self.pairs = 0
        self.unpaired = {cam: 0 for cam in CAMERAS}
        self.dts = []
        out_dir.mkdir(parents=True, exist_ok=True)
        if save:
            for cam in CAMERAS:
                (out_dir / cam).mkdir(parents=True, exist_ok=True)
        self.frames_file = open(out_dir / "frames.jsonl", "w", encoding="utf-8")
        self.stamps_file = open(out_dir / "stamps.jsonl", "w", encoding="utf-8")

    def corrected_ms(self, f) -> int:
        """서버로 보낼 시각: 받은 시각에서 그 카메라 지연을 뺀 값"""
        return int(round(f.recv_ms - self.offset[f.camera]))

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
            self._pair(a.popleft(), b.popleft(), dt)

    def _pair(self, f1, f2, dt):
        self.pairs += 1
        n = self.pairs
        if self.save:
            cv2.imwrite(str(self.out_dir / "cam1" / f"{n:06d}.jpg"), f1.image, self.params)
            cv2.imwrite(str(self.out_dir / "cam2" / f"{n:06d}.jpg"), f2.image, self.params)
        row = {"frame": n, "ts": f1.recv_ms, "objects": [], "dt_ms": round(dt, 1)}
        for f in (f1, f2):
            row[f.camera] = {"seq": f.seq, "pts_ms": round(f.pts_ms, 1), "recv_ms": f.recv_ms}
            self._stamp(f, n)
        self.frames_file.write(json.dumps(row) + "\n")
        self.dts.append(abs(dt))
        if self.on_pair:
            self.on_pair(n, f1, f2, dt)

    def close(self):
        for cam in CAMERAS:                    # 끝날 때 짝 없이 남은 것도 기록
            while self.waiting[cam]:
                self._drop(cam)
        self.frames_file.close()
        self.stamps_file.close()

    def status(self) -> str:
        dt = f"{statistics.median(self.dts):.0f}ms" if self.dts else "-"
        return f"짝 {self.pairs} | 짝 못 지음 cam1 {self.unpaired['cam1']}, cam2 {self.unpaired['cam2']} | 시각 차이 중간값 {dt}"


class Sender:
    """짝지은 프레임을 탐지해서 서버로 보낸다. 별도 스레드에서 가장 최근 짝 하나만 처리한다"""

    def __init__(self, session_id: str, detectors: dict, client, recorder: Recorder):
        self.session_id = session_id
        self.detectors = detectors
        self.client = client
        self.recorder = recorder
        self.stats = {"sent": 0, "skipped": 0, "removed": 0, "empty": 0, "errors": 0}
        self.stop_reason = None
        self._latest = None
        self._cond = threading.Condition()
        self._closing = False
        self._thread = threading.Thread(target=self._run, name="sender", daemon=True)
        self._thread.start()

    def offer(self, n, f1, f2, dt):
        """Recorder가 짝을 만들 때마다 부른다. 아직 탐지 못 한 짝이 있으면 버리고 새 짝으로 바꾼다"""
        with self._cond:
            if self._latest is not None:
                self.stats["skipped"] += 1
            self._latest = (n, f1, f2)
            self._cond.notify()

    def close(self, wait: float = 10):
        with self._cond:
            self._closing = True
            self._cond.notify()
        self._thread.join(timeout=wait)

    def _run(self):
        while True:
            with self._cond:
                while self._latest is None and not self._closing:
                    self._cond.wait()
                if self._latest is None:
                    return
                n, f1, f2 = self._latest
                self._latest = None
            try:
                frames = []
                for f in (f1, f2):
                    h, w = f.image.shape[:2]
                    dets, removed = clean_detections(self.detectors[f.camera](f.image), w, h)
                    self.stats["removed"] += removed
                    frames.append(build_frame(f.camera, n, self.recorder.corrected_ms(f), (w, h), dets,
                                              pts_ms=f.pts_ms, recv_ms=f.recv_ms))
            except Exception as e:                     # 모델 오류는 이 짝만 건너뜀
                self.stats["errors"] += 1
                print(f"  [탐지 오류] 짝 {n}: {e}")
                continue
            if not any(fr["detections"] for fr in frames):
                self.stats["empty"] += 1
            self.client.send(build_bundle(self.session_id, n, frames,
                                          max_sync_delta_ms=int(self.recorder.tol_ms)), path="/detections")
            self.stats["sent"] += 1
            self._check_server()

    def _check_server(self):
        """서버가 계속 거절할 이유(캘리브레이션 없음 등)로 실패했으면 멈춤 표시"""
        if self.client.last_failure and self.stop_reason is None:
            _, status, body = self.client.last_failure
            self.stop_reason = explain_failure(status, body)

    def status(self) -> str:
        s = self.stats
        return f"전송 {s['sent']} | 밀려서 건너뜀 {s['skipped']} | 서버 {self.client.summary()}"


def preview(f1, f2, width=640):
    def small(img):
        h, w = img.shape[:2]
        return cv2.resize(img, (width, int(h * width / w)))
    a, b = small(f1.image), small(f2.image)
    if a.shape[0] != b.shape[0]:
        b = cv2.resize(b, (b.shape[1], a.shape[0]))
    return cv2.hconcat([a, b])


def make_sender(args, recorder):
    """--send 준비: session_id 확인 → 서버 확인 → 탐지기 2개(카메라별 추적) 준비"""
    from detector import Detector, parse_class_conf, parse_classes   # torch는 전송할 때만 불러옴
    from server_client import ServerClient

    client = ServerClient(args.server, SEND_ROOT / args.session, dry_run=args.dry_run, drop_when_full=True)
    if not client.check_server():
        raise SystemExit(f"서버 {args.server}/health 응답 없음")
    detectors = {cam: Detector(model=args.model, conf=args.conf, imgsz=args.imgsz,
                               class_conf=parse_class_conf(args.class_conf), classes=parse_classes(args.classes),
                               foot=args.foot) for cam in CAMERAS}
    (client.out_dir / "edge_config.json").write_text(
        json.dumps(edge_config(detectors["cam1"]), indent=2, ensure_ascii=False), encoding="utf-8")
    mode = "dry-run (파일로만 저장)" if args.dry_run else args.server
    print(f"전송: session {args.session} | {mode} | 클래스 {args.classes} | 발 위치 {args.foot}")
    return Sender(args.session, detectors, client, recorder)


def main():
    parser = argparse.ArgumentParser(description="카메라 두 대 동시 녹화·실시간 전송")
    parser.add_argument("--cam1", required=True, help="웹캠 번호, 영상 파일, tapo:IP, rtsp://...")
    parser.add_argument("--cam2", required=True)
    parser.add_argument("--name", default=None, help="녹화 폴더 이름 앞부분 (기본: session_id, 없으면 rec)")
    parser.add_argument("--out", default=str(OUT_ROOT))
    parser.add_argument("--seconds", type=float, default=0, help="녹화 시간 (0 = q나 Ctrl+C로 끝낼 때까지)")
    parser.add_argument("--tol-ms", type=float, default=MAX_SYNC_DELTA_MS, help="짝으로 인정할 최대 시각 차이")
    parser.add_argument("--cam2-offset-ms", type=float, default=0, help="깜빡임 동기화로 잰 cam2 지연")
    parser.add_argument("--jpeg-quality", type=int, default=95)
    parser.add_argument("--no-save", action="store_true", help="사진 저장 안 함 (시각 기록은 남김)")
    parser.add_argument("--show", action="store_true", help="두 카메라 미리보기 (q로 종료)")
    send = parser.add_argument_group("서버 전송")
    send.add_argument("--send", action="store_true", help="짝마다 탐지해서 서버로 보냄")
    send.add_argument("--server", default=None, help="예: http://121.182.60.2:32130")
    send.add_argument("--dry-run", action="store_true", help="서버로 보내지 않고 파일로만 저장")
    send.add_argument("--session", default=None, help="session_id (예: classroom-1014-s2-t1)")
    send.add_argument("--sessions", default=None, help="session 목록 파일 (주면 목록에 있는지 확인)")
    send.add_argument("--model", choices=["coco", "v2", "ensemble"], default="coco")
    send.add_argument("--classes", default=REAL_CLASSES)
    send.add_argument("--class-conf", default=None, help="클래스별 conf. 예: person=0.5,chair=0.4")
    send.add_argument("--conf", type=float, default=0.4)
    send.add_argument("--imgsz", type=int, default=1280)
    send.add_argument("--foot", choices=["box", "ankle"], default="ankle")
    args = parser.parse_args()

    if args.send:
        if not args.session:
            raise SystemExit("--send 에는 --session 이 필요해요 (해민이 캘리브레이션을 등록한 이름)")
        check_session_id(args.session, args.sessions)
        if args.tol_ms < 0 or args.tol_ms > 10_000:
            raise SystemExit("--tol-ms 는 0~10000ms 범위여야 해요")
        if not args.dry_run and not args.server:
            raise SystemExit("--server 주소를 주거나 --dry-run 으로 실행하세요")

    name = args.name or args.session or "rec"
    out_dir = Path(args.out).expanduser() / f"{name}-{datetime.now():%Y%m%d-%H%M%S}"
    rec = Recorder(out_dir, args.tol_ms, args.cam2_offset_ms, args.jpeg_quality, save=not args.no_save)
    sender = make_sender(args, rec) if args.send else None   # 모델을 먼저 불러온 뒤 카메라를 연다
    if sender:
        rec.on_pair = sender.offer

    cams = {"cam1": CameraSource(args.cam1, name="cam1"), "cam2": CameraSource(args.cam2, name="cam2")}
    for cam in cams.values():
        cam.start()
    print(f"저장 위치: {out_dir}\n시작 (끝내기: q 또는 Ctrl+C)")

    started = time.time()
    last_print = started
    latest = {}
    try:
        while all(c.alive for c in cams.values()):
            if args.seconds and time.time() - started >= args.seconds:
                break
            if sender and sender.stop_reason:
                print(f"\n[멈춤] {sender.stop_reason}")
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
                if sender:
                    print(f"         | {sender.status()}")
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
        if sender:
            sender.close()
            sender.client.close(wait=10)
        if args.show:
            cv2.destroyAllWindows()

    elapsed = time.time() - started
    meta = {
        "name": name, "started": datetime.fromtimestamp(started).isoformat(timespec="seconds"),
        "seconds": round(elapsed, 1), "tol_ms": args.tol_ms, "cam2_offset_ms": args.cam2_offset_ms,
        "saved_images": not args.no_save,
        "pairs": rec.pairs, "pair_fps": round(rec.pairs / max(elapsed, 1e-9), 2),
        "dt_ms_median": round(statistics.median(rec.dts), 1) if rec.dts else None,
        "dt_ms_max": round(max(rec.dts), 1) if rec.dts else None,
        "cameras": {cam: {"source": c.shown, "kind": c.kind, "size": c.size, "fps": c.fps,
                          "received": c.received, "queue_dropped": c.dropped, "reconnects": c.reconnects,
                          "unpaired": rec.unpaired[cam], "error": c.error} for cam, c in cams.items()},
    }
    if sender:
        meta["send"] = {"session_id": args.session, "server": "dry-run" if args.dry_run else args.server,
                        **sender.stats, "server_result": sender.client.summary(),
                        "stop_reason": sender.stop_reason, "log_dir": str(sender.client.out_dir)}
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n끝: {elapsed:.1f}초 | {rec.status()} | 짝 {meta['pair_fps']} fps")
    for cam, c in cams.items():
        print(f"  {cam}: 받음 {c.received} | 큐에서 버림 {c.dropped} | 재연결 {c.reconnects} | {c.size}")
    if sender:
        s = sender.stats
        print(f"  전송: 보냄 {s['sent']} (탐지 0개 {s['empty']}) | 밀려서 건너뜀 {s['skipped']} | "
              f"탐지 오류 {s['errors']} | 뺀 탐지 {s['removed']}")
        print(f"  서버: {sender.client.summary()}")
        if sender.stop_reason:
            print(f"  멈춘 이유: {sender.stop_reason}")
        print(f"  전송 기록: {sender.client.out_dir}")
    print(f"저장 위치: {out_dir}")


if __name__ == "__main__":
    main()
