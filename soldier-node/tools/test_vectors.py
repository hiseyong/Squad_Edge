"""프로토콜 부록 A ADPCM 테스트 벡터 생성.

조건(프로토콜 §7.5): 8kHz 1초 사인파 440Hz, 진폭 8000, int16.
샘플 i = round(8000·sin(2π·440·i/8000)), predictor=0, step_index=0에서 IMA ADPCM 인코딩.
출력: 처음 16바이트(hex)와 전체 4000바이트의 CRC-16/CCITT-FALSE.

같은 값을 펌웨어 호스트 테스트(tests/host/test_crc_adpcm.cpp)에서도 검증한다.
실행: python3 tools/test_vectors.py
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adpcm  # noqa: E402
import frame_codec  # noqa: E402

# C 테스트(test_crc_adpcm.cpp)와 같은 값이어야 한다.
EXPECTED_FIRST16 = "70 77 77 77 F1 BB 9B 18 44 53 22 82 B8 CC AC 9B"
EXPECTED_CRC16 = 0x0166


def sine_440():
    # round-half-away-from-zero (C의 lround와 동일). .5가 나오는 샘플은 i=0(0) 뿐이라 결과는 같다.
    out = []
    for i in range(8000):
        v = 8000 * math.sin(2 * math.pi * 440 * i / 8000)
        out.append(int(math.floor(v + 0.5)) if v >= 0 else -int(math.floor(-v + 0.5)))
    return out


def compute():
    data, _ = adpcm.encode(sine_440(), 0, 0)
    return data, frame_codec.crc16_ccitt_false(data)


def main():
    data, crc = compute()
    first16 = frame_codec.to_hex(data[:16])
    print("부록 A. ADPCM 테스트 벡터 (440Hz, 진폭 8000, 8kHz 1초, 초기 predictor=0 step_index=0)")
    print(f"- 인코딩 길이: {len(data)}바이트")
    print(f"- 처음 16바이트: {first16}")
    print(f"- 전체 CRC16: 0x{crc:04X}")
    ok = first16 == EXPECTED_FIRST16 and crc == EXPECTED_CRC16
    print("C 테스트 기대값과 일치" if ok else
          f"기대값 불일치! EXPECTED_FIRST16={EXPECTED_FIRST16} EXPECTED_CRC16=0x{EXPECTED_CRC16:04X}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
