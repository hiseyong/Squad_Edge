"""한 파일에 이어 읽은 녹음 → 문장별 파일로 자르기 (가장 긴 무음 구간 N-1개에서 자른다).

    .venv/bin/python tools/split_recording.py 녹음.wav [--n 12] [--out recordings/stt_set]

결과: out/01.wav ... NN.wav (16kHz 모노 원음, 앞뒤 0.3초 여유). 잘린 구간 시각을 출력하니 확인용으로 본다.
"""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import soundfile as sf  # noqa: E402

from squad.audio.fmt import to_16k_mono  # noqa: E402

SR = 16000
FRAME = 320          # 20ms
PAD = int(0.3 * SR)


def split(x: np.ndarray, n: int) -> list[tuple[int, int]]:
    """음성 구간을 n개로: 짧은 무음은 무시하고 가장 긴 무음 n-1개를 경계로 쓴다."""
    frames = len(x) // FRAME
    e = np.array([np.sqrt(np.mean(x[i * FRAME:(i + 1) * FRAME] ** 2)) + 1e-9 for i in range(frames)])
    db = 20 * np.log10(e)
    floor, peak = np.percentile(db, 10), np.percentile(db, 95)
    voiced = db > floor + 0.35 * (peak - floor)          # 배경 소음과 말소리 사이 문턱
    idx = np.flatnonzero(voiced)
    if len(idx) == 0:
        raise SystemExit("음성을 찾지 못했습니다")
    gaps = [(idx[k + 1] - idx[k], idx[k], idx[k + 1]) for k in range(len(idx) - 1) if idx[k + 1] - idx[k] > 1]
    if len(gaps) < n - 1:
        raise SystemExit(f"쉬는 구간이 {len(gaps)}개뿐이라 {n}개로 못 자릅니다 (문장 사이를 더 쉬어 주세요)")
    cuts = sorted(gaps, key=lambda g: -g[0])[: n - 1]
    shortest = min(c[0] for c in cuts) * FRAME / SR
    nxt = sorted(gaps, key=lambda g: -g[0])[n - 1][0] * FRAME / SR if len(gaps) >= n else 0
    if nxt and shortest < 1.5 * nxt:
        print(f"! 주의: 경계로 쓴 가장 짧은 쉼 {shortest:.2f}s ≈ 문장 안 쉼 {nxt:.2f}s — 결과 확인 필요")
    bounds, start = [], idx[0]
    for _, a, b in sorted(cuts, key=lambda g: g[1]):
        bounds.append((start, a + 1))
        start = b
    bounds.append((start, idx[-1] + 1))
    return [(max(0, s * FRAME - PAD), min(len(x), e * FRAME + PAD)) for s, e in bounds]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--n", type=int, default=12)
    ap.add_argument("--out", default=str(ROOT / "recordings" / "stt_set"))
    a = ap.parse_args()
    x, sr = sf.read(a.wav, dtype="float32", always_2d=True)
    y = to_16k_mono(x, sr)
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    refs = {}
    if (out / "refs.tsv").exists():
        refs = dict(l.rstrip("\n").split("\t", 1) for l in (out / "refs.tsv").open(encoding="utf-8") if "\t" in l)
    for i, (s, e) in enumerate(split(y, a.n), 1):
        name = f"{i:02d}.wav"
        sf.write(out / name, y[s:e], SR, subtype="PCM_16")
        print(f"{name}  {s / SR:6.1f}~{e / SR:6.1f}s ({(e - s) / SR:4.1f}s)  {refs.get(name, '')}")


if __name__ == "__main__":
    main()
