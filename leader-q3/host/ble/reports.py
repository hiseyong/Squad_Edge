"""병사 BLE 보고 → COP ingest 이벤트."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import frame_codec as fc  # noqa: E402

from .ids import ble_to_cop

DIST_M = {0: 50, 1: 100, 2: 200}


def soldier_report_to_events(msg: dict[str, Any], *, squad: str) -> list[dict[str, Any]]:
    """병사 Notify 프레임 → COP 이벤트 목록 (없으면 [])."""
    t = msg["type"]
    sid = int(msg["src"])
    uid = ble_to_cop(squad, sid)
    out: list[dict[str, Any]] = []

    if t == fc.CONTACT:
        loc: dict[str, Any] = {"err": 80}
        if msg.get("azimuth", fc.NO_AZIMUTH) != fc.NO_AZIMUTH:
            loc = {
                "bearing": int(msg["azimuth"]),
                "dist": DIST_M.get(int(msg.get("dist_band", 0xFF)), 100),
                "err": 30,
            }
        out.append({
            "type": "report.new",
            "bytes": 40,
            "data": {
                "type": "CONTACT",
                "sender": uid,
                "priority": "urgent",
                "conf": 0.9,
                "summary": f"{uid} 접적",
                "fields": {
                    "kind": "contact",
                    "activity": "접적",
                    "unit": f"접적 · {uid}",
                    "location": loc,
                    "size": int(msg.get("count") or 0) or None,
                },
                "missing": [] if "bearing" in loc else ["bearing"],
            },
        })
    elif t == fc.CASUALTY_SELF:
        out.append({"type": "unit.status", "bytes": 4, "data": {"id": uid, "status": "wia"}})
        out.append({
            "type": "alert.new",
            "data": {"level": "crit", "kind": "wia", "msg": f"{uid} 본인 부상", "unit_id": uid},
        })
    elif t == fc.CASUALTY_FOUND:
        out.append({
            "type": "alert.new",
            "data": {"level": "crit", "kind": "wia", "msg": f"{uid} 아군 부상자 발견", "unit_id": uid},
        })
    elif t == fc.WEAPON_AMMO:
        out.append({
            "type": "alert.new",
            "data": {"level": "warn", "kind": "ammo", "msg": f"{uid} 탄약/화기 문제", "unit_id": uid},
        })
    elif t == fc.HAZARD:
        out.append({
            "type": "alert.new",
            "data": {"level": "warn", "kind": "hazard", "msg": f"{uid} 위험물·장애물", "unit_id": uid},
        })
    elif t in (fc.OK_READY, fc.SUSPICIOUS):
        pass  # 로그만 / 선택 확장
    return out


def link_events_from_ranging(
    sid: int,
    peers: list[dict[str, Any]],
    *,
    squad: str,
) -> list[dict[str, Any]]:
    a = ble_to_cop(squad, sid)
    out = []
    for p in peers:
        pid = int(p["peer_id"])
        if pid > 5:
            continue
        b = ble_to_cop(squad, pid)
        out.append({
            "type": "link.update",
            "bytes": 6,
            "data": {"a": a, "b": b, "rssi": int(p["rssi_avg"])},
        })
    return out
