"""
엣지 → 서버 전송기

메시지를 백그라운드 스레드에서 서버로 보낸다 (POST /detections, POST /ground-truth 등).
탐지 루프가 네트워크 때문에 멈추지 않게 큐에 넣고 바로 돌아온다.
캘리브레이션 등록(PUT)은 탐지보다 먼저 끝나야 해서 put_now()로 바로 보낸다.

큐가 꽉 찼을 때
- 기본 (drop_when_full=False): 자리가 날 때까지 기다린다. 폴더 재생처럼 메시지를 하나도 잃으면 안 될 때
- drop_when_full=True: 가장 오래된 메시지를 버린다. 실시간 카메라처럼 최신 프레임이 더 중요할 때
close()는 기본으로 큐가 빌 때까지 기다린다.

오래된 짝 버리기 (max_age_ms)
- 실시간은 늦게 도착한 위치가 쓸모없다. 화면까지 1초 목표를 넘길 짝은 보내지 않고 버린다
- 보내기 직전에 (send 때 받은 age_ms + 큐에서 기다린 시간)이 max_age_ms 를 넘으면 버리고 상태를 "stale"로 남긴다
- max_age_ms=None 이면 끄기 (기본). 버린 짝은 sent·failed 어디에도 쓰지 않는다
- heartbeat 용으로 버린 수(dropped_total)와 큐에서 가장 오래 기다린 시간(pop_max_queue_age_ms)을 준다

큐를 거치지 않는 POST (post_now)
- heartbeat 처럼 큐가 밀려도 제때 가야 하는 요청. 탐지 전송과 다른 HTTP 세션을 써서 서로 기다리지 않는다
- 실패해도 last_failure 에 넣지 않는다 (heartbeat 실패로 실시간 전송을 멈추지 않게)
- dry-run 이면 sent_<경로>.jsonl 에 저장만 한다 (예: sent_edge_heartbeat.jsonl)

- dry_run: 서버 없이 파일에 저장만 한다 (서버 준비 전 테스트용)
- 보낸 메시지: sent_<경로>.jsonl  (예: sent_detections.jsonl, sent_ground-truth.jsonl)
- /detections 서버 응답(매칭 결과, 3D 좌표): responses_detections.jsonl
- 실패한 메시지: failed.jsonl — HTTP 상태 코드와 서버 응답 본문을 같이 저장 (BE 공유용)

전송 결과 알림 (on_done)
- send(message, path, meta=...) 로 보낸 메시지가 끝나면 on_done(meta, 상태, rtt_ms, queue_ms) 를 부른다
    상태      서버 상태 코드(201 등), "network-error", "dry-run", "dropped"(큐가 꽉 차 버림), "stale"(오래돼서 버림)
    rtt_ms    요청을 보낸 순간부터 응답을 받기까지 (단조 시계). dry-run·버림은 None
    queue_ms  큐에 넣은 순간부터 실제로 보내기 시작하기까지
- realtime.py 는 이걸로 timings.jsonl 한 줄을 완성한다
"""

import json
import queue
import threading
import time
from collections import Counter
from pathlib import Path

import requests


