"""분대 BLE 통신 명세 v1 프레임 인코더/디코더 (프로토콜 §4~§7).

외부 의존성 없음(표준 라이브러리 struct만 사용) → 분대장 팀원이 그대로 복사해 사용 가능.
모든 다바이트 정수는 리틀엔디언.

메시지는 dict로 다룬다:
    {"type": 0x10, "seq": 5, "src": 0, "dst": 0x1F,
     "cmd_code": 2, "azimuth": 270, "dist_band": 0xFF, "extra": 0, "priority": 1}

    raw = encode(msg)          # bytes
    msg = decode(raw)          # dict (잘못된 프레임이면 FrameError)
    addressed_to_soldier(msg["dst"], 2)

기준: 프로토콜 v1.0.1. 자체 테스트(프로토콜 §11.1 hex 일치): python3 tools/frame_codec.py

비고
- 0x7F LOG: 병사 디버그 로그(병사 펌웨어 DEBUG_LOG 빌드 전용, 프로토콜 문서에 없음). 분대장 측은 무시해도 된다.
- 0x0C HEARTBEAT: v2 예약. 0x0E RANGING, 0x20 BEACON: v1.1 예정(형식만 정의).
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
        return struct.pack("<BhhB", msg["reporter_id"], msg["rx"], msg["ry"], msg["orig_type"]) + bytes(orig)
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
        try:
            out["orig"] = decode_payload(out["orig_type"], p[6:])
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


# ---------------- 자체 테스트 ----------------
SPEC_11_1 = [
    # (설명, hex, dict)
    ("전원 엄폐, 방위 270, 거리 없음, 긴급", "01 10 05 00 1F 06 02 0E 01 FF 00 01",
     dict(type=CMD_BUTTON, seq=5, src=0, dst=0x1F, cmd_code=2, azimuth=270, dist_band=0xFF, extra=0, priority=1)),
    ("병사1 적 위치 알림, 방위 45, 원거리, 3명", "01 10 06 00 01 06 09 2D 00 02 03 00",
     dict(type=CMD_BUTTON, seq=6, src=0, dst=0x01, cmd_code=9, azimuth=45, dist_band=2, extra=3, priority=0)),
    ("상태 보고 요청", "01 1F 07 00 01 00",
     dict(type=REQ_STATS, seq=7, src=0, dst=0x01)),
    # v1.0.1 정정: 시계 2, 내 방위 0 → azimuth = (0 + (2-12)*30) mod 360 = 60
    ("병사1 CONTACT 적 3, 시계 2, 원거리, 내 방위 0 → 방위 60", "01 01 07 01 80 07 3C 00 02 02 03 00 00",
     dict(type=CONTACT, seq=7, src=1, dst=0x80, azimuth=60, clock=2, dist_band=2, count=3, heading=0)),
]


def _self_test():
    for desc, hx, msg in SPEC_11_1:
        raw = from_hex(hx)
        assert encode(msg) == raw, f"encode 불일치: {desc}: {to_hex(encode(msg))}"
        assert decode(raw) == msg, f"decode 불일치: {desc}: {decode(raw)}"

    # 폐기 조건
    good = from_hex("01 10 05 00 1F 06 02 0E 01 FF 00 01")
    for bad, why in ((b"\x02" + good[1:], "ver"), (good[:-1], "len 짧음"), (good + b"\x00", "len 김"),
                     (good[:5], "헤더 부족"), (from_hex("01 10 05 00 1F 05 02 0E 01 FF 00"), "CMD_BUTTON 길이")):
        try:
            decode(bad)
        except FrameError:
            continue
        raise AssertionError(f"폐기되어야 함: {why}")

    # dst_mask
    assert addressed_to_soldier(0x1F, 1) and addressed_to_soldier(0x1F, 2)
    assert addressed_to_soldier(0x01, 1) and not addressed_to_soldier(0x01, 2)
    assert addressed_to_soldier(0x02, 2) and not addressed_to_soldier(0x02, 1)
    assert not addressed_to_soldier(0x80, 1) and not addressed_to_soldier(0x80, 2)
    assert dst_mask([1, 2]) == 0x03 and dst_mask("all") == 0x1F

    # 전체 타입 왕복
    samples = [
        dict(type=SUSPICIOUS, seq=1, src=2, dst=0x80, azimuth=300, clock=10, heading=0),
        dict(type=HAZARD, seq=2, src=2, dst=0x80, azimuth=0xFFFF, clock=0, heading=0xFFFF),
        dict(type=CASUALTY_FOUND, seq=3, src=1, dst=0x80, azimuth=90, clock=3, dist_band=0, heading=0),
        dict(type=OK_READY, seq=4, src=1, dst=0x80),
        dict(type=WEAPON_AMMO, seq=5, src=1, dst=0x80),
        dict(type=CASUALTY_SELF, seq=6, src=1, dst=0x80, heading=123),
        dict(type=ACK, seq=7, src=1, dst=0x80, ref_type=REF_BUTTON, ref_id=5),
        dict(type=CANNOT_COMPLY, seq=8, src=1, dst=0x80, ref_type=REF_VOICE, ref_id=9),
        dict(type=VOICE_RESULT, seq=9, src=1, dst=0x80, voice_id=9, status=1),
        dict(type=EMCON_STATE, seq=10, src=1, dst=0x80, mode=1),
        dict(type=HEARTBEAT, seq=11, src=1, dst=0x80, heading=0, battery_mv=3900, heart_rate=0, motion=0),
        dict(type=STATS, seq=12, src=1, dst=0x80, tx_frames=[0, 10, 300], tx_bytes=[0, 120, 70000]),
        dict(type=RANGING, seq=13, src=1, dst=0x80, peers=[dict(peer_id=2, rssi_avg=-67, samples=10)]),
        dict(type=VOICE_BEGIN, seq=14, src=0, dst=0x03, voice_id=1, codec=1, sample_rate=8000,
             total_samples=16000, total_chunks=35, predictor=-12, step_index=7, priority=0),
        dict(type=VOICE_CHUNK, seq=15, src=0, dst=0x03, voice_id=1, chunk_idx=34, data=bytes(range(10))),
        dict(type=VOICE_END, seq=16, src=0, dst=0x03, voice_id=1, crc16=0xBEEF),
        dict(type=POS_TABLE, seq=17, src=0, dst=0x1F, entries=[dict(id=0, x=0, y=0, heading=0),
                                                              dict(id=1, x=-100, y=-100, heading=0)]),
        dict(type=EMCON_SET, seq=18, src=0, dst=0x1F, mode=0),
        dict(type=RPT_ACK, seq=19, src=0, dst=0x01, ref_seq=7),
        dict(type=BEACON, seq=20, src=1, dst=0xFF, heading=270),
        dict(type=LOG, seq=21, src=1, dst=0x80, text="mtu=247"),
    ]
    for m in samples:
        assert decode(encode(m)) == m, MSG_NAMES[m["type"]]
    peer = dict(type=PEER_REPORT, seq=22, src=0, dst=0x02, reporter_id=1, rx=-100, ry=0, orig_type=CONTACT,
                orig=dict(azimuth=45, clock=2, dist_band=2, count=3, heading=0))
    d = decode(encode(peer))
    assert d["orig"] == dict(peer["orig"], type=CONTACT) and d["rx"] == -100

    assert crc16_ccitt_false(b"123456789") == 0x29B1
    print(f"frame_codec self-test OK (§11.1 예시 {len(SPEC_11_1)}개 + 메시지 {len(samples) + 1}종 왕복)")


if __name__ == "__main__":
    _self_test()
