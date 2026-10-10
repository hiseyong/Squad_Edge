"""입력 포맷 통일: 어떤 샘플레이트·채널·샘플 형식이든 16kHz 모노 float32로.

에어팟 마이크는 맥에서 HFP 모드로 잡히며 기종·OS에 따라 8k/16k/24k/48kHz로 보고된다.
맥 송신기(tools/mac_mic_sender.py)가 실제 값을 헤더로 보내고, 보드는 여기서 맞춘다.
"""
from __future__ import annotations

from math import gcd

import numpy as np
from scipy.signal import resample_poly

TARGET_SR = 16000

_DTYPES = {"s16le": ("<i2", 32768.0), "s32le": ("<i4", 2147483648.0), "f32le": ("<f4", 1.0)}


def pcm_to_float(raw: bytes, fmt: str, channels: int) -> np.ndarray:
    """raw PCM → (frames, channels) float32 [-1, 1]."""
    dtype, scale = _DTYPES[fmt]
    width = np.dtype(dtype).itemsize * channels
    usable = len(raw) - len(raw) % width
    x = np.frombuffer(raw[:usable], dtype=dtype).astype(np.float32) / scale
    return x.reshape(-1, channels)


def to_mono(x: np.ndarray) -> np.ndarray:
    """채널 합치기. 한쪽 채널만 살아 있으면(에어팟 한쪽 마이크) 평균 대신 그 채널만 써서 -6dB 손실을 막는다."""
    if x.ndim == 1:
        return x
    if x.shape[1] == 1:
        return x[:, 0]
    energy = (x.astype(np.float64) ** 2).mean(axis=0)
    loudest = int(np.argmax(energy))
    if energy.max() > 0 and np.sort(energy)[-2] < energy.max() * 0.01:
        return x[:, loudest]
    return x.mean(axis=1)


def resample(x: np.ndarray, sr_in: int, sr_out: int = TARGET_SR) -> np.ndarray:
    if sr_in == sr_out:
        return x
    g = gcd(sr_in, sr_out)
    return resample_poly(x, sr_out // g, sr_in // g).astype(np.float32)


def to_16k_mono(x: np.ndarray, sr: int) -> np.ndarray:
    """(frames,) 또는 (frames, ch) → 16kHz 모노 float32, DC 제거."""
    y = resample(to_mono(np.asarray(x, dtype=np.float32)), sr)
    return (y - y.mean()).astype(np.float32) if len(y) else y


def float_to_s16(x: np.ndarray) -> np.ndarray:
    return (np.clip(x, -1.0, 1.0) * 32767.0).astype(np.int16)


def dbfs(x: np.ndarray) -> float:
    rms = float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0
    return 20 * np.log10(rms + 1e-12)
