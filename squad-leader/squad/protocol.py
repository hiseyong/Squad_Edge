"""분대 BLE 통신 명세 v1.0.2 프레임 인코더/디코더 (docs/squad_ble_protocol_v1.0.2.md).

전송 계층(BLE)과 분리된 순수 바이트 변환만 담당한다. 다바이트 정수는 리틀엔디언.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

VER = 0x01
HEADER_LEN = 6

LEADER_ID = 0
DST_LEADER = 0x80
DST_ALL_SOLDIERS = 0x1F
DST_ALL = 0xFF

AZ_NONE = 0xFFFF
HEADING_NONE = 0xFFFF
DIST_NONE = 0xFF

NUS_SERVICE = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
NUS_RX = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # 분대장 → 병사 (write)
NUS_TX = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # 병사 → 분대장 (notify)
ADV_COMPANY_ID = 0xFFFF


class Msg(IntEnum):
    # 병사 → 분대장
    CONTACT = 0x01
    SUSPICIOUS = 0x02
    HAZARD = 0x03
    CASUALTY_FOUND = 0x04
    OK_READY = 0x05
    WEAPON_AMMO = 0x06
    CASUALTY_SELF = 0x07
    ACK = 0x08
    CANNOT_COMPLY = 0x09
    VOICE_RESULT = 0x0A
    EMCON_STATE = 0x0B
    HEARTBEAT = 0x0C
    STATS = 0x0D
    # §5.3 예약·예정 (분대장은 무시하거나 로그만)
    RANGING = 0x0E
    BEACON = 0x20
    LOG = 0x7F
    # 분대장 → 병사
    CMD_BUTTON = 0x10
    VOICE_BEGIN = 0x11
    VOICE_CHUNK = 0x12
    VOICE_END = 0x13
    PEER_REPORT = 0x14
    POS_TABLE = 0x15
    EMCON_SET = 0x16
    RPT_ACK = 0x17
    REQ_STATS = 0x1F


class Cmd(IntEnum):
    HALT = 0x01
    TAKE_COVER = 0x02
    ADVANCE = 0x03
    WITHDRAW = 0x04
    RALLY = 0x05
    OPEN_FIRE = 0x06
    CEASE_FIRE = 0x07
    OBSERVE = 0x08
    ENEMY_INFO = 0x09
    REPORT_STATUS = 0x0A
    SILENCE = 0x0B
    HOLD = 0x0C
    CANCEL = 0x0F


class Emcon(IntEnum):
    SILENT = 0
    MIN = 1
    NORMAL = 2


# §8.2: 병사가 RPT_ACK 없으면 재전송하는 긴급 보고
URGENT_REPORTS = frozenset(
    {Msg.CONTACT, Msg.HAZARD, Msg.CASUALTY_FOUND, Msg.WEAPON_AMMO, Msg.CASUALTY_SELF}
)

# §5.3: 지금 처리 의무 없이 로그만 남기는 타입
RESERVED = frozenset({Msg.RANGING, Msg.BEACON, Msg.LOG})

# 병사 → 분대장 보고 payload: (struct 형식, 필드명)
_REPORT_LAYOUT: dict[int, tuple[str, tuple[str, ...]]] = {
    Msg.CONTACT: ("<HBBBH", ("azimuth", "clock", "dist_band", "count", "heading")),
    Msg.SUSPICIOUS: ("<HBH", ("azimuth", "clock", "heading")),
    Msg.HAZARD: ("<HBH", ("azimuth", "clock", "heading")),
    Msg.CASUALTY_FOUND: ("<HBBH", ("azimuth", "clock", "dist_band", "heading")),
    Msg.OK_READY: ("<", ()),
    Msg.WEAPON_AMMO: ("<", ()),
    Msg.CASUALTY_SELF: ("<H", ("heading",)),
    Msg.ACK: ("<BB", ("ref_type", "ref_id")),
    Msg.CANNOT_COMPLY: ("<BB", ("ref_type", "ref_id")),
    Msg.VOICE_RESULT: ("<BB", ("voice_id", "status")),
    Msg.EMCON_STATE: ("<B", ("mode",)),
    Msg.HEARTBEAT: ("<HHBB", ("heading", "battery_mv", "heart_rate", "motion")),
    Msg.STATS: ("<3H3I", ("tx_frames_0", "tx_frames_1", "tx_frames_2",
                          "tx_bytes_0", "tx_bytes_1", "tx_bytes_2")),
    Msg.BEACON: ("<H", ("heading",)),
}


class FrameError(ValueError):
    pass


@dataclass(frozen=True)
class Frame:
    msg_type: int
    seq: int
    src_id: int
    dst_mask: int
    payload: bytes = b""

    def encode(self) -> bytes:
        if len(self.payload) > 255:
            raise FrameError("payload > 255 bytes")
        return bytes((VER, self.msg_type, self.seq & 0xFF, self.src_id,
                      self.dst_mask, len(self.payload))) + self.payload

    @classmethod
    def decode(cls, data: bytes) -> Frame:
        if len(data) < HEADER_LEN:
            raise FrameError(f"too short: {len(data)}")
        ver, msg_type, seq, src_id, dst_mask, length = data[:HEADER_LEN]
        if ver != VER:
            raise FrameError(f"bad ver 0x{ver:02x}")
        if len(data) - HEADER_LEN != length:
            raise FrameError(f"len mismatch: header {length}, actual {len(data) - HEADER_LEN}")
        return cls(msg_type, seq, src_id, dst_mask, bytes(data[HEADER_LEN:]))

    def is_for(self, node_id: int) -> bool:
        """§4: dst_mask에 자기 비트가 있는지. 0 = 분대장(bit7), n = bit(n-1)."""
        bit = 0x80 if node_id == LEADER_ID else 1 << (node_id - 1)
        return bool(self.dst_mask & bit)


def soldier_bit(soldier_id: int) -> int:
    if not 1 <= soldier_id <= 5:
        raise ValueError(f"soldier id out of range: {soldier_id}")
    return 1 << (soldier_id - 1)


# ---- 병사 → 분대장 보고 ----

def parse_report(frame: Frame) -> dict:
    """보고 payload를 필드 dict로. 알 수 없는 종류나 길이 불일치는 FrameError."""
    if frame.msg_type == Msg.RANGING:
        n = frame.payload[0] if frame.payload else 0
        if len(frame.payload) != 1 + 3 * n:
            raise FrameError(f"RANGING size {len(frame.payload)} != {1 + 3 * n}")
        peers = [dict(zip(("peer_id", "rssi_avg", "samples"), struct.unpack_from("<BbB", frame.payload, 1 + 3 * i)))
                 for i in range(n)]
        return {"peers": peers}
    if frame.msg_type == Msg.LOG:
        return {"text": frame.payload.decode("ascii", errors="replace")}
    layout = _REPORT_LAYOUT.get(frame.msg_type)
    if layout is None:
        raise FrameError(f"not a soldier report: 0x{frame.msg_type:02x}")
    fmt, names = layout
    if struct.calcsize(fmt) != len(frame.payload):
        raise FrameError(f"payload size {len(frame.payload)} != {struct.calcsize(fmt)}")
    return dict(zip(names, struct.unpack(fmt, frame.payload)))


def build_report(msg_type: int, seq: int, src_id: int, **fields) -> Frame:
    """모의 병사/테스트용 보고 프레임 생성."""
    fmt, names = _REPORT_LAYOUT[msg_type]
    payload = struct.pack(fmt, *(fields[n] for n in names))
    return Frame(msg_type, seq, src_id, DST_LEADER, payload)


# ---- 분대장 → 병사 ----

def cmd_button(seq: int, dst_mask: int, cmd: int, azimuth: int = AZ_NONE,
               dist_band: int = DIST_NONE, extra: int = 0, priority: int = 0) -> Frame:
    payload = struct.pack("<BHBBB", cmd, azimuth, dist_band, extra, priority)
    return Frame(Msg.CMD_BUTTON, seq, LEADER_ID, dst_mask, payload)


def parse_cmd_button(frame: Frame) -> dict:
    cmd, az, dist, extra, prio = struct.unpack("<BHBBB", frame.payload)
    return {"cmd": cmd, "azimuth": az, "dist_band": dist, "extra": extra, "priority": prio}


def rpt_ack(seq: int, dst_mask: int, ref_seq: int) -> Frame:
    return Frame(Msg.RPT_ACK, seq, LEADER_ID, dst_mask, bytes((ref_seq & 0xFF,)))


def emcon_set(seq: int, dst_mask: int, mode: int) -> Frame:
    return Frame(Msg.EMCON_SET, seq, LEADER_ID, dst_mask, bytes((mode,)))


def req_stats(seq: int, dst_mask: int) -> Frame:
    return Frame(Msg.REQ_STATS, seq, LEADER_ID, dst_mask)


def pos_table(seq: int, dst_mask: int, entries: list[tuple[int, int, int, int]]) -> Frame:
    """entries: (id, x_dm, y_dm, heading). x/y는 분대장 원점, 0.1m 단위."""
    payload = bytes((len(entries),)) + b"".join(
        struct.pack("<BhhH", i, x, y, h) for i, x, y, h in entries)
    return Frame(Msg.POS_TABLE, seq, LEADER_ID, dst_mask, payload)


def peer_report(seq: int, dst_mask: int, reporter_id: int, rx_dm: int, ry_dm: int,
                original: Frame) -> Frame:
    payload = struct.pack("<Bhh", reporter_id, rx_dm, ry_dm) + bytes((original.msg_type,)) \
        + original.payload
    return Frame(Msg.PEER_REPORT, seq, LEADER_ID, dst_mask, payload)


def voice_begin(seq: int, dst_mask: int, voice_id: int, total_samples: int, total_chunks: int,
                predictor: int, step_index: int, priority: int = 0,
                sample_rate: int = 8000, codec: int = 0x01) -> Frame:
    payload = struct.pack("<BBHIHhBB", voice_id, codec, sample_rate, total_samples,
                          total_chunks, predictor, step_index, priority)
    return Frame(Msg.VOICE_BEGIN, seq, LEADER_ID, dst_mask, payload)


def voice_chunk(seq: int, dst_mask: int, voice_id: int, chunk_idx: int, data: bytes) -> Frame:
    return Frame(Msg.VOICE_CHUNK, seq, LEADER_ID, dst_mask,
                 struct.pack("<BH", voice_id, chunk_idx) + data)


def voice_end(seq: int, dst_mask: int, voice_id: int, crc16: int) -> Frame:
    return Frame(Msg.VOICE_END, seq, LEADER_ID, dst_mask, struct.pack("<BH", voice_id, crc16))


def voice_chunk_size(mtu: int) -> int:
    """§7.3: N = (MTU-3) - 헤더 6 - 3. MTU 협상 실패 시 23(=20바이트 write) 가정."""
    return (mtu - 3) - HEADER_LEN - 3


# §3.2(v1.0.2): 침묵 모드 방송에 실을 수 있는 프레임. EMCON_SET은 침묵 중인 병사를 연결 모드로 되돌리는 용도
ADV_ALLOWED = frozenset({Msg.CMD_BUTTON, Msg.EMCON_SET})
ADV_MAX_FRAME = 31 - 3 - 4          # 레거시 광고 31바이트 - Flags(3) - MSD 길이·타입·Company ID(4)
ADV_INTERVAL_MS = 100               # §3.2: 100ms 간격으로 3초 반복 (리눅스 커널 기본 간격보다 짧아 명시 설정 필요)
ADV_DURATION_S = 3.0


def adv_manufacturer_data(frame: Frame) -> bytes:
    """§3.2: 침묵 모드 광고의 Manufacturer Specific Data 값(Company ID 뒤 부분)."""
    if frame.msg_type not in ADV_ALLOWED:
        raise FrameError("silent-mode advertising carries CMD_BUTTON or EMCON_SET only")
    data = frame.encode()
    if len(data) > ADV_MAX_FRAME:
        raise FrameError(f"advertising frame too long: {len(data)} > {ADV_MAX_FRAME}")
    return data


# ---- 방향 변환 ----

def clock_to_azimuth(heading: int, clock: int) -> int:
    """§5.1/§6.1: azimuth = (heading + (clock-12)*30) mod 360. clock 0 또는 센서 없음 → AZ_NONE."""
    if clock == 0 or heading == HEADING_NONE:
        return AZ_NONE
    return (heading + (clock - 12) * 30) % 360


def azimuth_to_clock(azimuth: int, my_heading: int) -> int:
    """병사 프로토콜 v1.1 §5.1: rel = (az - heading + 360) mod 360, clock = (rel + 15) // 30, 0이면 12.
    .5 경계는 올림(15도 → 1시). Python round()는 짝수 쪽으로 반올림하므로 쓰지 않는다.
    azimuth 없음(0xFFFF) → 0(방향 없음). heading 없음(0xFFFF) → 0(북쪽)으로 간주(v1.1, 골든 벡터)."""
    if azimuth == AZ_NONE:
        return 0
    if my_heading == HEADING_NONE:
        my_heading = 0
    c = (((azimuth - my_heading + 360) % 360) + 15) // 30 % 12
    return 12 if c == 0 else c
