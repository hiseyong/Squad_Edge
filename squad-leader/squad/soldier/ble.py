"""병사 BLE 링크 (BlueZ + bleak, Central 전용 — 병사 팀 안내문 D2).

포팅 원본: ~/work/soldier-node_ref_v1.1/tools/mock_leader.py (Leader.on_adv/connect/on_disconnect/scan_forever/write)
원본과 다른 점
- 연결 전에 스캔을 멈추고 연결이 끝나면 다시 켠다(가이드 f-2: BlueZ에서 스캔 중 연결이 InProgress로 실패할 수 있음).
- 병사별 GATT 쓰기를 asyncio.Lock으로 직렬화한다(RPT_ACK·명령·음성 청크가 섞여도 순서 보장).
- 병사 쪽에서 끊으면(재부팅·침묵·감독 시간 초과) 이전 클라이언트의 D-Bus 연결을 닫는다.
  (UNO Q 실측 2026-10-11, bleak 3.0.2 + BlueZ 5.82: 닫지 않으면 BlueZ가 이전 StartNotify 세션을 살려 둬서
  재연결 뒤 모든 notify가 두 번 들어왔다.) 이전 클라이언트에 disconnect()는 부르지 않는다: 같은 장치 경로라
  새 연결을 끊을 수 있다. 비공개 속성(_backend._bus)이라 bleak 버전을 고정한다(requirements.txt).
- notify는 연결 세대(gen)가 맞을 때만 넘긴다(늦게 도착한 이전 연결 notify 차단).
- 프로토콜 처리(RPT_ACK, 명령 추적 등)는 하지 않는다 → leader.py. 이 모듈은 연결과 바이트 송수신만.
현장에 BLE 장치가 수백 대라 스캔 콜백에서 이름부터 거른다. 침묵(EMCON 0)으로 병사가 사라져도 재연결 스캔은 계속 돈다.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Callable

from bleak import BleakClient, BleakScanner

NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # 분대장 → 병사 (Write)
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # 병사 → 분대장 (Notify)
NAME_RE = re.compile(r"^SQ1-S([1-5])$")
CONNECT_TIMEOUT_S = 15.0
MTU_FALLBACK = 23

log = logging.getLogger("soldier.ble")


@dataclass
class Peer:
    sid: int
    client: BleakClient | None = None
    mtu: int = 0
    connected: bool = False          # notify 구독까지 끝난 상태
    connecting: bool = False
    address: str = ""
    connected_at: float = 0.0
    connects: int = 0
    gen: int = 0                     # 연결 세대: 끊긴 이전 연결의 notify가 늦게(또는 계속) 오면 버린다
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class BleLink:
    """on_frame(sid, raw): 병사 notify 1건(= 프레임 1개). 연결 설정 중(구독 직후)에도 올 수 있다 → connected(sid)로 확인.
    on_connect(sid, mtu) / on_disconnect(sid): 상태 변화. on_tx(sid, raw): 실제로 쓴 프레임(기록용)."""

    def __init__(self, allowed: set[int], on_frame: Callable[[int, bytes], None],
                 on_connect: Callable[[int, int], None] = lambda s, m: None,
                 on_disconnect: Callable[[int], None] = lambda s: None,
                 on_tx: Callable[[int, bytes], None] = lambda s, r: None):
        self.peers = {sid: Peer(sid) for sid in sorted(allowed)}
        self.on_frame, self.on_connect, self.on_disconnect, self.on_tx = on_frame, on_connect, on_disconnect, on_tx
        self.stop = asyncio.Event()
        self._scanner: BleakScanner | None = None
        self._scanning = False
        self._connect_lock = asyncio.Lock()      # 한 번에 한 병사만 연결 시도(스캔 정지 → 연결 → 재개)
        self._tasks: set[asyncio.Task] = set()

    # ---- 상태 ----
    def connected(self, sid: int) -> bool:
        p = self.peers.get(sid)
        return bool(p and p.connected)

    def mtu(self, sid: int) -> int:
        return self.peers[sid].mtu

    def connected_ids(self) -> list[int]:
        return [s for s, p in self.peers.items() if p.connected]

    # ---- 스캔·연결 ----
    def _spawn(self, coro) -> asyncio.Task:
        t = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    def _on_adv(self, device, adv) -> None:
        m = NAME_RE.match(adv.local_name or device.name or "")
        if not m:
            return
        p = self.peers.get(int(m.group(1)))
        if p is None or p.connected or p.connecting:
            return
        p.connecting = True
        self._spawn(self._connect(p, device))

    async def _scan_set(self, on: bool) -> None:
        if on == self._scanning or self._scanner is None:
            return
        try:
            await (self._scanner.start() if on else self._scanner.stop())
            self._scanning = on
        except Exception as e:  # noqa: BLE001 - BlueZ 상태 경합은 다음 주기에 다시
            log.warning("스캔 %s 실패: %r", "시작" if on else "정지", e)

    async def _connect(self, p: Peer, device) -> None:
        async with self._connect_lock:
            await self._scan_set(False)
            log.info("[S%d] 발견 → 연결 시도 (%s)", p.sid, device.address)
            p.gen += 1
            gen = p.gen
            client = BleakClient(device, disconnected_callback=lambda c, sid=p.sid, g=gen: self._on_disc(sid, c, g))
            try:
                await client.connect(timeout=CONNECT_TIMEOUT_S)
                p.client, p.address = client, device.address
                acquire = getattr(getattr(client, "_backend", None), "_acquire_mtu", None)
                if acquire is not None:      # BlueZ: 부르지 않으면 mtu_size = 23(음성 청크 11B)
                    try:
                        await acquire()
                    except Exception as e:  # noqa: BLE001
                        log.warning("[S%d] MTU 읽기 실패(%r) → %d로 동작", p.sid, e, MTU_FALLBACK)
                p.mtu = client.mtu_size or MTU_FALLBACK
                await client.start_notify(NUS_TX, lambda _ch, data, sid=p.sid, g=gen: self._notify(sid, g, data))
                p.connected, p.connected_at = True, time.time()
                p.connects += 1
                log.info("[S%d] 연결됨, Notify 구독, MTU=%d (한 번에 쓸 수 있는 최대 %dB)", p.sid, p.mtu, p.mtu - 3)
                self.on_connect(p.sid, p.mtu)
            except Exception as e:  # noqa: BLE001 - 원인을 그대로 남기고 다음 광고에서 재시도
                log.warning("[S%d] 연결 실패: %r", p.sid, e)
                try:
                    await client.disconnect()
                except Exception:  # noqa: BLE001
                    pass
            finally:
                p.connecting = False

    def _notify(self, sid: int, gen: int, data) -> None:
        if self.peers[sid].gen != gen:            # 이전 연결의 처리기 → 버림
            return
        self.on_frame(sid, bytes(data))

    def _on_disc(self, sid: int, client, gen: int) -> None:
        p = self.peers[sid]
        bus = getattr(getattr(client, "_backend", None), "_bus", None)
        if bus is not None:                       # 이전 연결의 D-Bus 세션 정리 → BlueZ가 notify 세션을 버린다
            try:
                bus.disconnect()
            except Exception:  # noqa: BLE001
                pass
        if gen != p.gen:
            return
        if p.connected:
            log.info("[S%d] 연결 끊김 (%.0f초 유지) → 다시 찾는 중", sid, time.time() - p.connected_at)
        was = p.connected
        p.connected, p.client, p.mtu = False, None, 0
        p.gen += 1                                # 늦게 오는 이전 notify를 막는다
        if was:
            self.on_disconnect(sid)

    async def drop_stale(self) -> list[str]:
        """이전 프로세스가 남긴 병사 연결 끊기(UNO Q 실측 2026-10-11: 강제 재시작 뒤 BlueZ가 연결을 쥐고 있어
        병사가 광고를 멈추고 새 프로세스가 영영 못 찾았다)."""
        dropped = []
        try:
            out = await asyncio.create_subprocess_exec("bluetoothctl", "devices", "Connected",
                                                       stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
            text = (await asyncio.wait_for(out.communicate(), 10))[0].decode(errors="replace")
        except (OSError, asyncio.TimeoutError):
            return dropped
        for line in text.splitlines():
            parts = line.split(maxsplit=2)
            if len(parts) == 3 and parts[0] == "Device" and NAME_RE.match(parts[2].strip()):
                m = NAME_RE.match(parts[2].strip())
                if int(m.group(1)) in self.peers and not self.peers[int(m.group(1))].connected:
                    p = await asyncio.create_subprocess_exec("bluetoothctl", "disconnect", parts[1],
                                                             stdout=asyncio.subprocess.DEVNULL,
                                                             stderr=asyncio.subprocess.DEVNULL)
                    await asyncio.wait_for(p.wait(), 10)
                    dropped.append(parts[2].strip())
        if dropped:
            log.info("이전 프로세스의 병사 연결 정리: %s", ", ".join(dropped))
        return dropped

    async def run(self) -> None:
        """연결 안 된 병사가 있으면 스캔(이름 필터는 콜백, NUS UUID는 BlueZ 필터)."""
        await self.drop_stale()
        self._scanner = BleakScanner(detection_callback=self._on_adv, service_uuids=[NUS_SERVICE])
        try:
            while not self.stop.is_set():
                need = any(not p.connected for p in self.peers.values())
                if not self._connect_lock.locked():
                    await self._scan_set(need)
                await asyncio.sleep(1.0)
        finally:
            await self._scan_set(False)
            for p in self.peers.values():
                if p.client is not None:
                    try:
                        await p.client.disconnect()
                    except Exception:  # noqa: BLE001
                        pass

    # ---- 송신 ----
    async def write(self, sid: int, raw: bytes, response: bool = True) -> bool:
        """프레임 1개 = GATT write 1번. 병사별 직렬화. len ≤ MTU−3이 아니면 보내지 않는다."""
        p = self.peers.get(sid)
        if p is None or not p.connected or p.client is None:
            log.info("[S%d] 연결 안 됨 → 건너뜀", sid)
            return False
        if len(raw) > p.mtu - 3:
            log.warning("[S%d] → 보내지 않음: %dB > MTU-3 (%dB)", sid, len(raw), p.mtu - 3)
            return False
        async with p.lock:
            try:
                await p.client.write_gatt_char(NUS_RX, raw, response=response)
            except Exception as e:  # noqa: BLE001
                log.warning("[S%d] → 쓰기 실패: %r", sid, e)
                return False
        self.on_tx(sid, raw)
        return True
