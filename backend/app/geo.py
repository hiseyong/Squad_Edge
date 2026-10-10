"""간단한 지리 계산 헬퍼 (소부대 수백 m 범위에서는 평면 근사로 충분)."""
from __future__ import annotations

import math

EARTH_R = 6_371_000.0


def offset(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    """(lat, lon)에서 동쪽 east_m, 북쪽 north_m 만큼 이동한 좌표."""
    dlat = north_m / EARTH_R
    dlon = east_m / (EARTH_R * math.cos(math.radians(lat)))
    return lat + math.degrees(dlat), lon + math.degrees(dlon)


def enu(lat0: float, lon0: float, lat: float, lon: float) -> tuple[float, float]:
    """기준점 대비 (east, north) [m]."""
    north = math.radians(lat - lat0) * EARTH_R
    east = math.radians(lon - lon0) * EARTH_R * math.cos(math.radians(lat0))
    return east, north


def distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    e, n = enu(lat1, lon1, lat2, lon2)
    return math.hypot(e, n)


def bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """진북 기준 방위각 [deg, 0~360)."""
    e, n = enu(lat1, lon1, lat2, lon2)
    return (math.degrees(math.atan2(e, n)) + 360.0) % 360.0


def polar(lat: float, lon: float, bearing_deg: float, dist_m: float) -> tuple[float, float]:
    b = math.radians(bearing_deg)
    return offset(lat, lon, dist_m * math.sin(b), dist_m * math.cos(b))


def clock_dir(rel_bearing: float) -> int:
    """상대 방위각 → 시계 방향(1~12시)."""
    h = round(((rel_bearing % 360) / 30.0)) % 12
    return 12 if h == 0 else h
