"""위경도 → UTM → 군사 격자 좌표(MGRS). 외부 라이브러리 없이 (WGS84, Snyder 공식).

교범 표 9-1(SALUTE 위치): "보통 격자 좌표이며 100,000m 격자 구역 표시를 포함해야 한다 … 8자리 격자 좌표".
→ 기본 출력 "52S CG 3299 6612" (구역 + 100km 구역 문자 + 동·북 각 4자리 = 10m 단위).

분대 안의 상대 위치(분대장 원점, 동·북 m)는 UTM 좌표에 그대로 더한다. 진북과 도북의 차이(한반도 약 1~2도)는
분대 규모(수백 m)에서 수 m 수준이라 무시한다.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

_A = 6378137.0
_F = 1 / 298.257223563
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)
_K0 = 0.9996
_BANDS = "CDEFGHJKLMNPQRSTUVWX"
_COLS = ("ABCDEFGH", "JKLMNPQR", "STUVWXYZ")
_ROWS = "ABCDEFGHJKLMNPQRSTUV"


@dataclass(frozen=True)
class Utm:
    zone: int
    band: str
    easting: float
    northing: float

    def offset(self, east_m: float, north_m: float) -> "Utm":
        return Utm(self.zone, self.band, self.easting + east_m, self.northing + north_m)


def latlon_to_utm(lat: float, lon: float) -> Utm:
    if not -80 <= lat <= 84:
        raise ValueError("MGRS/UTM 범위 밖 (극지방)")
    zone = int((lon + 180) // 6) + 1
    if 56 <= lat < 64 and 3 <= lon < 12:          # 노르웨이 예외
        zone = 32
    if lat >= 72:                                 # 스발바르 예외
        zone = 31 if lon < 9 else 33 if lon < 21 else 35 if lon < 33 else 37
    band = _BANDS[min(int((lat + 80) // 8), len(_BANDS) - 1)]
    phi, lam = math.radians(lat), math.radians(lon)
    lam0 = math.radians((zone - 1) * 6 - 180 + 3)
    n = _A / math.sqrt(1 - _E2 * math.sin(phi) ** 2)
    t = math.tan(phi) ** 2
    c = _EP2 * math.cos(phi) ** 2
    a = math.cos(phi) * (lam - lam0)
    m = _A * ((1 - _E2 / 4 - 3 * _E2 ** 2 / 64 - 5 * _E2 ** 3 / 256) * phi
              - (3 * _E2 / 8 + 3 * _E2 ** 2 / 32 + 45 * _E2 ** 3 / 1024) * math.sin(2 * phi)
              + (15 * _E2 ** 2 / 256 + 45 * _E2 ** 3 / 1024) * math.sin(4 * phi)
              - (35 * _E2 ** 3 / 3072) * math.sin(6 * phi))
    e = _K0 * n * (a + (1 - t + c) * a ** 3 / 6 + (5 - 18 * t + t ** 2 + 72 * c - 58 * _EP2) * a ** 5 / 120) + 500000
    nn = _K0 * (m + n * math.tan(phi) * (a ** 2 / 2 + (5 - t + 9 * c + 4 * c ** 2) * a ** 4 / 24
                                          + (61 - 58 * t + t ** 2 + 600 * c - 330 * _EP2) * a ** 6 / 720))
    if lat < 0:
        nn += 10000000
    return Utm(zone, band, e, nn)


def utm_to_mgrs(u: Utm, digits: int = 8) -> str:
    """digits = 동·북 합친 자릿수 (8 → 10m, 10 → 1m)."""
    col = _COLS[(u.zone - 1) % 3][int(u.easting // 100000) - 1]
    row = _ROWS[(int(u.northing // 100000) + (5 if u.zone % 2 == 0 else 0)) % 20]
    half = digits // 2
    div = 10 ** (5 - half)
    e = int(u.easting % 100000) // div
    n = int(u.northing % 100000) // div
    return f"{u.zone}{u.band} {col}{row} {e:0{half}d} {n:0{half}d}"


def latlon_to_mgrs(lat: float, lon: float, digits: int = 8) -> str:
    return utm_to_mgrs(latlon_to_utm(lat, lon), digits)


CARDINALS = ("북", "북동", "동", "남동", "남", "남서", "서", "북서")


def cardinal(az: float) -> str:
    """방위각 → 8방위 (보고 문장용)."""
    return CARDINALS[int(((az % 360) + 22.5) // 45) % 8]
