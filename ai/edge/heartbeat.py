"""
엣지 → 서버 heartbeat (카메라마다 1초에 한 번 "살아 있어" 알리기)

탐지 결과와 따로 보낸다. 전송 큐가 밀리거나 오래된 짝을 버려도 heartbeat는 제때 간다.
계약: docs/specs/edge-heartbeat.md (서버: POST /edge/heartbeat → 204)

보내는 내용 (카메라마다)
  session_id        탐지 메시지와 같은 값
  camera_id         cam1, cam2
  edge_run_id       엣지를 켤 때마다 새로 만드는 UUID
  source            "rtsp"(웹캠·카메라) / "folder"(녹화 폴더·영상 파일 재생)
  last_recv_ms      이 카메라 프레임을 마지막으로 받은 시각. 첫 프레임 전에는 null
  sent_at_ms        heartbeat 를 보낸 시각
  dropped_count     버린 짝 수 (큐가 꽉 차서 + 오래돼서, 실행 시작부터 누적)
  max_queue_age_ms  직전 heartbeat 이후 전송 큐에서 가장 오래 기다린 시간

규칙
- last_recv_ms 와 sent_at_ms 는 같은 시계(clock.now_ms, 뒤로 가지 않음)로 만든다.
  last_recv_ms 는 메인 루프가 카메라 큐에서 프레임을 꺼낸 순간에 note_frame()으로 찍는다
- 한 스레드에서 카메라를 하나씩 순서대로 보낸다 (같은 카메라에 동시 요청 X)
- stop()은 마지막 요청이 끝날 때까지 기다린다. 다음 실행은 새 edge_run_id 로 시작한다
- 전송 큐는 두 카메라가 함께 쓰므로 max_queue_age_ms 는 한 바퀴에 한 번 꺼내 두 카메라에 같은 값을 넣는다
- 보내기 실패는 세기만 하고 탐지·전송을 멈추지 않는다
"""

import threading
import time
import uuid

import clock

SOURCE_KIND = {"webcam": "rtsp", "rtsp": "rtsp", "folder": "folder", "file": "folder"}


class Heartbeat:
    def __init__(self, session_id: str, sources: dict, client, interval_s: float = 1.0, now_ms=clock.now_ms):
        """sources: {카메라 이름: CameraSource.kind}. client: ServerClient (post_now, dropped_total, pop_max_queue_age_ms)"""
        self.session_id = session_id
        self.sources = {cam: SOURCE_KIND.get(kind, "rtsp") for cam, kind in sources.items()}
        self.client = client
        self.interval_s = interval_s
        self.edge_run_id = str(uuid.uuid4())
        self.stats = {"sent": 0, "failed": 0}
        self._now_ms = now_ms
        self._last_recv = {cam: None for cam in self.sources}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def note_frame(self, camera: str):
        """메인 루프가 프레임을 받을 때마다 부른다"""
        with self._lock:
            self._last_recv[camera] = self._now_ms()

    def build(self, camera: str, max_queue_age_ms: int) -> dict:
        with self._lock:
            last_recv = self._last_recv[camera]
        return {"session_id": self.session_id, "camera_id": camera, "edge_run_id": self.edge_run_id,
                "source": self.sources[camera], "last_recv_ms": last_recv, "sent_at_ms": self._now_ms(),
                "dropped_count": self.client.dropped_total, "max_queue_age_ms": max_queue_age_ms}

    def beat(self):
        """카메라마다 한 번씩 순서대로 보낸다"""
        max_queue_age_ms = self.client.pop_max_queue_age_ms()
        for camera in self.sources:
            ok = self.client.post_now("/edge/heartbeat", self.build(camera, max_queue_age_ms))
            self.stats["sent" if ok else "failed"] += 1

    def start(self):
        self._thread = threading.Thread(target=self._run, name="heartbeat", daemon=True)
        self._thread.start()

    def stop(self, wait: float = 5.0):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=wait)

    def _run(self):
        next_at = time.monotonic()
        while not self._stop.is_set():
            try:
                self.beat()
            except Exception as e:             # heartbeat 오류로 엣지 전체가 멈추지 않게
                self.stats["failed"] += 1
                print(f"[heartbeat 오류] {e}")
            next_at += self.interval_s
            delay = next_at - time.monotonic()
            if delay < 0:                      # 많이 밀렸으면 따라잡으려 몰아 보내지 않고 지금부터 다시 센다
                next_at, delay = time.monotonic(), 0
            self._stop.wait(delay)

    def summary(self) -> str:
        return f"heartbeat 보냄 {self.stats['sent']} | 실패 {self.stats['failed']} | run {self.edge_run_id[:8]}"
