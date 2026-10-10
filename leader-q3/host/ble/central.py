"""분대장 BLE Central — NU40-DK (SQ1-S1~S5) NUS 연결·POS_TABLE·명령·중계.

soldier-node/tools/mock_leader.py 의 핵심 경로를 서비스형으로 정리.
BlueZ(UNO Q Linux) / macOS bleak 모두 대상.
"""
from __future__ import annotations

import asyncio
import logging
import re
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Awaitable, Callable

_LIB = Path(__file__).resolve().parents[1] / "lib"
if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))

import frame_codec as fc  # noqa: E402

from .downlink_map import emcon_frame, order_to_cmd_frame
from .ids import ble_to_cop
from .localize import LocalizeEngine
from .reports import link_events_from_ranging, soldier_report_to_events

log = logging.getLogger("q3.ble")

NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"
NAME_RE = re.compile(r"^SQ1-S([1-5])$")

# RPT_ACK 대상(긴급 재전송 방지). ACK/VOICE_RESULT 자체에는 보내지 않음.
NEED_RPT_ACK = {
    fc.CONTACT, fc.SUSPICIOUS, fc.HAZARD, fc.CASUALTY_FOUND,
    fc.OK_READY, fc.WEAPON_AMMO, fc.CASUALTY_SELF, fc.EMCON_STATE,
}
PEER_TYPES = {fc.CONTACT, fc.SUSPICIOUS, fc.HAZARD, fc.CASUALTY_FOUND}

# COP 상향 이벤트 콜백
UplinkFn = Callable[[list[dict[str, Any]]], None]


class _Soldier:
    def __init__(self, sid: int) -> None:
        self.sid = sid
        self.client: Any = None
        self.address: str | None = None
        self.mtu = 23
        self.connected = False
        self.pending_acks: list[int] = []
        self.task: asyncio.Task | None = None


