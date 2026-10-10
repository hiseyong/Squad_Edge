"""분대장 → 소대장 규격 보고 sq-rpt/0.1 (docs/squad_platoon_report_protocol_v0.1.md).

  snapshot()   전투 데이터(상황 집계기) → 사실 값만 담은 스냅샷 (§6.1)
  rule_voice() 분대장 발화 → 활동·조치·요청·판단 칸 (규칙, LLM 실패 시 대체)
  assemble()   스냅샷 + 발화 칸 → report.new data (§3: text + body + 기존 호환 필드)
  priority()   우선순위 (§8.1, LLM 관여 없음)
  validate()   LLM이 만든 발화 칸 검증 (§6.3)
"""
from __future__ import annotations

import math
import re
import time
from pathlib import Path

from ..protocol import azimuth_to_clock
from .grid import Utm, cardinal, utm_to_mgrs
from .situation import Situation, bearing
from .utterance import Utterance

FMT = "sq-rpt/0.1"
PREC_KO = {"flash": "섬광", "urgent": "긴급", "priority": "우선", "routine": "보통"}
SUMMARY_MAX = 80

ACTIVITY_CODES = {"APPROACH": "접근 중", "FLANK_LEFT": "좌측 우회 중", "FLANK_RIGHT": "우측 우회 중", "FIRING": "사격 중",
                  "AMBUSH": "매복", "DIG_IN": "진지 구축 중", "WITHDRAW": "이탈 중", "HALTED": "고착",
                  "MOVING": "이동 중", "OBSERVING": "관측 중", "UNKNOWN": "미상"}
ACTION_CODES = {"HOLD": "고수", "TAKE_COVER": "엄폐", "OBSERVE": "경계", "ENGAGED": "교전 중", "OPEN_FIRE": "사격 개시",
                "FIRE_CONTROL": "사격 통제", "CEASE_FIRE": "사격 중지", "WITHDRAW": "철수", "MOVE": "이동 예정",
                "WAIT": "대기", "SELF_EVAC": "자체 후송"}
REQUEST_CODES = {"MEDEVAC": "의무후송", "FIRE_SUPPORT": "화력 지원", "REINFORCE": "증원", "RESUPPLY": "재보급",
                 "GUIDANCE": "지침", "ILLUM": "조명 지원"}
# 규칙 추출기(utterance.py) 표기 → 코드
_ACT_LABEL = {"접근 중": "APPROACH", "사격 중": "FIRING", "매복": "AMBUSH", "진지 구축 중": "DIG_IN",
              "이탈 중": "WITHDRAW", "고착": "HALTED", "이동 중": "MOVING", "관측 중": "OBSERVING", "우회 중": "FLANK_LEFT"}
_ACTION_LABEL = {"고수": "HOLD", "엄폐": "TAKE_COVER", "경계": "OBSERVE", "교전 중": "ENGAGED", "사격 개시": "OPEN_FIRE",
                 "사격 통제": "FIRE_CONTROL", "사격 중지": "CEASE_FIRE", "철수": "WITHDRAW", "이동 예정": "MOVE",
                 "대기": "WAIT", "자체 후송 중": "SELF_EVAC"}
_REQ_LABEL = {"의무후송": ("MEDEVAC", {}), "화력 지원(박격포)": ("FIRE_SUPPORT", {"asset": "mortar"}),
              "화력 지원(포병)": ("FIRE_SUPPORT", {"asset": "artillery"}), "화력 지원": ("FIRE_SUPPORT", {}),
              "증원": ("REINFORCE", {}), "재보급(탄약)": ("RESUPPLY", {"class": "ammo"}), "지침": ("GUIDANCE", {}),
              "조명 지원": ("ILLUM", {})}
_HAZ_KIND = {"폭발물 의심": "UXO_SUSPECT", "아군 부상자": "CASUALTY_FOUND", "의심 징후": "SUSPICIOUS"}
_BASIS = {"교차": "triangulated", "단독": "single", "같은 방향": "same_bearing", "방향 미상": "none"}


