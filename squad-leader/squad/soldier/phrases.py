"""병사 보고 → 분대장 헤드셋 문장 (가이드 e항, 병사 이어폰 문장과 같은 규칙).

방향: 보고 azimuth를 분대장 heading(0 고정)으로 시계 변환. 거리: 근·중·원(10·20·40m), 없음은 생략.
적 수: 1~4 "N명", 5 "다수", 0 "미상". CASUALTY_SELF는 최우선으로 2회(우선순위·반복은 호출 쪽이 정한다).
반환: (문장, 긴급도 "urgent"|"report"|"system", 반복 횟수) 또는 None(읽지 않는 종류).
"""
from __future__ import annotations

from . import codec as fc
from .geo import clock_from_azimuth

DIST = {0: "근거리", 1: "중거리", 2: "원거리"}
MODE = {0: "침묵", 1: "최소", 2: "정상"}
VOICE_FAIL = {1: "음성 실패 CRC", 2: "음성 실패 누락", 3: "음성 실패 메모리"}


def _count(n: int) -> str:
    return {0: "미상", 5: "다수"}.get(n, f"{n}명")


def _clock(az: int) -> str | None:
    c = clock_from_azimuth(az)
    return f"{c}시" if c else None


def report_sentence(m: dict) -> tuple[str, str, int] | None:
    sid, t = m["src"], m["type"]
    n = f"{sid}번"
    if t == fc.CONTACT:
        parts = [n, f"적 {_count(m['count'])}", _clock(m["azimuth"]), DIST.get(m["dist_band"])]
        return ", ".join(p for p in parts if p), "urgent", 1
    if t == fc.SUSPICIOUS:
        return ", ".join(p for p in (n, "징후", _clock(m["azimuth"])) if p), "report", 1
    if t == fc.HAZARD:
        return ", ".join(p for p in (n, "폭발물 의심", _clock(m["azimuth"])) if p), "urgent", 1
    if t == fc.CASUALTY_FOUND:
        return ", ".join(p for p in (n, "부상자 발견", _clock(m["azimuth"]), DIST.get(m["dist_band"])) if p), "urgent", 1
    if t == fc.OK_READY:
        return f"{n}, 이상 없음", "report", 1
    if t == fc.WEAPON_AMMO:
        return f"{n}, 탄약 화기 문제", "urgent", 1
    if t == fc.CASUALTY_SELF:
        return f"{n} 부상", "urgent", 2
    if t == fc.ACK:
        return f"{n} 수신", "report", 1
    if t == fc.CANNOT_COMPLY:
        return f"{n} 수행 불가", "urgent", 1
    if t == fc.VOICE_RESULT and m["status"]:
        return f"{n} {VOICE_FAIL.get(m['status'], '음성 실패')}", "report", 1
    if t == fc.EMCON_STATE:
        return f"{n} {MODE.get(m['mode'], '모드')}", "system", 1
    return None


def unacked_sentence(sids: list[int]) -> str:
    return ", ".join(f"{s}번" for s in sids) + " 미수신"