class ServerClient:
    def __init__(self, base_url: str | None, out_dir: Path, dry_run: bool = False,
                 timeout: float = 5.0, max_queue: int = 300, drop_when_full: bool = False,
                 max_age_ms: float | None = None):
        if not dry_run and not base_url:
            raise ValueError("서버 주소(--server)가 없으면 --dry-run 으로 실행하세요")
        self.base_url = base_url.rstrip("/") if base_url else None
        self.dry_run = dry_run
        self.timeout = timeout
        self.drop_when_full = drop_when_full
        self.max_age_ms = max_age_ms
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        self.failed_path = out_dir / "failed.jsonl"
        self.stats = {"sent": 0, "failed": 0, "dropped": 0, "stale": 0}
        self.status_counts: Counter = Counter()      # (경로, 상태 코드) → 개수
        self.last_failure = None                     # (경로, 상태 코드, 응답) 가장 최근 실패. 실시간에서 멈출지 판단용
        self.on_done = None                          # on_done(meta, 상태, rtt_ms, queue_ms). 위 설명 참고

        self._max_queue_age_ms = 0.0                 # 마지막 pop 이후 큐에서 가장 오래 기다린 시간
        self._age_lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue(maxsize=max_queue)
        self._session = requests.Session()
        self._now_session = requests.Session()       # post_now 전용 (탐지 전송과 연결을 나눠 서로 막지 않게)
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def check_server(self) -> bool:
        if self.dry_run:
            return True
        try:
            return self._session.get(f"{self.base_url}/health", timeout=self.timeout).ok
        except requests.RequestException:
            return False

    def put_now(self, path: str, body: dict) -> bool:
        """큐를 거치지 않고 바로 PUT 한다 (캘리브레이션 등록처럼 다음 단계 전에 꼭 끝나야 하는 요청)"""
        sent_path = self._sent_path(path.rsplit("/", 1)[-1])     # /cameras/cam1/calibration → sent_calibration.jsonl
        if self.dry_run:
            self._append(sent_path, {"path": path, **body})
            self.stats["sent"] += 1
            self.status_counts[(path, "dry-run")] += 1
            return True
        try:
            r = self._session.put(f"{self.base_url}{path}", json=body, timeout=self.timeout)
            status, text = r.status_code, r.text
        except requests.RequestException as e:
            status, text = "network-error", str(e)
        self.status_counts[(path, status)] += 1
        if isinstance(status, int) and 200 <= status < 300:
            self._append(sent_path, {"path": path, **body})
            self.stats["sent"] += 1
            return True
        self.stats["failed"] += 1
        try:
            text = json.loads(text)
        except (TypeError, ValueError):
            pass
        self._append(self.failed_path, {"path": path, "status": status, "response": text, "message": body})
        print(f"[전송 실패] PUT {path} → {status} {str(text)[:200]}")
        return False

    def post_now(self, path: str, body: dict, timeout: float = 0.5) -> bool:
        """큐를 거치지 않고 바로 POST 한다. 성공(2xx·dry-run)이면 True. 위 설명 참고"""
        if self.dry_run:
            self._append(self._sent_path(path), body)
            self.status_counts[(path, "dry-run")] += 1
            return True
        try:
            r = self._now_session.post(f"{self.base_url}{path}", json=body, timeout=timeout)
            status = r.status_code
        except requests.RequestException:
            status = "network-error"
        self.status_counts[(path, status)] += 1
        n = self.status_counts[(path, status)]
        if not (isinstance(status, int) and 200 <= status < 300):
            if n in (1, 10) or n % 100 == 0:
                print(f"[전송 실패] POST {path} → {status} ({n}번째)")
            return False
        return True

    def send(self, message: dict, path: str = "/detections", meta=None, age_ms: float = 0.0):
        """큐에 넣는다. 꽉 차면 기본은 자리가 날 때까지 기다리고, drop_when_full이면 가장 오래된 것을 버린다.
        meta 는 서버로 보내지 않고, 끝났을 때 on_done 에 그대로 돌려준다.
        age_ms 는 큐에 넣기 전까지 이미 지난 시간 (카메라 수신 → 지금). max_age_ms 판단에 쓴다"""
        item = (path, message, meta, time.perf_counter(), age_ms)
        if not self.drop_when_full:
            self._queue.put(item)
            return
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            try:
                old = self._queue.get_nowait()
                self._queue.task_done()
                self.stats["dropped"] += 1
                self._done(old[2], "dropped", None, (time.perf_counter() - old[3]) * 1000)
            except queue.Empty:
                pass
            self._queue.put_nowait(item)

    @property
    def dropped_total(self) -> int:
        """버린 짝 전체 (큐가 꽉 차서 + 오래돼서). heartbeat 의 dropped_count"""
        return self.stats["dropped"] + self.stats["stale"]

    def pop_max_queue_age_ms(self) -> int:
        """마지막으로 부른 뒤 큐에서 가장 오래 기다린 시간(ms)을 주고 0으로 되돌린다. heartbeat 의 max_queue_age_ms"""
        with self._age_lock:
            value, self._max_queue_age_ms = self._max_queue_age_ms, 0.0
        return int(round(value))

    def _note_queue_age(self, queue_ms: float):
        with self._age_lock:
            self._max_queue_age_ms = max(self._max_queue_age_ms, queue_ms)

    def _done(self, meta, status, rtt_ms, queue_ms):
        if self.on_done is not None:
            try:
                self.on_done(meta, status, rtt_ms, queue_ms)
            except Exception as e:                 # 기록 실패로 전송 스레드가 죽지 않게
                print(f"[기록 오류] {e}")

    def close(self, wait: float | None = None):
        """남은 메시지를 다 보낼 때까지 기다린다 (wait초를 주면 그만큼만). 못 보낸 게 있으면 경고"""
        deadline = None if wait is None else time.time() + wait
        while self._queue.unfinished_tasks:
            if deadline is not None and time.time() > deadline:
                break
            time.sleep(0.05)
        left = self._queue.unfinished_tasks
        if left or self.stats["dropped"]:
            print(f"[경고] 서버로 보내지 못한 메시지: 남음 {left}건, 버림 {self.stats['dropped']}건")
        if self.stats["stale"]:
            print(f"[알림] 오래돼서({self.max_age_ms:.0f}ms 초과) 보내지 않은 짝: {self.stats['stale']}건")

    def summary(self) -> str:
        codes = ", ".join(f"{p} {c}: {n}건" for (p, c), n in sorted(self.status_counts.items(), key=str))
        return (f"전송 {self.stats['sent']} | 실패 {self.stats['failed']} | 버림 {self.stats['dropped']} "
                f"| 오래돼서 버림 {self.stats['stale']} | {codes}")

    def _append(self, path: Path, record: dict):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _sent_path(self, path: str) -> Path:
        return self.out_dir / f"sent_{path.strip('/').replace('/', '_')}.jsonl"

    def _worker(self):
        while True:
            path, message, meta, queued_at, age_ms = self._queue.get()
            queue_ms = (time.perf_counter() - queued_at) * 1000
            self._note_queue_age(queue_ms)
            rtt_ms, status = None, None
            try:
                if self.max_age_ms is not None and age_ms + queue_ms > self.max_age_ms:
                    status = "stale"                 # 보내 봐야 화면에 늦게 뜬다. 다음(더 최신) 짝을 보낸다
                    self.stats["stale"] += 1
                    self.status_counts[(path, "stale")] += 1
                    continue
                if self.dry_run:
                    status = "dry-run"
                    self._append(self._sent_path(path), message)
                    self.stats["sent"] += 1
                    self.status_counts[(path, "dry-run")] += 1
                    continue
                t0 = time.perf_counter()
                try:
                    r = self._session.post(f"{self.base_url}{path}", json=message, timeout=self.timeout)
                except requests.RequestException as e:
                    status, body = "network-error", str(e)
                else:
                    status, body = r.status_code, r.text
                rtt_ms = (time.perf_counter() - t0) * 1000
                if status != "network-error":
                    if r.ok:
                        self._append(self._sent_path(path), message)
                        if path == "/detections":   # 서버가 계산한 매칭·3D 좌표 (오차 측정용)
                            try:
                                self._append(self.out_dir / "responses_detections.jsonl", r.json())
                            except ValueError:
                                pass
                        self.stats["sent"] += 1
                        self.status_counts[(path, status)] += 1
                        continue
                # 실패: 상태 코드 + 응답 본문 + 보낸 메시지를 같이 남긴다
                self.stats["failed"] += 1
                self.status_counts[(path, status)] += 1
                try:
                    body = json.loads(body)
                except (TypeError, ValueError):
                    pass
                self._append(self.failed_path, {"path": path, "status": status, "response": body, "message": message})
                self.last_failure = (path, status, body)
                if self.status_counts[(path, status)] in (1, 10) or self.status_counts[(path, status)] % 100 == 0:
                    print(f"[전송 실패] {path} → {status} {str(body)[:200]}")
            finally:
                self._done(meta, status, rtt_ms, queue_ms)   # task_done 전에 불러야 close() 뒤에 기록이 빠지지 않는다
                self._queue.task_done()