class Geo:
    """분대장 GPS 원점 → 격자·위경도 변환 (분대 안 상대 좌표는 동·북 m)."""

    def __init__(self, lat: float, lon: float, heading: int = 0):
        from .grid import latlon_to_utm
        self.lat, self.lon, self.heading = lat, lon, heading
        self.utm: Utm = latlon_to_utm(lat, lon)

    def mgrs(self, x: float, y: float) -> str:
        return utm_to_mgrs(self.utm.offset(x, y))

    def latlon(self, x: float, y: float) -> tuple[float, float]:
        r = 6_371_000.0
        return (round(self.lat + math.degrees(y / r), 6),
                round(self.lon + math.degrees(x / (r * math.cos(math.radians(self.lat)))), 6))


class ReportCounter:
    """보고 번호 (재부팅 후에도 이어짐)."""

    def __init__(self, path: Path | None = None):
        self.path = path
        self.n = int(path.read_text()) if path and path.exists() else 0

    def next(self) -> int:
        self.n += 1
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(str(self.n))
        return self.n


def _uid(squad: str, sid: int) -> str:
    return f"{squad}-{sid + 1}"


def _basis(text: str) -> str:
    return next((v for k, v in _BASIS.items() if k in text), "single")


# ---- 스냅샷 (사실 값) ----

def snapshot(sit: Situation, geo: Geo, now: float, squad: str = "1") -> dict:
    enemy = []
    for tr in sit.active_tracks(now)[:3]:
        loc = None
        if tr.pos:
            x, y = tr.pos
            lat, lon = geo.latlon(x, y)
            loc = {"mgrs": geo.mgrs(x, y), "lat": lat, "lon": lon, "err_m": round(tr.err_m),
                   "basis": _basis(tr.basis), "rel": {"ref": f"{squad}-1", "dx": round(x), "dy": round(y)},
                   "bearing": round(bearing(x, y)), "dist": round(math.hypot(x, y))}
        enemy.append({"tid": tr.tid,
                      "size": {"count": tr.count, "count_text": _count_text(tr.count), "kind": "infantry",
                               "src": "fused" if len(tr.reporters) > 1 else "sensor",
                               "reporters": [_uid(squad, s) for s in tr.reporters], "leader_count": None},
                      "activity": {"text": None, "code": "UNKNOWN", "src": None, "trend": tr.trend()},
                      "location": loc, "time": {"first": round(tr.first_t), "last": round(tr.last_t)},
                      "equipment": {"text": "미상", "src": None}})
    hazards = []
    for p in sit.points:
        if now - p.ts > 900 or p.kind == "의심 징후":
            continue
        hazards.append({"kind": _HAZ_KIND[p.kind], "mgrs": geo.mgrs(*p.pos) if p.pos else None,
                        "by": _uid(squad, p.sid), "ts": round(p.ts)})
    fr = sit.friendly(now)
    cas = [{"id": _uid(squad, sid), "kind": "self", "ts": round(sit.soldiers[sid].casualty_t), "urgency": "urgent"}
           for sid in fr["casualties"]]
    friendly = {"mgrs": geo.mgrs(0, 0), "lat": geo.lat, "lon": geo.lon, "heading": geo.heading,
                "total": fr["total"], "available": fr["available"], "casualties": cas,
                "ammo_issue": [_uid(squad, s) for s in fr["ammo_issue"]], "lost": [_uid(squad, s) for s in fr["lost"]],
                "silent": [_uid(squad, s) for s in fr["silent"]]}
    return {"now": now, "enemy": enemy, "friendly": friendly, "hazards": hazards}


def _count_text(n: int) -> str:
    return "미상" if n == 0 else "5명 이상" if n >= 5 else f"{n}명"


# ---- 발화 칸 ----

def rule_voice(u: Utterance) -> dict:
    """규칙 추출 결과 → §5 발화 칸 (activity/action/requests/judgment/leader_count/summary는 assemble이 채움)."""
    acts = []
    for a in u.activity:
        code = next((c for k, c in _ACT_LABEL.items() if k in a), "UNKNOWN")
        if code == "FLANK_LEFT" and ("우측" in a or a.startswith("우 ")):
            code = "FLANK_RIGHT"
        acts.append({"text": a, "code": code})
    reqs = []
    for r in u.requests:
        code, detail = _REQ_LABEL.get(r, ("GUIDANCE", {}))
        reqs.append({"text": r, "code": code, "detail": dict(detail)})
    return {"activity": acts,
            "action": [{"text": a, "code": _ACTION_LABEL.get(a, "WAIT")} for a in u.action],
            "requests": reqs, "judgment": [{"text": j} for j in u.judgment],
            "leader_count": u.enemy_count, "casualty_ids": u.casualty_ids, "summary": None}


