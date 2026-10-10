"""하향(소대장 → 분대장/병사) 메시지 송출 허브 + 감사 로그.

COP에서 만든 명령·보고 결과·진동 신호는 docs/TERMINAL_PROTOCOL.md 의 봉투 형식으로
여기에 들어오고, 연결된 모든 출력으로 동시에 나간다.

출력
  - SoftAP TCP (COP_Q3)      : q3_ap → squad-leader CopServer → 분대장(명령 텍스트)
  - WebSocket /ws/router     : 라우터 단말 양방향
  - WebSocket /ws/downlink   : 외부 게이트웨이 구독
  - Serial (COP_SERIAL)      : 같은 포트로 NDJSON 한 줄씩 기록
  - listener 콜백            : 시뮬레이터(가상 단말의 ACK 응답) 등
  - GET /api/downlink        : 최근 200건 (디버깅)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("cop.downlink")

AUDIT_PATH = Path(__file__).resolve().parents[1] / "data" / "audit.jsonl"


def audit(action: str, **kw: Any) -> None:
    """사후검토(AAR)용 감사 로그. 승인/기각/명령 등 지휘 결심을 모두 남긴다."""
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "action": action, **kw}, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("audit write failed: %s", e)


class Downlink:
    def __init__(self) -> None:
        self.seq = 0
        self.recent: deque[dict[str, Any]] = deque(maxlen=200)
        self._subs: set[asyncio.Queue] = set()
        self._writers: list[Callable[[str], None]] = []
        self._listeners: list[Callable[[dict[str, Any]], None]] = []

    # 출력 등록
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=500)
        self._subs.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subs.discard(q)

    def add_writer(self, fn: Callable[[str], None]) -> None:
        self._writers.append(fn)

    def add_listener(self, fn: Callable[[dict[str, Any]], None]) -> None:
        self._listeners.append(fn)

    # 송출
    def send(self, type_: str, dst: str, data: dict[str, Any], prio: str = "routine",
             ack: bool = False) -> dict[str, Any]:
        self.seq = (self.seq + 1) % 65536
        msg = {"v": 1, "type": type_, "src": "PL", "dst": dst, "seq": self.seq, "ts": time.time(),
               "prio": prio, "ack": ack, "ttl": 3, "data": data}
        self.recent.append(msg)
        line = json.dumps(msg, ensure_ascii=False)
        for q in list(self._subs):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                pass
        for w in self._writers:
            try:
                w(line + "\n")
            except Exception as e:
                log.warning("downlink writer error: %s", e)
        for fn in self._listeners:
            try:
                fn(msg)
            except Exception:
                log.exception("downlink listener error")
        return msg


def order_new_data(o: Any, recipients: list[str] | None = None, *, replay: bool = False) -> dict[str, Any]:
    """order.new data 페이로드 — SoftAP/라우터/시리얼 공통 (명령 텍스트 포함)."""
    targets = list(recipients if recipients is not None else getattr(o, "recipients", []))
    data: dict[str, Any] = {
        "id": o.id,
        "code": o.code,
        "text": o.text or "",
        "to": list(getattr(o, "to", []) or []),
        "recipients": targets,
        "params": dict(getattr(o, "params", None) or {}),
        "ref_report": getattr(o, "ref_report", None),
        "ack_required": True,
        "priority": getattr(o, "priority", "priority") or "priority",
    }
    if replay:
        data["replay"] = True
    return data


def order_cancel_data(o: Any, *, reason: str = "cancelled", by_code: str | None = None) -> dict[str, Any]:
    """order.cancel data — id·code·text·recipients (보드가 철회 문구 표시 가능)."""
    data: dict[str, Any] = {
        "id": o.id,
        "code": getattr(o, "code", ""),
        "text": getattr(o, "text", "") or "",
        "recipients": list(getattr(o, "recipients", []) or []),
        "reason": reason,
    }
    if by_code:
        data["by_code"] = by_code
    return data


downlink = Downlink()
