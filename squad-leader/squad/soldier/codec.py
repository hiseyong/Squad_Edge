"""병사 프로토콜 v1.1 프레임 인코더/디코더 (§4~§7).

포팅 원본: ~/work/soldier-node_ref_v1.1/tools/frame_codec.py (v1.1 레퍼런스, 2026-10-11)
  - 인코드/디코드 로직·필드 이름은 원본과 같게 유지한다(골든 벡터 `fields`와 1:1).
  - 원본의 자체 시험 함수는 옮기지 않았다 → tests/test_soldier_golden.py
  - 추가: 광고 AD 데이터 생성·파싱(adv_data, parse_adv). UNO Q는 광고를 내지 않지만(병사 팀 안내문 D2)
    골든 벡터 검증과 시험용으로 둔다.

메시지는 dict로 다룬다:
    {"type": 0x10, "seq": 5, "src": 0, "dst": 0x1F,
     "cmd_code": 2, "azimuth": 270, "dist_band": 0xFF, "extra": 0, "priority": 1}
    raw = encode(msg); msg = decode(raw)   # 잘못된 프레임이면 FrameError
모든 다바이트 정수는 리틀엔디언.
"""

import struct

VER = 0x01
HDR_LEN = 6
MAX_PAYLOAD = 238  # MTU 247 - 3 - 6

LEADER_ID = 0
DST_LEADER = 0x80
DST_ALL_SOLDIERS = 0x1F
DST_ALL = 0xFF
NO_AZIMUTH = 0xFFFF
NO_HEADING = 0xFFFF
NO_DIST = 0xFF
POS_UNKNOWN = -32768  # v1.1 예정: PEER_REPORT rx/ry "위치 모름"(병사 직접 방송에서 보고자가 POS_TABLE을 못 받았을 때)

# ---- msg_type ----
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
HEARTBEAT = 0x0C      # v2 예약
STATS = 0x0D
RANGING = 0x0E        # v1.1 예정
CMD_BUTTON = 0x10
VOICE_BEGIN = 0x11
VOICE_CHUNK = 0x12
VOICE_END = 0x13
PEER_REPORT = 0x14
POS_TABLE = 0x15
EMCON_SET = 0x16
RPT_ACK = 0x17
REQ_STATS = 0x1F
BEACON = 0x20         # v1.1 예정
LOG = 0x7F            # 디버그 전용

MSG_NAMES = {
    CONTACT: "CONTACT", SUSPICIOUS: "SUSPICIOUS", HAZARD: "HAZARD",
    CASUALTY_FOUND: "CASUALTY_FOUND", OK_READY: "OK_READY", WEAPON_AMMO: "WEAPON_AMMO",
    CASUALTY_SELF: "CASUALTY_SELF", ACK: "ACK", CANNOT_COMPLY: "CANNOT_COMPLY",
    VOICE_RESULT: "VOICE_RESULT", EMCON_STATE: "EMCON_STATE", HEARTBEAT: "HEARTBEAT",
    STATS: "STATS", RANGING: "RANGING", CMD_BUTTON: "CMD_BUTTON", VOICE_BEGIN: "VOICE_BEGIN",
    VOICE_CHUNK: "VOICE_CHUNK", VOICE_END: "VOICE_END", PEER_REPORT: "PEER_REPORT",
    POS_TABLE: "POS_TABLE", EMCON_SET: "EMCON_SET", RPT_ACK: "RPT_ACK", REQ_STATS: "REQ_STATS",
    BEACON: "BEACON", LOG: "LOG",
}

URGENT_TYPES = {CONTACT, HAZARD, CASUALTY_FOUND, WEAPON_AMMO, CASUALTY_SELF}

REF_BUTTON = 0x10
REF_VOICE = 0x11

CMD_CODES = {
    "HALT": 0x01, "TAKE_COVER": 0x02, "ADVANCE": 0x03, "WITHDRAW": 0x04, "RALLY": 0x05,
    "OPEN_FIRE": 0x06, "CEASE_FIRE": 0x07, "OBSERVE": 0x08, "ENEMY_INFO": 0x09,
    "REPORT_STATUS": 0x0A, "SILENCE": 0x0B, "HOLD": 0x0C, "CANCEL": 0x0F,
}