def rule_summary(snap: dict, v: dict) -> str:
    bits = []
    if snap["enemy"]:
        e = snap["enemy"][0]
        n = v.get("leader_count") or e["size"]["count"]
        where = f"{cardinal(e['location']['bearing'])} {round(e['location']['dist'], -1):.0f}m" if e["location"] else ""
        act = v["activity"][0]["text"] if v["activity"] else (e["activity"]["trend"] or "")
        bits.append(" ".join(x for x in (f"적 {_count_text(n)}", where, act) if x))
    cas = snap["friendly"]["casualties"]
    if cas:
        bits.append(f"아군 {len(cas)}명 부상")
    if snap["friendly"]["lost"]:
        bits.append(f"{len(snap['friendly']['lost'])}명 연락 두절")
    if v["action"]:
        bits.append(v["action"][0]["text"])
    if v["requests"]:
        bits.append(", ".join(r["text"] for r in v["requests"]) + " 요청")
    return (". ".join(bits) + ".") if bits else "특이사항 없음."


# ---- 우선순위 (§8.1) ----

def priority(events: list[str], snap: dict, v: dict, last_body: dict | None) -> str:
    prev_cas = {c["id"] for c in (last_body or {}).get("friendly", {}).get("casualties", [])}
    new_cas = {c["id"] for c in snap["friendly"]["casualties"]} - prev_cas
    if "new_contact" in events or "casualty" in events or new_cas:
        return "flash"
    if {"hazard", "contact_grew", "contact_closer", "ammo", "link_lost"} & set(events) or v["requests"]:
        return "urgent"
    if snap["enemy"]:
        return "priority"
    return "routine"


# ---- 조립 (§3, §4, §5) ----

def _medevac9(snap: dict) -> dict:
    n = len(snap["friendly"]["casualties"])
    return {"1": snap["friendly"]["mgrs"], "2": None, "3": {"urgent": n}, "4": None, "5": None,
            "6": "enemy_possible" if snap["enemy"] else "no_enemy", "7": None, "8": "friendly", "9": None}


def _lines(body: dict, unit: str) -> dict[str, str]:
    """규격 텍스트의 머리말 → 내용 (§4 순서)."""
    out: dict[str, str] = {"요지": body["summary"]}
    for i, e in enumerate(body["enemy"], 1):
        s = e["size"]
        size = f"보병 {s['count_text']}(" + ("분대장 육안" if s.get("src") == "voice" else f"병사{len(s['reporters'])} 보고") + ")"
        if s.get("leader_count") and s["leader_count"] != s["count"]:
            size = f"보병 {s['leader_count']}명(분대장 판단), 병사 확인 {s['count_text']}"
        act = e["activity"]["text"] or (f"{e['activity']['trend']}(보고 추세)" if e["activity"]["trend"] else "미상")
        if e["location"]:
            l = e["location"]
            loc = f"{l['mgrs']} ±{l['err_m']}m {dict(triangulated='교차추정', single='단독보고', same_bearing='같은방향', none='').get(l['basis'], '')}"
        else:
            loc = "미상"
        t = e["time"]
        tt = f"{time.strftime('%H%M', time.localtime(t['first']))}~{time.strftime('%H%M', time.localtime(t['last']))}"
        out[f"적{i}"] = f"규모 {size} / 활동 {act} / 위치 {loc.strip()} / 관측 {tt} / 장비 {e['equipment']['text']}"
    if body["hazards"]:
        out["위험"] = " / ".join(
            f"{dict(UXO_SUSPECT='폭발물 의심', CASUALTY_FOUND='아군 부상자', SUSPICIOUS='의심 징후')[h['kind']]} "
            f"{h['mgrs'] or '위치 미상'} ({h['by']}, {time.strftime('%H%M', time.localtime(h['ts']))})"
            for h in body["hazards"])
    f = body["friendly"]
    parts = [f"위치 {f['mgrs']} 정면 {cardinal(f['heading'])}", f"가용 {f['available']}/{f['total']}",
             "부상 " + (", ".join(c["id"] for c in f["casualties"]) or "없음"),
             "탄약 " + (", ".join(f["ammo_issue"]) + " 문제" if f["ammo_issue"] else "이상없음"),
             "두절 " + (", ".join(f["lost"]) or "없음")]
    if f["silent"]:
        parts.append("무선침묵 " + ", ".join(f["silent"]))
    out["아군"] = " / ".join(parts)
    out["조치"] = ", ".join(a["text"] for a in body["action"]) or "미보고"
    out["요청"] = ", ".join(r["text"] + (f"(긴급 {r['detail']['urgent']}명)" if r["detail"].get("urgent") else "")
                          for r in body["requests"]) or "없음"
    if body["judgment"]:
        out["판단"] = " / ".join(j["text"] for j in body["judgment"])
    if body.get("medevac9"):
        m = body["medevac9"]
        val = {"1": m["1"], "3": f"긴급{m['3']['urgent']}", "6": {"enemy_possible": "적 있음", "no_enemy": "적 없음"}[m["6"]],
               "8": "아군"}
        out["후송"] = " ".join(f"{k}){val.get(k, '-')}" for k in map(str, range(1, 10)))
    return out


