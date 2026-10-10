"""헤드셋 출력 중재: 다른 무선이 말하면 현재 재생을 끊는다.

규칙
- 새 메시지(소대장 명령, 병사 보고 낭독 등)가 들어오면 우선순위를 비교한다.
  더 높거나 같은 등급의 '무선' 메시지면 지금 재생 중인 낮은 등급 재생(교범 답변, 시스템 안내)을
  중단하고 바로 재생. 중단된 항목은 다시 들을 수 있게 큐 앞에 되돌린다.
- 같은 등급의 무선끼리는 끊지 않고 순서대로(먼저 온 보고를 끝까지).
- 분대장 PTT를 누르면(barge-in) 재생을 즉시 멈추고, 떼면 이어서 재생.
  PTT 중에도 URGENT(본인 부상 등)는 재생한다(이어폰이라 마이크로 새지 않음).
"""
from __future__ import annotations

import heapq
import itertools
import threading
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Protocol


class Priority(IntEnum):
    SYSTEM = 0    # 교범 답변, 시스템 안내, 복창 확인
    REPORT = 1    # 병사 보고 낭독
    COMMAND = 2   # 소대장 명령
    URGENT = 3    # 본인 부상·긴급 보고


RADIO = frozenset({Priority.REPORT, Priority.COMMAND, Priority.URGENT})


@dataclass(order=True)
class Item:
    sort_key: tuple = field(init=False, repr=False)
    priority: Priority = field(compare=False)
    text: str = field(compare=False)
    source: str = field(default="", compare=False)
    audio: object = field(default=None, compare=False)   # TTS 결과(있으면)
    interrupted: bool = field(default=False, compare=False)


class Player(Protocol):
    def play(self, item: Item) -> None: ...   # 비동기 재생 시작, 끝나면 arbiter.on_finished() 호출
    def stop(self) -> None: ...


class AudioArbiter:
    def __init__(self, player: Player):
        self.player = player
        self.current: Item | None = None
        self.ptt = False
        self._queue: list[Item] = []
        self._seq = itertools.count()
        self._lock = threading.RLock()
        self.log: list[str] = []

    def _push(self, item: Item, front: bool = False) -> None:
        n = next(self._seq)
        item.sort_key = (-int(item.priority), -n if front else n)
        heapq.heappush(self._queue, item)

    def submit(self, item: Item) -> None:
        with self._lock:
            cur = self.current
            if self.ptt and item.priority < Priority.URGENT:
                self._push(item)
                return
            if cur is None:
                self._start(item)
            elif item.priority in RADIO and item.priority > cur.priority:
                self._interrupt(f"{item.source or item.priority.name} 수신")
                self._start(item)
            else:
                self._push(item)

    def _interrupt(self, reason: str) -> None:
        cur = self.current
        if cur is None:
            return
        self.player.stop()
        cur.interrupted = True
        self._push(cur, front=True)
        self.log.append(f"중단: {cur.text!r} ({reason})")
        self.current = None

    def _start(self, item: Item) -> None:
        self.current = item
        self.log.append(f"재생: {item.text!r}")
        self.player.play(item)

    def on_finished(self) -> None:
        with self._lock:
            self.current = None
            self._next()

    def _next(self) -> None:
        while self._queue and self.current is None:
            if self.ptt and self._queue[0].priority < Priority.URGENT:
                return
            self._start(heapq.heappop(self._queue))

    def ptt_down(self) -> None:
        with self._lock:
            self.ptt = True
            if self.current and self.current.priority < Priority.URGENT:
                self._interrupt("PTT")

    def ptt_up(self) -> None:
        with self._lock:
            self.ptt = False
            self._next()

    def pending(self) -> list[Item]:
        with self._lock:
            return sorted(self._queue)
