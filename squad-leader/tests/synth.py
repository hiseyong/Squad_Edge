"""테스트용 합성 신호: 말소리 비슷한 유성음(배음 + 포먼트 + 음절 엔벨로프), 총성, 잡음."""
import numpy as np
from scipy.signal import lfilter

SR = 16000


def speech_like(seconds=3.0, f0=120.0, level=0.1, seed=0, sr=SR):
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    t = np.arange(n) / sr
    f = f0 * (1 + 0.08 * np.sin(2 * np.pi * 0.7 * t) + 0.01 * rng.standard_normal(n).cumsum() / np.sqrt(n))
    phase = 2 * np.pi * np.cumsum(f) / sr
    x = sum(np.sin(k * phase) / k for k in range(1, 30))
    for fc, bw in ((700, 130), (1200, 150), (2600, 250)):  # 포먼트
        r = np.exp(-np.pi * bw / sr)
        x = x + 0.5 * lfilter([1 - r], [1, -2 * r * np.cos(2 * np.pi * fc / sr), r * r], x)
    env = np.clip(np.sin(2 * np.pi * 3.5 * t), 0, None) ** 0.7       # 음절
    env *= (np.sin(2 * np.pi * 0.4 * t + 1) > -0.6)                   # 단어 사이 쉼
    lead = int(0.4 * sr)
    env[:lead] = 0                                                    # PTT 직후 무음
    env[-int(0.3 * sr):] = 0
    x = x * np.convolve(env, np.ones(160) / 160, "same")
    return (x / (np.abs(x).max() + 1e-9) * level * 3).astype(np.float32)


def gunshot(sr=SR, peak=0.95, seed=1):
    rng = np.random.default_rng(seed)
    n = int(0.12 * sr)
    t = np.arange(n) / sr
    burst = rng.standard_normal(n) * np.exp(-t / 0.02)
    burst[: int(0.0005 * sr)] *= np.linspace(0, 1, int(0.0005 * sr))  # 0.5ms 상승
    return (burst / np.abs(burst).max() * peak).astype(np.float32)


def noise(seconds, level=0.01, seed=2, sr=SR, color="pink"):
    rng = np.random.default_rng(seed)
    w = rng.standard_normal(int(seconds * sr))
    if color == "pink":
        w = lfilter([0.049922035, -0.095993537, 0.050612699, -0.004408786],
                    [1, -2.494956002, 2.017265875, -0.522189400], w)
    return (w / np.std(w) * level).astype(np.float32)


def snr_db(clean, test):
    clean, test = clean[: len(test)], test[: len(clean)]
    a = np.dot(test, clean) / (np.dot(clean, clean) + 1e-12)  # 이득 차이 보정
    err = test - a * clean
    return 10 * np.log10(np.sum((a * clean) ** 2) / (np.sum(err ** 2) + 1e-12))
