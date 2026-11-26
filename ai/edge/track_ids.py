"""추적 번호 정리 (torch 없이 불러올 수 있게 detector.py에서 분리)"""


class ClassStableIds:
    """추적 번호 하나가 한 클래스만 갖게 한다.

    ByteTrack은 클래스와 상관없이 상자를 이어 붙여서, 같은 번호가 사람이었다가 의자가 되기도 한다
    (11/25 복도 s41: cam1 2번이 사람 → 의자). 서버는 두 카메라 번호 짝을 클래스와 함께 기억하는데
    중복 검사는 클래스를 보지 않아서, 이런 번호가 오면 409로 그 묶음을 거절한다.
    처음 본 클래스는 원래 번호를 그대로 쓰고, 다른 클래스로 바뀌면 그 (번호, 클래스)에 새 번호를 준다.
    """
    SPLIT_BASE = 1_000_000          # 원래 번호(수천 이하)와 겹치지 않는 시작값

    def __init__(self):
        self._first_cls: dict[int, str] = {}
        self._split: dict[tuple[int, str], int] = {}
        self._next = self.SPLIT_BASE

    def __call__(self, track_id: int | None, cls: str) -> int | None:
        if track_id is None:
            return None
        if self._first_cls.setdefault(track_id, cls) == cls:
            return track_id
        key = (track_id, cls)
        if key not in self._split:
            self._split[key] = self._next
            self._next += 1
        return self._split[key]
