"""분대장 음성(STT 정규화 결과) → 병사 하달: 정해진 명령어면 CMD_BUTTON 필드, 아니면 None(음성 하달 대상).

예) "전원 9시 엄폐" / "2번 적 3명 2시 원거리" / "사격 중지" / "1번 집결" / "경계 3시" / "무선 침묵"
대상: "N번"(여러 개 가능) 또는 "전원"(기본). 방향: "N시". 거리: 근·중·원거리 또는 "Nm"(15·30m 경계로 구간).
방위는 분대장 방위 0 고정: azimuth = (시계 × 30) mod 360. 집결은 항상 방향 없음(병사가 계산).
STT 정규화가 수사를 숫자로 바꾼다("세 명" → "3명", "두 시" → "2시", "삼백 미터" → "300m").
"""
from __future__ import annotations

import re

from .geo import band_of

NO_AZIMUTH, NO_DIST = 0xFFFF, 0xFF

# (정규식, cmd_code, 이름, 방향 규칙, 거리 허용, 우선순위) — 먼저 맞는 것. 키패드 표와 같은 규칙
COMMANDS = [
    (r"사격\s*(중지|그만|멈춰)|쏘지\s*마", 0x07, "사격 중지", "none", False, 1),
    (r"사격\s*(개시|시작)|발사|쏴", 0x06, "사격 개시", "req", True, 1),
    (r"무선\s*침묵", 0x0B, "무선 침묵", "none", False, 1),
    (r"상태\s*보고", 0x0A, "상태 보고", "none", False, 0),
    (r"정지|멈춰|제자리", 0x01, "정지", "none", False, 1),
    (r"엄폐", 0x02, "엄폐", "opt", False, 1),
    (r"전진", 0x03, "전진", "opt", False, 0),
    (r"후퇴|철수", 0x04, "후퇴", "opt", False, 1),
    (r"집결|모여", 0x05, "집결", "never", False, 0),
    (r"경계", 0x08, "경계", "req", False, 0),
    (r"고수|현\s*위치", 0x0C, "고수", "none", False, 0),
    (r"명령\s*취소|취소", 0x0F, "취소", "none", False, 0),
    (r"적\s*(\d|다수|여러)", 0x09, "적 위치", "req", True, 0),
]
DIST_WORDS = {"근거리": 0, "중거리": 1, "원거리": 2}
DIST_TEXT = {0: "근거리", 1: "중거리", 2: "원거리"}


def parse(text: str, allowed=(1, 2, 3, 4, 5)) -> dict | None:
    """명령어면 {"cmd_code", "azimuth", "dist_band", "extra", "priority", "target", "text", "missing"} 아니면 None.
    missing: 필수 방향이 없을 때 "방향"(호출 쪽이 송신하지 않고 되묻는다)."""
    t = text.strip()
    for pat, code, name, rule, dist_ok, prio in COMMANDS:
        if re.search(pat, t):
            break
    else:
        return None
    ids = sorted({int(n) for n in re.findall(r"(\d)\s*번", t) if int(n) in allowed})
    target = "all" if not ids or re.search(r"전원|모두|분대\s*전체", t) else ",".join(map(str, ids))
    m = re.search(r"(1[0-2]|[1-9])\s*시", t)
    clock = int(m.group(1)) if m else 0
    dist = NO_DIST
    for w, b in DIST_WORDS.items():
        if w in t:
            dist = b
    if dist == NO_DIST and (m2 := re.search(r"(\d+)\s*(m|미터)", t)):
        dist = band_of(float(m2.group(1)))
    count = 0
    if code == 0x09:
        if m3 := re.search(r"적\s*(\d)\s*명", t):
            count = min(int(m3.group(1)), 5)
        elif re.search(r"적\s*(다수|여러)", t):
            count = 5
    az = NO_AZIMUTH if rule in ("none", "never") or not clock else (clock * 30) % 360
    parts = [name] + ([f"적 {'다수' if count == 5 else f'{count}명' if count else '수 미상'}"] if code == 0x09 else [])
    if clock and rule not in ("none", "never"):
        parts.append(f"{clock}시")
    if dist_ok and dist != NO_DIST:
        parts.append(DIST_TEXT[dist])
    parts.append("전원" if target == "all" else ", ".join(f"{i}번" for i in ids))
    return {"cmd_code": code, "azimuth": az, "dist_band": dist if dist_ok else NO_DIST, "extra": count,
            "priority": prio, "target": target, "text": ", ".join(parts),
            "missing": "방향" if rule == "req" and not clock else None}
