"""분대장 송신 seq (§4, 병사 팀 안내문 P1).

운용: 부팅마다 무작위로 시작해 프레임마다 +1(0~255 순환). 재전송은 새 seq를 받지 않고 같은 바이트를 다시 쓴다.
시험: start를 주면 그 값부터(`--seq-start N`) — mock_leader(0부터) 로그와 hex를 그대로 비교하기 위해.
"""
from __future__ import annotations

import random


class LeaderSeq:
    def __init__(self, start: int | None = None):
        self.value = random.SystemRandom().randrange(256) if start is None else start & 0xFF

    def next(self) -> int:
        s = self.value
        self.value = (self.value + 1) & 0xFF
        return s
