"""오프라인 한국어 TTS (sherpa-onnx VITS, mimic3 ko_KO-kss).

보드(QRB2210, 4스레드)에서 실시간의 약 0.7배 속도라 짧은 문장도 2초 가까이 걸린다. 그래서
- 병사 보고처럼 정해진 문장은 조각("3번", "두 시 방향" 등)을 미리 합성해 디스크에 캐시하고 이어 붙인다.
- 상급 부대 텍스트는 문장 단위로 합성해 첫 문장부터 바로 재생한다(stream()).
"""
from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Callable, Iterator

import numpy as np

from ..audio.fmt import resample
from .verbalize import split_sentences, verbalize

ROOT = Path(__file__).resolve().parents[2]
MODEL_DIR = ROOT / "models" / "tts" / "vits-mimic3-ko_KO-kss_low"
CACHE_DIR = ROOT / "models" / "tts" / "cache"
OUT_SR = 16000          # 에어팟 HFP와 맞춘 출력 샘플레이트
GAP_S = 0.12            # 조각 사이 쉼


class Synth:
    """텍스트 → 16kHz float32. 메모리 LRU + 디스크 캐시."""

    def __init__(self, model_dir: Path = MODEL_DIR, threads: int = 4, speed: float = 1.1,
                 cache_dir: Path | None = CACHE_DIR, backend: Callable[[str], tuple[np.ndarray, int]] | None = None):
        self.model_dir, self.threads, self.speed = model_dir, threads, speed
        self.cache_dir = cache_dir
        self._backend = backend
        self._tts = None
        self._lock = threading.Lock()
        self._mem: OrderedDict[str, np.ndarray] = OrderedDict()
        if cache_dir:
            cache_dir.mkdir(parents=True, exist_ok=True)

    def _load(self):
        import sherpa_onnx

        m = self.model_dir
        cfg = sherpa_onnx.OfflineTtsConfig(model=sherpa_onnx.OfflineTtsModelConfig(
            vits=sherpa_onnx.OfflineTtsVitsModelConfig(model=str(m / "ko_KO-kss_low.onnx"),
                                                       tokens=str(m / "tokens.txt"),
                                                       data_dir=str(m / "espeak-ng-data")),
            num_threads=self.threads))
        self._tts = sherpa_onnx.OfflineTts(cfg)

    def _raw(self, text: str) -> np.ndarray:
        if self._backend:
            x, sr = self._backend(text)
        else:
            if self._tts is None:
                self._load()
            a = self._tts.generate(text, sid=0, speed=self.speed)
            x, sr = np.asarray(a.samples, dtype=np.float32), a.sample_rate
        return resample(np.asarray(x, dtype=np.float32), sr, OUT_SR)

    def _key(self, text: str) -> str:
        return hashlib.sha1(f"{self.model_dir.name}|{self.speed}|{text}".encode()).hexdigest()[:16]

    def __call__(self, text: str, cache: bool = True) -> np.ndarray:
        """이미 읽기 변환된 텍스트를 합성."""
        key = self._key(text)
        if key in self._mem:
            self._mem.move_to_end(key)
            return self._mem[key]
        path = self.cache_dir / f"{key}.npy" if (self.cache_dir and cache) else None
        if path and path.exists():
            x = np.load(path)
        else:
            with self._lock:  # sherpa-onnx 인스턴스는 한 번에 하나만
                x = self._raw(text)
            if path:
                np.save(path, x)
        self._mem[key] = x
        if len(self._mem) > 256:
            self._mem.popitem(last=False)
        return x

    def phrases(self, parts: list[str], gap_s: float = GAP_S) -> np.ndarray:
        """조각들을 쉼을 두고 이어 붙인다 (조각마다 캐시)."""
        gap = np.zeros(int(OUT_SR * gap_s), np.float32)
        out = []
        for i, p in enumerate(parts):
            if i:
                out.append(gap)
            out.append(self(verbalize(p)))
        return np.concatenate(out) if out else np.zeros(0, np.float32)

    def stream(self, text: str, cache: bool = False) -> Iterator[np.ndarray]:
        """자유 텍스트: 문장 단위로 합성해 차례로 내보낸다 (첫 문장 지연만 체감)."""
        for s in split_sentences(text):
            yield self(verbalize(s), cache=cache)
            yield np.zeros(int(OUT_SR * 0.25), np.float32)

    def warm(self, texts: list[str]) -> int:
        """조각 미리 합성(최초 1회, 이후 디스크 캐시). 새로 합성한 개수 반환."""
        n = 0
        for t in texts:
            key = self._key(verbalize(t))
            if not (self.cache_dir and (self.cache_dir / f"{key}.npy").exists()):
                n += 1
            self(verbalize(t))
        return n
