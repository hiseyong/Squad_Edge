"""발화 단위 전처리 파이프라인: 포맷 통일 → 임펄스 억제 → 고역통과 → 노이즈 제거 → AGC."""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from . import dsp
from .fmt import TARGET_SR, dbfs, to_16k_mono


@dataclass
class PreprocessConfig:
    impulse: bool = True
    highpass_hz: float | None = 100.0
    denoise: bool = True
    denoise_floor_db: float = -15.0
    agc: bool = True
    agc_target_dbfs: float = -20.0
    trim: bool = False


@dataclass
class PreprocessResult:
    audio: np.ndarray                     # 16kHz 모노 float32
    sr: int = TARGET_SR
    input_sr: int = 0
    impulses: list[dsp.ImpulseEvent] = field(default_factory=list)
    speech_ratio: float = 0.0
    level_in_dbfs: float = 0.0
    level_out_dbfs: float = 0.0
    elapsed_ms: float = 0.0


def preprocess(x: np.ndarray, sr: int, cfg: PreprocessConfig | None = None) -> PreprocessResult:
    cfg = cfg or PreprocessConfig()
    t0 = time.perf_counter()
    y = to_16k_mono(x, sr)
    res = PreprocessResult(audio=y, input_sr=sr, level_in_dbfs=dbfs(y))
    if len(y) == 0:
        return res
    if cfg.impulse:
        y, res.impulses = dsp.suppress_impulses(y, TARGET_SR)
    if cfg.highpass_hz:
        y = dsp.highpass(y, TARGET_SR, cfg.highpass_hz)
    mask = dsp.vad_samples(y, TARGET_SR)
    if cfg.denoise:
        y = dsp.spectral_denoise(y, TARGET_SR, speech_mask=mask, floor_db=cfg.denoise_floor_db)
        mask = dsp.vad_samples(y, TARGET_SR)
    if cfg.agc:
        y = dsp.agc(y, TARGET_SR, speech_mask=mask, target_dbfs=cfg.agc_target_dbfs)
    if cfg.trim:
        y = dsp.trim_silence(y, TARGET_SR)
    res.audio = y
    res.speech_ratio = float(mask.mean()) if len(mask) else 0.0
    res.level_out_dbfs = dbfs(y)
    res.elapsed_ms = (time.perf_counter() - t0) * 1000
    return res


class StreamPreprocessor:
    """실시간(PTT 중) 전처리: 같은 preprocess()를 겹치는 창으로 돌려 조각씩 내보낸다.

    preprocess()는 발화 전체용이다 (양방향 필터, 구간 백분위로 잡음·배경 추정). 그래서
    [앞 맥락 ctx_s | 새 블록 block_s | 뒤 여유 look_s] 창을 처리하고 가운데 블록만 내보낸다.
    → 앞 맥락으로 잡음·음량 통계를 잡고, 뒤 여유로 필터 가장자리 왜곡을 피한다.
    지연: 블록 + 뒤 여유 (기본 0.75초)만큼 늦게 나오지만, PTT를 뗄 때 flush()로 남은 것을 바로 처리한다.
    입력은 16kHz 모노 float32.
    """

    def __init__(self, cfg: PreprocessConfig | None = None, block_s: float = 0.5, ctx_s: float = 1.5,
                 look_s: float = 0.25):
        self.cfg = cfg or PreprocessConfig()
        self.block, self.ctx, self.look = (int(s * TARGET_SR) for s in (block_s, ctx_s, look_s))
        self.buf = np.zeros(0, np.float32)
        self.done = 0                     # buf 안에서 이미 내보낸 위치
        self.impulses = 0

    def _run(self, end: int, final: bool) -> np.ndarray:
        start = max(0, self.done - self.ctx)
        stop = len(self.buf) if final else min(len(self.buf), end + self.look)
        res = preprocess(self.buf[start:stop], TARGET_SR, self.cfg)
        self.impulses += sum(1 for e in res.impulses if e.start_s * TARGET_SR >= self.done - start)
        out = res.audio[self.done - start:end - start]
        self.done = end
        # 맥락으로 쓸 만큼만 남기고 버퍼를 줄인다
        cut = max(0, self.done - self.ctx)
        if cut:
            self.buf, self.done = self.buf[cut:], self.done - cut
        return out

    def feed(self, x: np.ndarray) -> np.ndarray:
        self.buf = np.concatenate([self.buf, np.asarray(x, np.float32)])
        outs = []
        while len(self.buf) - self.done >= self.block + self.look:
            outs.append(self._run(self.done + self.block, final=False))
        return np.concatenate(outs) if outs else np.zeros(0, np.float32)

    def flush(self) -> np.ndarray:
        if len(self.buf) <= self.done:
            return np.zeros(0, np.float32)
        return self._run(len(self.buf), final=True)
