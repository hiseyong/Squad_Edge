"""전투 데이터 보고 (전투 종료 뒤): 무전 회의록 + 전투 로그 요약 → 압축해 상급 부대로.

입력: 전투 로그(CombatLog)의 이번 전투 구간 [t0, now], 상황 정리(Situation), 분대장 위치 기록.
출력: {"text": 사람이 읽는 요약+회의록, "summary": 한 줄, "payload": 압축 JSON(zlib+base64), "stats": …}
형식은 팀 간 미확정 → 초안(sq-battle/0.1). 병사 프로토콜을 모른다: 전투 로그에 앱 계층이 남긴 설명 문자열만 쓴다.

전투 로그 kind(앱 계층이 남김)
  soldier      병사 보고 {desc, hex, retx, target?}            voice   분대장 발화(STT) {ptt, text}
  cmd          분대장 명령(키패드·음성·소대장 지시) {...}      sent    소대장에 보낸 정형 보고서 {rpt, text}
  contact_up   적 발견 자동 보고 {summary, fields}             pos     위치표 {pos}
  leader_pos   분대장 위치 {lat, lon, mgrs}                    note    기타(미수신·임무 변경 등)
"""
from __future__ import annotations

import base64
import json
import time
import zlib

FMT = "sq-battle/0.1"
SOLDIER_UID = lambda squad, n: f"{squad}-{int(n) + 1}"     # noqa: E731 - 분대원 n번 → 소대장 쪽 ID


def _hm(ts: float) -> str:
    return time.strftime("%H:%M:%S", time.localtime(ts))


def minutes(events, squad: str) -> list[str]:
    """무전 회의록: 시간순 '시각 [보낸 쪽→받는 쪽] 내용'."""
    me = f"{squad}-1"
    out = []
    for e in events:
        d, k = e.data, e.kind
        if k == "soldier":
            if d.get("retx"):
                continue
            desc = d.get("desc", "").split(" | ", 1)
            body = desc[1] if len(desc) > 1 else desc[0]
            name = desc[0].split(" ", 1)[0] if desc else ""
            line = f"[{SOLDIER_UID(squad, e.src)}→{me}] {name} {body}".rstrip()
            if t := d.get("target"):
                line += f" ⇒ 분대장 기준 {t.get('clock', 0)}시 {round(t.get('dist', 0))}m"
            out.append(f"{_hm(e.ts)} {line}")
        elif k == "voice":
            out.append(f"{_hm(e.ts)} [{me} 발화·{ {'report': '보고', 'manual': '교범', 'voice_cmd': '하달'}.get(d.get('ptt'), d.get('ptt'))}] {d.get('text', '')}")
        elif k == "cmd":
            if d.get("from") == "PL" and "cancel" in d:
                o = d["cancel"]
                out.append(f"{_hm(e.ts)} [소대장→{me}] 지시 취소 {o.get('code', '')} {o.get('text', '')}".rstrip())
            elif d.get("from") == "PL":
                o = d.get("order", {})
                out.append(f"{_hm(e.ts)} [소대장→{me}] 지시 {o.get('code', '')} {o.get('text') or json.dumps(o.get('params') or {}, ensure_ascii=False)}")
            elif d.get("from") == "voice":
                out.append(f"{_hm(e.ts)} [{me}→분대] 음성 하달 \"{d.get('text', '')}\"")
            else:
                out.append(f"{_hm(e.ts)} [{me}→분대] 명령 {d.get('text') or d.get('cmd_code')} (대상 {d.get('target', 'all')})")
        elif k == "sent":
            out.append(f"{_hm(e.ts)} [{me}→소대장] 정형 보고 {d.get('rpt', {}).get('id', '')} [{d.get('priority', '')}] "
                       + (d.get("text", "").split("\n")[1] if "\n" in d.get("text", "") else ""))
        elif k == "contact_up":
            out.append(f"{_hm(e.ts)} [{me}→소대장] 적 발견 자동 보고: {d.get('summary', '')}")
        elif k == "note":
            if "unacked" in d:
                out.append(f"{_hm(e.ts)} [분대] 미수신 {d['unacked'].get('sids')}")
            elif "mission" in d:
                out.append(f"{_hm(e.ts)} [소대장→{me}] 임무 변경 {json.dumps(d['mission'], ensure_ascii=False)}")
    return out


