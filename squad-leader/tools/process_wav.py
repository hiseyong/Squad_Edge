"""WAV 파일 오프라인 전처리 (맥에서 녹음한 파일 시험용).

    .venv/bin/python tools/process_wav.py input.wav [--no-denoise] [--no-impulse] [--no-agc]
결과: input_proc.wav (16kHz 모노)
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import soundfile as sf  # noqa: E402

from squad.audio.pipeline import PreprocessConfig, preprocess  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("wav")
ap.add_argument("--no-denoise", action="store_true")
ap.add_argument("--no-impulse", action="store_true")
ap.add_argument("--no-agc", action="store_true")
a = ap.parse_args()
x, sr = sf.read(a.wav, dtype="float32")
cfg = PreprocessConfig(denoise=not a.no_denoise, impulse=not a.no_impulse, agc=not a.no_agc)
r = preprocess(x, sr, cfg)
out = Path(a.wav).with_name(Path(a.wav).stem + "_proc.wav")
sf.write(out, r.audio, r.sr)
print(f"{sr}Hz {x.shape} → 16kHz {len(r.audio) / r.sr:.1f}s, {r.elapsed_ms:.0f}ms, "
      f"레벨 {r.level_in_dbfs:.1f}→{r.level_out_dbfs:.1f}dBFS, 임펄스 {len(r.impulses)}건 → {out}")
