"""
전역 Clock 추상화.

프로덕션 사용:
    from core import clock
    now = clock.now()

테스트 사용:
    with clock.freeze_time(datetime(2027, 1, 2)):
        ...

[중요] MySQL NOW() 사용 금지
----------------------------
배치/시간 의존 쿼리에서 MySQL NOW(), CURRENT_TIMESTAMP, NOW() - INTERVAL 사용 금지.
반드시 Python clock.now()에서 cutoff를 계산해 파라미터로 전달할 것.
MySQL NOW()는 DB 서버 실시간을 반환하므로 freeze_time()으로 얼릴 수 없어
테스트가 통과해도 실제 배치는 다른 시간으로 동작할 위험이 있음.
"""
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))


class Clock:
    def now(self) -> datetime:
        return datetime.now(KST)


class FrozenClock(Clock):
    def __init__(self, fixed: datetime):
        if fixed.tzinfo is None:
            fixed = fixed.replace(tzinfo=KST)
        self.fixed = fixed

    def now(self) -> datetime:
        return self.fixed

    def advance(self, delta: timedelta) -> None:
        self.fixed += delta


_clock: Clock = Clock()


def now() -> datetime:
    return _clock.now()


@contextmanager
def freeze_time(fixed: datetime):
    global _clock
    prev = _clock
    _clock = FrozenClock(fixed)
    try:
        yield _clock
    finally:
        _clock = prev
