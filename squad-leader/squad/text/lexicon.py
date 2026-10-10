"""군 용어 가중치: STT 바이어싱용 용어집 + 오인식 교정.

1) STT 입력 쪽: `stt_prompt()`(whisper.cpp --prompt / initial_prompt), `hotwords()`(faster-whisper 등)
2) STT 출력 쪽: `correct()` — 알려진 오인식 사전 + 자모 편집거리 기반 퍼지 교정

퍼지 교정은 3음절 이상 용어에만 적용한다. 2음절 용어("전진" ↔ "전지")는 일반 단어와 쉽게 겹쳐서
명시적 오인식 사전으로만 고친다.
"""
from __future__ import annotations

import re

TERMS: dict[str, tuple[str, ...]] = {
    "명령": ("정지", "엄폐", "전진", "후퇴", "집결", "사격 개시", "사격 중지", "경계",
             "상태 보고", "무선 침묵", "현 위치 고수", "취소", "포복", "산개", "엄호", "돌격",
             "우회", "매복", "철수", "대기"),
    "보고": ("적 발견", "의심 징후", "폭발물 의심", "부상자 발견", "이상 없음", "준비 완료",
             "이동 완료", "탄약 부족", "화기 고장", "수행 불가", "수신 완료", "적정 보고",
             "상황 보고", "복창"),
    "적·표적": ("적", "적 병력", "저격수", "기관총", "박격포", "장갑차", "전차", "차량",
               "수류탄", "지뢰", "급조폭발물", "드론", "관측소", "진지", "참호"),
    "방향·위치": ("시 방향", "방위", "전방", "후방", "좌측", "우측", "측방", "고지", "능선",
                 "개활지", "숲", "건물", "교차로", "좌표", "그리드", "집결지", "목표"),
    "부대·인원": ("분대", "소대", "중대", "대대", "분대장", "소대장", "부분대장", "사수",
                 "부사수", "통신병", "의무병", "병사"),
}

# STT가 자주 틀리는 형태 → 바른 용어 (실측하면서 추가)
MISHEARD: dict[str, str] = {
    "엄페": "엄폐", "음폐": "엄폐", "엄패": "엄폐",
    "사격 게시": "사격 개시", "사격개시": "사격 개시", "사격 계시": "사격 개시",
    "사격중지": "사격 중지", "사격 정지": "사격 중지",
    "포보": "포복", "산게": "산개", "엄오": "엄호",
    "탄냑": "탄약", "타냑": "탄약",
    "적정보고": "적정 보고", "적정 보구": "적정 보고",
    "무선침묵": "무선 침묵", "무전 침묵": "무선 침묵",
    "분대 장": "분대장", "소대 장": "소대장",
    "박격 포": "박격포", "장갑 차": "장갑차",
    "복차": "복창",
}

# 퍼지 교정 대상에서 빼야 하는 일반 단어(자모 거리 1로 용어와 겹치는 것)
COMMON_WORDS = frozenset({"상태 보조", "준비 완성"})


def all_terms() -> list[str]:
    seen: dict[str, None] = {}
    for group in TERMS.values():
        for t in group:
            seen.setdefault(t, None)
    return list(seen)


def hotwords() -> list[str]:
    return all_terms()


def stt_prompt(max_chars: int = 200) -> str:
    """Whisper initial prompt. 문장 형태가 단순 나열보다 바이어싱 효과가 좋다."""
    base = ("분대 무전. 2시 방향 300m 적 3명 발견. 전원 엄폐, 사격 개시. 사격 중지. "
            "상태 보고. 무선 침묵. 현 위치 고수. ")
    extra = [t for t in all_terms() if t not in base]
    out = base
    for t in extra:
        if len(out) + len(t) + 2 > max_chars:
            break
        out += t + ", "
    return out.rstrip(", ")


# ---- 자모 편집거리 ----

_CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ"
_JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ"
_JONG = " ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ"


def to_jamo(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            out.append(_CHO[code // 588])
            out.append(_JUNG[(code % 588) // 28])
            if code % 28:
                out.append(_JONG[code % 28])
        elif not ch.isspace():
            out.append(ch)
    return "".join(out)


def _edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def _fuzzy_terms() -> list[tuple[str, str, int]]:
    """(용어, 자모, 음절 수) — 3음절 이상만."""
    out = []
    for t in all_terms():
        syl = len(t.replace(" ", ""))
        if syl >= 3:
            out.append((t, to_jamo(t), syl))
    return out


_FUZZY = _fuzzy_terms()


def _max_dist(syllables: int) -> int:
    return 1 if syllables <= 4 else 2


def correct(text: str) -> tuple[str, list[tuple[str, str]]]:
    """오인식 교정. (교정된 텍스트, [(원문, 교정)]) 반환."""
    changes: list[tuple[str, str]] = []
    for wrong in sorted(MISHEARD, key=len, reverse=True):
        if wrong in text:
            text = text.replace(wrong, MISHEARD[wrong])
            changes.append((wrong, MISHEARD[wrong]))

    tokens = text.split(" ")
    out: list[str] = []
    i = 0
    while i < len(tokens):
        best = None  # (dist, n_tokens, term, suffix)
        for n in (3, 2, 1):  # 여러 어절 용어("현 위치 고수", "사격 개시")를 먼저
            if i + n > len(tokens):
                continue
            window = " ".join(tokens[i:i + n])
            if re.search(r"\d", window) or window in COMMON_WORDS:
                continue
            compact = window.replace(" ", "")
            for term, term_jamo, syl in _FUZZY:
                if term.count(" ") + 1 != n:
                    continue
                # 어미·조사가 붙은 경우: 용어 길이만큼 앞부분만 비교 ("엄호하라" 등)
                for cut in {syl, syl + 1} if len(compact) > syl else {len(compact)}:
                    head = compact[:cut]
                    if head == term.replace(" ", ""):
                        best = best or (0, n, term, compact[cut:])
                        continue
                    if abs(len(head) - syl) > 1:
                        continue
                    d = _edit_distance(to_jamo(head), term_jamo)
                    if d <= _max_dist(syl) and (best is None or d < best[0]):
                        best = (d, n, term, compact[cut:])
            if best:
                break
        if best and best[0] > 0:
            _, n, term, suffix = best
            original = " ".join(tokens[i:i + n])
            fixed = term + suffix
            changes.append((original, fixed))
            out.append(fixed)
            i += n
        else:
            out.append(tokens[i])
            i += 1
    return " ".join(out), changes
