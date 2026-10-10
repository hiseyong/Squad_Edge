"""음성 하달 준비: PCM → 8 kHz 모노 int16 → IMA ADPCM → VOICE_BEGIN/CHUNK/END 프레임 (§7).

포팅 원본: ~/work/soldier-node_ref_v1.1/tools/mock_leader.py (load_wav_8k, Leader.stream_voice의 프레임 구성)
- 전처리는 원본과 같다: 모노 합성(정수 평균) → 선형 보간 8 kHz → 앞뒤 무음 제거(최대값 2% 문턱, 앞뒤 50 ms 여유)
  → 최대 10초 → 최대 −3 dBFS(0.7079) 정규화. 같은 입력이면 원본과 같은 샘플·바이트가 나온다.
- 추가: TTS 출력(float32 numpy, −1~1)을 받는 from_float().
- 쓰기 방식: BEGIN·END는 Write With Response, CHUNK는 Without Response(간격 15 ms) — 보내는 쪽(leader)이 지킨다.
"""
from __future__ import annotations

import array
import sys
import wave
from dataclasses import dataclass

from . import codec as fc
from . import config
from .adpcm import crc16, encode


def read_wav(path) -> tuple[list[int], int]:
    """8/16비트 PCM WAV → (모노 int16 목록, 샘플레이트). 다채널은 정수 평균."""
    with wave.open(str(path), "rb") as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        a = array.array("h")
        a.frombytes(raw)
        if sys.byteorder == "big":
            a.byteswap()
        x = list(a)
    elif sw == 1:
        x = [(b - 128) << 8 for b in raw]
    else:
        raise ValueError(f"{sw * 8}비트 WAV는 지원하지 않음(8/16비트 PCM만)")
    if ch > 1:
        x = [sum(x[i:i + ch]) // ch for i in range(0, len(x), ch)]
    return x, rate


def from_float(samples) -> list[int]:
    """float(−1~1) → int16 목록(TTS 출력용)."""
    return [max(-32768, min(32767, int(round(float(v) * 32767)))) for v in samples]


def prepare_8k(x: list[int], rate: int, max_s: float = config.VOICE_MAX_S) -> list[int]:
    """모노 int16 → 8 kHz, 무음 제거, 최대 max_s초, −3 dBFS 정규화 (원본 load_wav_8k와 같은 계산)."""
    if rate != 8000:  # 선형 보간 리샘플
        m = int(len(x) * 8000 / rate)
        step = rate / 8000
        x = [int(x[min(int(i * step), len(x) - 1)] + (x[min(int(i * step) + 1, len(x) - 1)]
                                                       - x[min(int(i * step), len(x) - 1)]) * ((i * step) % 1))
             for i in range(m)]
    peak = max((abs(v) for v in x), default=0)
    if peak == 0:
        raise ValueError("무음")
    thr = peak * 0.02
    first = next(i for i, v in enumerate(x) if abs(v) > thr)
    last = len(x) - next(i for i, v in enumerate(reversed(x)) if abs(v) > thr)
    x = x[max(0, first - 400):min(len(x), last + 400)]  # 앞뒤 50ms 여유
    x = x[:int(max_s * 8000)]
    g = 0.7079 * 32767 / max(abs(v) for v in x)
    return [max(-32768, min(32767, int(v * g))) for v in x]


def load_wav_8k(path, max_s: float = config.VOICE_MAX_S) -> list[int]:
    x, rate = read_wav(path)
    return prepare_8k(x, rate, max_s)


@dataclass
class VoiceClip:
    """한 번 인코딩해 두고 병사마다(MTU별 청크) 같은 voice_id로 보낸다. 재전송도 같은 내용."""
    voice_id: int
    data: bytes          # ADPCM 전체
    nsamples: int
    priority: int = 0

    @property
    def crc(self) -> int:
        return crc16(self.data)

    @classmethod
    def from_pcm8k(cls, voice_id: int, samples: list[int], priority: int = 0) -> "VoiceClip":
        data, _ = encode(samples, 0, 0)       # 레퍼런스 인코더는 predictor 0, step_index 0에서 시작
        return cls(voice_id & 0xFF, data, len(samples), priority)


def chunk_size(mtu: int) -> int:
    """§7.2: N = (MTU − 3) − 헤더 6 − 3. MTU 247이면 235."""
    return (mtu - 3) - fc.HDR_LEN - 3


def voice_frames(clip: VoiceClip, mtu: int, dst: int, next_seq) -> list[tuple[bytes, bool]]:
    """[(프레임, response)] — BEGIN(True), CHUNK…(False), END(True). next_seq()는 프레임마다 새 seq."""
    n = chunk_size(mtu)
    if n <= 0:
        raise ValueError(f"MTU {mtu}로는 음성을 보낼 수 없음")
    chunks = [clip.data[i:i + n] for i in range(0, len(clip.data), n)]
    base = dict(src=fc.LEADER_ID, dst=dst)
    out = [(fc.encode(dict(base, type=fc.VOICE_BEGIN, seq=next_seq(), voice_id=clip.voice_id, codec=1,
                           sample_rate=8000, total_samples=clip.nsamples, total_chunks=len(chunks),
                           predictor=0, step_index=0, priority=clip.priority)), True)]
    for i, c in enumerate(chunks):
        out.append((fc.encode(dict(base, type=fc.VOICE_CHUNK, seq=next_seq(), voice_id=clip.voice_id,
                                   chunk_idx=i, data=c)), False))
    out.append((fc.encode(dict(base, type=fc.VOICE_END, seq=next_seq(), voice_id=clip.voice_id, crc16=clip.crc)), True))
    return out
