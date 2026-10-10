"""COP 하향(order.new 등) → BLE CMD_BUTTON / EMCON_SET."""
from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import frame_codec as fc  # noqa: E402

from .ids import cop_to_ble

# COP order.code → BLE cmd_code 이름
ORDER_TO_CMD: dict[str, str] = {
    "HALT": "HALT",
    "TAKE_COVER": "TAKE_COVER",
    "RALLY": "RALLY",
    "MOVE": "ADVANCE",
    "WEAPONS_HOLD": "CEASE_FIRE",
    "WEAPONS_FREE": "OPEN_FIRE",
    "RECHECK": "REPORT_STATUS",
    "FRAGO": "OBSERVE",
}


def recipients_to_ble_ids(recipients: list[str], squad: str) -> list[int]:
    """COP recipients → BLE 병사 ID.

    명령 하달은 분대장 SoftAP/MCU만 — 분대원 BLE 개별 전송 없음 → 항상 [].
    (mission.update 등 다른 경로에서 병사 지정이 필요하면 별도 호출.)
    """
    _ = recipients, squad
    return []


def _bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    """from (lat1,lon1) → (lat2,lon2) 절대방위 0–359."""
    φ1, φ2 = math.radians(lat1), math.radians(lat2)
    dλ = math.radians(lon2 - lon1)
    y = math.sin(dλ) * math.cos(φ2)
    x = math.cos(φ1) * math.sin(φ2) - math.sin(φ1) * math.cos(φ2) * math.cos(dλ)
    return int(round(math.degrees(math.atan2(y, x)))) % 360


def order_to_cmd_frame(
    order: dict[str, Any],
    *,
    seq: int,
    squad: str,
    leader_heading: int = 0,
    leader_lat: float | None = None,
    leader_lon: float | None = None,
) -> tuple[bytes, list[int], str] | None:
    """order.new data → (raw frame, ble_ids, cmd_name). 매핑 불가면 None.

    params.bearing / azimuth / clock / lat·lon 있으면 절대방위 반영.
    """
    code = str(order.get("code", "")).upper()
    cmd_name = ORDER_TO_CMD.get(code)
    if cmd_name is None:
        return None
    ble_ids = recipients_to_ble_ids(list(order.get("recipients") or ["*"]), squad)
    if not ble_ids:
        return None  # 타 분대 전용 — 이 보드에서 송신하지 않음
    params = order.get("params") or {}
    az = fc.NO_AZIMUTH
    if "azimuth" in params:
        az = int(params["azimuth"]) % 360
    elif "bearing" in params:
        az = int(params["bearing"]) % 360
    elif "clock" in params:
        clock = int(params["clock"])
        if 1 <= clock <= 12:
            az = (leader_heading + (clock - 12) * 30) % 360
    elif (
        leader_lat is not None and leader_lon is not None
        and isinstance(params.get("lat"), (int, float))
        and isinstance(params.get("lon"), (int, float))
    ):
        az = _bearing_deg(float(leader_lat), float(leader_lon), float(params["lat"]), float(params["lon"]))
    dist = fc.NO_DIST
    if "dist_band" in params:
        dist = int(params["dist_band"])
    prio = 1 if order.get("priority") == "urgent" or code in ("HALT", "TAKE_COVER", "WEAPONS_HOLD") else 0
    dst = fc.dst_mask(ble_ids) if len(ble_ids) < 5 else fc.DST_ALL_SOLDIERS
    raw = fc.encode(dict(
        type=fc.CMD_BUTTON,
        seq=seq & 0xFF,
        src=fc.LEADER_ID,
        dst=dst,
        cmd_code=fc.CMD_CODES[cmd_name],
        azimuth=az,
        dist_band=dist,
        extra=int(params.get("extra", 0)),
        priority=prio,
    ))
    return raw, ble_ids, cmd_name


def emcon_frame(mode: int, seq: int, ble_ids: list[int] | None = None) -> bytes:
    ids = ble_ids or list(range(1, 6))
    dst = fc.DST_ALL_SOLDIERS if len(ids) >= 5 else fc.dst_mask(ids)
    return fc.encode(dict(
        type=fc.EMCON_SET, seq=seq & 0xFF, src=fc.LEADER_ID, dst=dst, mode=int(mode),
    ))
