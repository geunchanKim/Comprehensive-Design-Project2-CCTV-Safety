"""
엣지 → 서버 전송기

묶음 메시지를 백그라운드 스레드에서 서버 POST /detections 로 보낸다.
탐지 루프가 네트워크 때문에 멈추지 않게 큐에 넣고 바로 돌아온다.

- dry_run: 서버 없이 JSONL 파일에 저장만 한다 (서버 준비 전 테스트용)
- 전송 실패한 메시지는 failed.jsonl 에 모아 두고 나중에 다시 보낼 수 있다
"""

import json
import queue
import threading
import time
from pathlib import Path

import requests


class ServerClient:
    def __init__(self, base_url: str | None, out_dir: Path, dry_run: bool = False,
                 timeout: float = 2.0, max_queue: int = 300):
        if not dry_run and not base_url:
            raise ValueError("서버 주소(--server)가 없으면 --dry-run 으로 실행하세요")
        self.base_url = base_url.rstrip("/") if base_url else None
        self.dry_run = dry_run
        self.timeout = timeout
        out_dir.mkdir(parents=True, exist_ok=True)
        self.sent_path = out_dir / "sent.jsonl"        # 보낸(또는 dry-run으로 저장한) 메시지
        self.failed_path = out_dir / "failed.jsonl"    # 전송 실패한 메시지
        self.stats = {"sent": 0, "failed": 0, "dropped": 0}

        self._queue: queue.Queue = queue.Queue(maxsize=max_queue)
        self._session = requests.Session()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def check_server(self) -> bool:
        if self.dry_run:
            return True
        try:
            r = self._session.get(f"{self.base_url}/health", timeout=self.timeout)
            return r.ok
        except requests.RequestException:
            return False

    def send(self, message: dict):
        """큐에 넣고 바로 돌아온다. 큐가 꽉 차면 가장 오래된 메시지를 버린다."""
        try:
            self._queue.put_nowait(message)
        except queue.Full:
            try:
                self._queue.get_nowait()
                self.stats["dropped"] += 1
            except queue.Empty:
                pass
            self._queue.put_nowait(message)

    def close(self, wait: float = 5.0):
        """남은 메시지를 최대 wait초 동안 보내고 종료"""
        deadline = time.time() + wait
        while not self._queue.empty() and time.time() < deadline:
            time.sleep(0.05)

    def _append(self, path: Path, message: dict):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(message, ensure_ascii=False) + "\n")

    def _worker(self):
        while True:
            message = self._queue.get()
            if self.dry_run:
                self._append(self.sent_path, message)
                self.stats["sent"] += 1
                continue
            try:
                r = self._session.post(f"{self.base_url}/detections", json=message, timeout=self.timeout)
                r.raise_for_status()
                self._append(self.sent_path, message)
                self.stats["sent"] += 1
            except requests.RequestException as e:
                self._append(self.failed_path, message)
                self.stats["failed"] += 1
                if self.stats["failed"] in (1, 10) or self.stats["failed"] % 100 == 0:
                    print(f"[서버 전송 실패 {self.stats['failed']}건] {e}")