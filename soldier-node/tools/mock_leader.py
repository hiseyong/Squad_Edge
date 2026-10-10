#!/usr/bin/env python3
"""분대장 대역(BLE Central CLI) — 병사 단말 개발용 (CLAUDE.md §7.4, 프로토콜 v1.0.1).

구현 범위(단계 9까지)
- SQ1-S1~S5 스캔·동시 연결, 각 병사 TX Notify 구독, 병사별 MTU 출력, 끊기면 다시 찾아 재연결.
- 수신 프레임을 사람이 읽는 형태로 출력(병사 ID 표시, 연결 ID와 src_id가 다르면 경고).
- 병사 보고(0x01~0x0B) 수신 시 RPT_ACK 자동 송신(`ack off`로 끄면 병사의 긴급 보고 재전송을 볼 수 있다).
  같은 (병사, seq)가 다시 오면 "재전송"으로 표시.
- cmd <name|code> [az] [dist] [extra] [prio] [targets]: CMD_BUTTON 송신. 대상별 ACK/수행 불가를 모아
  "S1 수신, S2 미수신"으로 표시, 15초 안에 ACK 없는 대상에는 같은 seq로 1회 재전송, 그래도 없으면 미수신 알림(프로토콜 §8.1).
- voice <wav> [prio] [targets]: WAV → 모노 8kHz → 앞뒤 무음 제거·정규화(−3dBFS)·최대 10초 → IMA ADPCM →
  VOICE_BEGIN/CHUNK/END(청크 = 병사 MTU−3−6−3, 간격 --gap-ms). VOICE_RESULT 대상별 표시, status≠0이면 같은 voice_id로 1회 재전송(§7.4).
- emcon <0|1|2> [targets]: EMCON_SET(연결 모드). 0이면 병사가 연결을 끊고 수동 스캔으로 간다.
- 침묵 모드 방송: --beacon-port로 분대장 비콘(firmware/diag/LeaderBeacon, 보드 A USB)을 열면
  bcmd <name|code> [az] [dist] [extra] [prio] [targets] / bemcon <1|2> [targets] 로 광고 방송(100ms × 3초).
- --log-csv <파일>: 송수신한 모든 프레임을 CSV로(송신량 비교: tools/tx_summary.py).
- RANGING(0x0E, v1.1 예정) 표시: 피어별 RSSI 중앙값·표본 수 + 경로손실 추정 거리(--pathloss P1m,n, 기본 -59,2.0).
  mark <m>: 거리 보정 시험용 표시(CSV에 'mark' 행 → tools/fit_pathloss.py가 구간을 나눔).
- 단계 9(분대 위치표·다른 병사 보고):
  pos <wedge|line|column|auto> [targets]: POS_TABLE(분대장 원점, 간격 10m, heading 0). auto = RANGING 실측 →
    tools/squad_localize.py(쌍별 거리 → MDS → 분대장 원점, 현재 대형 기준 정렬), 실측 없는 쌍은 대형 거리로 채움.
  peer <reporter_id> <az> <dist> <count> [targets]: 수동 PEER_REPORT(CONTACT).
  relay on|off(기본 on): 병사의 CONTACT/SUSPICIOUS/HAZARD/CASUALTY_FOUND를 다른 연결된 병사들에게 PEER_REPORT로 중계.
  map: ASCII 대형 지도(분대장 L, 병사 1~5, 마지막 표적 T) + 병사별 표적 방향. dist: 쌍별 거리(POS_TABLE vs RSSI 실측).
  분대장 줄(ID 0) RSSI: --beacon-port 보드 A(LeaderBeacon)가 병사 비콘을 재서 'BCN …'으로 알려 줌. lbeacon on|off = 보드 A
  분대장 위치 비콘(BEACON src 0) 켜고 끄기.
- 명령: cmd, voice, emcon, bcmd, bemcon, mark, pos, peer, relay, map, dist, lbeacon, raw <id|all> <hex>,
  stats <id|all>, ack on|off, list, help, quit

사용
    python3 tools/mock_leader.py                # SQ1-S1~S5 모두
    python3 tools/mock_leader.py --only S1      # S1만
    python3 tools/mock_leader.py --only S1,S2

macOS: 처음 실행하면 터미널(또는 IDE)에 Bluetooth 권한을 묻는다. 허용해야 스캔된다.
"""

import argparse
import array
import asyncio
import csv
import datetime
import math
import select
import termios
import tty
import os
import re
import sys
import threading
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adpcm  # noqa: E402
import frame_codec as fc  # noqa: E402
import squad_localize as sl  # noqa: E402

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    print("bleak가 없습니다. 설치: python3 -m pip install -r tools/requirements.txt")
    sys.exit(1)

NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # 분대장 → 병사 (Write)
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # 병사 → 분대장 (Notify)
NAME_RE = re.compile(r"^SQ1-S([1-5])$")

DIST_NAMES = {0: "근거리", 1: "중거리", 2: "원거리", 0xFF: "거리없음"}
MODE_NAMES = {0: "침묵", 1: "최소", 2: "정상"}
VOICE_STATUS = {0: "정상", 1: "CRC 오류", 2: "시간 초과", 3: "메모리 부족"}
PATHLOSS = {"p1m": -59.0, "n": 2.0}  # --pathloss로 바꿈(tools/fit_pathloss.py 결과)


def est_distance(rssi):
    return 10 ** ((PATHLOSS["p1m"] - rssi) / (10 * PATHLOSS["n"]))


RANGING_STALE_S = 30.0   # 이보다 오래된 RANGING/비콘 값은 위치 계산에 쓰지 않음(펌웨어 RANGING_STALE_MS와 같게)
RSSI_WINDOW = 15         # 분대장 줄 이동 중앙값 창(펌웨어 RANGING_WINDOW와 같게)
PEER_TYPES = {fc.CONTACT, fc.SUSPICIOUS, fc.HAZARD, fc.CASUALTY_FOUND}  # 중계 대상(단계 9)


def peer_name(pid):
    return "분대장" if pid == 0 else f"S{pid}"


