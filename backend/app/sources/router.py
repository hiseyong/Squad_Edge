"""Realtime 시연용 라우터 WebSocket 허브.

분대장 단말기(또는 UNO Q SoftAP)가 `ws://<COP>/ws/router` 에 접속한다.

  상향(단말 → COP): 분대원 `unit.relpos` (+보고 등) → store.ingest
  하향(COP → 단말): downlink 메시지 중계 (명령·진동·보고 결과)

Realtime 역할 분담
  - 1분대장(1-1) GPS: COP mock (단말 unit.position 은 무시) — Arduino 연결 중에만
  - 1분대원(1-2~1-4) 상대좌표: unit.relpos (이상적 주기 1초)
  - 메시 링크: COP가 mock과 동일하게 합성
  - Arduino/라우터 끊김: 1분대 전원(1-1 포함) 두절 · 지도 비표시
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from fastapi import WebSocket, WebSocketDisconnect

from .ingest_util import normalize_event, should_ingest_hw_event

log = logging.getLogger("cop.router")

HW_SQUAD = "1"
HW_GPS_UNITS: tuple[str, ...] = ()  # 분대장 GPS는 COP mock
HW_RELPOS_UNITS = ("1-2", "1-3", "1-4")
MOCK_GPS_UNITS: tuple[str, ...] = ("1-1",)
# SoftAP/라우터 단절 시 두절 표시 대상 (분대장 mock GPS 포함)
NOLINK_ON_DISCONNECT: tuple[str, ...] = MOCK_GPS_UNITS + HW_RELPOS_UNITS
HW_SQUAD_UNITS = NOLINK_ON_DISCONNECT
HW_UNITS = HW_SQUAD_UNITS  # status API


class RouterHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._links: set[str] = set()  # "q3-ap" 등 WS 외 전송 경로
        self._last_rx: float = 0.0
        self._rx_count: int = 0
        self._lock = asyncio.Lock()

    @property
    def connected(self) -> bool:
        return len(self._clients) > 0 or len(self._links) > 0

    @property
    def clients(self) -> int:
        return len(self._clients)

    @property
    def links(self) -> set[str]:
        return set(self._links)

    def status(self) -> dict[str, Any]:
        return {
            "connected": self.connected,
            "clients": self.clients,
            "links": sorted(self._links),
            "last_rx": self._last_rx or None,
            "rx_count": self._rx_count,
            "hw_squad": HW_SQUAD,
            "hw_units": list(HW_SQUAD_UNITS),
            "hw_gps": list(HW_GPS_UNITS),
            "hw_relpos": list(HW_RELPOS_UNITS),
            "mock_gps": list(MOCK_GPS_UNITS),
            "period_s": 1.0,
        }

    async def register(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.add(ws)
        log.info("router client connected (%d)", len(self._clients))
        self._on_link_up()

    async def unregister(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)
        log.info("router client disconnected (%d)", len(self._clients))

    def attach_link(self, name: str) -> None:
        """WS 외 전송(Q3 SoftAP TCP 등)을 라우터 연결로 등록."""
        self._links.add(name)
        log.info("router link attach %s (links=%s ws=%d)", name, sorted(self._links), len(self._clients))
        self._on_link_up()

    def _on_link_up(self) -> None:
        """연결 복구 시 구 두절·측위대기 경보 정리."""
        try:
            from ..state import store
            store.clear_squad1_link_alerts()
        except Exception:
            pass

    def detach_link(self, name: str) -> bool:
        """링크 제거. 제거됐으면 True."""
        if name not in self._links:
            return False
        self._links.discard(name)
        log.info("router link detach %s (links=%s ws=%d)", name, sorted(self._links), len(self._clients))
        return True

    def note_rx(self) -> None:
        self._last_rx = time.time()
        self._rx_count += 1

    async def broadcast(self, line: str) -> None:
        dead: list[WebSocket] = []
        for ws in list(self._clients):
            try:
                await ws.send_text(line)
            except Exception:
                dead.append(ws)
        for ws in dead:
            await self.unregister(ws)


router_hub = RouterHub()


async def handle_router_ws(ws: WebSocket, store) -> None:
    """분대장 단말기 ↔ COP 양방향 라우터 소켓."""
    from ..downlink import downlink

    await ws.accept()
    await router_hub.register(ws)
    q = downlink.subscribe()

    async def pump_downlink() -> None:
        try:
            while True:
                line = await q.get()
                await ws.send_text(line)
        except (WebSocketDisconnect, asyncio.CancelledError, RuntimeError):
            pass

    down_task = asyncio.create_task(pump_downlink())
    try:
        await ws.send_text(json.dumps({
            "v": 1, "type": "router.hello", "src": "PL", "dst": "1-1",
            "data": {
                "mode": "realtime",
                "hw_gps": list(HW_GPS_UNITS),
                "hw_relpos": list(HW_RELPOS_UNITS),
                "hw_units": list(HW_SQUAD_UNITS),
                "mock_gps": list(MOCK_GPS_UNITS),
                "period_s": 1.0,
                "note": "1-1 GPS=COP mock(연결 시) · 1-2~1-4 relpos · 단절 시 1분대 전원 두절.",
            },
        }, ensure_ascii=False))
        while True:
            raw = await ws.receive_text()
            for line in raw.splitlines():
                line = line.strip()
                if not line.startswith("{"):
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("router bad json: %s", line[:120])
                    continue
                items = obj if isinstance(obj, list) else [obj]
                for item in items:
                    ev = normalize_event(item) if isinstance(item, dict) else None
                    if ev is None or not should_ingest_hw_event(ev):
                        continue
                    router_hub.note_rx()
                    store.ingest(ev)
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("router ws error")
    finally:
        down_task.cancel()
        downlink.unsubscribe(q)
        await router_hub.unregister(ws)
        # 마지막 클라이언트 종료 → 1분대 전원 두절 (1-1 포함)
        if not router_hub.connected:
            store.mark_units_nolink(NOLINK_ON_DISCONNECT, reason="라우터 연결 없음")
            log.info("router offline → mark nolink %s", list(NOLINK_ON_DISCONNECT))
