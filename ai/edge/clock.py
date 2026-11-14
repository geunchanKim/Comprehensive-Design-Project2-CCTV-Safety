"""
엣지 시각: 뒤로 가지 않는 epoch ms

시스템 시계(time.time)는 인터넷 시간 자동 보정으로 뒤로 갈 수 있다.
heartbeat의 sent_at_ms가 같은 실행 안에서 뒤로 가면 서버가 그 heartbeat를 무시하고,
3초 뒤 카메라가 멀쩡해도 online=false가 된다 (docs/specs/edge-heartbeat.md).

그래서 시작할 때 시스템 시각을 한 번만 읽고, 그 뒤로는 monotonic 경과 시간을 더한다.
값은 epoch ms라 기존 recv_ms와 같은 단위로 쓸 수 있다.
"""

import time


class EdgeClock:
    def __init__(self) -> None:
        self._base_epoch_ms = time.time() * 1000
        self._base_mono = time.monotonic()

    def now_ms(self) -> int:
        return int(self._base_epoch_ms + (time.monotonic() - self._base_mono) * 1000)


_CLOCK = EdgeClock()


def now_ms() -> int:
    """엣지 실행 전체에서 같은 기준으로 쓰는 현재 시각 (epoch ms, 뒤로 가지 않음)."""
    return _CLOCK.now_ms()