class SquadBle:
    def __init__(
        self,
        *,
        squad: str = "1",
        only: set[int] | None = None,
        formation: str = "wedge",
        localize_period_s: float = 10.0,
        relay: bool = True,
        on_uplink: UplinkFn | None = None,
        p1m: float = -59.0,
        path_n: float = 2.0,
    ) -> None:
        self.squad = squad
        self.only = only or {1, 2, 3, 4, 5}
        self.localize_period_s = localize_period_s
        self.relay = relay
        self.on_uplink = on_uplink or (lambda _ev: None)
        self.engine = LocalizeEngine(formation=formation, p1m=p1m, n=path_n)
        self.soldiers = {i: _Soldier(i) for i in range(1, 6) if i in self.only}
        self._seq = 0
        self._seen: dict[int, deque[int]] = {i: deque(maxlen=16) for i in self.soldiers}
        self._stop = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()
        self.leader_heading = 0
        self.leader_lat: float | None = None
        self.leader_lon: float | None = None
        # CMD_BUTTON seq → COP order id (병사 ACK 매핑)
        self._pending_cmd: dict[int, dict[str, Any]] = {}
        self._BleakClient = None
        self._BleakScanner = None

    def next_seq(self) -> int:
        self._seq = (self._seq + 1) % 256
        return self._seq

    @property
    def connected_ids(self) -> set[int]:
        return {i for i, s in self.soldiers.items() if s.connected}

    def _emit(self, events: list[dict[str, Any]]) -> None:
        if events:
            self.on_uplink(events)

    async def start(self) -> None:
        try:
            from bleak import BleakClient, BleakScanner
        except ImportError as e:
            raise SystemExit(
                "bleak 필요: pip install bleak  (leader-q3/host/requirements.txt)"
            ) from e
        self._BleakClient = BleakClient
        self._BleakScanner = BleakScanner
        self._stop.clear()
        self._spawn(self._scanner_loop())
        self._spawn(self._localize_loop())
        log.info("BLE Central start only=%s formation=%s", sorted(self.only), self.engine.formation)

    async def stop(self) -> None:
        self._stop.set()
        for s in self.soldiers.values():
            if s.client and s.connected:
                try:
                    await s.client.disconnect()
                except Exception:
                    pass
                s.connected = False
        for t in list(self._tasks):
            t.cancel()

    def _spawn(self, coro: Awaitable[Any]) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    async def _scanner_loop(self) -> None:
        while not self._stop.is_set():
            try:
                devices = await self._BleakScanner.discover(timeout=3.0)
            except Exception as e:
                log.warning("scan error: %s", e)
                await asyncio.sleep(2)
                continue
            for d in devices:
                name = d.name or ""
                m = NAME_RE.match(name)
                if not m:
                    continue
                sid = int(m.group(1))
                if sid not in self.soldiers:
                    continue
                s = self.soldiers[sid]
                if s.connected or s.task is not None:
                    continue
                s.address = d.address
                s.task = self._spawn(self._maintain(sid, d.address))
            await asyncio.sleep(2)

    async def _maintain(self, sid: int, address: str) -> None:
        s = self.soldiers[sid]
        try:
            async with self._BleakClient(address) as client:
                s.client = client
                s.connected = True
                try:
                    s.mtu = int(client.mtu_size)
                except Exception:
                    s.mtu = 23
                log.info("S%d connected %s mtu=%d", sid, address, s.mtu)

                def _cb(_sender, data: bytearray) -> None:
                    self._on_notify(sid, bytes(data))

                await client.start_notify(NUS_TX, _cb)
                # 연결 직후 POS_TABLE
                await self.push_pos_table(mode=self.engine.formation, targets=[sid])
                for seq in s.pending_acks:
                    await self._write_one(sid, fc.encode(dict(
                        type=fc.RPT_ACK, seq=self.next_seq(), src=fc.LEADER_ID,
                        dst=fc.dst_bit(sid), ref_seq=seq,
                    )))
                s.pending_acks.clear()
                while client.is_connected and not self._stop.is_set():
                    await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning("S%d session end: %s", sid, e)
        finally:
            s.connected = False
            s.client = None
            s.task = None
            log.info("S%d disconnected", sid)

    def _on_notify(self, sid: int, data: bytes) -> None:
        try:
            msg = fc.decode(data)
        except fc.FrameError as e:
            log.warning("S%d bad frame: %s", sid, e)
            return
        t = msg["type"]
        if t == fc.RANGING:
            self.engine.note_ranging(sid, msg["peers"])
            if msg.get("peers"):
                # heading은 RANGING에 없음 — HEARTBEAT/보고에서
                self._emit(link_events_from_ranging(sid, msg["peers"], squad=self.squad))
            return
        if t in NEED_RPT_ACK or t in PEER_TYPES:
            recent = self._seen[sid]
            is_dup = msg["seq"] in recent
            if not is_dup:
                recent.append(msg["seq"])
            if t in PEER_TYPES and msg.get("heading", fc.NO_HEADING) != fc.NO_HEADING:
                self.engine.note_heading(sid, msg["heading"])
            if not is_dup:
                self._emit(soldier_report_to_events(msg, squad=self.squad))
                if self.relay and t in PEER_TYPES:
                    self._spawn(self._relay_peer(sid, msg))
            if t in NEED_RPT_ACK:
                s = self.soldiers.get(sid)
                if s is not None:
                    if s.connected and s.client:
                        self._spawn(self._write_one(sid, fc.encode(dict(
                            type=fc.RPT_ACK, seq=self.next_seq(), src=fc.LEADER_ID,
                            dst=fc.dst_bit(sid), ref_seq=msg["seq"],
                        ))))
                    else:
                        s.pending_acks.append(msg["seq"])
        if t in (fc.ACK, fc.CANNOT_COMPLY) and msg.get("ref_type") == fc.REF_BUTTON:
            ref_id = int(msg.get("ref_id", -1))
            pending = self._pending_cmd.get(ref_id)
            order_id = pending["order_id"] if pending else f"ble-cmd-{ref_id}"
            ok = t == fc.ACK
            self._emit([{
                "type": "ack",
                "data": {
                    "ref": order_id,
                    "from": ble_to_cop(self.squad, sid),
                    "ok": ok,
                },
            }])
            if pending:
                left = set(pending.get("ble_ids") or []) - {sid}
                pending["ble_ids"] = list(left)
                if not left:
                    self._pending_cmd.pop(ref_id, None)

    async def _relay_peer(self, reporter: int, msg: dict[str, Any]) -> None:
        targets = [i for i in self.connected_ids if i != reporter]
        if not targets:
            return
        rx, ry = self.engine.reporter_xy_dm(reporter)
        try:
            orig_payload = fc.encode_payload(msg)
        except fc.FrameError as e:
            log.warning("PEER_REPORT encode fail: %s", e)
            return
        raw = fc.encode(dict(
            type=fc.PEER_REPORT,
            seq=self.next_seq(),
            src=fc.LEADER_ID,
            dst=fc.dst_mask(targets),
            reporter_id=reporter,
            rx=rx,
            ry=ry,
            orig_type=msg["type"],
            orig_payload=orig_payload,
        ))
        await self.write(targets, raw)
        log.info("PEER_REPORT relay S%d → %s", reporter, targets)

    async def _localize_loop(self) -> None:
        while not self._stop.is_set():
            await asyncio.sleep(self.localize_period_s)
            if not self.connected_ids and not self.engine.rssi_rows():
                continue
            try:
                await self.push_pos_table(mode="auto")
            except Exception:
                log.exception("localize push failed")

    async def push_pos_table(self, *, mode: str = "auto", targets: list[int] | None = None) -> None:
        ids = targets if targets is not None else sorted(self.connected_ids)
        pos, entries = self.engine.compute(connected=self.connected_ids, mode=mode)
        if not ids:
            return
        raw = fc.encode(dict(
            type=fc.POS_TABLE,
            seq=self.next_seq(),
            src=fc.LEADER_ID,
            dst=fc.dst_mask(ids) if len(ids) < 5 else fc.DST_ALL_SOLDIERS,
            entries=entries,
        ))
        await self.write(ids, raw)
        log.info("POS_TABLE → %s (%s) n=%d", ids, self.engine.last_info.get("method"), len(entries))
        _ = pos

    async def write(self, ids: list[int], raw: bytes) -> None:
        for sid in ids:
            await self._write_one(sid, raw)

    async def _write_one(self, sid: int, raw: bytes) -> None:
        s = self.soldiers.get(sid)
        if not s or not s.connected or not s.client:
            return
        try:
            # 버튼/표/중계 = Write With Response
            await s.client.write_gatt_char(NUS_RX, raw, response=True)
        except Exception as e:
            log.warning("S%d write fail: %s", sid, e)

    async def handle_cop_downlink(self, obj: dict[str, Any]) -> list[dict[str, Any]]:
        """COP 하향 JSON → BLE 송신.

        반환: GATT Write 성공한 병사에 대한 전달(delivery) ack.
        병사 버튼 ACK는 Notify 경로에서 order.id 로 추가 상향.
        """
        typ = obj.get("type")
        data = obj.get("data") or {}
        acks: list[dict[str, Any]] = []
        if typ == "order.new":
            seq = self.next_seq()
            mapped = order_to_cmd_frame(
                data,
                seq=seq,
                squad=self.squad,
                leader_heading=self.leader_heading,
                leader_lat=self.leader_lat,
                leader_lon=self.leader_lon,
            )
            if mapped is None:
                log.info("order %s: BLE 매핑/수신자 없음 (스킵)", data.get("code"))
                return acks
            raw, ble_ids, name = mapped
            live = [i for i in ble_ids if i in self.connected_ids]
            if not live:
                log.warning("CMD_BUTTON %s: 연결 병사 없음 (ble_ids=%s)", name, ble_ids)
                return acks
            self._pending_cmd[seq & 0xFF] = {
                "order_id": data.get("id"),
                "ble_ids": list(live),
                "ts": time.time(),
                "cmd": name,
            }
            # 오래된 pending 정리
            cutoff = time.time() - 60
            for k in [k for k, v in self._pending_cmd.items() if v.get("ts", 0) < cutoff]:
                self._pending_cmd.pop(k, None)
            await self.write(live, raw)
            log.info("CMD_BUTTON %s seq=%d → BLE %s", name, seq & 0xFF, live)
            # 전달 ack (COP UI 즉시 반영). 병사 compliance ACK는 Notify에서 동일 ref로 갱신.
            for bid in live:
                acks.append({
                    "type": "ack",
                    "data": {"ref": data.get("id"), "from": ble_to_cop(self.squad, bid), "ok": True},
                })
        elif typ == "order.cancel":
            # 철회: HALT로 대체 통지 (프로토콜에 cancel 프레임 없음)
            seq = self.next_seq()
            live = sorted(self.connected_ids)
            if live:
                raw = fc.encode(dict(
                    type=fc.CMD_BUTTON, seq=seq & 0xFF, src=fc.LEADER_ID,
                    dst=fc.dst_mask(live) if len(live) < 5 else fc.DST_ALL_SOLDIERS,
                    cmd_code=fc.CMD_CODES["HALT"],
                    azimuth=fc.NO_AZIMUTH, dist_band=fc.NO_DIST, extra=0, priority=1,
                ))
                await self.write(live, raw)
                log.info("order.cancel → HALT to %s (ref=%s)", live, data.get("id"))
        elif typ == "mission.update" and "emcon" in data:
            mode = 0 if data.get("emcon") else 2
            raw = emcon_frame(mode, self.next_seq())
            await self.write(sorted(self.connected_ids), raw)
        elif typ == "haptic":
            # 진동은 병사 태그 전용 — BLE 버튼 매핑 없음. MCU LED는 bridge에서 처리.
            pass
        return acks

    def telemetry_members(self) -> list[dict[str, Any]]:
        """bridge_server 상향용 분대원 relpos (BLE 측위 결과)."""
        if not self.engine.pos:
            self.engine.compute(connected=self.connected_ids, mode=self.engine.formation)
        return self.engine.members_relpos_m(sorted(self.only))

    def note_bcn_line(self, line: str) -> None:
        """LeaderBeacon USB: `BCN <src> <rssi> <heading>`."""
        parts = line.strip().split()
        if len(parts) < 3 or parts[0] != "BCN":
            return
        try:
            src, rssi = int(parts[1]), int(parts[2])
            hd = int(parts[3]) if len(parts) > 3 else None
        except ValueError:
            return
        self.engine.note_leader_beacon(src, rssi, hd)
