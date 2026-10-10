"""IMA ADPCM 4bit (명세 §7.1) + CRC-16/CCITT-FALSE (§7.3).

audioop는 Python 3.13에서 제거되어 직접 구현한다. 한 바이트에 샘플 2개, 하위 니블이 먼저.
"""
from __future__ import annotations

STEP_TABLE = (
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
    50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230,
    253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963,
    1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327,
    3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
    11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794,
    32767,
)
INDEX_TABLE = (-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8)


def _clamp(v: int, lo: int, hi: int) -> int:
    return lo if v < lo else hi if v > hi else v


def _decode_nibble(code: int, predictor: int, index: int) -> tuple[int, int]:
    step = STEP_TABLE[index]
    diff = step >> 3
    if code & 4:
        diff += step
    if code & 2:
        diff += step >> 1
    if code & 1:
        diff += step >> 2
    predictor = predictor - diff if code & 8 else predictor + diff
    return _clamp(predictor, -32768, 32767), _clamp(index + INDEX_TABLE[code], 0, 88)


def encode(samples: list[int], predictor: int = 0, index: int = 0) -> bytes:
    """int16 샘플 → ADPCM 바이트. 홀수 개면 마지막 상위 니블은 0."""
    codes = []
    for s in samples:
        step = STEP_TABLE[index]
        diff = s - predictor
        code = 0
        if diff < 0:
            code = 8
            diff = -diff
        if diff >= step:
            code |= 4
            diff -= step
        if diff >= step >> 1:
            code |= 2
            diff -= step >> 1
        if diff >= step >> 2:
            code |= 1
        # 디코더와 같은 식으로 예측값을 갱신해야 양측 상태가 어긋나지 않는다
        predictor, index = _decode_nibble(code, predictor, index)
        codes.append(code)
    if len(codes) % 2:
        codes.append(0)
    return bytes(codes[i] | (codes[i + 1] << 4) for i in range(0, len(codes), 2))


def decode(data: bytes, total_samples: int, predictor: int = 0, index: int = 0) -> list[int]:
    out = []
    for b in data:
        for code in (b & 0x0F, b >> 4):
            if len(out) == total_samples:
                return out
            predictor, index = _decode_nibble(code, predictor, index)
            out.append(predictor)
    return out


def crc16_ccitt_false(data: bytes) -> int:
    crc = 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc
