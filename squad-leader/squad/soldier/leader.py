"""분대장 쪽 병사 링크 상태기계 (BLE를 모름: Transport 위에서 동작 → 오프라인 시험과 실기가 같은 코드).

포팅 원본: ~/work/soldier-node_ref_v1.1/tools/mock_leader.py
  (Leader.on_notify/send_rpt_ack/send_cmd/on_cmd_ack/watch_cmds/send_msg/targets/build_cmd, PendingCmd, parse_cmd_code,
   PendingVoice/send_voice/stream_voice/on_voice_result, send_emcon, on_peer_report/pos_dm/send_peer, send_pos(프리셋))
원본과 다른 점
- 재전송 판정: (병사, seq, 바이트 동일, 60초) + 새 연결 때 초기화(가이드 f-4). 원본은 최근 seq 16개만 본다.
- seq 시작: 무작위(운용) / --seq-start(시험). 원본은 0부터.
- 화면 출력 대신 logging + on_event 콜백(앱 계층이 헤드셋·전투 로그로 넘긴다).
- 침묵 방송(bcmd/bemcon)·분대장 비콘은 없다: UNO Q는 Central만(병사 팀 안내문 D2). 침묵 중인 병사에게는 보내지 않고
  "침묵 중, 보드 A 버튼" 이벤트를 낸다. 음성은 침묵 중 금지.
- 병사별 상태표(SoldierState): 연결, EMCON, 마지막 보고, 미확인 명령, 위치, 마지막 통신 시각.
- 0x7F LOG는 별도 로거(soldier.log7f)로만 남긴다(화면 홍수 방지, 가이드 f-9).
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from . import codec as fc
from . import config
from .dedup import ReportDedup
from .describe import describe
from .geo import NO_AZIMUTH, POS_UNKNOWN, m_to_dm, rssi_to_m, target_estimate
from .localize import localize, measured_from_distances, measured_from_rssi, preset_positions, to_pos_table
from .seq import LeaderSeq
from .txlog import TxLog
from .voice import VoiceClip, voice_frames

log = logging.getLogger("soldier.leader")
log7f = logging.getLogger("soldier.log7f")          # 병사 디버그 LOG(0x7F): 표시·기록만
PEER_TYPES = {fc.CONTACT, fc.SUSPICIOUS, fc.HAZARD, fc.CASUALTY_FOUND}   # 중계 대상
MODE_NAMES = {0: "침묵", 1: "최소", 2: "정상"}
VOICE_STATUS = {0: "정상", 1: "CRC 오류", 2: "시간 초과", 3: "메모리 부족"}

REPORT_TYPES = set(range(0x01, 0x0C))     # RPT_ACK 대상(STATS·RANGING·LOG 제외)
CMD_NAMES = {v: k for k, v in fc.CMD_CODES.items()}
DIST_ARGS = {"near": 0, "mid": 1, "far": 2, "0": 0, "1": 1, "2": 2, "-": fc.NO_DIST, "none": fc.NO_DIST}


class Transport(Protocol):
    def connected(self, sid: int) -> bool: ...
    def connected_ids(self) -> list[int]: ...
    def mtu(self, sid: int) -> int: ...
    async def write(self, sid: int, raw: bytes, response: bool = True) -> bool: ...


@dataclass
class SoldierState:
    sid: int
    connected: bool = False
    emcon: int | None = None            # 병사가 알린(EMCON_STATE) 또는 우리가 지정한 모드. None = 모름(부팅 기본 2)
    last_report: str | None = None      # 마지막 보고 설명
    last_report_t: float = 0.0
    last_rx_t: float = 0.0              # 마지막 통신(수신) 시각
    mtu: int = 0
    ranging: dict = field(default_factory=dict)   # peer_id → (rssi, samples, t)
    stats: dict | None = None


def parse_cmd_code(tok: str) -> int:
    t = tok.strip().upper()
    if t in fc.CMD_CODES:
        return fc.CMD_CODES[t]
    code = int(t, 16) if t.startswith("0X") else int(t)
    if code not in CMD_NAMES:
        raise ValueError(f"cmd_code 0x{code:02X}는 프로토콜 §6에 없음")
    return code


@dataclass
class PendingCmd:
    seq: int
    code: int
    raw: bytes
    status: dict[int, str | None]          # sid → None(미수신) / "수신" / "수행 불가"
    sent_at: float
    retried: bool = False
    done: bool = False

    def summary(self) -> str:
        parts = [f"S{sid} {st or '미수신'}" for sid, st in sorted(self.status.items())]
        return f"cmd seq={self.seq} {CMD_NAMES.get(self.code, hex(self.code))}: " + ", ".join(parts)


@dataclass
class PendingVoice:
    clip: VoiceClip
    dst: int
    status: dict[int, int | None]      # sid → None(대기) / VOICE_RESULT status
    retried: set = field(default_factory=set)
    gen: dict[int, int] = field(default_factory=dict)   # 병사별 전송 세대: 바뀌면 진행 중 전송 중단

    def summary(self) -> str:
        parts = [f"S{sid} {'대기' if st is None else VOICE_STATUS.get(st, st)}" for sid, st in sorted(self.status.items())]
        return f"voice {self.clip.voice_id}: " + ", ".join(parts)


@dataclass
class SquadLeader:
    link: Transport
    seq: LeaderSeq = field(default_factory=LeaderSeq)
    txlog: TxLog = field(default_factory=lambda: TxLog(None))
    on_event: Callable[[dict], None] = lambda e: None
    allowed: tuple[int, ...] = (1, 2, 3, 4, 5)
    auto_ack: bool = True
    dedup: ReportDedup = field(default_factory=ReportDedup)
    pending_acks: dict[int, list[int]] = field(default_factory=dict)
    cmds: dict[int, PendingCmd] = field(default_factory=dict)
    voices: dict[int, PendingVoice] = field(default_factory=dict)
    voice_id: int = 0
    relay: bool = True
    pos: dict = field(default_factory=dict)        # 마지막 POS_TABLE {id: (x_m, y_m)} (중계 rx/ry)
    formation: str | None = None
    pathloss: tuple[float, float] = (config.PATHLOSS_P1M_DBM, config.PATHLOSS_N)
    clocks: dict = field(default_factory=lambda: dict(config.DEFAULT_CLOCKS))   # 분대장이 본 병사 방향
    auto_pos: bool = False
    auto_pos_move_m: float = 3.0       # 다시 계산한 위치가 이만큼 바뀐 병사가 있을 때만 POS_TABLE 재송신
    auto_pos_period_s: float = 10.0    # RANGING 주기와 같게
    pos_smooth: float = 0.5            # 실측 위치 평활(새 값 비중). RSSI 흔들림 완화
    live_pos: dict = field(default_factory=dict)   # 최신 실측 위치(평활) — 분대장 쪽 표시·계산용, 병사 표와 다를 수 있음
    pos_info: dict | None = None
    soldiers: dict[int, SoldierState] = field(default_factory=dict)
    clock: Callable[[], float] = time.monotonic
    _tasks: set = field(default_factory=set)

    def __post_init__(self):
        for sid in self.allowed:
            self.soldiers.setdefault(sid, SoldierState(sid))

    # ---- 연결 상태 (BleLink 콜백) ----
    def on_connect(self, sid: int, mtu: int) -> None:
        st = self.soldiers.setdefault(sid, SoldierState(sid))
        st.connected, st.mtu, st.last_rx_t = True, mtu, time.time()
        if st.emcon == 0:                         # 연결됐으면 침묵이 풀린 것(모드는 EMCON_STATE로 확정)
            st.emcon = None
        self.dedup.reset(sid)                     # 병사가 재부팅했을 수 있음(seq 0부터)
        acks, self.pending_acks[sid] = self.pending_acks.get(sid, []), []
        for ref in acks:                          # 연결 설정 중에 받은 보고(병사 큐에서 바로 나온 것)
            self._spawn(self.send_rpt_ack(sid, ref))
        if self.pos:                              # 위치표는 연결 직후에도 보낸다(재부팅·재연결한 병사)
            self._spawn(self.send_msg([sid], {"type": fc.POS_TABLE, "entries": to_pos_table(self.pos)}))
        self.on_event({"kind": "link", "sid": sid, "up": True, "mtu": mtu})

    def on_disconnect(self, sid: int) -> None:
        self.soldiers.setdefault(sid, SoldierState(sid)).connected = False
        self.pending_acks[sid] = []
        self.on_event({"kind": "link", "sid": sid, "up": False})

    def on_tx(self, sid: int, raw: bytes) -> None:
        self.txlog.record("tx", sid, raw)
        try:
            what = describe(fc.decode(raw))
        except fc.FrameError:
            what = "raw"
        log.info("[S%d] → %s  (%s)", sid, what, fc.to_hex(raw))

    # ---- 수신 ----
    def on_frame(self, sid: int, raw: bytes) -> None:
        self.txlog.record("rx", sid, raw)
        try:
            m = fc.decode(raw)
        except fc.FrameError as e:
            log.warning("[S%d] ← 잘못된 프레임(%s): %s", sid, e, fc.to_hex(raw))
            return
        st = self.soldiers.setdefault(sid, SoldierState(sid))
        st.last_rx_t = time.time()
        if m["type"] == fc.LOG:                   # 디버그 LOG: 별도 로거, RPT_ACK 대상 아님
            log7f.info("[S%d] %s", sid, m["text"])
            return
        warn = "" if m["src"] == sid else f"  ⚠ 연결 ID S{sid} ≠ src_id {m['src']}"
        retx = False
        tag = ""
        if m["type"] in REPORT_TYPES:
            retx = self.dedup.is_retransmit(sid, raw, self.clock())
            tag = "  ↻ 재전송(같은 seq·같은 바이트)" if retx else ""
            if fc.is_urgent(m["type"]):
                tag += "  ★긴급"
        log.info("[S%d] ← %s%s%s", sid, describe(m), tag, warn)
        if m["type"] in (fc.ACK, fc.CANNOT_COMPLY) and m["ref_type"] == fc.REF_BUTTON:
            self.on_cmd_ack(sid, m["ref_id"], "수신" if m["type"] == fc.ACK else "수행 불가")
        if m["type"] in (fc.ACK, fc.CANNOT_COMPLY) and m["ref_type"] == fc.REF_VOICE:
            self.on_event({"kind": "voice_ack", "sid": sid, "voice_id": m["ref_id"],
                           "status": "수신" if m["type"] == fc.ACK else "수행 불가"})
        if m["type"] == fc.VOICE_RESULT:
            self.on_voice_result(sid, m["voice_id"], m["status"])
        if m["type"] == fc.EMCON_STATE:
            st.emcon = m["mode"]
        if m["type"] == fc.RANGING:
            now = self.clock()
            st.ranging = {p["peer_id"]: (p["rssi_avg"], p["samples"], now) for p in m["peers"]}
        if m["type"] == fc.STATS:
            st.stats = {"tx_frames": m["tx_frames"], "tx_bytes": m["tx_bytes"]}
        if m["type"] in REPORT_TYPES and m["type"] not in (fc.ACK, fc.CANNOT_COMPLY, fc.VOICE_RESULT):
            st.last_report, st.last_report_t = describe(m).split(" | ", 1)[-1] or fc.MSG_NAMES[m["type"]], time.time()
        if m["type"] in REPORT_TYPES:
            if self.auto_ack:
                if self.link.connected(sid):
                    self._spawn(self.send_rpt_ack(sid, m["seq"]))
                else:                             # notify는 켜졌지만 연결 설정이 아직 → 끝나면 보냄
                    self.pending_acks.setdefault(sid, []).append(m["seq"])
            else:
                log.info("[S%d]   (ack off: RPT_ACK 보내지 않음)", sid)
        if m["type"] in PEER_TYPES and not retx:      # RPT_ACK 다음에 중계(원본 mock_leader는 중계가 먼저)
            self.on_peer_report(sid, m)
        ev = {"kind": "frame", "sid": sid, "msg": m, "raw": raw, "retransmit": retx, "ts": time.time()}
        if m["type"] in PEER_TYPES:               # 분대장 기준 표적 위치(보고자 위치 = 마지막 위치표)
            rep = self.live_pos.get(sid, self.pos.get(sid))
            ev["target"] = target_estimate(rep, m.get("azimuth", NO_AZIMUTH), m.get("dist_band", fc.NO_DIST))
            t = ev["target"]
            log.info("   ⇒ 분대장 기준 %s: %d시 %.0fm (방위 %d°, 동 %.0f 북 %.0f m, ±%.0fm, %s)",
                     fc.MSG_NAMES[m["type"]], t["clock"], t["dist"], t["bearing"], t["x"], t["y"], t["err"], t["basis"])
        self.on_event(ev)

    # ---- 송신 ----
    def _spawn(self, coro):
        t = asyncio.get_running_loop().create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    def targets(self, spec: str) -> list[int]:
        """'all' / '1' / 'S1' / '1,2' → 연결된 병사 ID 목록."""
        if spec.lower() == "all":
            ids = list(self.allowed)
        else:
            ids = []
            for part in spec.split(","):
                part = part.strip().upper().lstrip("S")
                if not part.isdigit() or int(part) not in self.allowed:
                    raise ValueError(f"대상 '{spec}' 이해 못 함(허용: {list(self.allowed)})")
                ids.append(int(part))
        live = [i for i in ids if self.link.connected(i)]
        silent = [i for i in ids if i not in live and self.soldiers.get(i, SoldierState(i)).emcon == 0]
        for i in ids:
            if i in silent:
                log.info("[S%d] 침묵(EMCON 0) 중 → 연결 송신 불가. 침묵 중 명령은 보드 A 버튼", i)
            elif i not in live:
                log.info("[S%d] 연결 안 됨 → 건너뜀", i)
        if silent:
            self.on_event({"kind": "silent_blocked", "sids": silent})
        return live

    async def write(self, ids: list[int], raw: bytes, response: bool = True) -> list[int]:
        ok = []
        for sid in ids:
            if await self.link.write(sid, raw, response):
                ok.append(sid)
        return ok

    async def send_msg(self, ids: list[int], msg: dict) -> None:
        if not ids:
            return
        msg = dict(msg, seq=self.seq.next(), src=fc.LEADER_ID, dst=fc.dst_mask(ids))
        await self.write(ids, fc.encode(msg))

    async def send_rpt_ack(self, sid: int, ref_seq: int) -> None:
        await self.send_msg([sid], {"type": fc.RPT_ACK, "ref_seq": ref_seq})

    async def send_cmd(self, code: int, azimuth: int = fc.NO_AZIMUTH, dist_band: int = fc.NO_DIST, extra: int = 0,
                       priority: int = 0, spec: str = "all") -> PendingCmd | None:
        """CMD_BUTTON. dst = 전원이면 0x1F, 아니면 대상 비트. 대상별 ACK를 모으고 15초 무응답이면 같은 바이트로 1회 재전송."""
        if azimuth != fc.NO_AZIMUTH and not 0 <= azimuth <= 359:
            raise ValueError("azimuth는 0~359 또는 0xFFFF")
        ids = self.targets(spec)
        if not ids:
            return None
        dst = fc.DST_ALL_SOLDIERS if spec.lower() == "all" else fc.dst_mask(ids)
        seq = self.seq.next()
        raw = fc.encode(dict(type=fc.CMD_BUTTON, seq=seq, src=fc.LEADER_ID, dst=dst, cmd_code=code, azimuth=azimuth,
                             dist_band=dist_band, extra=extra, priority=priority))
        pc = self.cmds[seq] = PendingCmd(seq, code, raw, {sid: None for sid in ids}, self.clock())
        await self.write(ids, raw)
        log.info("  ▶ %s  (%d초 안에 ACK 없으면 1회 재전송)", pc.summary(), int(config.CMD_ACK_TIMEOUT_S))
        return pc

    def on_cmd_ack(self, sid: int, ref_id: int, what: str) -> None:
        pc = self.cmds.get(ref_id)
        if pc is None or sid not in pc.status:
            log.info("[S%d]   (참고) seq=%d는 추적 중인 명령/대상이 아님", sid, ref_id)
            return
        first = pc.status[sid] is None
        pc.status[sid] = what
        if first:
            log.info("  ▶ %s", pc.summary())
        self.on_event({"kind": "cmd_ack", "sid": sid, "seq": ref_id, "status": what})
        if not pc.done and all(v is not None for v in pc.status.values()):
            pc.done = True
            log.info("  ✔ 전원 응답: %s", pc.summary())

    async def check_cmds(self) -> None:
        """주기 호출: 15초 무응답 대상에 같은 바이트로 1회 재전송, 그래도 없으면 미수신 알림."""
        now = self.clock()
        for pc in list(self.cmds.values()):
            if pc.done or now - pc.sent_at < config.CMD_ACK_TIMEOUT_S:
                continue
            missing = [sid for sid, st in pc.status.items() if st is None]
            if not pc.retried:
                pc.retried, pc.sent_at = True, now
                log.info("  ⏱ %d초 ACK 없음 → 같은 seq=%d로 1회 재전송: %s", int(config.CMD_ACK_TIMEOUT_S), pc.seq,
                         ", ".join(f"S{i}" for i in missing))
                await self.write([i for i in missing if self.link.connected(i)], pc.raw)
            else:
                pc.done = True
                log.info("  ✖ 재전송 후에도 ACK 없음: %s", pc.summary())
                self.on_event({"kind": "cmd_unacked", "seq": pc.seq, "code": pc.code, "sids": missing})

    async def watch(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            await asyncio.sleep(0.5)
            await self.check_cmds()

    async def req_stats(self, spec: str = "all") -> None:
        await self.send_msg(self.targets(spec), {"type": fc.REQ_STATS})

    # ---- EMCON (연결 write만. 침묵 방송은 보드 A) ----
    async def send_emcon(self, mode: int, spec: str = "all") -> list[int]:
        if mode not in (0, 1, 2):
            raise ValueError("mode는 0|1|2")
        ids = self.targets(spec)
        if not ids:
            return []
        dst = fc.DST_ALL_SOLDIERS if spec.lower() == "all" else fc.dst_mask(ids)
        ok = await self.write(ids, fc.encode(dict(type=fc.EMCON_SET, seq=self.seq.next(), src=fc.LEADER_ID, dst=dst,
                                                   mode=mode)))
        for sid in ok:
            self.soldiers[sid].emcon = mode
        if mode == 0:
            log.info("  (병사는 연결을 끊고 침묵. 침묵 중 명령 = 보드 A 버튼1~4, 해제 = 보드 A 버튼4 길게 또는 병사 직접)")
        self.on_event({"kind": "emcon_set", "mode": mode, "sids": ok})
        return ok

    # ---- 음성 하달 (연결 전용, 침묵 중 금지) ----
    async def send_voice(self, pcm8k: list[int], priority: int = 0, spec: str = "all") -> PendingVoice | None:
        ids = self.targets(spec)
        if not ids:
            return None
        clip = VoiceClip.from_pcm8k(self.voice_id, pcm8k, priority)
        self.voice_id = (self.voice_id + 1) & 0xFF
        dst = fc.DST_ALL_SOLDIERS if spec.lower() == "all" else fc.dst_mask(ids)
        pv = self.voices[clip.voice_id] = PendingVoice(clip, dst, {sid: None for sid in ids},
                                                       gen={sid: 0 for sid in ids})
        log.info("음성 %d: %.2f초, ADPCM %dB, %s, 대상 %s", clip.voice_id, clip.nsamples / 8000, len(clip.data),
                 "긴급" if priority else "일반", ", ".join(f"S{i}" for i in ids))
        self._spawn(self._stream_all(pv, ids))
        return pv

    async def _stream_all(self, pv: PendingVoice, ids: list[int]) -> None:
        for sid in ids:                              # 병사별로 차례로(각자 MTU에 맞춘 청크, 같은 voice_id)
            await self.stream_voice(pv, sid)

    async def stream_voice(self, pv: PendingVoice, sid: int) -> bool:
        my_gen = pv.gen[sid]
        try:
            frames = voice_frames(pv.clip, self.link.mtu(sid), pv.dst, self.seq.next)
        except ValueError as e:
            log.warning("[S%d] %s", sid, e)
            return False
        t0 = time.monotonic()
        for i, (raw, response) in enumerate(frames):
            if pv.gen[sid] != my_gen or not self.link.connected(sid):
                log.info("[S%d] → 음성 %d 전송 중단(%d/%d 프레임에서)", sid, pv.clip.voice_id, i, len(frames))
                return False
            if not await self.link.write(sid, raw, response):
                return False
            if not response:
                await asyncio.sleep(config.VOICE_CHUNK_GAP_S)
        dt = max(time.monotonic() - t0, 1e-3)
        log.info("[S%d] → 음성 %d 송신 완료: %dB, 프레임 %d, %.2f초 (%.1fkB/s), CRC %04X", sid, pv.clip.voice_id,
                 len(pv.clip.data), len(frames), dt, len(pv.clip.data) / dt / 1000, pv.clip.crc)
        return True

    def on_voice_result(self, sid: int, voice_id: int, status: int) -> None:
        pv = self.voices.get(voice_id)
        if pv is None or sid not in pv.status:
            return
        pv.status[sid] = status
        log.info("  ▶ %s", pv.summary())
        self.on_event({"kind": "voice_result", "sid": sid, "voice_id": voice_id, "status": status})
        if status != 0:
            pv.gen[sid] += 1                         # 병사가 실패를 알렸으니 진행 중 청크 전송은 멈춘다
            if sid not in pv.retried and self.link.connected(sid):
                pv.retried.add(sid)
                log.info("  ↻ S%d %s → 같은 voice_id=%d로 전체 1회 재전송", sid, VOICE_STATUS.get(status, status), voice_id)
                self._spawn(self.stream_voice(pv, sid))

    # ---- 다른 병사 보고 중계 (PEER_REPORT + orig_seq) ----
    def pos_dm(self, sid: int) -> tuple[int, int]:
        if sid not in self.pos:
            return POS_UNKNOWN, POS_UNKNOWN            # 위치 모름(절대 0,0 아님)
        x, y = self.pos[sid]
        return m_to_dm(x), m_to_dm(y)

    def on_peer_report(self, sid: int, m: dict) -> None:
        if not self.relay:
            return
        others = [i for i in self.link.connected_ids() if i != sid]
        if not others:
            log.info("  (중계 대상 없음: S%d 말고 연결된 병사 없음)", sid)
            return
        rx, ry = self.pos_dm(sid)
        if rx == POS_UNKNOWN:
            log.info("  (위치표 없음: 보고자 위치 0x8000 → 병사는 '%d번 기준'으로 재생)", sid)
        msg = {"type": fc.PEER_REPORT, "reporter_id": sid, "rx": rx, "ry": ry, "orig_type": m["type"],
               "orig_payload": fc.encode_payload(m), "orig_seq": m["seq"]}
        self._spawn(self.send_msg(others, msg))

    async def send_peer(self, reporter: int, azimuth: int, dist_band: int, count: int, spec: str = "all") -> None:
        """시험용 수동 PEER_REPORT(CONTACT). 가짜 orig_seq는 128부터(실제 보고 seq와 겹치지 않게)."""
        from .geo import clock_from_azimuth
        ids = [i for i in self.targets(spec) if i != reporter]
        orig = dict(type=fc.CONTACT, azimuth=azimuth, clock=clock_from_azimuth(azimuth, 0), dist_band=dist_band,
                    count=count, heading=0)
        self._peer_seq = (getattr(self, "_peer_seq", 0x7F) + 1) & 0xFF
        rx, ry = self.pos_dm(reporter)
        await self.send_msg(ids, {"type": fc.PEER_REPORT, "reporter_id": reporter, "rx": rx, "ry": ry,
                                  "orig_type": fc.CONTACT, "orig_payload": fc.encode_payload(orig),
                                  "orig_seq": self._peer_seq})

    # ---- 위치표 (프리셋. RANGING 위치 복원은 S4) ----
    async def send_pos(self, pos: dict, spec: str = "all", formation: str | None = None) -> None:
        """pos {id: (x_m, y_m)} (분대장 원점, id 0 포함) → POS_TABLE(heading 0) 전원."""
        pos = dict(pos)
        pos.setdefault(0, (0.0, 0.0))
        self.pos, self.formation = pos, formation or self.formation
        for i, v in pos.items():
            self.live_pos.setdefault(i, v)
        if formation:                              # 프리셋을 새로 고르면 실측 표시도 그 대형에서 다시 시작
            self.live_pos = dict(pos)
        ids = self.targets(spec)
        if ids:
            await self.send_msg(ids, {"type": fc.POS_TABLE, "entries": to_pos_table(pos)})
        else:
            log.info("  (연결된 대상 없음: 위치표만 갱신)")
        self.on_event({"kind": "pos_table", "pos": pos, "sids": ids})

    async def send_pos_preset(self, name: str, spec: str = "all") -> None:
        await self.send_pos(preset_positions(name), spec, name)

    # ---- 상태표 ----
    def status_lines(self) -> list[str]:
        now = time.time()
        out = []
        for sid, st in sorted(self.soldiers.items()):
            unacked = [f"{CMD_NAMES.get(pc.code, pc.code)}#{pc.seq}" for pc in self.cmds.values()
                       if not pc.done and pc.status.get(sid, "x") is None]
            pos = self.pos.get(sid)
            out.append(f"S{sid}: {'연결' if st.connected else '끊김'} MTU {st.mtu or '-'} | EMCON "
                       f"{MODE_NAMES.get(st.emcon, '?')} | 마지막 보고 {st.last_report or '-'} | 미확인 "
                       f"{', '.join(unacked) or '-'} | 위치 {f'({pos[0]:.1f},{pos[1]:.1f})m' if pos else '-'} | 마지막 통신 "
                       f"{f'{now - st.last_rx_t:.0f}초 전' if st.last_rx_t else '-'}")
        return out

    # ---- 위치 복원 (S4): 병사 RANGING → 거리 → MDS → 방향 정렬 → POS_TABLE ----
    def rssi_rows(self) -> dict:
        """{i: {j: rssi}} — 병사 줄만(병사 팀 안내문 D4: 분대장 줄 없음, peer 0 = 보드 A 비콘). 30초 지난 값은 뺀다."""
        now = self.clock()
        rows = {}
        for sid, st in self.soldiers.items():
            r = {p: v[0] for p, v in st.ranging.items() if now - v[2] <= config.RANGING_STALE_S}
            if r:
                rows[sid] = r
        return rows

    def _localize(self, ids, meas, clocks) -> tuple[dict, dict]:
        prior = self.formation or "wedge"
        pos, info = localize(ids, meas, prior, clocks=self.clocks if clocks is None else clocks)
        info["prior"] = prior
        return pos, info

    def compute_auto(self, clocks: dict | None = None) -> tuple[dict, dict]:
        rows = self.rssi_rows()
        ids = sorted({0} | set(self.link.connected_ids()) | set(rows) | {j for r in rows.values() for j in r if j <= 5})
        meas = measured_from_rssi(rows, *self.pathloss)
        pos, info = self._localize(ids, meas, clocks)
        info["rows"] = rows
        return pos, info

    def log_localize(self, pos: dict, info: dict, how: str) -> None:
        al = ("분대장이 본 방향 " + ", ".join(f"S{i} {c}시" for i, c in sorted(info.get("clocks", {}).items()))
              if info.get("align") == "clocks" else f"{info.get('prior')} 대형")
        log.info("위치 복원(%s): 실측 %d/%d쌍(나머지 %s 대형 거리), 방식 %s, 정렬 %s, 거리 잔차 %.1fm%s", how,
                 info["measured"], info["pairs"], info.get("prior"), info["method"], al, info.get("stress", 0.0),
                 f", 방향 잔차 {info['clock_err_m']:.1f}m" if "clock_err_m" in info else "")
        for line in self.matrix_lines(info):
            log.info("  %s", line)
        from .geo import bearing_range, clock_from_azimuth
        res = []
        for i in sorted(pos):
            if i:
                b, r = bearing_range((0, 0), pos[i])
                res.append(f"S{i} {clock_from_azimuth(b)}시 {r:.1f}m ({pos[i][0]:.1f},{pos[i][1]:.1f})")
        log.info("  분대장 기준: %s", ", ".join(res))

    @staticmethod
    def matrix_lines(info: dict) -> list[str]:
        ids, D, src = info["ids"], info["D"], info["src"]
        mark = {"meas": " ", "one": "¹", "prior": "*"}
        name = lambda i: "분대장" if i == 0 else f"S{i}"
        out = ["거리 행렬(m): ¹ 한쪽만 실측, * 대형 값", "      " + "".join(f"{name(j):>8}" for j in ids)]
        for a, i in enumerate(ids):
            out.append(f"{name(i):>6}" + "".join(f"{'-':>8}" if a == b else f"{D[a][b]:>7.1f}{mark[src[a][b]]}"
                                                for b in range(len(ids))))
        return out

    async def pos_auto(self, clocks: dict | None = None, spec: str = "all") -> dict:
        pos, info = self.compute_auto(clocks)
        self.pos_info = info
        self.log_localize(pos, info, "RANGING 실측")
        await self.send_pos(pos, spec)
        return pos

    async def pos_dist(self, d01: float, d02: float, d12: float, clocks: dict | None = None, spec: str = "all") -> dict:
        pos, info = self._localize([0, 1, 2], measured_from_distances(d01, d02, d12), clocks)
        self.pos_info = info
        self.log_localize(pos, info, "거리 직접 입력")
        await self.send_pos(pos, spec)
        return pos

    def update_live(self) -> tuple[dict, dict] | None:
        """실측으로 다시 계산 → 평활 → live_pos. 실측 쌍이 없거나 결과가 대형 방향과 크게 어긋나면 None.
        빠진 쌍(이번 RANGING에 없는 쌍)은 대형 거리 대신 직전 실측 위치 사이 거리로 채운다(현장 실측: 대형 거리 20m로
        채웠더니 1~3m 실측과 어긋나 S2가 반대쪽으로 뒤집혔다)."""
        rows = self.rssi_rows()
        ids = sorted({0} | set(self.link.connected_ids()) | set(rows) | {j for r in rows.values() for j in r if j <= 5})
        meas = measured_from_rssi(rows, *self.pathloss)
        if self.pos_info and self.pos_info.get("measured"):
            for a_, i in enumerate(ids):
                for j in ids[a_ + 1:]:
                    if (i, j) not in meas and (j, i) not in meas and i in self.live_pos and j in self.live_pos:
                        (xi, yi), (xj, yj) = self.live_pos[i], self.live_pos[j]
                        meas[(i, j)] = max(((xi - xj) ** 2 + (yi - yj) ** 2) ** 0.5, 0.1)
        if not any(k for k in meas):
            return None
        pos, info = self._localize(ids, meas, None)
        info["rows"] = rows
        if info["measured"] == 0:
            return None
        ref = max(1.0, sum((x * x + y * y) ** 0.5 for i, (x, y) in pos.items() if i) / max(1, len(pos) - 1))
        if info.get("clock_err_m", 0.0) > max(3.0, 0.6 * ref):
            log.info("위치 복원 결과 버림: 방향 잔차 %.1fm(평균 거리 %.1fm) — 대형 방향과 안 맞음, 직전 위치 유지",
                     info["clock_err_m"], ref)
            return None
        a = self.pos_smooth
        live = {}
        for i, (x, y) in pos.items():
            if i in self.live_pos and i != 0:
                px, py = self.live_pos[i]
                live[i] = (px + a * (x - px), py + a * (y - py))
            else:
                live[i] = (x, y)
        self.live_pos = live
        self.pos_info = info
        self.on_event({"kind": "pos_live", "pos": dict(live), "measured": info["measured"], "pairs": info["pairs"]})
        return live, info

    async def auto_pos_loop(self, stop: asyncio.Event, period_s: float | None = None) -> None:
        """자동 위치: period_s마다 실측 재계산(live_pos, 분대장 표시). 병사 위치표는 처음이거나 auto_pos_move_m 이상
        바뀐 병사가 있을 때만 다시 보낸다(송신량 절약)."""
        while not stop.is_set():
            await asyncio.sleep(period_s or self.auto_pos_period_s)
            if not self.auto_pos or not self.link.connected_ids():
                continue
            got = self.update_live()
            if got is None:
                continue
            live, info = got
            moved = max((((live[i][0] - self.pos[i][0]) ** 2 + (live[i][1] - self.pos[i][1]) ** 2) ** 0.5
                         for i in live if i in self.pos), default=float("inf"))
            if not self.pos or moved >= self.auto_pos_move_m:
                self.log_localize(live, info, f"자동, 최대 이동 {moved:.1f}m" if self.pos else "자동")
                await self.send_pos(live)

    def dist_lines(self) -> list[str]:
        rows = self.rssi_rows()
        p1m, n = self.pathloss
        ids = sorted({0} | set(rows) | {j for r in rows.values() for j in r} | set(self.pos))
        name = lambda i: "분대장" if i == 0 else f"S{i}"
        out = [f"쌍별 거리(경로손실 P1m {p1m:g}, n {n:g}) — i가 j의 비콘을 잰 RSSI 중앙값"]
        for a, i in enumerate(ids):
            for j in ids[a + 1:]:
                parts = [f"{name(x)}→{name(y)} {rows[x][y]}dBm≈{rssi_to_m(rows[x][y], p1m, n):.1f}m"
                         for x, y in ((i, j), (j, i)) if y in rows.get(x, {})]
                tab = (f"위치표 {((self.pos[i][0] - self.pos[j][0]) ** 2 + (self.pos[i][1] - self.pos[j][1]) ** 2) ** 0.5:.1f}m"
                       if i in self.pos and j in self.pos else "위치표 없음")
                if parts or (i in self.pos and j in self.pos):
                    out.append(f"  {name(i)}–{name(j)}: {tab} | " + (", ".join(parts) or "실측 없음"))
        return out

    async def send_peer_type(self, orig_type: int, reporter: int, azimuth: int, dist_band: int, count: int = 0,
                             spec: str = "all") -> None:
        """시험용 수동 PEER_REPORT(CONTACT/SUSPICIOUS/HAZARD/CASUALTY_FOUND)."""
        from .geo import clock_from_azimuth
        clock = clock_from_azimuth(azimuth, 0)
        fields = {fc.CONTACT: dict(azimuth=azimuth, clock=clock, dist_band=dist_band, count=count, heading=0),
                  fc.SUSPICIOUS: dict(azimuth=azimuth, clock=clock, heading=0),
                  fc.HAZARD: dict(azimuth=azimuth, clock=clock, heading=0),
                  fc.CASUALTY_FOUND: dict(azimuth=azimuth, clock=clock, dist_band=dist_band, heading=0)}[orig_type]
        ids = [i for i in self.targets(spec) if i != reporter]
        self._peer_seq = (getattr(self, "_peer_seq", 0x7F) + 1) & 0xFF
        rx, ry = self.pos_dm(reporter)
        await self.send_msg(ids, {"type": fc.PEER_REPORT, "reporter_id": reporter, "rx": rx, "ry": ry,
                                  "orig_type": orig_type, "orig_payload": fc.encode_payload(dict(fields, type=orig_type)),
                                  "orig_seq": self._peer_seq})