def build(events, sit, geo, squad: str, unit: str, t0: float, now: float, battle_id: str,
          member_pos: dict | None = None) -> dict:
    """전투 데이터 보고 한 건."""
    mins = minutes(events, squad)
    kinds = {}
    for e in events:
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
    soldier_n = sum(1 for e in events if e.kind == "soldier" and not e.data.get("retx"))
    # 적 표적
    enemy = []
    for tr in sit.tracks:
        loc = None
        if tr.pos:
            loc = {"mgrs": geo.mgrs(*tr.pos), "dx": round(tr.pos[0]), "dy": round(tr.pos[1]), "err_m": round(tr.err_m)}
        enemy.append({"tid": tr.tid, "count": tr.count, "reporters": [SOLDIER_UID(squad, s) for s in tr.reporters],
                      "first": _hm(tr.first_t), "last": _hm(tr.last_t), "trend": tr.trend(), "loc": loc})
    contacts_leader = [e.data.get("summary") for e in events if e.kind == "contact_up"]
    # 아군
    fr = sit.friendly(now)
    soldiers = {}
    for sid, st in sorted(sit.soldiers.items()):
        p = (member_pos or {}).get(sid) or st.pos
        soldiers[SOLDIER_UID(squad, sid)] = {
            "casualty": st.casualty_t is not None, "ammo_issue": sid in fr["ammo_issue"],
            "last_report": _hm(st.last_rx) if st.last_rx else None,
            "pos": {"dx": round(p[0], 1), "dy": round(p[1], 1), "mgrs": geo.mgrs(*p)} if p else None}
    track = [{"t": _hm(e.ts), "mgrs": e.data.get("mgrs")} for e in events if e.kind == "leader_pos"]
    result = {"enemy_tracks": len(enemy), "contact_reports_up": len(contacts_leader), "soldier_reports": soldier_n,
              "commands": kinds.get("cmd", 0), "formatted_reports_sent": kinds.get("sent", 0),
              "casualties": len(fr["casualties"]), "unacked": kinds.get("note", 0)}
    summary = (f"전투 {_hm(t0)}~{_hm(now)}: 적 표적 {len(enemy)}개, 아군 부상 {len(fr['casualties'])}명, "
               f"병사 보고 {soldier_n}건, 명령 {kinds.get('cmd', 0)}건, 정형 보고 {kinds.get('sent', 0)}건")
    lines = [f"[전투 데이터] {unit} {battle_id} {_hm(t0)}~{_hm(now)}", f"요약: {summary}"]
    for e in enemy:
        lines.append(f"적{e['tid']}: {e['count'] or '미상'}명 ({', '.join(e['reporters'])}) {e['first']}~{e['last']}"
                     + (f" / {e['loc']['mgrs']} ±{e['loc']['err_m']}m" if e["loc"] else " / 위치 미상"))
    lines.append("아군: " + ", ".join(f"{k}{' 부상' if v['casualty'] else ''}{' 탄약' if v['ammo_issue'] else ''}"
                                     f"{' @' + v['pos']['mgrs'] if v['pos'] else ''}" for k, v in soldiers.items()))
    lines.append(f"분대장 위치: {geo.mgrs(0, 0)} (기록 {len(track)}점)")
    lines.append("— 무전 회의록 —")
    lines += mins
    doc = {"fmt": FMT, "battle_id": battle_id, "unit": unit, "squad": squad, "t0": round(t0, 1), "t1": round(now, 1),
           "summary": summary, "result": result, "enemy": enemy, "soldiers": soldiers, "leader_track": track,
           "minutes": mins, "events": [{"ts": round(e.ts, 1), "kind": e.kind, "src": e.src, "data": e.data} for e in events]}
    raw = json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode()
    packed = zlib.compress(raw, 9)
    return {"fmt": FMT, "battle_id": battle_id, "summary": summary, "text": "\n".join(lines), "result": result,
            "payload": {"enc": "zlib+base64+json", "raw_bytes": len(raw), "bytes": len(packed),
                        "data": base64.b64encode(packed).decode()}}


def unpack(payload: dict) -> dict:
    """수신 쪽(소대장·중대) 복원용."""
    return json.loads(zlib.decompress(base64.b64decode(payload["data"])))