def assemble(snap: dict, v: dict, *, prec: str, rpt_id: str, rev: int, unit: str, gen: dict,
             voice_text: str | None, last: dict | None = None, squad: str = "1") -> dict:
    """report.new의 data. last = 직전 송신한 data (변동분 계산용)."""
    body = {"summary": v.get("summary") or rule_summary(snap, v), "enemy": [dict(e) for e in snap["enemy"]],
            "hazards": snap["hazards"], "friendly": snap["friendly"], "action": [], "requests": [],
            "judgment": [], "medevac9": None, "delta": None}
    if body["enemy"]:                                   # 분대장 발화는 주 표적에만
        e0 = body["enemy"][0] = {**body["enemy"][0]}
        e0["size"] = {**e0["size"], "leader_count": v.get("leader_count")}
        if v["activity"]:
            a = v["activity"][0]
            e0["activity"] = {"text": a["text"], "code": a["code"], "src": "voice", "trend": e0["activity"]["trend"]}
    body["action"] = [{**a, "src": "voice"} for a in v["action"]]
    body["judgment"] = [{**j, "src": "voice"} for j in v["judgment"]]
    n_cas = len(snap["friendly"]["casualties"])
    for r in v["requests"]:
        d = dict(r.get("detail") or {})
        if r["code"] == "MEDEVAC" and n_cas:
            d.setdefault("urgent", n_cas)
        body["requests"].append({"text": r["text"], "code": r["code"], "detail": d, "src": "voice"})
    kinds = (["SPOT"] if body["enemy"] else []) + ["SIT"]
    if n_cas and any(r["code"] == "MEDEVAC" for r in body["requests"]):
        body["medevac9"] = _medevac9(snap)
        kinds.append("MEDEVAC")
    if snap["friendly"]["ammo_issue"]:
        kinds.append("ACE")

    lines = _lines(body, unit)
    unchanged = []
    if last and last.get("fmt") == FMT:
        prev = last.get("_lines", {})
        for k in list(lines):
            if k != "요지" and prev.get(k) == lines[k]:
                unchanged.append(k)
        body["delta"] = {"since": last["rpt"]["id"], "unchanged": unchanged}
    ts = snap["now"]
    name = "적정·상황보고" if body["enemy"] else "상황보고"
    head = f"[{PREC_KO[prec]}] {time.strftime('%d%H%M', time.localtime(ts))} {unit}→소대장 {name} #{rpt_id.rsplit('-', 1)[-1]}"
    if rev:
        head += f" 정정{rev}"
    text = "\n".join([head] + [f"{k}: {'변동 없음' if k in unchanged else val}" for k, val in lines.items()])

    e0 = body["enemy"][0] if body["enemy"] else None
    fields = {"location": ({**{k: e0["location"][k] for k in ("bearing", "dist", "err_m", "mgrs")},
                            "err": e0["location"]["err_m"], "ref": f"{squad}-1"} if e0 and e0["location"] else None),
              "size": e0["size"]["count"] if e0 else None,
              "activity": e0["activity"]["text"] if e0 else None}
    missing = []
    if (body["enemy"] or n_cas) and not body["action"]:
        missing.append("action")
    if n_cas and not any(r["code"] == "MEDEVAC" for r in body["requests"]):
        missing.append("medevac_request")
    return {"type": ("SPOTREP" if body["enemy"] and not n_cas else "SITREP"), "sender": f"{squad}-1",
            "priority": prec, "conf": 0.8, "summary": body["summary"], "fields": fields, "missing": missing,
            "fmt": FMT,
            "rpt": {"id": rpt_id, "rev": rev, "ts": round(ts, 1), "dtg": time.strftime("%d%H%M", time.localtime(ts)),
                    "kinds": kinds},
            "text": text, "body": body, "gen": gen,
            "voice": {"text": voice_text, "stt": "zipformer-ko-174m", "conf": None} if voice_text else None,
            "_lines": lines}