def median(v):
    s = sorted(v)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else int((s[n // 2 - 1] + s[n // 2]) / 2)  # 펌웨어처럼 0쪽으로 버림
CMD_ACK_TIMEOUT_S = 15.0  # 프로토콜 §8.1-5
DIST_ARGS = {"near": 0, "mid": 1, "far": 2, "0": 0, "1": 1, "2": 2, "-": fc.NO_DIST, "none": fc.NO_DIST}
CMD_NAMES = {v: k for k, v in fc.CMD_CODES.items()}


def parse_cmd_code(tok):
    t = tok.upper()
    if t in fc.CMD_CODES:
        return fc.CMD_CODES[t]
    try:
        code = int(tok, 0)
    except ValueError:
        raise ValueError(f"명령 '{tok}' 모름. 이름: {', '.join(k.lower() for k in fc.CMD_CODES)}") from None
    if code not in CMD_NAMES:
        raise ValueError(f"cmd_code 0x{code:02X}는 프로토콜 §6.2에 없음")
    return code


class PendingCmd:
    def __init__(self, seq, code, raw, targets):
        self.seq, self.code, self.raw = seq, code, raw
        self.status = {sid: None for sid in targets}  # None 미수신 / "수신" / "수행 불가"
        self.sent_at = time.monotonic()
        self.retried = False
        self.done = False

    def summary(self):
        parts = [f"S{sid} {st or '미수신'}" for sid, st in sorted(self.status.items())]
        return f"cmd seq={self.seq} {CMD_NAMES[self.code]}: " + ", ".join(parts)


def load_wav_8k(path, max_s=10.0):
    """WAV → 모노 8kHz int16 목록(프로토콜 §7.1 전처리: 리샘플, 앞뒤 무음 제거, 최대 −3dBFS 정규화)."""
    with wave.open(path, "rb") as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw == 2:
        a = array.array("h")
        a.frombytes(raw)
        if sys.byteorder == "big":
            a.byteswap()
        x = list(a)
    elif sw == 1:
        x = [(b - 128) << 8 for b in raw]
    else:
        raise ValueError(f"{sw * 8}비트 WAV는 지원하지 않음(8/16비트 PCM만)")
    if ch > 1:
        x = [sum(x[i:i + ch]) // ch for i in range(0, len(x), ch)]
    if rate != 8000:  # 선형 보간 리샘플
        m = int(len(x) * 8000 / rate)
        step = rate / 8000
        x = [int(x[min(int(i * step), len(x) - 1)] + (x[min(int(i * step) + 1, len(x) - 1)] - x[min(int(i * step), len(x) - 1)]) * ((i * step) % 1)) for i in range(m)]
    peak = max((abs(v) for v in x), default=0)
    if peak == 0:
        raise ValueError("무음 WAV")
    thr = peak * 0.02
    first = next(i for i, v in enumerate(x) if abs(v) > thr)
    last = len(x) - next(i for i, v in enumerate(reversed(x)) if abs(v) > thr)
    x = x[max(0, first - 400):min(len(x), last + 400)]  # 앞뒤 50ms 여유
    x = x[:int(max_s * 8000)]
    g = 0.7079 * 32767 / max(abs(v) for v in x)
    return [max(-32768, min(32767, int(v * g))) for v in x]


class PendingVoice:
    def __init__(self, voice_id, path, data, nsamples, prio, dst, targets):
        self.voice_id, self.path, self.data, self.nsamples, self.prio, self.dst = voice_id, path, data, nsamples, prio, dst
        self.crc = fc.crc16_ccitt_false(data)
        self.status = {sid: None for sid in targets}
        self.retried = set()
        self.gen = {sid: 0 for sid in targets}  # 병사별 전송 세대: 바뀌면 진행 중인 전송을 멈춤

    def summary(self):
        parts = [f"S{sid} {'대기' if st is None else ml_voice_status(st)}" for sid, st in sorted(self.status.items())]
        return f"voice {self.voice_id}: " + ", ".join(parts)


def ml_voice_status(st):
    return VOICE_STATUS.get(st, str(st))


# RPT_ACK를 자동으로 보내는 병사 → 분대장 메시지(보고 코드 0x01~0x0B; STATS/LOG/RANGING 제외)
REPORT_TYPES = set(range(0x01, 0x0C))


def ts():
    return time.strftime("%H:%M:%S")


def log(msg):
    print(f"{ts()} {msg}", flush=True)


def az_text(az):
    return "방위 없음" if az == fc.NO_AZIMUTH else f"방위 {az}°"


def clock_text(c):
    return "시계 없음" if c == 0 else f"{c}시"


def describe(m):
    """디코드된 프레임 → 한 줄 설명."""
    t = m["type"]
    name = fc.MSG_NAMES.get(t, f"0x{t:02X}")
    head = f"{name} seq={m['seq']} src={m['src']} dst=0x{m['dst']:02X}"
    if t == fc.CONTACT:
        cnt = {0: "미상", 5: "다수"}.get(m["count"], str(m["count"]))
        body = f"적 {cnt}, {az_text(m['azimuth'])}, {clock_text(m['clock'])}, {DIST_NAMES.get(m['dist_band'], m['dist_band'])}, heading {m['heading']}"
    elif t in (fc.SUSPICIOUS, fc.HAZARD):
        body = f"{az_text(m['azimuth'])}, {clock_text(m['clock'])}, heading {m['heading']}"
    elif t == fc.CASUALTY_FOUND:
        body = f"{az_text(m['azimuth'])}, {clock_text(m['clock'])}, {DIST_NAMES.get(m['dist_band'], m['dist_band'])}"
    elif t == fc.CASUALTY_SELF:
        body = f"heading {m['heading']}"
    elif t in (fc.ACK, fc.CANNOT_COMPLY):
        kind = {fc.REF_BUTTON: "버튼 명령 seq", fc.REF_VOICE: "음성 voice_id"}.get(m["ref_type"], f"ref_type 0x{m['ref_type']:02X}")
        body = f"대상 {kind} {m['ref_id']}"
    elif t == fc.VOICE_RESULT:
        body = f"voice_id {m['voice_id']} {VOICE_STATUS.get(m['status'], m['status'])}"
    elif t in (fc.EMCON_STATE, fc.EMCON_SET):
        body = f"모드 {m['mode']}({MODE_NAMES.get(m['mode'], '?')})"
    elif t == fc.STATS:
        body = ", ".join(f"EMCON{i} {m['tx_frames'][i]}프레임/{m['tx_bytes'][i]}B" for i in range(3))
    elif t == fc.CMD_BUTTON:
        name = {v: k for k, v in fc.CMD_CODES.items()}.get(m["cmd_code"], f"0x{m['cmd_code']:02X}")
        body = f"{name}, {az_text(m['azimuth'])}, {DIST_NAMES.get(m['dist_band'], m['dist_band'])}, extra {m['extra']}, {'긴급' if m['priority'] else '일반'}"
    elif t == fc.LOG:
        body = f'"{m["text"]}"'
    elif t == fc.RANGING:
        body = ", ".join(f"{peer_name(p['peer_id'])} {p['rssi_avg']}dBm×{p['samples']} ≈{est_distance(p['rssi_avg']):.1f}m"
                         for p in m["peers"]) or "피어 없음"
    elif t == fc.POS_TABLE:
        body = ", ".join(f"{peer_name(e['id'])}({e['x'] / 10:g},{e['y'] / 10:g})m h{e['heading']}" for e in m["entries"])
    elif t == fc.PEER_REPORT:
        o = m.get("orig")
        pos = "위치 모름" if fc.POS_UNKNOWN in (m["rx"], m["ry"]) else f"({m['rx'] / 10:g},{m['ry'] / 10:g})m"
        inner = describe(dict(o, seq=0, src=m["reporter_id"], dst=0)).split(" | ", 1)[-1] if o else "원 보고 해석 불가"
        body = f"보고자 S{m['reporter_id']} {pos}, {fc.MSG_NAMES.get(m['orig_type'], hex(m['orig_type']))}: {inner}"
    else:
        body = ", ".join(f"{k}={v}" for k, v in m.items() if k not in ("type", "seq", "src", "dst"))
    return f"{head} | {body}" if body else head


class Soldier:
    def __init__(self, sid):
        self.sid = sid
        self.client = None
        self.mtu = 0
        self.connected = False
        self.connecting = False
        self.pending_acks = []  # 연결 설정이 끝나기 전에 온 보고의 RPT_ACK(연결 완료 후 송신)


class Leader:
    def __init__(self, allowed):
        self.allowed = allowed  # 연결할 병사 ID 집합
        self.soldiers = {sid: Soldier(sid) for sid in allowed}
        self.seq = 0
        self.stop = asyncio.Event()
        self.auto_ack = True
        self.cmds = {}  # seq -> PendingCmd (ACK 수집 중인 버튼 명령)
        self.voices = {}  # voice_id -> PendingVoice
        self.voice_id = 0
        self.gap_ms = 15
        self.csv = None       # (파일, writer)
        self.t0 = time.monotonic()
        self.beacon_fd = None
        self.tasks = set()  # 백그라운드 작업 참조 유지(가비지 수집으로 'Task was destroyed' 방지)
        self.seen = {sid: [] for sid in allowed}  # 병사별 최근 보고 seq(재전송 표시용)
        # 단계 9
        self.relay = True
        self.formation = None     # 마지막으로 보낸 프리셋 대형(auto의 정렬 기준)
        self.pos = {}             # 마지막 POS_TABLE {id: (x_m, y_m)}
        self.ranging = {}         # 병사 줄 {sid: {peer: (rssi, samples, t)}}
        self.leader_rssi = {}     # 분대장 줄 {sid: [(t, rssi), ...]} (보드 A 'BCN')
        self.headings = {}        # 비콘 heading {sid: deg}
        self.bcn_lines = 0
        self.last_target = None   # (reporter, az, dist_band, 설명)

    # ---------- 연결 ----------
    def on_adv(self, device, adv):
        name = adv.local_name or device.name or ""
        mt = NAME_RE.match(name)
        if not mt:
            return
        sid = int(mt.group(1))
        s = self.soldiers.get(sid)
        if s is None or s.connected or s.connecting:
            return
        s.connecting = True
        self.spawn(self.connect(s, device))

    async def connect(self, s, device):
        log(f"[S{s.sid}] 발견 → 연결 시도 ({device.address})")
        client = BleakClient(device, disconnected_callback=lambda _c, sid=s.sid: self.on_disconnect(sid))
        try:
            await client.connect(timeout=15.0)
            s.client = client
            s.mtu = client.mtu_size
            await client.start_notify(NUS_TX, lambda _ch, data, sid=s.sid: self.on_notify(sid, data))
            s.connected = True
            log(f"[S{s.sid}] 연결됨, Notify 구독, MTU={s.mtu} (한 번에 쓸 수 있는 최대 {s.mtu - 3}B)")
            acks, s.pending_acks = s.pending_acks, []
            for ref in acks:  # 연결 설정 중에 받은 보고(병사 큐에서 바로 나온 것)
                self.spawn(self.send_rpt_ack(s.sid, ref))
        except Exception as e:  # noqa: BLE001 - 연결 실패 원인을 그대로 보여 준다
            log(f"[S{s.sid}] 연결 실패: {e!r}")
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        finally:
            s.connecting = False

    def on_disconnect(self, sid):
        s = self.soldiers[sid]
        if s.connected:
            log(f"[S{sid}] 연결 끊김 → 다시 찾는 중")
        s.connected = False
        s.client = None
        s.mtu = 0
        s.pending_acks = []

    async def scan_forever(self):
        scanner = BleakScanner(detection_callback=self.on_adv, service_uuids=[NUS_SERVICE])
        scanning = False
        while not self.stop.is_set():
            need = any(not s.connected for s in self.soldiers.values())
            if need and not scanning:
                await scanner.start()
                scanning = True
            elif not need and scanning:
                await scanner.stop()
                scanning = False
            await asyncio.sleep(1.0)
        if scanning:
            await scanner.stop()

    # ---------- 수신 ----------
    # ---------- CSV ----------
    def open_csv(self, path):
        f = open(path, "w", newline="", encoding="utf-8")
        w = csv.writer(f)
        w.writerow(["time", "t_s", "dir", "soldier", "type", "name", "seq", "src", "dst", "len", "hex"])
        self.csv = (f, w)
        log(f"CSV 기록: {path}")

    def record(self, direction, sid, raw):
        if self.csv is None:
            return
        raw = bytes(raw)
        t = raw[1] if len(raw) > 1 else -1
        row = [datetime.datetime.now().isoformat(timespec="milliseconds"), f"{time.monotonic() - self.t0:.3f}",
               direction, sid, f"0x{t:02X}" if t >= 0 else "", fc.MSG_NAMES.get(t, "?"),
               raw[2] if len(raw) > 2 else "", raw[3] if len(raw) > 3 else "", f"0x{raw[4]:02X}" if len(raw) > 4 else "",
               len(raw), raw.hex()]
        self.csv[1].writerow(row)
        self.csv[0].flush()

    # ---------- 분대장 비콘(침묵 모드 방송, USB) ----------
    def open_beacon(self, path):
        fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        tty.setraw(fd)
        attrs = termios.tcgetattr(fd)
        attrs[4] = attrs[5] = termios.B115200  # 1200bps는 부트로더 진입이므로 쓰지 않는다
        termios.tcsetattr(fd, termios.TCSANOW, attrs)
        self.beacon_fd = fd
        log(f"분대장 비콘 포트: {path}")

    async def beacon_reader(self):
        buf = b""
        while not self.stop.is_set():
            if self.beacon_fd is None:
                await asyncio.sleep(0.5)
                continue
            r, _, _ = select.select([self.beacon_fd], [], [], 0)
            if r:
                try:
                    buf += os.read(self.beacon_fd, 1024)
                except OSError as e:
                    log(f"비콘 포트 읽기 오류: {e}")
                    self.beacon_fd = None
                    continue
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    text = line.decode(errors="replace").strip()
                    if text.startswith("BCN "):
                        self.on_leader_bcn(text)  # 병사 비콘 RSSI(분대장 줄) — 화면에는 찍지 않음(초당 여러 줄)
                    elif text:
                        log(f"[비콘] {text}")
            await asyncio.sleep(0.05)

    def beacon_send(self, raw):
        if self.beacon_fd is None:
            raise ValueError("비콘 포트가 없음: --beacon-port /dev/cu.usbmodem… 로 실행")
        os.write(self.beacon_fd, (fc.to_hex(raw) + "\n").encode())
        self.record("tx_adv", "beacon", raw)
        log(f"[비콘] → 방송 요청 {describe(fc.decode(raw))}  ({fc.to_hex(raw)})")

    def on_leader_bcn(self, text):
        try:
            _, src, rssi, hd = text.split()
            src, rssi, hd = int(src), int(rssi), int(hd)
        except ValueError:
            return
        self.bcn_lines += 1
        now = time.monotonic()
        v = self.leader_rssi.setdefault(src, [])
        if v and now - v[-1][0] > RANGING_STALE_S:
            v.clear()  # 오래 끊겼다 다시 들림 → 새로 시작
        v.append((now, rssi))
        del v[:-RSSI_WINDOW]
        if hd != fc.NO_HEADING:
            self.headings[src] = hd

    def leader_row(self):
        """분대장 줄: {sid: rssi 중앙값} (30초 안, 3개 이상)."""
        now = time.monotonic()
        row = {}
        for sid, v in self.leader_rssi.items():
            if v and now - v[-1][0] <= RANGING_STALE_S and len(v) >= 3:
                row[sid] = median([r for _, r in v])
        return row

    def rssi_rows(self):
        """{i: {j: rssi}} — 병사 줄(RANGING) + 분대장 줄(보드 A)."""
        now = time.monotonic()
        rows = {}
        for sid, peers in self.ranging.items():
            r = {p: v[0] for p, v in peers.items() if now - v[2] <= RANGING_STALE_S}
            if r:
                rows[sid] = r
        lr = self.leader_row()
        if lr:
            rows[0] = lr
        return rows

    def on_notify(self, sid, data):
        data = bytes(data)
        self.record("rx", sid, data)
        try:
            m = fc.decode(data)
        except fc.FrameError as e:
            log(f"[S{sid}] ← 잘못된 프레임({e}): {fc.to_hex(data)}")
            return
        warn = "" if m["src"] == sid else f"  ⚠ 연결 ID S{sid} ≠ src_id {m['src']}"
        tag = ""
        if m["type"] in REPORT_TYPES:
            recent = self.seen[sid]
            if m["seq"] in recent:
                tag = "  ↻ 재전송(같은 seq)"
            else:
                recent.append(m["seq"])
                del recent[:-16]
            if fc.is_urgent(m["type"]):
                tag += "  ★긴급"
        log(f"[S{sid}] ← {describe(m)}{tag}{warn}")
        if m["type"] in (fc.ACK, fc.CANNOT_COMPLY) and m["ref_type"] == fc.REF_BUTTON:
            self.on_cmd_ack(sid, m["ref_id"], "수신" if m["type"] == fc.ACK else "수행 불가")
        if m["type"] == fc.VOICE_RESULT:
            self.on_voice_result(sid, m["voice_id"], m["status"])
        if m["type"] == fc.RANGING:
            now = time.monotonic()
            self.ranging[sid] = {p["peer_id"]: (p["rssi_avg"], p["samples"], now) for p in m["peers"]}
        if m["type"] in PEER_TYPES and "재전송" not in tag:
            self.on_peer_report(sid, m)
        if m["type"] in REPORT_TYPES:
            if self.auto_ack:
                s = self.soldiers[sid]
                if s.connected:
                    self.spawn(self.send_rpt_ack(sid, m["seq"]))
                else:  # Notify는 켜졌지만 연결 설정(start_notify 이후)이 아직 → 끝나면 보냄
                    s.pending_acks.append(m["seq"])
            else:
                log(f"[S{sid}]   (ack off: RPT_ACK 보내지 않음)")

    def on_cmd_ack(self, sid, ref_id, what):
        pc = self.cmds.get(ref_id)
        if pc is None or sid not in pc.status:
            log(f"[S{sid}]   (참고) seq={ref_id}는 추적 중인 명령/대상이 아님")
            return
        first = pc.status[sid] is None
        pc.status[sid] = what
        if first:
            log(f"  ▶ {pc.summary()}")
        if not pc.done and all(v is not None for v in pc.status.values()):
            pc.done = True
            log(f"  ✔ 전원 응답: {pc.summary()}")

    async def watch_cmds(self):
        while not self.stop.is_set():
            await asyncio.sleep(0.5)
            now = time.monotonic()
            for pc in list(self.cmds.values()):
                if pc.done or now - pc.sent_at < CMD_ACK_TIMEOUT_S:
                    continue
                missing = [sid for sid, st in pc.status.items() if st is None]
                if not pc.retried:
                    pc.retried = True
                    pc.sent_at = now
                    log(f"  ⏱ 15초 ACK 없음 → 같은 seq={pc.seq}로 1회 재전송: {', '.join(f'S{i}' for i in missing)}")
                    await self.write([i for i in missing if self.soldiers[i].connected], pc.raw)
                else:
                    pc.done = True
                    log(f"  ✖ 재전송 후에도 ACK 없음: {pc.summary()}")

    def build_cmd(self, args, ids, spec):
        """cmd/bcmd 공통: 인자 → CMD_BUTTON 프레임(bytes), cmd_code."""
        code = parse_cmd_code(args[0])
        opt = args[1:] + ["-"] * (6 - len(args))
        az_s, dist_s, extra_s, prio_s = opt[:4]
        az = fc.NO_AZIMUTH if az_s in ("-", "none") else int(az_s)
        if az != fc.NO_AZIMUTH and not 0 <= az <= 359:
            raise ValueError("az는 0~359 또는 '-'")
        if dist_s.lower() not in DIST_ARGS:
            raise ValueError("dist는 near|mid|far|0|1|2|-")
        extra = 0 if extra_s == "-" else int(extra_s)
        prio = 0 if prio_s == "-" else int(prio_s)
        if prio not in (0, 1):
            raise ValueError("prio는 0 또는 1")
        dst = fc.DST_ALL_SOLDIERS if spec.lower() == "all" else fc.dst_mask(ids)
        raw = fc.encode(dict(type=fc.CMD_BUTTON, seq=self.next_seq(), src=fc.LEADER_ID, dst=dst, cmd_code=code,
                             azimuth=az, dist_band=DIST_ARGS[dist_s.lower()], extra=extra, priority=prio))
        return raw, code

    def spec_ids(self, spec):
        """방송용 대상(연결 여부와 무관): all | 1 | 1,2."""
        if spec.lower() == "all":
            return list(range(1, 6))
        return [int(p.strip().upper().lstrip("S")) for p in spec.split(",")]

    async def send_bcmd(self, args):
        if not args or len(args) > 6:
            raise ValueError("사용: bcmd <name|code> [az] [dist] [extra] [prio] [targets]  (침묵 모드 광고, 비콘 보드 경유)")
        spec = args[5] if len(args) == 6 and args[5] != "-" else "all"
        raw, _ = self.build_cmd(args, self.spec_ids(spec), spec)
        self.beacon_send(raw)

    async def send_emcon(self, args, via_beacon):
        if not args or len(args) > 2 or args[0] not in ("0", "1", "2"):
            raise ValueError("사용: emcon <0|1|2> [targets]  /  bemcon <1|2> [targets](광고)")
        mode = int(args[0])
        spec = args[1] if len(args) == 2 else "all"
        if via_beacon:
            if mode == 0:
                raise ValueError("bemcon 0은 의미 없음(광고를 받는 병사는 이미 침묵 모드). bemcon 1|2로 연결 모드로 되돌린다")
            ids = self.spec_ids(spec)
            dst = fc.DST_ALL_SOLDIERS if spec.lower() == "all" else fc.dst_mask(ids)
            self.beacon_send(fc.encode(dict(type=fc.EMCON_SET, seq=self.next_seq(), src=fc.LEADER_ID, dst=dst, mode=mode)))
            return
        ids = self.targets(spec)
        if not ids:
            return
        dst = fc.DST_ALL_SOLDIERS if spec.lower() == "all" else fc.dst_mask(ids)
        await self.write(ids, fc.encode(dict(type=fc.EMCON_SET, seq=self.next_seq(), src=fc.LEADER_ID, dst=dst, mode=mode)))
        if mode == 0:
            log("  (병사는 연결을 끊고 수동 스캔으로 감 — 되돌리려면 bemcon 1|2 또는 병사 조작)")

    async def send_cmd(self, args):
        if not args:
            raise ValueError("사용: cmd <name|code> [az] [dist] [extra] [prio] [targets]  ('-' = 기본값)")
        if len(args) > 6:
            raise ValueError(f"인자가 너무 많음({len(args)}개): 한 줄에 명령 하나만. 사용: cmd <name|code> [az] [dist] [extra] [prio] [targets]")
        code = parse_cmd_code(args[0])
        opt = args[1:] + ["-"] * (6 - len(args))
        az_s, dist_s, extra_s, prio_s, tgt_s = opt[:5]
        az = fc.NO_AZIMUTH if az_s in ("-", "none") else int(az_s)
        if az != fc.NO_AZIMUTH and not 0 <= az <= 359:
            raise ValueError("az는 0~359 또는 '-'")
        if dist_s.lower() not in DIST_ARGS:
            raise ValueError("dist는 near|mid|far|0|1|2|-")
        dist = DIST_ARGS[dist_s.lower()]
        extra = 0 if extra_s == "-" else int(extra_s)
        prio = 0 if prio_s == "-" else int(prio_s)
        if prio not in (0, 1):
            raise ValueError("prio는 0 또는 1")
        spec = "all" if tgt_s == "-" else tgt_s
        ids = self.targets(spec)
        if not ids:
            return
        dst = fc.DST_ALL_SOLDIERS if spec.lower() == "all" else fc.dst_mask(ids)  # 전원 = 0x1F(§11.1 예시와 같음)
        seq = self.next_seq()
        raw = fc.encode(dict(type=fc.CMD_BUTTON, seq=seq, src=fc.LEADER_ID, dst=dst, cmd_code=code, azimuth=az,
                             dist_band=dist, extra=extra, priority=prio))
        self.cmds[seq] = PendingCmd(seq, code, raw, ids)
        await self.write(ids, raw)
        log(f"  ▶ {self.cmds[seq].summary()}  (15초 안에 ACK 없으면 1회 재전송)")

    def spawn(self, coro):
        t = asyncio.get_running_loop().create_task(coro)
        self.tasks.add(t)
        t.add_done_callback(self.tasks.discard)
        return t

    def on_voice_result(self, sid, voice_id, status):
        pv = self.voices.get(voice_id)
        if pv is None or sid not in pv.status:
            return
        pv.status[sid] = status
        log(f"  ▶ {pv.summary()}")
        if status != 0:
            pv.gen[sid] += 1  # 병사가 이미 실패를 알렸으니 진행 중인 청크 전송은 멈춘다
        if status != 0 and sid not in pv.retried and self.soldiers[sid].connected:
            pv.retried.add(sid)
            log(f"  ↻ S{sid} {ml_voice_status(status)} → 같은 voice_id={voice_id}로 전체 1회 재전송(§7.4-5)")
            self.spawn(self.stream_voice(pv, sid))

    async def stream_voice(self, pv, sid):
        s = self.soldiers[sid]
        n = s.mtu - 3 - fc.HDR_LEN - 3  # 프로토콜 §7.3: N = (MTU−3) − 헤더 6 − 3
        if n <= 0:
            log(f"[S{sid}] MTU {s.mtu}로는 음성을 보낼 수 없음")
            return
        chunks = [pv.data[i:i + n] for i in range(0, len(pv.data), n)]
        my_gen = pv.gen[sid]
        base = dict(src=fc.LEADER_ID, dst=pv.dst)
        begin = fc.encode(dict(base, type=fc.VOICE_BEGIN, seq=self.next_seq(), voice_id=pv.voice_id, codec=1,
                               sample_rate=8000, total_samples=pv.nsamples, total_chunks=len(chunks), predictor=0,
                               step_index=0, priority=pv.prio))
        t0 = time.monotonic()
        try:
            await s.client.write_gatt_char(NUS_RX, begin, response=True)
            self.record("tx", sid, begin)
            for i, c in enumerate(chunks):
                if pv.gen[sid] != my_gen or not s.connected:
                    log(f"[S{sid}] → 음성 {pv.voice_id} 전송 중단({i}/{len(chunks)} 청크에서)")
                    return
                f = fc.encode(dict(base, type=fc.VOICE_CHUNK, seq=self.next_seq(), voice_id=pv.voice_id, chunk_idx=i, data=c))
                await s.client.write_gatt_char(NUS_RX, f, response=False)
                self.record("tx", sid, f)
                await asyncio.sleep(self.gap_ms / 1000)
            end = fc.encode(dict(base, type=fc.VOICE_END, seq=self.next_seq(), voice_id=pv.voice_id, crc16=pv.crc))
            await s.client.write_gatt_char(NUS_RX, end, response=True)
            self.record("tx", sid, end)
        except Exception as e:  # noqa: BLE001
            log(f"[S{sid}] → 음성 송신 실패: {e!r}")
            return
        dt = time.monotonic() - t0
        log(f"[S{sid}] → 음성 {pv.voice_id} 송신 완료: {len(pv.data)}B, 청크 {len(chunks)}×{n}B, {dt:.2f}초 "
            f"({len(pv.data) / dt / 1000:.1f}kB/s), CRC {pv.crc:04X}")

    async def send_voice(self, args):
        if not args or len(args) > 3:
            raise ValueError("사용: voice <wav> [prio] [targets]  (예: voice assets/test_voice/cover_9.wav 0 all)")
        path = os.path.expanduser(args[0])
        prio = 0 if len(args) < 2 or args[1] == "-" else int(args[1])
        spec = "all" if len(args) < 3 or args[2] == "-" else args[2]
        if prio not in (0, 1):
            raise ValueError("prio는 0 또는 1")
        try:
            samples = load_wav_8k(path)
        except (OSError, ValueError, wave.Error, StopIteration) as e:
            raise ValueError(f"WAV 읽기 실패: {e}") from None
        ids = self.targets(spec)
        if not ids:
            return
        data, _ = adpcm.encode(samples, 0, 0)
        dst = fc.DST_ALL_SOLDIERS if spec.lower() == "all" else fc.dst_mask(ids)
        pv = PendingVoice(self.voice_id, path, data, len(samples), prio, dst, ids)
        self.voices[pv.voice_id] = pv
        self.voice_id = (self.voice_id + 1) & 0xFF
        log(f"음성 {pv.voice_id}: {os.path.basename(path)} → {len(samples) / 8000:.2f}초, ADPCM {len(data)}B, "
            f"{'긴급' if prio else '일반'}, 대상 {', '.join(f'S{i}' for i in ids)}")
        self.spawn(self.stream_all(pv, ids))  # 백그라운드: CLI가 막히지 않게

    async def stream_all(self, pv, ids):
        for sid in ids:  # 병사별로 차례로(각자 MTU에 맞춘 청크)
            await self.stream_voice(pv, sid)

    async def send_rpt_ack(self, sid, ref_seq):
        await self.send_msg([sid], {"type": fc.RPT_ACK, "ref_seq": ref_seq})

    # ---------- 송신 ----------
    def targets(self, spec):
        """'all' / '1' / 'S1' / '1,2' → 연결된 병사 ID 목록."""
        if spec.lower() == "all":
            ids = sorted(self.soldiers)
        else:
            ids = []
            for part in spec.split(","):
                part = part.strip().upper().lstrip("S")
                if not part.isdigit() or int(part) not in self.soldiers:
                    raise ValueError(f"대상 '{spec}' 이해 못 함(연결 허용: {sorted(self.soldiers)})")
                ids.append(int(part))
        live = [i for i in ids if self.soldiers[i].connected]
        for i in ids:
            if i not in live:
                log(f"[S{i}] 연결 안 됨 → 건너뜀")
        return live

    def next_seq(self):
        s = self.seq
        self.seq = (self.seq + 1) & 0xFF
        return s

    async def write(self, ids, raw, response=True):
        m = None
        try:
            m = fc.decode(raw)
        except fc.FrameError as e:
            log(f"(참고) 프로토콜 형식이 아님: {e}")
        for sid in ids:
            s = self.soldiers[sid]
            if len(raw) > s.mtu - 3:
                log(f"[S{sid}] → 보내지 않음: {len(raw)}B > MTU-3 ({s.mtu - 3}B)")
                continue
            if m is not None and not fc.addressed_to_soldier(m["dst"], sid):
                log(f"[S{sid}] (참고) dst=0x{m['dst']:02X}에 S{sid} 비트가 없음 → 병사가 폐기할 것")
            what = describe(m) if m is not None else "raw"
            try:
                await s.client.write_gatt_char(NUS_RX, raw, response=response)
                self.record("tx", sid, raw)
                log(f"[S{sid}] → {what}  ({fc.to_hex(raw)})")
            except Exception as e:  # noqa: BLE001
                log(f"[S{sid}] → 쓰기 실패: {e!r}")

    async def send_msg(self, ids, msg):
        if not ids:
            return
        msg = dict(msg, seq=self.next_seq(), src=fc.LEADER_ID, dst=fc.dst_mask(ids))
        await self.write(ids, fc.encode(msg))

    # ---------- 단계 9: POS_TABLE, PEER_REPORT 중계, 지도 ----------
    def on_peer_report(self, sid, m):
        orig = fc.encode_payload(dict(m))
        az = m.get("azimuth", fc.NO_AZIMUTH)
        band = m.get("dist_band", fc.NO_DIST)
        self.last_target = (sid, az, band, describe(m).split(" | ", 1)[-1])
        if not self.relay:
            return
        others = [i for i, s in self.soldiers.items() if i != sid and s.connected]
        if not others:
            log(f"  (중계 대상 없음: S{sid} 말고 연결된 병사 없음)")
            return
        rx, ry = self.pos_dm(sid)
        msg = {"type": fc.PEER_REPORT, "reporter_id": sid, "rx": rx, "ry": ry, "orig_type": m["type"], "orig_payload": orig}
        if rx == fc.POS_UNKNOWN:
            log("  (POS_TABLE을 아직 안 보냄: 보고자 위치 0x8000 = 모름 → 병사는 보고자 기준 방향으로 재생. 'pos wedge' 등 먼저)")
        self.spawn(self.send_msg(others, msg))
        self.spawn(self._print_peer_view(sid, az, band))

    async def _print_peer_view(self, sid, az, band):
        await asyncio.sleep(0)  # 송신 로그 뒤에
        for line in self.peer_view(sid, az, band):
            log(f"  ▷ {line}")

    def pos_dm(self, sid):
        if sid not in self.pos:
            return fc.POS_UNKNOWN, fc.POS_UNKNOWN
        x, y = self.pos[sid]
        return int(round(x * 10)), int(round(y * 10))

    def peer_view(self, rep, az, band):
        """병사별로 그 표적이 어떻게 들리는지(펌웨어와 같은 계산, heading 0 가정)."""
        if rep not in self.pos:
            return ["(위치표 없음: 병사는 보고자 기준 방향 그대로 재생)"]
        if az == fc.NO_AZIMUTH:
            return ["(방향 미상 보고: 병사는 보고자 쪽 방향으로 재생)"]
        out = []
        for sid in sorted(i for i in self.pos if i != 0 and i != rep):
            c, b, brg, r = sl.peer_to_me(self.pos[rep], az, band, self.pos[sid], self.headings.get(sid, 0))
            out.append(f"S{sid} 기준: {c}시 {DIST_NAMES[b]} (방위 {brg}°, {r:.0f}m)")
        return out

    def render_map(self):
        if not self.pos:
            return ["(POS_TABLE 없음: pos wedge|line|column|auto 먼저)"]
        pts = dict(self.pos)
        tgt = None
        if self.last_target and self.last_target[0] in pts and self.last_target[1] != fc.NO_AZIMUTH:
            rep, az, band, _ = self.last_target
            tgt = sl.target_pos(pts[rep], az, band)
        ext = list(pts.values())
        if tgt and max(sl.dist(tgt, p) for p in ext) <= 120:  # 가까운 표적(근·중거리)은 지도 안에, 먼 표적은 가장자리 방향 표시
            ext.append(tgt)
        xs = [p[0] for p in ext]
        ys = [p[1] for p in ext]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 20.0) * 1.4
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        W, H = 41, 21
        grid = [[" "] * W for _ in range(H)]

        def put(x, y, ch, clamp=False):
            col = int(round((x - cx) / span * (W - 1) + (W - 1) / 2))
            row = int(round((cy - y) / span * (H - 1) + (H - 1) / 2))
            if not (0 <= col < W and 0 <= row < H):
                if not clamp:
                    return False
                col, row = min(max(col, 0), W - 1), min(max(row, 0), H - 1)
            grid[row][col] = ch
            return True

        inside = True
        if tgt:
            inside = put(tgt[0], tgt[1], "T")
            if not inside:  # 지도 밖: 방향만 가장자리에
                d = math.hypot(tgt[0] - cx, tgt[1] - cy)
                put(cx + (tgt[0] - cx) / d * span, cy + (tgt[1] - cy) / d * span, "t", clamp=True)
        for i, (x, y) in pts.items():
            put(x, y, "L" if i == 0 else str(i))
        lines = [f"지도 (북쪽 ↑, 가로·세로 약 {span:.0f}m, 대형 {self.formation or 'auto'})", "+" + "-" * W + "+"]
        lines += ["|" + "".join(r) + "|" for r in grid]
        lines.append("+" + "-" * W + "+")
        lines += [f"{peer_name(i)} ({x:.1f}, {y:.1f})m" for i, (x, y) in sorted(pts.items())]
        if tgt:
            rep, az, band, desc = self.last_target
            lines.append(f"표적 {'T' if inside else 't(지도 밖)'}: S{rep} 보고 {desc} → 추정 ({tgt[0]:.0f}, {tgt[1]:.0f})m")
            lines += self.peer_view(rep, az, band)
        return lines

    async def send_pos(self, args):
        if not args or len(args) > 2:
            raise ValueError("사용: pos <wedge|line|column|auto> [targets]")
        name = args[0].lower()
        spec = args[1] if len(args) == 2 else "all"
        if name == "auto":
            prior = self.formation or "wedge"
            rows = self.rssi_rows()
            ids = sorted({0} | {i for i, s in self.soldiers.items() if s.connected} | set(rows)
                         | {j for r in rows.values() for j in r if j <= 5})
            meas = sl.measured_from_rssi(rows, PATHLOSS["p1m"], PATHLOSS["n"])
            pos, info = sl.localize(ids, meas, prior)
            log(f"위치 복원: 실측 {info['measured']}/{info['pairs']}쌍(나머지는 {prior} 대형 거리), 방식 {info['method']}, "
                f"잔차 {info['stress']:.1f}m" + (f", 회전 {info['rot_deg']:.0f}° 반사 {info['flip']}" if info["method"] == "mds" else ""))
            for line in self.matrix_lines(info):
                log(f"  {line}")
        else:
            pos = sl.preset_positions(name)
            self.formation = name
        ids = self.targets(spec)
        self.pos = dict(pos)
        entries = sl.to_pos_table(pos, {i: h for i, h in self.headings.items()} if name == "auto" else None)
        if not ids:
            log("  (연결된 대상 없음: 위치표만 갱신)")
        else:
            await self.send_msg(ids, {"type": fc.POS_TABLE, "entries": entries})
        for line in self.render_map():
            print("   " + line)

    def matrix_lines(self, info):
        ids, D, src = info["ids"], info["D"], info["src"]
        mark = {"meas": "", "one": "¹", "prior": "*"}
        out = ["거리 행렬(m): ¹ 한쪽만 실측, * 대형 값"]
        out.append("        " + "".join(f"{peer_name(j):>8}" for j in ids))
        for a, i in enumerate(ids):
            out.append(f"{peer_name(i):>8}" + "".join(
                f"{'-':>8}" if a == b else f"{D[a][b]:>7.1f}{mark[src[a][b]] or ' '}" for b in range(len(ids))))
        return out

    def dist_lines(self):
        rows = self.rssi_rows()
        ids = sorted({0} | set(rows) | {j for r in rows.values() for j in r} | set(self.pos))
        out = [f"쌍별 거리(경로손실 P1m {PATHLOSS['p1m']:g}, n {PATHLOSS['n']:g}) — RSSI는 i가 j의 비콘을 잰 중앙값"]
        for a, i in enumerate(ids):
            for j in ids[a + 1:]:
                parts = []
                for x, y in ((i, j), (j, i)):
                    r = rows.get(x, {}).get(y)
                    if r is not None:
                        parts.append(f"{peer_name(x)}→{peer_name(y)} {r}dBm≈{est_distance(r):.1f}m")
                tab = f"위치표 {sl.dist(self.pos[i], self.pos[j]):.1f}m" if i in self.pos and j in self.pos else "위치표 없음"
                if parts or (i in self.pos and j in self.pos):
                    out.append(f"  {peer_name(i)}–{peer_name(j)}: {tab} | " + (", ".join(parts) or "실측 없음"))
        if 0 not in rows:
            out.append("  (분대장 줄 없음: --beacon-port 보드 A가 병사 비콘을 들어야 함. 들은 BCN 줄 "
                       f"{self.bcn_lines}개)")
        return out

    async def send_peer(self, args):
        if len(args) < 4 or len(args) > 5:
            raise ValueError("사용: peer <reporter_id> <az|-> <dist near|mid|far|-> <count 0~5> [targets]")
        rep = int(args[0].upper().lstrip("S"))
        if not 1 <= rep <= 5:
            raise ValueError("reporter_id는 1~5")
        az = fc.NO_AZIMUTH if args[1] in ("-", "none") else int(args[1])
        if az != fc.NO_AZIMUTH and not 0 <= az <= 359:
            raise ValueError("az는 0~359 또는 '-'")
        if args[2].lower() not in DIST_ARGS:
            raise ValueError("dist는 near|mid|far|0|1|2|-")
        band = DIST_ARGS[args[2].lower()]
        count = int(args[3])
        if not 0 <= count <= 5:
            raise ValueError("count는 0~5")
        spec = args[4] if len(args) == 5 else "all"
        ids = [i for i in self.targets(spec) if i != rep]
        clock = 0 if az == fc.NO_AZIMUTH else sl.clock_from(az, 0)
        orig = dict(type=fc.CONTACT, azimuth=az, clock=clock, dist_band=band, count=count, heading=0)
        rx, ry = self.pos_dm(rep)
        self.last_target = (rep, az, band, describe(dict(orig, seq=0, src=rep, dst=0)).split(" | ", 1)[-1])
        await self.send_msg(ids, {"type": fc.PEER_REPORT, "reporter_id": rep, "rx": rx, "ry": ry,
                                  "orig_type": fc.CONTACT, "orig_payload": fc.encode_payload(orig)})
        for line in self.peer_view(rep, az, band):
            log(f"  ▷ {line}")

    def send_lbeacon(self, args):
        if len(args) != 1 or args[0] not in ("on", "off"):
            raise ValueError("사용: lbeacon on|off  (보드 A 분대장 위치 비콘)")
        if self.beacon_fd is None:
            raise ValueError("비콘 포트가 없음: --beacon-port /dev/cu.usbmodem… 로 실행")
        os.write(self.beacon_fd, f"beacon {args[0]}\n".encode())

    # ---------- CLI ----------
    async def handle(self, line):
        parts = line.split()
        if not parts:
            return
        cmd, args = parts[0].lower(), parts[1:]
        if cmd in ("quit", "exit", "q"):
            self.stop.set()
        elif cmd == "help":
            print(HELP)
        elif cmd == "list":
            for s in self.soldiers.values():
                st = f"연결됨 MTU={s.mtu}" if s.connected else ("연결 중" if s.connecting else "찾는 중")
                print(f"  S{s.sid}: {st}")
        elif cmd == "raw":
            if len(args) < 2:
                raise ValueError("사용: raw <id|all> <hex>")
            await self.write(self.targets(args[0]), fc.from_hex("".join(args[1:])))
        elif cmd == "cmd":
            await self.send_cmd(args)
        elif cmd == "voice":
            await self.send_voice(args)
        elif cmd == "emcon":
            await self.send_emcon(args, via_beacon=False)
        elif cmd == "bemcon":
            await self.send_emcon(args, via_beacon=True)
        elif cmd == "bcmd":
            await self.send_bcmd(args)
        elif cmd == "mark":
            if len(args) != 1:
                raise ValueError("사용: mark <실제 거리 m>  (예: mark 3) — 이후 RANGING을 그 거리로 기록, 'mark -'는 구간 끝")
            if self.csv is None:
                raise ValueError("--log-csv로 실행해야 기록됨")
            self.csv[1].writerow([datetime.datetime.now().isoformat(timespec="milliseconds"),
                                  f"{time.monotonic() - self.t0:.3f}", "mark", "", "", args[0], "", "", "", 0, ""])
            self.csv[0].flush()
            log(f"표시: 실제 거리 = {args[0]} m (CSV)")
        elif cmd == "pos":
            await self.send_pos(args)
        elif cmd == "peer":
            await self.send_peer(args)
        elif cmd == "relay":
            if len(args) != 1 or args[0] not in ("on", "off"):
                raise ValueError(f"사용: relay on|off (현재 {'on' if self.relay else 'off'})")
            self.relay = args[0] == "on"
            log(f"PEER_REPORT 자동 중계 {'켬' if self.relay else '끔'}")
        elif cmd == "map":
            for ln in self.render_map():
                print("   " + ln)
        elif cmd == "dist":
            for ln in self.dist_lines():
                print("   " + ln)
        elif cmd == "lbeacon":
            self.send_lbeacon(args)
        elif cmd == "ack":
            if len(args) != 1 or args[0] not in ("on", "off"):
                raise ValueError(f"사용: ack on|off (현재 {'on' if self.auto_ack else 'off'})")
            self.auto_ack = args[0] == "on"
            log(f"RPT_ACK 자동 응답 {'켬' if self.auto_ack else '끔'}")
        elif cmd == "stats":
            if len(args) != 1:
                raise ValueError("사용: stats <id|all>")
            await self.send_msg(self.targets(args[0]), {"type": fc.REQ_STATS})
        else:
            raise ValueError(f"알 수 없는 명령 '{cmd}' (help 참고)")

    async def cli(self):
        # stdin은 데몬 스레드에서 읽는다(종료 시 입력 대기 때문에 멈추지 않도록).
        loop = asyncio.get_running_loop()
        lines = asyncio.Queue()

        def reader():
            for raw in sys.stdin:
                loop.call_soon_threadsafe(lines.put_nowait, raw)
            loop.call_soon_threadsafe(lines.put_nowait, None)  # EOF

        threading.Thread(target=reader, daemon=True).start()
        print(HELP)
        while not self.stop.is_set():
            line = await lines.get()
            if line is None:
                self.stop.set()
                break
            try:
                await self.handle(line.strip())
            except ValueError as e:
                log(f"오류: {e}")

    async def run(self):
        scan = asyncio.create_task(self.scan_forever())
        watch = asyncio.create_task(self.watch_cmds())
        beacon = asyncio.create_task(self.beacon_reader())
        try:
            await self.cli()
        finally:
            self.stop.set()
            await scan
            await watch
            await beacon
            if self.csv:
                self.csv[0].close()
            for s in self.soldiers.values():
                if s.client is not None:
                    try:
                        await s.client.disconnect()
                    except Exception:  # noqa: BLE001
                        pass


HELP = """명령:
  list                  연결 상태
  cmd <name|code> [az] [dist] [extra] [prio] [targets]
                        버튼 명령. '-' = 기본값(az 없음, dist 없음, extra 0, prio 0, targets all)
                        예: cmd take_cover 270 - - 1 all   /  cmd enemy_info 45 far 3 0 1  /  cmd halt - - - - 2
                        이름: halt take_cover advance withdraw rally open_fire cease_fire observe
                              enemy_info report_status silence hold cancel (또는 코드 0x01~0x0F)
                        targets: all | 1 | 2 | 1,2
  emcon <0|1|2> [targets]  EMCON_SET(연결). 0 = 병사가 연결 끊고 침묵(수동 스캔)
  bcmd <name|code> [az] [dist] [extra] [prio] [targets]
                        침묵 모드 광고로 버튼 명령(--beacon-port 필요). 예: bcmd take_cover 270 - - 1 all
  bemcon <1|2> [targets]   침묵 모드 광고로 EMCON_SET(병사를 연결 모드로 되돌림)
  voice <wav> [prio] [targets]
                        음성 명령(8/16비트 PCM WAV, 10초까지). 예: voice assets/test_voice/cover_9.wav 0 all
  mark <m> | mark -     거리 보정: 지금부터 RANGING을 실제 거리 m로 CSV에 표시('-' = 구간 끝)
  pos <wedge|line|column|auto> [targets]
                        POS_TABLE(분대장 원점, 간격 10m). auto = RANGING 실측으로 위치 복원(squad_localize)
  peer <reporter> <az|-> <dist> <count> [targets]
                        수동 PEER_REPORT(CONTACT). 예: peer 2 0 near 3  (S2가 12시 근거리 적 3 보고한 것처럼)
  relay on|off          병사 보고(적·징후·폭발물·부상자)를 다른 병사에게 PEER_REPORT로 자동 중계 (기본 on)
  map                   ASCII 대형 지도 + 마지막 표적의 병사별 방향
  dist                  쌍별 거리: 위치표 vs RSSI 실측(병사 RANGING + 분대장 줄)
  lbeacon on|off        보드 A 분대장 위치 비콘(BEACON src 0) 켜기/끄기 (--beacon-port)
  stats <id|all>        REQ_STATS 송신 (예: stats all, stats 2)
  raw <id|all> <hex>    프레임 hex를 그대로 송신 (예: raw 1 01 1F 07 00 01 00)
  ack on|off            보고에 RPT_ACK 자동 응답 켬/끔 (기본 on)
  help, quit"""


def parse_only(spec):
    if not spec:
        return set(range(1, 6))
    ids = set()
    for part in spec.split(","):
        part = part.strip().upper().lstrip("S")
        if not part.isdigit() or not 1 <= int(part) <= 5:
            raise SystemExit(f"--only 값 오류: {spec} (예: S1 또는 S1,S2)")
        ids.add(int(part))
    return ids


def main():
    ap = argparse.ArgumentParser(description="분대장 대역 BLE Central (병사 단말 시험용)")
    ap.add_argument("--only", help="연결할 병사 제한, 예: S1 또는 S1,S2 (기본: S1~S5)")
    ap.add_argument("--gap-ms", type=int, default=15, help="음성 청크 간격 ms (기본 15)")
    ap.add_argument("--log-csv", help="송수신 프레임 CSV 파일(송신량 비교용)")
    ap.add_argument("--beacon-port", help="분대장 비콘 보드(LeaderBeacon) USB 포트 /dev/cu.usbmodem…")
    ap.add_argument("--pathloss", help="경로손실 보정값 'P1m,n' (예: -59,2.0; tools/fit_pathloss.py 결과)")
    args = ap.parse_args()
    if args.pathloss:
        try:
            p1m, n = (float(x) for x in args.pathloss.split(","))
        except ValueError:
            raise SystemExit("--pathloss 형식: P1m,n  (예: -59,2.0)") from None
        PATHLOSS.update(p1m=p1m, n=n)
    allowed = parse_only(args.only)
    log(f"SQ1-S{{{','.join(map(str, sorted(allowed)))}}} 찾는 중 … (Ctrl+C 또는 quit로 종료)")
    try:
        leader = Leader(allowed)
        leader.gap_ms = args.gap_ms
        if args.log_csv:
            leader.open_csv(args.log_csv)
        if args.beacon_port:
            leader.open_beacon(args.beacon_port)
        asyncio.run(leader.run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
