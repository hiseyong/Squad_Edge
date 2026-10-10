"""STT 결과 텍스트 정규화: 한글 수사 → 숫자, 단위 표기, 음성부호 → 알파벳.

예) "적 세 명 삼백 미터" → "적 3명 300m", "그리드 알파 브라보 일 이 삼 사" → "그리드 AB 1234"

오변환을 줄이려고 보수적으로 동작한다:
- 한자어 수사는 단어 경계에서 시작하고, 자릿수(십/백/천/만)가 있거나 뒤에 단위가 올 때만 변환
  ("사격", "이동", "오른쪽", "구역"은 그대로)
- 숫자 한 자리씩 읽기("일 이 삼 사", "하나 둘")는 2개 이상 연속일 때만
- 고유어 수사("세 명", "두 시")는 단위가 바로 뒤에 올 때만
"""
from __future__ import annotations

import re

_SINO_DIGIT = {"영": 0, "공": 0, "일": 1, "이": 2, "삼": 3, "사": 4, "오": 5,
               "육": 6, "륙": 6, "칠": 7, "팔": 8, "구": 9}
# 군 숫자 호칭(하나·둘·삼·넷·오·여섯·칠·여덟·아홉·공)까지 포함한 한 자리 읽기
_DIGIT_WORD = {**_SINO_DIGIT, "하나": 1, "둘": 2, "셋": 3, "넷": 4, "다섯": 5,
               "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9}
_NATIVE = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7,
           "여덟": 8, "아홉": 9, "열": 10, "스무": 20}
# 열한~열아홉, 스물한~스물네 (24시간제 시각)
for _w, _v in (("한", 1), ("두", 2), ("세", 3), ("네", 4), ("다섯", 5), ("여섯", 6),
               ("일곱", 7), ("여덟", 8), ("아홉", 9)):
    _NATIVE["열" + _w] = 10 + _v
    if _v <= 4:
        _NATIVE["스물" + _w] = 20 + _v

_UNIT_RE = r"(?:킬로미터|킬로|키로|미터|메타|도|분|초|발|명|시|호|번|개|대|소대|분대|중대|km|m)"
# 자릿수 없는 한 자리 한자어 수사 뒤에 와도 되는 단위 ("이번", "사시" 같은 오변환 방지)
_SINGLE_UNITS = ("킬로미터", "킬로", "키로", "미터", "메타", "도", "분", "초", "발", "km", "m")
_NATIVE_UNITS = r"(?:명|시|개|발|대|번|곳|군데|정)"

_PHONETIC = {
    "알파": "A", "알하": "A", "브라보": "B", "찰리": "C", "델타": "D", "에코": "E",
    "폭스트롯": "F", "폭스트로트": "F", "골프": "G", "호텔": "H", "인디아": "I",
    "줄리엣": "J", "킬로": "K", "리마": "L", "마이크": "M", "노벰버": "N", "오스카": "O",
    "파파": "P", "퀘벡": "Q", "로미오": "R", "시에라": "S", "탱고": "T", "유니폼": "U",
    "빅터": "V", "위스키": "W", "엑스레이": "X", "양키": "Y", "줄루": "Z",
}

_HANGUL = "가-힣"
_PARTICLE = r"(?:에서|에|으로|로|의|은|는|을|를|까지|부터|쯤|정도|가|이)"
_SINO_PARSE = re.compile(
    r"^(?:[일이삼사오육칠팔구]?만)?(?:[일이삼사오육칠팔구]?천)?"
    r"(?:[일이삼사오육칠팔구]?백)?(?:[일이삼사오육칠팔구]?십)?[영공일이삼사오육칠팔구]?$")
_PLACE = {"십": 10, "백": 100, "천": 1000}
# 수사+단위처럼 생긴 보통 낱말 (단독으로 쓰였을 때 숫자로 바꾸지 않음)
_WORDS_NOT_NUM = {"구분", "이분", "구도", "이도", "사분"}
# "오분후", "삼분간", "십초뒤": 단위 뒤에 붙어도 숫자인 시간 표현
_AFTER_TIME = r"(?:후|뒤|전|간|동안|내|안에|이내)"


