"""분대장 헤드셋 입출력: 맥 브리지(에어팟/맥북 마이크) 수신 + PTT 음성 인식 + TTS 재생(우선순위 중재).

  마이크: 맥 tools/mac_mic_sender.py → adb forward tcp:7100 → MicStreamServer(127.0.0.1:7100)
  인식:   PTT 누르는 동안 ZipformerSession.feed (preroll 0.2초), 떼면 finish → 정규화 텍스트
  재생:   Synth(16kHz) → AudioArbiter(우선순위·끼어들기, PTT 중 재생 멈춤) → RemotePlayer(같은 연결로 맥에 PCM)
맥이 안 붙어 있으면 재생은 로그만 남기고, 인식은 빈 결과를 낸다.
"""
from __future__ import annotations

import asyncio
import logging
import time

from ..audio.arbiter import AudioArbiter, Item, Priority
from ..audio.output import RemotePlayer
from ..audio.stream import MicStreamServer
from .tts import Synth
from .verbalize import verbalize

log = logging.getLogger("headset")

URGENCY = {"urgent": Priority.URGENT, "command": Priority.COMMAND, "report": Priority.REPORT, "system": Priority.SYSTEM}


class Headset:
    def __init__(self, port: int = 7100, stt=None):
        self.mic = MicStreamServer(port=port)
        self.synth = Synth()
        self.player = RemotePlayer(self.mic, log=lambda m: log.debug(m))
        self.arbiter = AudioArbiter(self.player)
        self.player.bind(self.arbiter)
        self.stt = stt                      # ZipformerStt (start()에서 읽음)
        self._session = None
        self._t_down = 0.0

    async def start(self, load_stt: bool = True) -> None:
        asyncio.get_running_loop().create_task(self.mic.serve())
        await asyncio.sleep(0)
        if load_stt and self.stt is None:
            from .stt import ZipformerStt
            t = time.monotonic()
            self.stt = await asyncio.to_thread(ZipformerStt)
            log.info("STT(Zipformer) 준비 %.0f초", time.monotonic() - t)

    @property
    def connected(self) -> bool:
        return self.mic.connected.is_set() and self.mic.can_play()

    # ---- 재생 ----
    def say(self, text: str, urgency: str = "system", repeat: int = 1, source: str = "") -> None:
        spoken = verbalize(text)
        for _ in range(repeat):
            self.arbiter.submit(Item(URGENCY.get(urgency, Priority.SYSTEM), text, source,
                                     audio=lambda s=spoken: [self.synth(s)]))

    def say_long(self, text: str, urgency: str = "system", source: str = "") -> None:
        """교범 답변 같은 긴 글: 문장 단위로 합성하며 재생(첫 문장 지연만)."""
        self.arbiter.submit(Item(URGENCY.get(urgency, Priority.SYSTEM), text, source,
                                 audio=lambda: self.synth.stream(text)))

    def warm(self, texts: list[str]) -> None:
        for t in texts:
            self.synth(verbalize(t))

    # ---- PTT ----
    def ptt_down(self) -> bool:
        self.arbiter.ptt_down()
        if self.stt is None or not self.mic.connected.is_set():
            return False
        self._session = self.stt.session()
        self._t_down = time.monotonic()
        self.mic.ptt_down(preroll_s=0.2, sink=self._session.feed)
        return True

    async def ptt_up(self):
        """→ SttResult 또는 None(마이크 없음·너무 짧음)."""
        self.mic.ptt_up()
        s, self._session = self._session, None
        held = time.monotonic() - self._t_down
        self.arbiter.ptt_up()
        if s is None:
            return None
        r = await asyncio.to_thread(s.finish)
        log.info("STT %.1f초 발화, 뗀 뒤 %.2f초: %s", held, r.elapsed_s, r.text)
        return r if r.text.strip() else None