# 고정 길이 payload: (struct 형식, 필드 이름들)
_FIXED = {
    CONTACT: ("<HBBBH", ("azimuth", "clock", "dist_band", "count", "heading")),
    SUSPICIOUS: ("<HBH", ("azimuth", "clock", "heading")),
    HAZARD: ("<HBH", ("azimuth", "clock", "heading")),
    CASUALTY_FOUND: ("<HBBH", ("azimuth", "clock", "dist_band", "heading")),
    OK_READY: ("<", ()),
    WEAPON_AMMO: ("<", ()),
    CASUALTY_SELF: ("<H", ("heading",)),
    ACK: ("<BB", ("ref_type", "ref_id")),
    CANNOT_COMPLY: ("<BB", ("ref_type", "ref_id")),
    VOICE_RESULT: ("<BB", ("voice_id", "status")),
    EMCON_STATE: ("<B", ("mode",)),
    HEARTBEAT: ("<HHBB", ("heading", "battery_mv", "heart_rate", "motion")),
    CMD_BUTTON: ("<BHBBB", ("cmd_code", "azimuth", "dist_band", "extra", "priority")),
    VOICE_BEGIN: ("<BBHIHhBB", ("voice_id", "codec", "sample_rate", "total_samples",
                                "total_chunks", "predictor", "step_index", "priority")),
    VOICE_END: ("<BH", ("voice_id", "crc16")),
    EMCON_SET: ("<B", ("mode",)),
    RPT_ACK: ("<B", ("ref_seq",)),
    REQ_STATS: ("<", ()),
    BEACON: ("<H", ("heading",)),
}

POS_TABLE_MAX = 8
RANGING_MAX = 8
LOG_MAX = 100


class FrameError(ValueError):
    pass


def crc16_ccitt_false(data, crc=0xFFFF):
    """CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF, 반사 없음, xorout 0)."""
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def dst_bit(soldier_id):
    return 1 << (soldier_id - 1) if 1 <= soldier_id <= 5 else 0


def dst_mask(targets):
    """'all' 또는 병사 ID 목록 → dst_mask."""
    if targets in ("all", None):
        return DST_ALL_SOLDIERS
    m = 0
    for t in targets:
        if not 1 <= int(t) <= 5:
            raise ValueError(f"병사 ID 범위 밖: {t}")
        m |= dst_bit(int(t))
    return m


def addressed_to_soldier(mask, soldier_id):
    b = dst_bit(soldier_id)
    return b != 0 and (mask & b) != 0


def encode_payload(msg):
    t = msg["type"]
    if t in _FIXED:
        fmt, names = _FIXED[t]
        return struct.pack(fmt, *(msg[n] for n in names))
    if t == STATS:
        return struct.pack("<3H3I", *msg["tx_frames"], *msg["tx_bytes"])
    if t == RANGING:
        peers = msg["peers"]
        if len(peers) > RANGING_MAX:
            raise FrameError("RANGING peers 초과")
        return bytes([len(peers)]) + b"".join(
            struct.pack("<BbB", p["peer_id"], p["rssi_avg"], p["samples"]) for p in peers)
    if t == VOICE_CHUNK:
        return struct.pack("<BH", msg["voice_id"], msg["chunk_idx"]) + bytes(msg["data"])
    if t == PEER_REPORT:
        orig = msg.get("orig_payload")
        if orig is None:
            orig = encode_payload(dict(msg["orig"], type=msg["orig_type"]))
        tail = bytes([msg["orig_seq"] & 0xFF]) if msg.get("orig_seq") is not None else b""  # v1.1 예정
        return struct.pack("<BhhB", msg["reporter_id"], msg["rx"], msg["ry"], msg["orig_type"]) + bytes(orig) + tail
    if t == POS_TABLE:
        ents = msg["entries"]
        if len(ents) > POS_TABLE_MAX:
            raise FrameError("POS_TABLE entries 초과")
        return bytes([len(ents)]) + b"".join(
            struct.pack("<BhhH", e["id"], e["x"], e["y"], e["heading"]) for e in ents)
    if t == LOG:
        text = msg["text"].encode("ascii") if isinstance(msg["text"], str) else bytes(msg["text"])
        if len(text) > LOG_MAX:
            raise FrameError("LOG 100바이트 초과")
        return text
    raise FrameError(f"알 수 없는 msg_type 0x{t:02X}")


def encode(msg):
    payload = encode_payload(msg)
    if len(payload) > MAX_PAYLOAD:
        raise FrameError("payload 너무 김")
    return bytes([VER, msg["type"], msg["seq"] & 0xFF, msg["src"], msg["dst"], len(payload)]) + payload