def _parse_sino(run: str) -> int | None:
    """'삼백오십' → 350, '이만오천' → 25000. 자릿수 순서가 틀리면 None ('천천', '이삼')."""
    if not run or not _SINO_PARSE.match(run):
        return None
    result = section = 0
    digit = None
    for c in run:
        if c in _SINO_DIGIT:
            digit = _SINO_DIGIT[c]
        elif c in _PLACE:
            section += (1 if digit is None else digit) * _PLACE[c]
            digit = None
        else:  # 만
            result += (section + (digit or 0) or 1) * 10000
            section, digit = 0, None
    return result + section + (digit or 0)


def _digit_sequences(text: str) -> str:
    """'일 이 삼 사' / '하나 둘' → '1234' / '12' (2개 이상 연속일 때만)."""
    tokens = text.split(" ")
    out, run = [], []

    def flush():
        if len(run) >= 2:
            out.append("".join(str(_DIGIT_WORD[t]) for t in run))
        else:
            out.extend(run)
        run.clear()

    for tok in tokens:
        if tok in _DIGIT_WORD:
            run.append(tok)
        else:
            flush()
            out.append(tok)
    flush()
    return " ".join(out)


def _sino_numbers(text: str) -> str:
    def repl(m: re.Match) -> str:
        run, space = m.group(1), m.group(2)
        rest = text[m.end():]
        value = _parse_sino(run)
        if value is None:
            return m.group(0)
        unit = re.match(_UNIT_RE, rest) is not None
        if any(c in run for c in "십백천만"):
            # 자릿수 단독("십자", "백색")은 단위가 있어야, 뒤에 붙은 한글은 단위/조사일 때만
            if len(run) == 1 and not unit:
                return m.group(0)
            if (not space and re.match(f"[{_HANGUL}]", rest[:1])
                    and not unit and not re.match(_PARTICLE, rest)):
                return m.group(0)
            return f"{value}{space}"
        if len(run) == 1 and rest.startswith(_SINGLE_UNITS):
            # 붙어 있고 단위 뒤에 다시 한글 낱말이 이어지면 낱말("구분해야", "오도가도")이다. 단 "일분대"는 숫자
            unit = next(u for u in _SINGLE_UNITS if rest.startswith(u))
            after = rest[len(unit):]
            if run + unit in _WORDS_NOT_NUM and not re.match(f"[{_HANGUL}]", after[:1]):
                return m.group(0)
            if (not space and re.match(f"[{_HANGUL}]", after[:1]) and not re.match(_PARTICLE, after)
                    and not re.match(_AFTER_TIME, after) and not (unit == "분" and after.startswith("대"))):
                return m.group(0)
            return f"{value}{space}"
        # "이 번 병사", "적 이 명": 띄어 쓴 경우만 ("이번"은 보호)
        if len(run) == 1 and space and re.match(r"(?:번|명|호|소대|중대|대대)", rest):
            return f"{value}{space}"
        return m.group(0)

    return re.sub(rf"(?<![{_HANGUL}])([영공일이삼사오육칠팔구십백천만]+)(\s?)", repl, text)


def _native_numbers(text: str) -> str:
    words = sorted(_NATIVE, key=len, reverse=True)
    pat = re.compile(rf"(?<![{_HANGUL}])({'|'.join(words)})\s?(?={_NATIVE_UNITS})")

    def repl(m: re.Match) -> str:
        word = m.group(1)
        if word == "한" and text[m.end():].startswith("번"):
            return m.group(0)  # '한번 더' 같은 부사
        return str(_NATIVE[word])

    return pat.sub(repl, text)


def _units(text: str) -> str:
    text = re.sub(r"(\d)\s*(?:킬로미터|킬로|키로|km)(?![a-zA-Z])", r"\1km", text)
    text = re.sub(r"(\d)\s*(?:미터|메타|m)(?![a-zA-Z])", r"\1m", text)
    return re.sub(r"(\d)\s+(도|분|초|발|명|시|호|번|개|대)", r"\1\2", text)


def _phonetic(text: str) -> str:
    tokens = text.split(" ")
    out = [_PHONETIC.get(t, t) for t in tokens]
    # 연속된 단일 알파벳은 붙인다: "A B" → "AB"
    merged: list[str] = []
    for tok in out:
        if merged and len(tok) == 1 and tok.isupper() and re.fullmatch(r"[A-Z]+", merged[-1]):
            merged[-1] += tok
        else:
            merged.append(tok)
    return " ".join(merged)


def normalize(text: str) -> str:
    text = re.sub(r"\s+", " ", text.strip())
    text = _digit_sequences(text)
    text = _sino_numbers(text)
    text = _native_numbers(text)
    text = _units(text)
    text = _phonetic(text)
    return text
