"""방향·거리 계산 (병사 프로토콜 v1.1 §4, §5.1, §9.5, §9.6).

포팅 원본: ~/work/soldier-node_ref_v1.1/tools/squad_localize.py (clock_from, target_pos, bearing_range, band_of,
peer_to_me, rssi_to_m), ~/work/soldier-node_ref_v1.1/tools/mock_leader.py (median)
원본과 다른 점(병사 팀 안내문 2026-10-11 P2·P3)
- 반올림은 **0에서 먼 쪽**(펌웨어 C와 같음). 원본 Python의 round()(짝수 쪽)는 레퍼런스 결함이라 따르지 않는다.
- 경로손실 기본값은 config(−65.5 dBm, n 1.6). 원본 함수 기본 인자(−59, 2.0)는 옛 값.
- 시계 변환은 §7.1 규칙 그대로(azimuth 0xFFFF → 0, heading 0xFFFF → 0으로 간주).
좌표: 분대장 원점, x 동쪽, y 북쪽. 계산은 m, 무선은 0.1m(dm) 정수.
"""
from __future__ import annotations

import math

from . import config

NO_AZIMUTH = 0xFFFF
NO_HEADING = 0xFFFF
NO_DIST = 0xFF
POS_UNKNOWN = -32768


def round_half_away(x: float) -> int:
    """0에서 먼 쪽 반올림: 2.5 → 3, −2.5 → −3."""
    return int(math.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


def clock_from_azimuth(azimuth: int, my_heading: int = config.LEADER_HEADING) -> int:
    """방위 → 시계 1~12. rel = (az − heading + 360) % 360, clock = (rel + 15) // 30, 0 → 12. az 없음 → 0."""
    if azimuth == NO_AZIMUTH:
        return 0
    if my_heading == NO_HEADING:
        my_heading = 0
    c = ((azimuth - my_heading + 360) % 360 + 15) // 30
    return 12 if c in (0, 12) else c


def azimuth_from_clock(clock: int, my_heading: int = config.LEADER_HEADING) -> int:
    """시계 → 방위. az = (heading + (clock − 12)·30) mod 360. clock 0 또는 heading 없음 → 0xFFFF."""
    if clock == 0 or my_heading == NO_HEADING:
        return NO_AZIMUTH
    return (my_heading + (clock - 12) * 30) % 360


def band_m(dist_band: int) -> float:
    """거리 구간 → 대표값(m). 없음·모름 → 20m."""
    return config.DIST_REP_M.get(dist_band, config.DIST_NONE_M)


def band_of(r_m: float) -> int:
    """거리(m) → 구간: 15m 미만 근(0), 30m 미만 중(1), 그 외 원(2)."""
    lo, hi = config.BAND_EDGES_M
    return 0 if r_m < lo else (1 if r_m < hi else 2)


def target_pos(rep_m: tuple[float, float], azimuth: int, dist_band: int) -> tuple[float, float]:
    d = band_m(dist_band)
    a = math.radians(azimuth)
    return rep_m[0] + d * math.sin(a), rep_m[1] + d * math.cos(a)


def bearing_range(p_m: tuple[float, float], t_m: tuple[float, float]) -> tuple[int, float]:
    dx, dy = t_m[0] - p_m[0], t_m[1] - p_m[1]
    return round_half_away(math.degrees(math.atan2(dx, dy))) % 360, math.hypot(dx, dy)


def peer_to_me(rep_m, azimuth, dist_band, me_m, my_heading=0):
    """다른 병사 보고 → 내 기준 (clock, band, bearing, range_m) (§9.5)."""
    b, r = bearing_range(me_m, target_pos(rep_m, azimuth, dist_band))
    return clock_from_azimuth(b, my_heading), band_of(r), b, r


def rssi_to_m(rssi: float, p1m: float = config.PATHLOSS_P1M_DBM, n: float = config.PATHLOSS_N) -> float:
    """경로손실 d = 10^((P1m − RSSI) / (10·n)) [m]."""
    return 10 ** ((p1m - rssi) / (10.0 * n))


def rssi_median(values) -> int | None:
    """최근 RSSI_WINDOW개의 중앙값. 짝수 개면 가운데 두 값 평균을 0쪽으로 버림(C 정수 나눗셈)."""
    s = sorted(list(values)[-config.RSSI_WINDOW:])
    n = len(s)
    if n == 0:
        return None
    if n % 2:
        return s[n // 2]
    return int((s[n // 2 - 1] + s[n // 2]) / 2)


def m_to_dm(v: float) -> int:
    """m → 0.1m 정수(0에서 먼 쪽 반올림, int16 범위로 자름)."""
    return max(-32767, min(32767, round_half_away(v * 10)))   # −32768(0x8000)은 "위치 모름" 값이라 피한다


TARGET_ERR_M = {0: 5.0, 1: 10.0, 2: 20.0}     # 거리 구간만으로 정한 표적 위치 오차(대표값의 절반)
TARGET_ERR_NONE_M = 20.0


def target_estimate(rep_m, azimuth: int, dist_band: int) -> dict:
    """병사 보고(보고자 위치 + 방위 + 거리 구간) → 분대장 기준 표적 위치 (§9.5와 같은 표적 계산).
    rep_m: 보고자 위치(분대장 원점, m). None이면 보고자를 분대장 자리로 보고 basis="leader_origin".
    방위가 없으면 표적 = 보고자 위치(그 병사 쪽), basis="toward_reporter"."""
    basis = "pos_table"
    if rep_m is None:
        rep_m, basis = (0.0, 0.0), "leader_origin"
    if azimuth == NO_AZIMUTH:
        x, y = rep_m
        err = band_m(dist_band) if dist_band != NO_DIST else TARGET_ERR_NONE_M
        basis = "toward_reporter" if basis == "pos_table" else basis
    else:
        x, y = target_pos(rep_m, azimuth, dist_band)
        err = TARGET_ERR_M.get(dist_band, TARGET_ERR_NONE_M)
    b, r = bearing_range((0.0, 0.0), (x, y))
    return {"x": round(x, 1), "y": round(y, 1), "bearing": b, "dist": round(r, 1), "err": err,
            "clock": clock_from_azimuth(b) if r >= 0.5 else 0, "basis": basis}
