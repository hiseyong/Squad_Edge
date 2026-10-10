"""음성 전처리 DSP: VAD, 임펄스(총성·폭발) 억제, 고역통과, 스펙트럼 노이즈 제거, AGC.

모두 16kHz 모노 float32 입력, 발화(PTT 한 번) 단위 처리. 신경망 없이 numpy/scipy만 사용해
저전력 보드에서 10초 발화를 수십 ms 안에 처리하는 것이 목표.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.ndimage import binary_dilation, binary_opening
from scipy.signal import butter, istft, sosfiltfilt, stft


def _frames_rms_db(x: np.ndarray, sr: int, frame_ms: float, hop_ms: float) -> np.ndarray:
    frame, hop = int(sr * frame_ms / 1000), int(sr * hop_ms / 1000)
    if len(x) < frame:
        return np.array([20 * np.log10(np.sqrt(np.mean(x ** 2)) + 1e-12)]) if len(x) else np.zeros(0)
    n = 1 + (len(x) - frame) // hop
    idx = np.arange(frame)[None, :] + hop * np.arange(n)[:, None]
    rms = np.sqrt(np.mean(x[idx].astype(np.float64) ** 2, axis=1))
    return 20 * np.log10(rms + 1e-12)


def _expand(mask: np.ndarray, hop: int, n: int) -> np.ndarray:
    out = np.repeat(mask, hop)[:n]
    if len(out) < n:
        out = np.pad(out, (0, n - len(out)), mode="edge" if len(out) else "constant")
    return out


# ---------------------------------------------------------------- VAD

def energy_vad(x: np.ndarray, sr: int, margin_db: float = 9.0, abs_floor_db: float = -55.0,
               hangover_ms: float = 200, min_speech_ms: float = 60, hop_ms: float = 10) -> np.ndarray:
    """프레임(10ms) 단위 음성 여부. 잡음 바닥 = 하위 10% 에너지, 임계 = 바닥 + margin."""
    db = _frames_rms_db(x, sr, 20, hop_ms)
    if len(db) == 0:
        return np.zeros(0, dtype=bool)
    floor = np.percentile(db, 10)
    raw = db > max(floor + margin_db, abs_floor_db)
    # 짧은 튐 제거 후 hangover로 어미가 잘리지 않게
    k = max(1, int(min_speech_ms / hop_ms))
    opened = binary_opening(raw, structure=np.ones(k)) if k > 1 else raw
    hang = int(hangover_ms / hop_ms)
    return binary_dilation(opened, structure=np.ones(2 * hang + 1)) if hang else opened


def vad_samples(x: np.ndarray, sr: int, **kw) -> np.ndarray:
    return _expand(energy_vad(x, sr, **kw), int(sr * 0.01), len(x))


def trim_silence(x: np.ndarray, sr: int, pad_ms: float = 150) -> np.ndarray:
    m = vad_samples(x, sr)
    if not m.any():
        return x[:0]
    idx = np.flatnonzero(m)
    pad = int(sr * pad_ms / 1000)
    return x[max(0, idx[0] - pad): idx[-1] + pad]


# ---------------------------------------------------------------- 임펄스

@dataclass
class ImpulseEvent:
    start_s: float
    end_s: float
    peak_dbfs: float
    reduction_db: float


def suppress_impulses(x: np.ndarray, sr: int, ratio_db: float = 15.0, rise_ratio: float = 4.0,
                      min_peak_dbfs: float = -20.0, max_len_ms: float = 200.0, min_zcr: float = 0.2,
                      ) -> tuple[np.ndarray, list[ImpulseEvent]]:
    """총성·폭발음처럼 2~4ms 안에 급상승하는 큰 과도음을 배경 수준까지 눌러준다.

    판정: 1ms 피크 엔벨로프가 ① 직전 300ms 상위 20% 수준보다 ratio_db 이상 크고 ② 2~4ms 전보다
    rise_ratio배 이상 급상승하고 ③ 절대 크기가 min_peak_dbfs 이상. 말소리의 시작은 보통
    10ms 이상 걸쳐 올라가므로 ②에서 걸러지고, 그래도 걸리는 큰 유성음은 ④ 영교차율(광대역성)
    또는 클리핑 여부로 한 번 더 거른다.
    """
    y = x.astype(np.float32).copy()
    ms = sr // 1000
    n = len(x) // ms
    if n < 10:
        return y, []
    env = np.abs(x[: n * ms]).reshape(n, ms).max(axis=1)
    ratio = 10 ** (ratio_db / 20)
    min_peak = 10 ** (min_peak_dbfs / 20)
    gain = np.ones(n, dtype=np.float64)
    events: list[ImpulseEvent] = []
    # 값싼 조건(급상승 + 절대 크기)으로 후보를 먼저 거르고, 배경 중앙값은 후보에서만 계산
    prev = np.maximum.reduce([np.roll(env, k) for k in (2, 3, 4)]) + 1e-6
    cand = np.flatnonzero((env > rise_ratio * prev) & (env > min_peak))
    cand = cand[cand >= 4]
    skip_until = -1
    for i in cand:
        if i <= skip_until:
            continue
        bg = np.percentile(env[max(0, i - 300): i], 80) + 1e-5  # 말하는 중이면 말소리 수준
        if env[i] <= ratio * bg:
            continue
        # 총성·폭발은 광대역(잡음성) 또는 클리핑. 큰 목소리의 유성음 시작은 영교차율이 낮다
        seg = x[i * ms: (i + 4) * ms]
        zcr = np.mean(np.signbit(seg[1:]) != np.signbit(seg[:-1])) if len(seg) > 1 else 0.0
        if zcr < min_zcr and np.abs(seg).max() < 0.98:
            continue
        target = max(bg * 2.0, 1e-4)
        j = i
        limit = min(n, i + int(max_len_ms))
        while j < limit and env[j] > target:
            gain[j] = min(gain[j], target / env[j])
            j += 1
        events.append(ImpulseEvent(i / 1000, j / 1000, 20 * np.log10(env[i]),
                                   -20 * np.log10(gain[i: j].min() + 1e-12)))
        skip_until = j
    if not events:
        return y, []
    # 앞뒤 1ms까지 이득을 넓혀(직전 프레임의 상승 시작 포함) 샘플 단위로 보간 → 클릭 방지
    g = np.minimum.reduce([np.roll(gain, s) for s in (-1, 0, 1)])
    t = (np.arange(n) + 0.5) * ms
    gs = np.interp(np.arange(len(x)), t, g).astype(np.float32)
    y *= gs
    return y, events


# ---------------------------------------------------------------- 노이즈 제거

def highpass(x: np.ndarray, sr: int, fc: float = 100.0) -> np.ndarray:
    """바람·핸들링 저역 잡음 제거. 음성 기본주파수(남성 ~85Hz~) 영향 최소화."""
    if len(x) < 64:
        return x
    sos = butter(4, fc, btype="highpass", fs=sr, output="sos")
    return sosfiltfilt(sos, x).astype(np.float32)


def spectral_denoise(x: np.ndarray, sr: int, speech_mask: np.ndarray | None = None,
                     n_fft: int = 512, hop: int = 128, floor_db: float = -15.0,
                     alpha: float = 0.98, noise_percentile: float = 10.0) -> np.ndarray:
    """정상 잡음(엔진·바람·웅성거림) 제거. 결정지향(decision-directed) 위너 필터.

    잡음 스펙트럼: 비음성 구간(speech_mask=False)이 0.2초 이상이면 그 평균, 아니면 주파수별 하위
    noise_percentile% (짧은 발화에서도 동작). 이득 하한(floor_db)으로 뮤지컬 노이즈를 억제.
    """
    if len(x) < n_fft:
        return x
    _, _, Z = stft(x, fs=sr, nperseg=n_fft, noverlap=n_fft - hop, window="hann")
    P = np.abs(Z) ** 2
    noise = None
    if speech_mask is not None:
        centers = np.clip(np.arange(P.shape[1]) * hop, 0, len(speech_mask) - 1)
        quiet = ~speech_mask[centers]
        if quiet.sum() * hop >= 0.2 * sr:
            noise = P[:, quiet].mean(axis=1)
    if noise is None:
        noise = np.percentile(P, noise_percentile, axis=1)
    noise = noise[:, None] + 1e-12

    gamma = P / noise
    floor = 10 ** (floor_db / 20)
    G = np.empty_like(P)
    g_prev = np.ones(P.shape[0])
    gamma_prev = np.ones(P.shape[0])
    for t in range(P.shape[1]):
        xi = alpha * (g_prev ** 2) * gamma_prev + (1 - alpha) * np.maximum(gamma[:, t] - 1, 0)
        g = np.maximum(xi / (1 + xi), floor)
        G[:, t] = g
        g_prev, gamma_prev = g, gamma[:, t]
    # 주파수 방향 3탭 평활로 뮤지컬 노이즈 완화
    G = np.maximum((np.roll(G, 1, axis=0) + 2 * G + np.roll(G, -1, axis=0)) / 4, floor)
    _, y = istft(Z * G, fs=sr, nperseg=n_fft, noverlap=n_fft - hop, window="hann")
    return y[: len(x)].astype(np.float32)


# ---------------------------------------------------------------- AGC

def agc(x: np.ndarray, sr: int, speech_mask: np.ndarray | None = None, target_dbfs: float = -20.0,
        max_gain_db: float = 30.0, min_gain_db: float = -12.0, attack_ms: float = 15.0,
        release_ms: float = 400.0, limit_dbfs: float = -1.0) -> np.ndarray:
    """속삭임~고함을 일정 크기로. 음성 프레임에서만 이득을 정하고 무음에서는 유지해
    잡음을 끌어올리는 펌핑을 막는다. 마지막에 소프트 리미터."""
    hop = int(sr * 0.01)
    db = _frames_rms_db(x, sr, 30, 10)
    if len(db) == 0:
        return x
    if speech_mask is None:
        speech_mask = vad_samples(x, sr)
    speech = speech_mask[np.clip(np.arange(len(db)) * hop, 0, len(speech_mask) - 1)]
    want = np.clip(target_dbfs - db, min_gain_db, max_gain_db)
    start = float(np.median(want[speech])) if speech.any() else 0.0
    a_att = np.exp(-10.0 / attack_ms)
    a_rel = np.exp(-10.0 / release_ms)
    g = np.empty(len(db))
    cur = start
    for i in range(len(db)):
        if speech[i]:
            tgt = want[i]
            a = a_att if tgt < cur else a_rel
            cur = a * cur + (1 - a) * tgt
        g[i] = cur
    t = np.arange(len(db)) * hop + hop
    gain = 10 ** (np.interp(np.arange(len(x)), t, g) / 20)
    y = x * gain
    lim = 10 ** (limit_dbfs / 20)
    knee = lim * 0.7
    over = np.abs(y) > knee
    y[over] = np.sign(y[over]) * (knee + (lim - knee) * np.tanh((np.abs(y[over]) - knee) / (lim - knee)))
    return y.astype(np.float32)
