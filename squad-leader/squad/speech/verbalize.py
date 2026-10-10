"""TTS용 읽기 변환: 숫자·단위·기호를 군 무전 방식의 한국어 읽기로.

예) "3번, 적 3명, 2시 방향 300m" → "삼 번, 적 세 명, 두 시 방향 삼백 미터"
    "격자 329966" → "격자 삼 둘 아홉 아홉 여섯 여섯"   (5자리 이상 = 한 자리씩, 군 숫자 호칭)
    "16시 30분" → "십육 시 삼십 분",  "1630Z" → "십육 시 삼십 분 표준시"
text.normalize의 반대 방향이다.
"""
from __future__ import annotations

import re

_SINO = "영일이삼사오육칠팔구"
# 군 무전 숫자 호칭 (한 자리씩 읽을 때)
_MIL_DIGIT = ["공", "하나", "둘", "삼", "넷", "오", "여섯", "칠", "팔", "아홉"]
_NATIVE_ONES = ["", "한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉"]
_NATIVE_TENS = ["", "열", "스물", "서른", "마흔", "쉰", "예순", "일흔", "여든", "아흔"]
_PHONETIC = {
    "A": "알파", "B": "브라보", "C": "찰리", "D": "델타", "E": "에코", "F": "폭스트롯", "G": "골프",
    "H": "호텔", "I": "인디아", "J": "줄리엣", "K": "킬로", "L": "리마", "M": "마이크", "N": "노벰버",
    "O": "오스카", "P": "파파", "Q": "퀘벡", "R": "로미오", "S": "시에라", "T": "탱고", "U": "유니폼",
    "V": "빅터", "W": "위스키", "X": "엑스레이", "Y": "양키", "Z": "줄루",
}
# 그대로 읽는 약어 (음성부호로 풀지 않음)
_KEEP_ABBR = {"SALUTE": "살루트", "EOD": "이오디", "IED": "급조폭발물", "UXO": "불발탄",
              "MEDEVAC": "메디백", "QRF": "신속대응부대", "GPS": "지피에스", "PTT": "피티티"}


def sino(n: int) -> str:
    """한자어 수: 350 → 삼백오십, 12000 → 만이천."""
    if n == 0:
        return "영"
    out = ""
    for unit_val, unit in ((10 ** 8, "억"), (10 ** 4, "만"), (1, "")):
        part = n // unit_val % 10000
        if not part:
            continue
        s = ""
        for place_val, place in ((1000, "천"), (100, "백"), (10, "십"), (1, "")):
            d = part // place_val % 10
            if d:
                s += ("" if d == 1 and place else _SINO[d]) + place
        if unit == "만" and part == 1:
            s = ""
        out += s + unit
    return out


def native(n: int) -> str:
    """고유어 수 관형형(단위 앞): 1 → 한, 3 → 세, 20 → 스무, 99 → 아흔아홉. 100 이상은 한자어."""
    if not 0 < n < 100:
        return sino(n)
    if n == 20:
        return "스무"
    return _NATIVE_TENS[n // 10] + _NATIVE_ONES[n % 10]


def digits(s: str) -> str:
    return " ".join(_MIL_DIGIT[int(c)] for c in s)


def _clock_time(h: int, m: int) -> str:
    return f"{sino(h) if h else '영'} 시" + (f" {sino(m)} 분" if m else "")


def verbalize(text: str) -> str:
    t = text
    # 격자 좌표: "격자/좌표/그리드" 또는 격자 구역 문자(AB) 뒤의 4자리 이상 숫자 묶음은 한 자리씩
    t = re.sub(r"(격자|좌표|그리드|(?<![A-Za-z])[A-Z]{2})((?:\s*\d{4,})+)",
               lambda m: m[1] + " " + " ".join(digits(g) for g in m[2].split()), t)
    # 시각: 1630Z / 0905z (4자리 + Z) → 시·분 + 표준시
    t = re.sub(r"(?<!\d)([01]\d|2[0-3])([0-5]\d)\s*[Zz](?![A-Za-z])", lambda m: _clock_time(int(m[1]), int(m[2])) + " 표준시", t)
    # 16:30
    t = re.sub(r"(?<!\d)([01]?\d|2[0-3]):([0-5]\d)(?!\d)", lambda m: _clock_time(int(m[1]), int(m[2])), t)
    # 약어
    for k, v in _KEEP_ABBR.items():
        t = re.sub(rf"(?<![A-Za-z]){k}(?![A-Za-z])", v, t)
    # 단위: km, m, °/도, %
    t = re.sub(r"(\d+(?:\.\d+)?)\s*km(?![A-Za-z])", lambda m: _num(m[1]) + " 킬로미터", t)
    t = re.sub(r"(\d+(?:\.\d+)?)\s*m(?![A-Za-z])", lambda m: _num(m[1]) + " 미터", t)
    t = re.sub(r"(\d+)\s*(?:°|도)", lambda m: sino(int(m[1])) + " 도", t)
    t = re.sub(r"(\d+)\s*%", lambda m: sino(int(m[1])) + " 퍼센트", t)
    # 시(時): 12 이하는 고유어(두 시 방향), 13 이상은 한자어(십육 시)
    t = re.sub(r"(\d{1,2})\s*시(?=[\s,.]|방향|$|[^가-힣])",
               lambda m: (native(int(m[1])) if 1 <= int(m[1]) <= 12 else sino(int(m[1]))) + " 시", t)
    # 고유어로 세는 단위
    t = re.sub(r"(\d{1,2})\s*(명|개|발|대|곳|군데|정|시간)", lambda m: native(int(m[1])) + " " + m[2], t)
    # 그 밖의 단위는 한자어 (번, 분, 초, 분대, 소대, 호, 일, 월, 년)
    t = re.sub(r"(\d+)\s*(번|분대|소대|중대|대대|분|초|호|일|월|년|원)",
               lambda m: sino(int(m[1])) + " " + m[2], t)
    # 5자리 이상(격자 좌표 등)은 한 자리씩
    t = re.sub(r"\d{5,}", lambda m: digits(m[0]), t)
    # 나머지 숫자는 한자어
    t = re.sub(r"\d+(?:\.\d+)?", lambda m: _num(m[0]), t)
    # 대문자 묶음(격자 구역 "AB" 등) → 음성부호
    t = re.sub(r"(?<![A-Za-z])[A-Z]{1,4}(?![A-Za-z])", lambda m: " ".join(_PHONETIC[c] for c in m[0]), t)
    # 읽지 않는 기호 정리
    t = t.replace("/", " ").replace("~", " 에서 ").replace("--", ", ")
    t = re.sub(r"[\"'()\[\]{}<>*#_|]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def _num(s: str) -> str:
    if "." in s:
        a, b = s.split(".", 1)
        return sino(int(a)) + " 점 " + " ".join(_SINO[int(c)] for c in b)
    return sino(int(s))


def split_sentences(text: str, max_len: int = 60) -> list[str]:
    """스트리밍 합성용 문장 분리. 긴 문장은 쉼표에서 한 번 더 자른다."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?。])\s+|\n+", text) if p.strip()]
    out: list[str] = []
    for p in parts:
        while len(p) > max_len and "," in p[:max_len]:
            cut = p.rfind(",", 0, max_len) + 1
            out.append(p[:cut].strip())
            p = p[cut:].strip()
        out.append(p)
    return out
