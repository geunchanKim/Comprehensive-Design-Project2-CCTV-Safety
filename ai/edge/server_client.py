"""
엣지 → 서버 전송기

메시지를 백그라운드 스레드에서 서버로 보낸다 (POST /detections, POST /ground-truth 등).
탐지 루프가 네트워크 때문에 멈추지 않게 큐에 넣고 바로 돌아온다.

- dry_run: 서버 없이 파일에 저장만 한다 (서버 준비 전 테스트용)
- 보낸 메시지: sent_<경로>.jsonl  (예: sent_detections.jsonl, sent_ground-truth.jsonl)
- 실패한 메시지: failed.jsonl — HTTP 상태 코드와 서버 응답 본문을 같이 저장 (BE 공유용)
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
                 timeout: float = 5.0, max_queue: int = 300):
        if not dry_run and not base_url:
            raise ValueError("서버 주소(--server)가 없으면 --dry-run 으로 실행하세요")
        self.base_url = base_url.rstrip("/") if base_url else None
        self.dry_run = dry_run
        self.timeout = timeout
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        self.failed_path = out_dir / "failed.jsonl"
        self.stats = {"sent": 0, "failed": 0, "dropped": 0}
        self.status_counts: Counter = Counter()      # (경로, 상태 코드) → 개수

        self._queue: queue.Queue = queue.Queue(maxsize=max_queue)
        self._busy = False
        self._session = requests.Session()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def check_server(self) -> bool:
        if self.dry_run:
            return True
        try:
            return self._session.get(f"{self.base_url}/health", timeout=self.timeout).ok
        except requests.RequestException:
            return False

    def send(self, message: dict, path: str = "/detections"):
        """큐에 넣고 바로 돌아온다. 큐가 꽉 차면 가장 오래된 메시지를 버린다."""
        item = (path, message)
        try:
            self._queue.put_nowait(item)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self.stats["dropped"] += 1
            except queue.Empty:
                pass
            self._queue.put_nowait(item)

    def close(self, wait: float = 30.0):
        """남은 메시지를 최대 wait초 동안 보내고 끝낸다"""
        deadline = time.time() + wait
        while (not self._queue.empty() or self._busy) and time.time() < deadline:
            time.sleep(0.05)

    def summary(self) -> str:
        codes = ", ".join(f"{p} {c}: {n}건" for (p, c), n in sorted(self.status_counts.items(), key=str))
        return f"전송 {self.stats['sent']} | 실패 {self.stats['failed']} | 버림 {self.stats['dropped']} | {codes}"

    def _append(self, path: Path, record: dict):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _sent_path(self, path: str) -> Path:
        return self.out_dir / f"sent_{path.strip('/').replace('/', '_')}.jsonl"

    def _worker(self):
        while True:
            path, message = self._queue.get()
            self._busy = True
            try:
                if self.dry_run:
                    self._append(self._sent_path(path), message)
                    self.stats["sent"] += 1
                    self.status_counts[(path, "dry-run")] += 1
                    continue
                try:
                    r = self._session.post(f"{self.base_url}{path}", json=message, timeout=self.timeout)
                except requests.RequestException as e:
                    status, body = "network-error", str(e)
                else:
                    status, body = r.status_code, r.text
                    if r.ok:
                        self._append(self._sent_path(path), message)
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
                if self.status_counts[(path, status)] in (1, 10) or self.status_counts[(path, status)] % 100 == 0:
                    print(f"[전송 실패] {path} → {status} {str(body)[:200]}")
            finally:
                self._busy = False