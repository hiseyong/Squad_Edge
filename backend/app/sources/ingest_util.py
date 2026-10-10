"""게이트웨이/라우터/Q3 SoftAP JSON → store.ingest 가능 이벤트로 정규화.

분대장 draft-1 보고(SPOTREP+SITREP, priority=flash, text 필드 등)도 여기서 맞춘다.
BATTLE_DATA: zlib+base64+json payload 펼침.
"""
from __future__ import annotations

import base64
import json
import logging
import zlib
from typing import Any

log = logging.getLogger("cop.ingest")

# 단말 source → COP PosSource
_POS_SOURCE = {
    "demo": "gps",
    "softap": "gps",
    "q3": "gps",
    "gps": "gps",
    "ble-rel": "ble-rel",
    "manual": "manual",
    "dr": "dr",
}

# 우선순위 별칭 (미군 flash/immediate 등)
_PRIO = {
    "flash": "urgent",
    "immediate": "urgent",
    "priority": "priority",
    "routine": "routine",
    "urgent": "urgent",
}

# 보고 type 별칭 → COP ReportType
_REPORT_TYPE = {
    "SPOTREP": "SPOT",
    "SPOTREP+SITREP": "SPOTREP+SITREP",
    "SPOT_SITREP": "SPOTREP+SITREP",
    "COMBINED": "SPOTREP+SITREP",
    "BATTLE_DATA": "BATTLE_DATA",
    "BATTLE": "BATTLE_DATA",
    "SQ-BATTLE": "BATTLE_DATA",
}


def decode_compressed_payload(payload: Any) -> Any | None:
    """payload: {enc:'zlib+base64+json', data:'…'} → dict/str. 실패 시 None."""
    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, str) or not data:
        return None
    enc = str(payload.get("enc") or "").lower()
    try:
        raw = data.encode("ascii") if "base64" not in enc else base64.b64decode(data)
        if "zlib" in enc:
            raw = zlib.decompress(raw)
        if "json" in enc or (isinstance(raw, (bytes, bytearray)) and raw[:1] in (b"{", b"[")):
            return json.loads(raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else raw)
        if isinstance(raw, (bytes, bytearray)):
            return raw.decode("utf-8", errors="replace")
        return raw
    except Exception as e:
        log.warning("report payload decode failed enc=%s: %s", enc or "?", e)
        return None


# realtime: 분대장 GPS·메시 링크는 COP mock — HW가 보내도 ingest 하지 않음
_SKIP_HW_POSITION_IDS = frozenset({"1-1"})
_SKIP_HW_TYPES = frozenset({"link.update"})


def should_ingest_hw_event(ev: dict[str, Any]) -> bool:
    """라우터/Q3 SoftAP 상향 이벤트 중 COP mock과 충돌하는 것을 걸러낸다."""
    typ = ev.get("type")
    if typ in _SKIP_HW_TYPES:
        return False
    if typ == "unit.position":
        data = ev.get("data") or {}
        if isinstance(data, dict) and data.get("id") in _SKIP_HW_POSITION_IDS:
            return False
    return True


def normalize_event(raw: dict[str, Any]) -> dict[str, Any] | None:
    """§2.3 봉투 또는 {type,data,bytes} 짧은 형식을 ingest 이벤트로 만든다."""
    if not isinstance(raw, dict):
        return None
    if "type" not in raw or "data" not in raw:
        return None
    typ = raw["type"]
    data = raw["data"]
    if not isinstance(data, dict):
        return None

    if typ == "router.hello":
        return None  # 상태 전용 — 호출측에서 처리

    data = dict(data)
    if typ == "unit.position":
        src = data.get("source")
        if isinstance(src, str):
            data["source"] = _POS_SOURCE.get(src.lower(), "gps")
    elif typ == "report.new":
        data = normalize_report_data(data)

    ev: dict[str, Any] = {"type": typ, "data": data}
    if "bytes" in raw and raw["bytes"] is not None:
        ev["bytes"] = raw["bytes"]
    return ev


def normalize_report_data(d: dict[str, Any]) -> dict[str, Any]:
    """draft-1 / 확장 보고 → Report 모델에 맞는 data."""
    out = dict(d)

    # type
    t = str(out.get("type") or "FREE")
    t_up = t.upper()
    out["type"] = _REPORT_TYPE.get(t_up, t_up if t_up in (
        "SALUTE", "SPOT", "MEDEVAC", "SITREP", "CONTACT", "FREE", "SPOTREP+SITREP", "BATTLE_DATA",
    ) else t)
    if out["type"] not in (
        "SALUTE", "SPOT", "MEDEVAC", "SITREP", "CONTACT", "FREE", "SPOTREP+SITREP", "BATTLE_DATA",
    ):
        out["type"] = "FREE"

    # priority
    p = str(out.get("priority") or "routine").lower()
    out["priority"] = _PRIO.get(p, "priority" if p not in _PRIO else p)
    if out["priority"] not in ("routine", "priority", "urgent"):
        out["priority"] = "urgent" if p in ("flash", "immediate") else "routine"

    # draft-1 / battle: text → raw_text
    if out.get("text") and not out.get("raw_text"):
        out["raw_text"] = out["text"]
    # format 메타는 fields에 보존 (fmt | format)
    fmt = out.pop("format", None) or out.pop("fmt", None)
    fields = dict(out.get("fields") or {})
    if fmt:
        fields["_format"] = fmt

    # BATTLE_DATA / 압축 payload → 펼쳐서 fields에 보관 (원본 base64는 보관하지 않음)
    payload = out.pop("payload", None)
    decoded = decode_compressed_payload(payload)
    if isinstance(decoded, dict):
        fields["battle"] = decoded
        if not fmt and decoded.get("fmt"):
            fields["_format"] = decoded["fmt"]
        if decoded.get("battle_id"):
            fields.setdefault("battle_id", decoded["battle_id"])
        if isinstance(decoded.get("result"), dict):
            fields.setdefault("result", decoded["result"])
        if not out.get("summary") and decoded.get("summary"):
            out["summary"] = decoded["summary"]
        if not out.get("raw_text"):
            mins = decoded.get("minutes")
            parts = []
            if decoded.get("summary"):
                parts.append(str(decoded["summary"]))
            if isinstance(mins, list) and mins:
                parts.append("— 무전 회의록 —")
                parts.extend(str(m) for m in mins)
            if parts:
                out["raw_text"] = "\n".join(parts)
    elif decoded is not None:
        fields["battle"] = decoded

    # 봉투에 있던 battle 메타
    bid = out.pop("battle_id", None)
    if bid:
        fields.setdefault("battle_id", bid)
    res = out.pop("result", None)
    if isinstance(res, dict):
        fields.setdefault("result", res)

    if "text" in out:
        out.pop("text", None)
    out["fields"] = fields

    # location.ref 만 있고 sender 없으면 ref를 sender로
    loc = fields.get("location")
    if isinstance(loc, dict) and not out.get("sender") and loc.get("ref"):
        out["sender"] = loc["ref"]

    # Report 생성에 불필요한 키 제거 (pydantic ignore 이지만 안전하게)
    for k in ("v", "src", "dst", "seq", "ts", "prio", "ttl", "ack"):
        out.pop(k, None)

    return out
