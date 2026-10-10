"""발화자 인증(보조 수단): 등록한 분대장 목소리와 비교.

두 가지 백엔드
- `SpeakerVerifier.neural(model_path)`: WeSpeaker ResNet34 (VoxCeleb, 26MB ONNX, sherpa-onnx로 실행).
  오프라인 동작, 코사인 유사도. 기본 권장.
- `SpeakerVerifier()`: MFCC 통계 기준선. 모델 파일 없이 동작하지만 비슷한 목소리는 구분 못 함.

보안 메모: 프로필(임베딩)은 생체정보이므로 저장 시 암호화 + crypto-erase 대상에 포함해야 한다.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np
from scipy.fft import dct

from . import dsp

SR = 16000
DEFAULT_MODEL = "models/wespeaker_en_voxceleb_resnet34.onnx"


def _mel_filterbank(n_mels: int, n_fft: int, sr: int, fmin: float = 60, fmax: float = 7600) -> np.ndarray:
    def hz2mel(f):
        return 2595 * np.log10(1 + f / 700)

    def mel2hz(m):
        return 700 * (10 ** (m / 2595) - 1)

    mels = np.linspace(hz2mel(fmin), hz2mel(fmax), n_mels + 2)
    bins = np.floor((n_fft + 1) * mel2hz(mels) / sr).astype(int)
    fb = np.zeros((n_mels, n_fft // 2 + 1))
    for m in range(1, n_mels + 1):
        lo, c, hi = bins[m - 1], bins[m], bins[m + 1]
        if c > lo:
            fb[m - 1, lo:c] = (np.arange(lo, c) - lo) / (c - lo)
        if hi > c:
            fb[m - 1, c:hi] = (hi - np.arange(c, hi)) / (hi - c)
    return fb


_FB = _mel_filterbank(40, 512, SR)


def mfcc(x: np.ndarray, n_mfcc: int = 20, win: int = 400, hop: int = 160, n_fft: int = 512) -> np.ndarray:
    """(frames, n_mfcc)."""
    if len(x) < win:
        return np.zeros((0, n_mfcc))
    x = np.append(x[0], x[1:] - 0.97 * x[:-1])
    n = 1 + (len(x) - win) // hop
    idx = np.arange(win)[None, :] + hop * np.arange(n)[:, None]
    frames = x[idx] * np.hamming(win)
    power = np.abs(np.fft.rfft(frames, n_fft)) ** 2
    logmel = np.log(power @ _FB.T + 1e-10)
    return dct(logmel, type=2, axis=1, norm="ortho")[:, :n_mfcc]


def mfcc_embedding(x: np.ndarray) -> np.ndarray:
    """음성 프레임만 골라 MFCC(1~19) + 델타의 평균·표준편차."""
    feats = mfcc(x)
    if len(feats) == 0:
        return np.zeros(76)
    speech = dsp.energy_vad(x, SR)
    k = min(len(speech), len(feats))
    sel = feats[:k][speech[:k]] if speech[:k].sum() >= 20 else feats
    c = sel[:, 1:]
    delta = np.gradient(c, axis=0) if len(c) > 2 else np.zeros_like(c)
    return np.concatenate([c.mean(0), c.std(0), delta.std(0), np.abs(delta).mean(0)])


@dataclass
class VerifyResult:
    accepted: bool
    score: float
    threshold: float


def onnx_embedder(model_path: str = DEFAULT_MODEL, threads: int = 2) -> Callable[[np.ndarray], np.ndarray]:
    import sherpa_onnx

    cfg = sherpa_onnx.SpeakerEmbeddingExtractorConfig(model=model_path, num_threads=threads)
    extractor = sherpa_onnx.SpeakerEmbeddingExtractor(cfg)

    def embed(x: np.ndarray) -> np.ndarray:
        stream = extractor.create_stream()
        stream.accept_waveform(SR, np.ascontiguousarray(x, dtype=np.float32))
        stream.input_finished()
        return np.array(extractor.compute(stream), dtype=np.float32)

    return embed


class SpeakerVerifier:
    """점수 0~1(MFCC) 또는 코사인 -1~1(신경망). 점수 >= threshold면 통과.

    MFCC: 등록 발화가 3~5개뿐이라 차원별 분산을 믿을 수 없어서, 블록(MFCC 평균·표준편차·델타 등)별
    평균 크기로만 정규화한 거리 → exp(-mean(z^2)).
    신경망: L2 정규화 임베딩 평균과의 코사인.
    """

    def __init__(self, embed_fn: Callable[[np.ndarray], np.ndarray] = mfcc_embedding,
                 threshold: float = 0.90, metric: str = "block", block: int = 19):
        self.embed_fn = embed_fn
        self.threshold = threshold
        self.metric = metric
        self.block = block
        self.mu: np.ndarray | None = None
        self.scale: np.ndarray | None = None

    @classmethod
    def neural(cls, model_path: str = DEFAULT_MODEL, threshold: float = 0.55) -> "SpeakerVerifier":
        return cls(onnx_embedder(model_path), threshold=threshold, metric="cosine")

    def enroll(self, utterances: list[np.ndarray]) -> None:
        """16kHz 발화 3개 이상 권장(각 3초 이상)."""
        embs = np.stack([self.embed_fn(u) for u in utterances])
        if self.metric == "cosine":
            embs /= np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9
            self.mu = embs.mean(0) / (np.linalg.norm(embs.mean(0)) + 1e-9)
            self.scale = np.ones_like(self.mu)
            return
        self.mu = embs.mean(0)
        dim = embs.shape[1]
        b = self.block if dim % self.block == 0 else dim
        self.scale = np.repeat(np.abs(embs).reshape(len(embs), -1, b).mean(axis=(0, 2)), b) + 1e-6

    @property
    def enrolled(self) -> bool:
        return self.mu is not None

    def score(self, x: np.ndarray) -> float:
        if not self.enrolled:
            raise RuntimeError("not enrolled")
        e = self.embed_fn(x)
        if self.metric == "cosine":
            return float(e @ self.mu / (np.linalg.norm(e) + 1e-9))
        z = (e - self.mu) / self.scale
        return float(np.exp(-np.mean(z ** 2)))

    def verify(self, x: np.ndarray) -> VerifyResult:
        s = self.score(x)
        return VerifyResult(s >= self.threshold, s, self.threshold)

    def save(self, path: str) -> None:
        np.savez(path, mu=self.mu, scale=self.scale, threshold=self.threshold, metric=self.metric)

    @classmethod
    def from_profile(cls, path: str, model_path: str = DEFAULT_MODEL) -> "SpeakerVerifier":
        d = np.load(path)
        metric = str(d["metric"]) if "metric" in d else "block"
        v = cls.neural(model_path) if metric == "cosine" else cls()
        v.load(path)
        return v

    def load(self, path: str) -> None:
        d = np.load(path)
        self.mu, self.scale = d["mu"], d["scale"]
        self.threshold = float(d["threshold"])
        self.metric = str(d["metric"]) if "metric" in d else "block"
