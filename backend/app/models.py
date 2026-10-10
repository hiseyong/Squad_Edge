"""COP 데이터 모델. 프론트엔드 `src/types.ts`와 1:1로 맞춘다."""
from __future__ import annotations

import time
import uuid
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


def now() -> float:
    return time.time()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


UnitStatus = Literal["ok", "wia", "kia", "nolink"]
PosSource = Literal["gps", "ble-rel", "manual", "dr", "demo"]


class Unit(BaseModel):
    id: str
    callsign: str
    role: Literal["pl", "sl", "rifleman", "gunner", "medic", "radio"] = "rifleman"
    squad: str = "HQ"                      # "HQ", "1", "2", "3"
    lat: Optional[float] = None
    lon: Optional[float] = None
    heading: float = 0.0
    pos_err: float = 0.0                   # 위치 불확실성 반경 [m]
    pos_source: PosSource = "gps"
    status: UnitStatus = "ok"
    battery: float = 100.0                 # %
    rssi: Optional[float] = None           # 게이트웨이 기준 최근 RSSI [dBm]
    last_seen: float = Field(default_factory=now)
    trail: list[tuple[float, float]] = Field(default_factory=list)


class Target(BaseModel):
    id: str = Field(default_factory=lambda: new_id("T"))
    affiliation: Literal["hostile", "unknown", "neutral"] = "unknown"
    kind: str = "infantry"                 # infantry / vehicle / movement / sniper ...
    label: str = ""
    lat: float
    lon: float
    count: Optional[int] = None
    activity: str = ""
    err_m: float = 30.0
    conf: float = 0.5
    reported_by: Optional[str] = None
    source: Literal["voice", "sensor", "manual", "fusion"] = "voice"
    status: Literal["pending", "confirmed", "rejected"] = "pending"
    first_seen: float = Field(default_factory=now)
    last_seen: float = Field(default_factory=now)


ReportType = Literal[
    "SALUTE", "SPOT", "MEDEVAC", "SITREP", "CONTACT", "FREE", "SPOTREP+SITREP", "BATTLE_DATA",
]


class Report(BaseModel):
    model_config = {"extra": "ignore"}

    id: str = Field(default_factory=lambda: new_id("R"))
    type: ReportType = "FREE"
    sender: str                             # unit id
    ts: float = Field(default_factory=now)
    priority: Literal["routine", "priority", "urgent"] = "routine"
    raw_text: str = ""                      # STT 원문 (draft-1 text 포함)
    summary: str = ""                       # AI 한 줄 요약
    fields: dict[str, Any] = Field(default_factory=dict)  # 양식 필드 (+ draft-1 friendly/enemy…)
    missing: list[str] = Field(default_factory=list)      # 비어있는 필수 항목
    conf: float = 1.0
    status: Literal["pending", "confirmed", "rejected"] = "confirmed"
    target_id: Optional[str] = None
    bytes: int = 0                          # 무선 전송 크기 추정
    # --- 승인 워크플로
    decided_by: Optional[str] = None        # 승인/기각한 노드 (보통 PL)
    decided_at: Optional[float] = None
    decision_note: str = ""
    recheck_count: int = 0                  # 재확인 요청 횟수
    sender_acked: bool = False              # 결과가 보고자 단말에 도달했는지
    history: list[dict[str, Any]] = Field(default_factory=list)  # [{ts, action, by, note, edits}]


OrderCode = Literal["HALT", "MOVE", "RALLY", "TAKE_COVER", "WEAPONS_HOLD", "WEAPONS_FREE",
                    "RECHECK", "FRAGO"]


class Order(BaseModel):
    """소대장 → 예하 분대/병사 명령. 수신 단말의 ACK를 집계한다."""
    id: str = Field(default_factory=lambda: new_id("O"))
    code: OrderCode = "FRAGO"
    text: str = ""
    to: list[str] = Field(default_factory=lambda: ["*"])   # 분대 번호 / 노드 ID / "*"
    recipients: list[str] = Field(default_factory=list)    # 실제 수신 대상 = 분대장(SL) ID만
    params: dict[str, Any] = Field(default_factory=dict)   # {lat, lon} 목표·집결지 등
    priority: Literal["routine", "priority", "urgent"] = "priority"
    issuer: str = "PL"
    ts: float = Field(default_factory=now)
    acks: dict[str, float] = Field(default_factory=dict)   # node_id → ack 시각
    status: Literal["sent", "partial", "acked", "cancelled", "expired", "superseded"] = "sent"
    ref_report: Optional[str] = None                        # RECHECK 등 보고 연계
    tx_count: int = 1                                       # 송신(재전송 포함) 횟수
    last_tx: float = Field(default_factory=now)


class Sensor(BaseModel):
    id: str
    kind: Literal["pir", "acoustic", "ultrasonic", "seismic"] = "pir"
    lat: float
    lon: float
    status: Literal["idle", "triggered", "offline"] = "idle"
    last_trigger: Optional[float] = None
    battery: float = 100.0
    last_seen: float = Field(default_factory=now)


class Link(BaseModel):
    id: str                                 # "a|b" (정렬)
    a: str
    b: str
    rssi: float
    ts: float = Field(default_factory=now)


class Alert(BaseModel):
    id: str = Field(default_factory=lambda: new_id("A"))
    level: Literal["info", "warn", "crit"] = "info"
    kind: str = "generic"
    msg: str
    unit_id: Optional[str] = None
    ts: float = Field(default_factory=now)
    ack: bool = False


class Stats(BaseModel):
    started: float = Field(default_factory=now)
    tx_bytes: int = 0
    tx_msgs: int = 0
    tx_by_type: dict[str, int] = Field(default_factory=dict)
    voice_equiv_bytes: int = 0              # 보고류를 음성으로 보냈을 때 추정치
    voiceable_bytes: int = 0                # 보고류(음성으로 할 법한 메시지)의 실제 송신량


class Mission(BaseModel):
    name: str = "OP NIGHTOWL · 소대 정찰"
    emcon: bool = False
    origin: tuple[float, float] = (36.3005, 127.4185)
    objective: Optional[tuple[float, float]] = None
    route: list[tuple[float, float]] = Field(default_factory=list)
    phase_lines: list[dict[str, Any]] = Field(default_factory=list)


class Event(BaseModel):
    """외부 소스(게이트웨이, 음성 AI, 시뮬레이터)가 넣는 표준 이벤트 봉투."""
    type: str
    data: dict[str, Any] = Field(default_factory=dict)
    bytes: Optional[int] = None             # 실제 무선 프레임 크기를 알면 기입
