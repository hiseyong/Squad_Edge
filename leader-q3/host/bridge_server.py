#!/usr/bin/env python3
"""분대장1 SoftAP TCP + BLE(NU40) 브리지 — Arduino UNO Q Linux.

  SoftAP(192.168.4.1) + TCP :9000 NDJSON ↔ COP
  BLE Central ↔ SQ1-S1~S5 (측위 POS_TABLE, 명령, 보고 중계)

사용:
  sudo ./ap_start.sh
  python3 bridge_server.py                 # BLE+데모 GPS
  python3 bridge_server.py --no-ble        # SoftAP TCP만
  python3 bridge_server.py --demo --no-ble # 보드 없이 COP 연동 시험
  python3 bridge_server.py --beacon-port /dev/ttyACM0
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import random
import time
from typing import Any

from ble.central import SquadBle
from ble.ids import ble_to_cop
from config import (
    AP_IP,
    AP_SSID,
    BEACON_BAUD,
    BEACON_PORT,
    BLE_ENABLE,
    BLE_FORMATION,
    BLE_LOCALIZE_S,
    BLE_PATHLOSS_N,
    BLE_PATHLOSS_P1M,
    BLE_RELAY,
    DEMO_LAT,
    DEMO_LON,
    LISTEN_HOST,
    LISTEN_PORT,
    MEMBERS,
    NODE_ID,
    PERIOD_S,
    RPC_ORDER,
    RPC_PING,
    RPC_TELEMETRY,
    SQUAD_ID,
    USE_BRIDGE,
    parse_ble_only,
)

log = logging.getLogger("q3.bridge")

_PRESET = {
    "1-2": (-9.0, -8.0),
    "1-3": (9.0, -8.0),
    "1-4": (-18.0, -16.0),
}


def _offset(lat: float, lon: float, east_m: float, north_m: float) -> tuple[float, float]:
    r = 6_371_000.0
    return (
        lat + math.degrees(north_m / r),
        lon + math.degrees(east_m / (r * math.cos(math.radians(lat)))),
    )


class TelemetrySource:
    """MCU Bridge / 데모 GPS + (선택) BLE 측위 분대원 좌표."""

    def __init__(self, use_bridge: bool, ble: SquadBle | None = None) -> None:
        self._bridge = None
        self._t0 = time.time()
        self.ble = ble
        if use_bridge:
            try:
                from arduino.app_utils import Bridge  # type: ignore

                Bridge.begin()
                pong = Bridge.call(RPC_PING)
                log.info("MCU Bridge ok (%s=%s)", RPC_PING, pong)
                self._bridge = Bridge
            except Exception as e:
                log.warning("Bridge 사용 불가 → 데모 포즈: %s", e)

    def snapshot(self) -> dict[str, Any]:
        base = None
        if self._bridge is not None:
            try:
                raw = self._bridge.call(RPC_TELEMETRY)
                if isinstance(raw, (bytes, bytearray)):
                    raw = raw.decode("utf-8", "ignore")
                obj = json.loads(str(raw))
                if isinstance(obj, dict) and "lat" in obj:
                    base = obj
            except Exception as e:
                log.warning("telemetry_json 실패: %s", e)
        if base is None:
            base = self._demo_gps()
        # BLE 측위가 있으면 members 덮어쓰기
        if self.ble is not None:
            members = []
            for m in self.ble.telemetry_members():
                members.append({
                    "id": ble_to_cop(SQUAD_ID, m["ble_id"]),
                    "dx": m["dx"],
                    "dy": m["dy"],
                    "err": m["err"],
                    "heading": m.get("heading", base.get("heading", 0)),
                })
            if members:
                base["members"] = members
                base["pose_source"] = "ble-localize"
            else:
                base["pose_source"] = "ble-waiting"
        else:
            base.setdefault("members", self._demo_members(base.get("heading", 45)))
            base["pose_source"] = "demo"
        return base

    def notify_order(self, notice: str) -> None:
        """MCU Bridge RPC order_notify — code 또는 'CODE|text' (길이 제한은 MCU 버퍼)."""
        if self._bridge is None:
            return
        try:
            # Bridge RPC 인자 과도 길이 방지 (MCU g_last_order ≈ 160B)
            payload = notice if len(notice) <= 150 else notice[:147] + "…"
            self._bridge.call(RPC_ORDER, payload)
        except Exception as e:
            log.warning("order_notify 실패: %s", e)

    def _demo_gps(self) -> dict[str, Any]:
        elapsed = time.time() - self._t0
        hdg = (45 + math.sin(elapsed / 20) * 10) % 360
        dist = elapsed * 1.2
        rad = math.radians(45)
        lat, lon = _offset(DEMO_LAT, DEMO_LON, dist * math.sin(rad), dist * math.cos(rad))
        return {
            "node": NODE_ID,
            "squad": SQUAD_ID,
            "lat": lat,
            "lon": lon,
            "heading": hdg,
            "battery": max(40, 95 - elapsed / 60),
            "err": 3.0,
        }

    def _demo_members(self, heading: float) -> list[dict[str, Any]]:
        elapsed = time.time() - self._t0
        wobble = math.sin(elapsed / 8) * 1.5
        out = []
        for uid in MEMBERS:
            dx, dy = _PRESET[uid]
            out.append({
                "id": uid,
                "dx": dx + wobble + random.gauss(0, 0.4),
                "dy": dy + random.gauss(0, 0.4),
                "err": random.uniform(3.5, 6.0),
                "heading": heading,
            })
        return out


def events_from_tel(tel: dict[str, Any], *, synthetic_links: bool) -> list[dict[str, Any]]:
    nid = tel.get("node") or NODE_ID
    out: list[dict[str, Any]] = [{
        "v": 1,
        "type": "unit.position",
        "src": nid,
        "dst": "PL",
        "bytes": 18,
        "data": {
            "id": nid,
            "lat": float(tel["lat"]),
            "lon": float(tel["lon"]),
            "heading": float(tel.get("heading", 0)),
            "err": float(tel.get("err", 3.0)),
            "source": "gps",
            "battery": int(tel.get("battery", 90)),
        },
    }]
    for m in tel.get("members") or []:
        out.append({
            "v": 1,
            "type": "unit.relpos",
            "src": nid,
            "dst": "PL",
            "bytes": 14,
            "data": {
                "id": m["id"],
                "ref": nid,
                "dx": float(m["dx"]),
                "dy": float(m["dy"]),
                "err": float(m.get("err", 5.0)),
                "heading": float(m.get("heading", tel.get("heading", 0))),
                "battery": int(tel.get("battery", 90)),
            },
        })
    if synthetic_links:
        for a, b in ((nid, "1-2"), (nid, "1-3"), (nid, "1-4"), ("1-2", "1-3")):
            out.append({
                "type": "link.update",
                "bytes": 6,
                "data": {"a": a, "b": b, "rssi": -55 - random.randint(0, 20)},
            })
    return out


class BridgeServer:
    def __init__(self, tel: TelemetrySource, period: float, ble: SquadBle | None = None) -> None:
        self.tel = tel
        self.period = period
        self.ble = ble
        self._clients: set[asyncio.StreamWriter] = set()
        self._lock = asyncio.Lock()
        self._uplink: asyncio.Queue[list[dict[str, Any]]] = asyncio.Queue(maxsize=200)

    def push_uplink(self, events: list[dict[str, Any]]) -> None:
        try:
            self._uplink.put_nowait(events)
        except asyncio.QueueFull:
            pass

    async def broadcast_events(self, events: list[dict[str, Any]]) -> None:
        if not events:
            return
        payload = "".join(json.dumps(ev, ensure_ascii=False) + "\n" for ev in events).encode()
        dead: list[asyncio.StreamWriter] = []
        async with self._lock:
            clients = list(self._clients)
        for w in clients:
            try:
                w.write(payload)
                await w.drain()
            except Exception:
                dead.append(w)
        for w in dead:
            async with self._lock:
                self._clients.discard(w)

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info("peername")
        log.info("COP client connected %s", peer)
        async with self._lock:
            self._clients.add(writer)
        hello = {
            "v": 1,
            "type": "router.hello",
            "src": NODE_ID,
            "dst": "PL",
            "data": {
                "role": "squad_leader",
                "node": NODE_ID,
                "squad": SQUAD_ID,
                "hw_gps": [],
                "mock_gps": [NODE_ID],
                "hw_relpos": list(MEMBERS),
                "period_s": self.period,
                "ap_ip": AP_IP,
                "transport": "tcp-ndjson",
                "downlink": True,
                "ble": self.ble is not None,
                "formation": self.ble.engine.formation if self.ble else None,
            },
        }
        try:
            writer.write((json.dumps(hello, ensure_ascii=False) + "\n").encode())
            await writer.drain()
            rx = asyncio.create_task(self._pump_rx(reader, writer))
            tx = asyncio.create_task(self._pump_tx(writer))
            up = asyncio.create_task(self._pump_uplink())
            done, pending = await asyncio.wait({rx, tx}, return_when=asyncio.FIRST_COMPLETED)
            for t in pending | {up}:
                t.cancel()
            for t in done:
                if t.exception():
                    log.debug("client task end: %s", t.exception())
        finally:
            async with self._lock:
                self._clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            log.info("COP client disconnected %s", peer)

    async def _pump_uplink(self) -> None:
        while True:
            events = await self._uplink.get()
            await self.broadcast_events(events)

    async def _pump_tx(self, writer: asyncio.StreamWriter) -> None:
        while True:
            tel = self.tel.snapshot()
            if self.ble is not None:
                self.ble.leader_heading = int(tel.get("heading", 0)) % 360
                try:
                    self.ble.leader_lat = float(tel["lat"])
                    self.ble.leader_lon = float(tel["lon"])
                except (KeyError, TypeError, ValueError):
                    pass
            for ev in events_from_tel(tel, synthetic_links=self.ble is None):
                writer.write((json.dumps(ev, ensure_ascii=False) + "\n").encode())
            await writer.drain()
            await asyncio.sleep(self.period)

    async def _pump_rx(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        while True:
            raw = await reader.readline()
            if not raw:
                raise ConnectionError("eof")
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                log.warning("bad json: %s", line[:120])
                continue
            await self._on_downlink(obj, writer)

    def _squad_targets(self, data: dict[str, Any], dst: str) -> list[str]:
        """이 보드가 처리할 수신자. 명령은 분대장(SQUAD-1)만 — 분대원 개인 전송 없음."""
        sl = f"{SQUAD_ID}-1"
        if dst == sl or dst == NODE_ID:
            return [sl]
        if dst.startswith(f"{SQUAD_ID}-") and dst != sl:
            return []  # 분대원 개인 dst — 무시
        if dst == SQUAD_ID:
            return [sl]
        pool = list(data.get("recipients") or []) or list(data.get("to") or [])
        for r in pool:
            rs = str(r)
            if rs in ("*", SQUAD_ID, sl) or rs.startswith(f"{SQUAD_ID}-"):
                return [sl]
        return []

    async def _on_downlink(self, obj: dict[str, Any], writer: asyncio.StreamWriter) -> None:
        typ = obj.get("type")
        data = obj.get("data") if isinstance(obj.get("data"), dict) else {}
        dst = str(obj.get("dst") or "")
        log.info("↓ %s dst=%s %s", typ, dst, json.dumps(data, ensure_ascii=False)[:160])

        # 타 분대 전용은 무시 (mission.update 는 전역)
        if typ in ("order.new", "order.cancel"):
            if not self._squad_targets(data, dst):
                log.debug("↓ %s: 타 분대/분대원 — 무시", typ)
                return
        elif typ in ("haptic", "report.update"):
            if dst and not (dst.startswith(f"{SQUAD_ID}-") or dst in ("*", SQUAD_ID, NODE_ID)):
                return
            # 햅틱도 분대장 단말만
            if typ == "haptic" and dst.startswith(f"{SQUAD_ID}-") and dst != f"{SQUAD_ID}-1":
                return

        # 명령은 SoftAP→MCU만. 분대원 BLE CMD_BUTTON 미전송.
        # mission.update / (비명령) haptic 만 BLE 경로 유지
        ble_acks: list[dict[str, Any]] = []
        if self.ble is not None and typ in ("mission.update",):
            ble_acks = await self.ble.handle_cop_downlink(obj)
            for ack in ble_acks:
                writer.write((json.dumps(ack) + "\n").encode())
            if ble_acks:
                await writer.drain()

        # MCU LED + 명령 텍스트 (Arduino Bridge RPC order_notify)
        if typ == "order.new":
            code = str(data.get("code") or "")
            text = str(data.get("text") or "").strip()
            notice = f"{code}|{text}" if text else code
            log.info("↓ order → MCU(분대장) code=%s text=%s", code, text[:80] if text else "")
            self.tel.notify_order(notice)
            # 분대장 수신 ACK (보드 측 전달 확인)
            ack = {
                "type": "ack",
                "data": {"ref": data.get("id"), "from": f"{SQUAD_ID}-1", "ok": True},
            }
            writer.write((json.dumps(ack) + "\n").encode())
            await writer.drain()
        elif typ == "order.cancel":
            code = str(data.get("code") or "")
            text = str(data.get("text") or "").strip()
            notice = f"CANCEL:{code}|{text}" if (code or text) else f"CANCEL:{data.get('id', '')}"
            self.tel.notify_order(notice)
        elif typ == "report.update":
            ack = {
                "type": "ack",
                "data": {"ref": data.get("id"), "from": dst if dst.startswith(f"{SQUAD_ID}-") else NODE_ID, "ok": True},
            }
            writer.write((json.dumps(ack) + "\n").encode())
            await writer.drain()
        elif typ == "haptic":
            self.tel.notify_order(f"haptic:{data.get('pattern', '')}")


async def _beacon_usb_loop(ble: SquadBle, port: str, baud: int) -> None:
    """LeaderBeacon 보드 A USB: BCN / 명령 hex 중계는 추후. 지금은 BCN RSSI만."""
    try:
        import serial  # type: ignore
    except ImportError:
        log.warning("pyserial 없음 — Q3_BEACON_PORT 무시")
        return
    log.info("LeaderBeacon USB %s @%d", port, baud)
    while True:
        try:
            with serial.Serial(port, baud, timeout=1) as ser:
                while True:
                    line = ser.readline().decode("utf-8", "ignore").strip()
                    if line.startswith("BCN"):
                        ble.note_bcn_line(line)
        except Exception as e:
            log.warning("beacon usb: %s (3s 후 재시도)", e)
            await asyncio.sleep(3)


async def main() -> None:
    p = argparse.ArgumentParser(description="분대장1 SoftAP TCP + BLE 브리지")
    p.add_argument("--host", default=LISTEN_HOST)
    p.add_argument("--port", type=int, default=LISTEN_PORT)
    p.add_argument("--period", type=float, default=PERIOD_S)
    p.add_argument("--demo", action="store_true", help="MCU Bridge 없이 데모 GPS")
    p.add_argument("--no-ble", action="store_true", help="BLE Central 비활성")
    p.add_argument("--ble-only", default=None, help="연결할 병사 ID (예: 1,2,3)")
    p.add_argument("--formation", default=BLE_FORMATION, choices=("wedge", "line", "column"))
    p.add_argument("--beacon-port", default=BEACON_PORT or None)
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    ble: SquadBle | None = None
    srv_holder: dict[str, BridgeServer] = {}

    def on_uplink(events: list[dict[str, Any]]) -> None:
        s = srv_holder.get("s")
        if s:
            s.push_uplink(events)

    if BLE_ENABLE and not args.no_ble:
        ble = SquadBle(
            squad=SQUAD_ID,
            only=parse_ble_only(args.ble_only),
            formation=args.formation,
            localize_period_s=BLE_LOCALIZE_S,
            relay=BLE_RELAY,
            on_uplink=on_uplink,
            p1m=BLE_PATHLOSS_P1M,
            path_n=BLE_PATHLOSS_N,
        )
        # 시작 시 프리셋으로 위치표 준비(연결 전 COP 상향용)
        ble.engine.compute(mode=args.formation)

    use_bridge = USE_BRIDGE and not args.demo
    tel = TelemetrySource(use_bridge=use_bridge, ble=ble)
    srv = BridgeServer(tel, args.period, ble=ble)
    srv_holder["s"] = srv

    if ble is not None:
        await ble.start()
    if args.beacon_port and ble is not None:
        asyncio.create_task(_beacon_usb_loop(ble, args.beacon_port, BEACON_BAUD))

    server = await asyncio.start_server(srv.handle, args.host, args.port)
    addrs = ", ".join(str(s.getsockname()) for s in server.sockets or [])
    log.info("listening %s  AP=%s(%s)  node=%s  ble=%s", addrs, AP_SSID, AP_IP, NODE_ID, ble is not None)
    log.info("노트북: Wi-Fi '%s' 조인 → COP_Q3_HOST=%s COP_MODE=realtime COP_Q3=1 ./run.sh", AP_SSID, AP_IP)
    try:
        async with server:
            await server.serve_forever()
    finally:
        if ble is not None:
            await ble.stop()


if __name__ == "__main__":
    asyncio.run(main())
