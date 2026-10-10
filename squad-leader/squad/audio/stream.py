"""맥 → 보드 마이크 스트림 수신기 (에어팟 → 맥 → USB adb 포워딩 → 보드).

연결 방식: 맥에서 `adb forward tcp:7100 tcp:7100` 후 맥 송신기가 localhost:7100으로 접속.
보드는 127.0.0.1에만 바인드한다(대회 Wi-Fi 등 외부망에 노출하지 않음).

와이어 형식 (초안, 보드-맥 로컬 전용):
  맥 → 보드: 1) 헤더 한 줄 JSON + '\\n': {"v":1, "sr":24000, "ch":1, "fmt":"s16le", "device":"AirPods Pro"}
             2) 이후 raw PCM 연속 전송 (헤더의 형식 그대로)
  보드 → 맥 (같은 연결, 헤드셋 재생용):
             b"A" + uint32 sr + uint32 nbytes + s16le 모노 PCM   → 재생 큐에 추가
             b"S"                                              → 재생 즉시 중단·큐 비움
"""
from __future__ import annotations

import asyncio
import json
import logging
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass

import numpy as np

from .fmt import pcm_to_float, to_mono

log = logging.getLogger(__name__)

DEFAULT_PORT = 7100


@dataclass
class StreamInfo:
    sr: int
    channels: int
    fmt: str
    device: str = ""


class MicStreamServer:
    """원본 샘플레이트 그대로 최근 buffer_s초를 링버퍼에 보관하고, PTT 구간을 잘라 준다."""

    def __init__(self, host: str = "127.0.0.1", port: int = DEFAULT_PORT, buffer_s: float = 30.0):
        self.host, self.port, self.buffer_s = host, port, buffer_s
        self.info: StreamInfo | None = None
        self.connected = asyncio.Event()
        self._chunks: deque[np.ndarray] = deque()
        self._buffered = 0
        self._total = 0              # 연결 후 누적 샘플 수 (PTT 위치 계산용)
        self._ptt_start: int | None = None
        self._sink = None            # PTT 동안 새 오디오를 실시간으로 받을 함수 (스트리밍 STT)
        self._lock = threading.Lock()
        self.level_dbfs = -120.0
        self.last_rx = 0.0
        self._writer: asyncio.StreamWriter | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def serve(self) -> None:
        server = await asyncio.start_server(self._handle, self.host, self.port)
        log.info("mic stream listening on %s:%d", self.host, self.port)
        async with server:
            await server.serve_forever()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        try:
            hdr = json.loads((await reader.readline()).decode())
            if hdr.get("v") != 1:
                raise ValueError(f"unsupported header version: {hdr}")
            info = StreamInfo(int(hdr["sr"]), int(hdr["ch"]), hdr.get("fmt", "s16le"), hdr.get("device", ""))
        except Exception as e:  # noqa: BLE001
            log.warning("bad stream header from %s: %s", peer, e)
            writer.close()
            return
        with self._lock:
            self.info = info
            self._chunks.clear()
            self._buffered = self._total = 0
            self._ptt_start = None
        log.info("mic connected from %s: %s", peer, info)
        self._writer, self._loop = writer, asyncio.get_running_loop()
        self.connected.set()
        width = {"s16le": 2, "s32le": 4, "f32le": 4}[info.fmt] * info.channels
        pending = b""
        try:
            while data := await reader.read(4096):
                pending += data
                usable = len(pending) - len(pending) % width
                if not usable:
                    continue
                mono = to_mono(pcm_to_float(pending[:usable], info.fmt, info.channels))
                pending = pending[usable:]
                self._push(mono)
        finally:
            log.info("mic disconnected")
            self.connected.clear()
            if self._writer is writer:
                self._writer = None
            writer.close()

    def _push(self, mono: np.ndarray) -> None:
        with self._lock:
            self._chunks.append(mono)
            self._buffered += len(mono)
            self._total += len(mono)
            limit = int(self.buffer_s * self.info.sr)
            while self._buffered - len(self._chunks[0]) > limit and self._ptt_start is None:
                self._buffered -= len(self._chunks.popleft())
            sink, sr = self._sink, self.info.sr
        if sink is not None:
            sink(mono, sr)
        self.level_dbfs = 20 * np.log10(np.sqrt(np.mean(mono.astype(np.float64) ** 2)) + 1e-12)
        self.last_rx = time.monotonic()

    def _buffer(self) -> tuple[np.ndarray, int]:
        """(버퍼 전체, 버퍼 첫 샘플의 누적 위치)."""
        data = np.concatenate(self._chunks) if self._chunks else np.zeros(0, np.float32)
        return data, self._total - len(data)

    # ---- 헤드셋 출력 (보드 → 맥) ----

    def _send(self, data: bytes) -> bool:
        w, loop = self._writer, self._loop
        if w is None or loop is None:
            return False
        loop.call_soon_threadsafe(w.write, data)
        return True

    def send_audio(self, pcm16: bytes, sr: int) -> bool:
        """다른 스레드에서 호출 가능. 맥이 연결되어 있지 않으면 False."""
        return self._send(b"A" + struct.pack("<II", sr, len(pcm16)) + pcm16)

    def send_stop(self) -> bool:
        return self._send(b"S")

    @property
    def can_play(self) -> bool:
        return self._writer is not None

    # ---- PTT ----

    def ptt_down(self, preroll_s: float = 0.2, sink=None) -> None:
        """PTT 누름. 말머리가 잘리지 않게 preroll만큼 앞에서부터 잡는다.
        sink(mono_float32, sr)를 주면 preroll부터 PTT를 뗄 때까지 들어오는 오디오를 실시간으로 넘긴다."""
        with self._lock:
            sr = self.info.sr if self.info else 16000
            self._ptt_start = max(0, self._total - int(preroll_s * sr))
            if sink is not None and self.info is not None:
                data, base = self._buffer()
                pre = data[max(0, self._ptt_start - base):]
                if len(pre):
                    sink(pre.copy(), sr)
            self._sink = sink

    def ptt_up(self) -> tuple[np.ndarray, int]:
        """PTT 뗌 → (원본 샘플레이트 모노 float32, sr)."""
        with self._lock:
            start, self._ptt_start = self._ptt_start, None
            self._sink = None
            if start is None or self.info is None:
                return np.zeros(0, np.float32), 16000
            data, base = self._buffer()
            return data[max(0, start - base):].copy(), self.info.sr

    def last(self, seconds: float) -> tuple[np.ndarray, int]:
        with self._lock:
            if self.info is None:
                return np.zeros(0, np.float32), 16000
            data, _ = self._buffer()
            return data[-int(seconds * self.info.sr):].copy(), self.info.sr
