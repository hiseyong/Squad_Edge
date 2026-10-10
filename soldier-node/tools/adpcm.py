"""IMA ADPCM 4bit 인코더/디코더 (분대 BLE 통신 명세 v1 §7.1).

- 표준 IMA ADPCM 스텝 표(89개)/인덱스 표(16개).
- 한 바이트에 샘플 2개, **하위 니블이 먼저**.
- `audioop` 미사용(Python 3.13에서 제거됨). 외부 의존성 없음 → 분대장 팀원이 그대로 복사해 사용 가능.

사용:
    data, (pred, idx) = encode(samples, predictor=0, step_index=0)
    samples, (pred, idx) = decode(data, num_samples, predictor=0, step_index=0)

자체 테스트: python3 tools/adpcm.py
"""

STEP_TABLE = (
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
    50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230,
    253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963,
    1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327,
    3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487,
    12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
)

INDEX_TABLE = (-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def decode_nibble(nibble, predictor, step_index):
    """니블 하나 → (샘플, predictor, step_index)."""
    step = STEP_TABLE[step_index]
    diff = step >> 3
    if nibble & 4:
        diff += step
    if nibble & 2:
        diff += step >> 1
    if nibble & 1:
        diff += step >> 2
    predictor = predictor - diff if nibble & 8 else predictor + diff
    predictor = _clamp(predictor, -32768, 32767)
    step_index = _clamp(step_index + INDEX_TABLE[nibble & 0x0F], 0, 88)
    return predictor, predictor, step_index


def encode_sample(sample, predictor, step_index):
    """샘플 하나 → (니블, predictor, step_index). 디코더와 같은 재구성값을 추적한다."""
    step = STEP_TABLE[step_index]
    diff = sample - predictor
    nibble = 0
    if diff < 0:
        nibble = 8
        diff = -diff
    if diff >= step:
        nibble |= 4
        diff -= step
    if diff >= (step >> 1):
        nibble |= 2
        diff -= step >> 1
    if diff >= (step >> 2):
        nibble |= 1
    _, predictor, step_index = decode_nibble(nibble, predictor, step_index)
    return nibble, predictor, step_index


def encode(samples, predictor=0, step_index=0):
    """int16 목록 → (bytes, (predictor, step_index)). 홀수 개면 마지막 상위 니블 = 0."""
    out = bytearray((len(samples) + 1) // 2)
    for i, s in enumerate(samples):
        s = _clamp(int(s), -32768, 32767)
        nibble, predictor, step_index = encode_sample(s, predictor, step_index)
        if i & 1:
            out[i >> 1] |= nibble << 4
        else:
            out[i >> 1] = nibble
    return bytes(out), (predictor, step_index)


def decode(data, num_samples=None, predictor=0, step_index=0):
    """bytes → (int16 목록, (predictor, step_index)). num_samples 생략 시 len(data)*2."""
    if num_samples is None:
        num_samples = len(data) * 2
    out = []
    for i in range(num_samples):
        b = data[i >> 1]
        nibble = (b >> 4) if (i & 1) else (b & 0x0F)
        s, predictor, step_index = decode_nibble(nibble, predictor, step_index)
        out.append(s)
    return out, (predictor, step_index)


def _self_test():
    import math

    sine = [round(8000 * math.sin(2 * math.pi * 440 * i / 8000)) for i in range(8000)]
    data, state = encode(sine, 0, 0)
    assert len(data) == 4000
    dec, state2 = decode(data, len(sine), 0, 0)
    assert state == state2, "인코더/디코더 최종 상태 불일치"
    # 처음 수렴 구간(스텝이 커지는 동안) 이후 오차가 작아야 한다.
    max_err = max(abs(a - b) for a, b in zip(sine[200:], dec[200:]))
    assert max_err < 800, max_err
    # 홀수 개, 하위 니블 먼저
    d1, _ = encode([1000], 0, 0)
    assert len(d1) == 1 and (d1[0] >> 4) == 0
    print(f"adpcm self-test OK (안정 구간 최대 오차 {max_err})")


if __name__ == "__main__":
    _self_test()