def wire(data: dict) -> dict:
    """송신용: 내부 전용 키(_lines) 제거."""
    return {k: v for k, v in data.items() if not k.startswith("_")}


# ---- 복창 (분대장 헤드셋) ----

def readback(data: dict, leader_heading: int) -> str:
    b = data["body"]
    out = [PREC_KO[data["priority"]]]
    if b["enemy"]:
        e = b["enemy"][0]
        n = e["size"]["leader_count"] or e["size"]["count"]
        s = f"적 {_count_text(n)}"
        if e["location"]:
            s += f", {azimuth_to_clock(e['location']['bearing'], leader_heading)}시 방향 {round(e['location']['dist'], -1):.0f}미터"
        if e["activity"]["text"]:
            s += f", {e['activity']['text']}"
        out.append(s)
    if b["friendly"]["casualties"]:
        # 소대장용 ID "1-4" → 분대장이 쓰는 병사 번호 3번 (BLE n = COP n+1)
        out.append(", ".join(f"{int(c['id'].split('-')[1]) - 1}번" for c in b["friendly"]["casualties"]) + " 부상")
    if b["action"]:
        out.append(", ".join(a["text"] for a in b["action"]))
    if b["requests"]:
        out.append(", ".join(r["text"] for r in b["requests"]) + " 요청")
    return ". ".join(out) + ". 송신할까요?"


# ---- LLM 칸 검증 (§6.3) ----

RE_NUM = re.compile(r"\d+")
_NEG_AFTER = r"\S{0,4}\s?(하지\s?않|안\s?하|말|못\s?하|하지\s?마)"
_KW = {"HOLD": "고수", "TAKE_COVER": "엄폐", "OBSERVE": "경계", "OPEN_FIRE": "사격\\s?개시", "WITHDRAW": "철수|후퇴",
       "MEDEVAC": "후송", "FIRE_SUPPORT": "화력|포병|박격포", "REINFORCE": "증원", "RESUPPLY": "보급|탄약"}


def _snap_numbers(snap: dict) -> set[str]:
    nums = set(RE_NUM.findall(repr(snap)))
    for e in snap["enemy"]:
        if e["location"]:
            d = e["location"]["dist"]
            nums |= {str(d), str(round(d, -1)), str(int(round(d, -1)))}
    return nums


def validate(v: dict, snap: dict, voice_text: str) -> str | None:
    """LLM 발화 칸 검증. 실패 이유 또는 None."""
    allowed = _snap_numbers(snap) | set(RE_NUM.findall(voice_text or ""))
    texts = [v.get("summary") or ""] + [x["text"] for k in ("activity", "action", "requests", "judgment") for x in v[k]]
    extra = {n for t in texts for n in RE_NUM.findall(t)} - allowed
    if extra:
        return f"근거에 없는 숫자 {sorted(extra)}"
    for k, codes in (("activity", ACTIVITY_CODES), ("action", ACTION_CODES), ("requests", REQUEST_CODES)):
        bad = [x["code"] for x in v[k] if x["code"] not in codes]
        if bad:
            return f"모르는 코드 {bad}"
    for k in ("action", "requests"):
        for x in v[k]:
            kw = _KW.get(x["code"])
            if kw and re.search(f"({kw}){_NEG_AFTER}", voice_text or ""):
                return f"부정된 발화를 {x['code']}로 분류"
    lc = v.get("leader_count")
    if lc is not None and str(lc) not in set(RE_NUM.findall(voice_text or "")):
        return f"발화에 없는 적 수 {lc}"
    if not v.get("summary") or len(v["summary"]) > SUMMARY_MAX:
        return "요지 길이"
    return None
