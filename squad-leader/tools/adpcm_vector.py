"""명세 부록 A ADPCM 테스트 벡터 계산: 8kHz 1초 440Hz 사인, 진폭 8000, predictor=0, step_index=0."""
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from squad import adpcm  # noqa: E402

raw = [8000 * math.sin(2 * math.pi * 440 * i / 8000) for i in range(8000)]
ties = [i for i, v in enumerate(raw) if abs(abs(v - math.trunc(v)) - 0.5) < 1e-6]
samples = [round(v) for v in raw]
enc = adpcm.encode(samples, 0, 0)

print("samples[:8]   :", samples[:8])
print("round ties    :", ties or "none (C lround과 결과 동일)")
print("encoded bytes :", len(enc))
print("first 16 bytes:", " ".join(f"{b:02X}" for b in enc[:16]))
print(f"CRC16         : 0x{adpcm.crc16_ccitt_false(enc):04X}")
