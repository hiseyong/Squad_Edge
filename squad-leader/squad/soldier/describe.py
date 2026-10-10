"""수신·송신 프레임 → 한 줄 설명(로그·시험 CLI용). 헤드셋 문장은 phrases.py(가이드 e)에서 따로 만든다.

포팅 원본: ~/work/soldier-node_ref_v1.1/tools/mock_leader.py (describe, az_text, clock_text, peer_name, 이름 표)
"""
from . import codec as fc
from .geo import rssi_to_m

DIST_NAMES = {0: "근거리", 1: "중거리", 2: "원거리", 0xFF: "거리없음"}
MODE_NAMES = {0: "침묵", 1: "최소", 2: "정상"}
VOICE_STATUS = {0: "정상", 1: "CRC 오류", 2: "시간 초과", 3: "메모리 부족"}


def peer_name(pid):
    return "분대장" if pid == 0 else f"S{pid}"


def est_distance(rssi):
    return rssi_to_m(rssi)


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
        oseq = "" if m.get("orig_seq") is None else f" 원seq={m['orig_seq']}"
        body = f"보고자 S{m['reporter_id']} {pos}{oseq}, {fc.MSG_NAMES.get(m['orig_type'], hex(m['orig_type']))}: {inner}"
    else:
        body = ", ".join(f"{k}={v}" for k, v in m.items() if k not in ("type", "seq", "src", "dst"))
    return f"{head} | {body}" if body else head