def decode_payload(t, p):
    """payload만 해석 → 필드 dict(type 포함)."""
    p = bytes(p)
    out = {"type": t}
    if t in _FIXED:
        fmt, names = _FIXED[t]
        if len(p) != struct.calcsize(fmt):
            raise FrameError(f"{MSG_NAMES[t]} payload 길이 {len(p)}")
        out.update(zip(names, struct.unpack(fmt, p)))
        if t in (EMCON_STATE, EMCON_SET) and out["mode"] > 2:
            raise FrameError("mode 범위 밖")
        if t == VOICE_BEGIN and out["step_index"] > 88:
            raise FrameError("step_index 범위 밖")
        return out
    if t == STATS:
        if len(p) != 18:
            raise FrameError("STATS payload 길이")
        v = struct.unpack("<3H3I", p)
        out["tx_frames"], out["tx_bytes"] = list(v[:3]), list(v[3:])
        return out
    if t == RANGING:
        if len(p) < 1 or p[0] > RANGING_MAX or len(p) != 1 + 3 * p[0]:
            raise FrameError("RANGING payload 길이")
        out["peers"] = [dict(zip(("peer_id", "rssi_avg", "samples"), struct.unpack_from("<BbB", p, 1 + 3 * i)))
                        for i in range(p[0])]
        return out
    if t == VOICE_CHUNK:
        if len(p) < 3:
            raise FrameError("VOICE_CHUNK payload 길이")
        out["voice_id"], out["chunk_idx"] = struct.unpack_from("<BH", p)
        out["data"] = p[3:]
        return out
    if t == PEER_REPORT:
        if len(p) < 6:
            raise FrameError("PEER_REPORT payload 길이")
        out["reporter_id"], out["rx"], out["ry"], out["orig_type"] = struct.unpack_from("<BhhB", p)
        out["orig_payload"] = p[6:]
        out["orig_seq"] = None
        fixed = _FIXED.get(out["orig_type"])
        if fixed is not None and len(p) == 6 + struct.calcsize(fixed[0]) + 1:  # v1.1 예정: 끝 1바이트 = orig_seq
            out["orig_seq"] = p[-1]
            out["orig_payload"] = p[6:-1]
        try:
            out["orig"] = decode_payload(out["orig_type"], out["orig_payload"])
        except FrameError:
            out["orig"] = None
        return out
    if t == POS_TABLE:
        if len(p) < 1 or p[0] > POS_TABLE_MAX or len(p) != 1 + 7 * p[0]:
            raise FrameError("POS_TABLE payload 길이")
        out["entries"] = [dict(zip(("id", "x", "y", "heading"), struct.unpack_from("<BhhH", p, 1 + 7 * i)))
                          for i in range(p[0])]
        return out
    if t == LOG:
        if len(p) > LOG_MAX:
            raise FrameError("LOG 길이")
        out["text"] = p.decode("ascii", errors="replace")
        return out
    raise FrameError(f"알 수 없는 msg_type 0x{t:02X}")


def decode(raw):
    raw = bytes(raw)
    if len(raw) < HDR_LEN:
        raise FrameError("헤더보다 짧음")
    if raw[0] != VER:
        raise FrameError(f"ver 0x{raw[0]:02X}")
    if raw[5] != len(raw) - HDR_LEN:
        raise FrameError(f"len 필드 {raw[5]} != 실제 {len(raw) - HDR_LEN}")
    msg = decode_payload(raw[1], raw[HDR_LEN:])
    msg.update(seq=raw[2], src=raw[3], dst=raw[4])
    return msg


def is_urgent(msg_type):
    return msg_type in URGENT_TYPES


def to_hex(raw):
    return " ".join(f"{b:02X}" for b in raw)


def from_hex(s):
    return bytes.fromhex(s.replace(" ", ""))


# ---------------- 광고 AD 데이터 (§3.2, §3.3) ----------------
COMPANY_ID = 0xFFFF
AD_FLAGS = bytes([0x02, 0x01, 0x06])
AD_MAX = 31


def adv_data(raw):
    """프레임 → 광고 AD 데이터 전체: Flags(02 01 06) + MSD(LL FF FF FF + 프레임)."""
    raw = bytes(raw)
    ad = AD_FLAGS + bytes([1 + 2 + len(raw), 0xFF, COMPANY_ID & 0xFF, COMPANY_ID >> 8]) + raw
    if len(ad) > AD_MAX:
        raise FrameError(f"광고 데이터 {len(ad)}B > 31B")
    return ad


def parse_adv(ad):
    """광고 AD 데이터 → 프레임 bytes(MSD 0xFFFF가 없으면 None). AD 구조 순회."""
    ad = bytes(ad)
    i = 0
    while i < len(ad):
        n = ad[i]
        if n == 0 or i + 1 + n > len(ad):
            return None
        if ad[i + 1] == 0xFF and n >= 3 and ad[i + 2] | (ad[i + 3] << 8) == COMPANY_ID:
            return ad[i + 4:i + 1 + n]
        i += 1 + n
    return None
