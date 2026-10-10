"""헤드셋 출력 플레이어 (AudioArbiter의 Player 구현).

Item.audio: 16kHz float32 배열, 또는 배열 조각을 차례로 내놓는 함수(스트리밍 합성).
재생 끝 시점은 보낸 오디오 길이로 계산한다(맥이 받은 순서대로 이어서 재생).
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Iterable

import numpy as np

from .arbiter import Item
from .fmt import float_to_s16

SR = 16000


def _chunks(audio) -> Iterable[np.ndarray]:
    if audio is None:
        return []
    if callable(audio):
        return audio()
    return [audio]


class _BasePlayer:
    def __init__(self):
        self.on_finished: Callable[[], None] = lambda: None
        self._gen = 0
        self._lock = threading.Lock()

    def bind(self, arbiter) -> None:
        self.on_finished = arbiter.on_finished

    def play(self, item: Item) -> None:
        with self._lock:
            self._gen += 1
            gen = self._gen
        threading.Thread(target=self._run, args=(item, gen), daemon=True).start()

    def stop(self) -> None:
        with self._lock:
            self._gen += 1
        self._stop_output()

    def _alive(self, gen: int) -> bool:
        return gen == self._gen

    def _run(self, item: Item, gen: int) -> None:
        end = time.monotonic()
        for chunk in _chunks(item.audio):
            if not self._alive(gen):
                return
            end = max(end, time.monotonic()) + len(chunk) / SR
            self._emit(chunk)
        while time.monotonic() < end:
            if not self._alive(gen):
                return
            time.sleep(0.02)
        if self._alive(gen):
            self.on_finished()

    def _emit(self, chunk: np.ndarray) -> None:
        raise NotImplementedError

    def _stop_output(self) -> None:
        pass


class RemotePlayer(_BasePlayer):
    """맥(에어팟)으로 보내 재생. 맥이 안 붙어 있으면 버리고 로그만 남긴다."""

    def __init__(self, server, log: Callable[[str], None] = print):
        super().__init__()
        self.server = server
        self.log = log

    def _emit(self, chunk: np.ndarray) -> None:
        if not self.server.send_audio(float_to_s16(chunk).tobytes(), SR):
            self.log("헤드셋 미연결: 재생 못 함")

    def _stop_output(self) -> None:
        self.server.send_stop()


class RecordingPlayer(_BasePlayer):
    """시험용: 실제 재생 대신 버퍼에 모은다. realtime=False면 즉시 끝난 것으로 처리."""

    def __init__(self, realtime: bool = False):
        super().__init__()
        self.realtime = realtime
        self.played: list[tuple[str, np.ndarray]] = []
        self._cur: list[np.ndarray] = []

    def _run(self, item: Item, gen: int) -> None:
        if self.realtime:
            self._cur = []
            super()._run(item, gen)
            self.played.append((item.text, np.concatenate(self._cur) if self._cur else np.zeros(0)))
            return
        audio = np.concatenate(list(_chunks(item.audio)) or [np.zeros(0, np.float32)])
        if self._alive(gen):
            self.played.append((item.text, audio))
            self.on_finished()

    def _emit(self, chunk: np.ndarray) -> None:
        self._cur.append(chunk)
