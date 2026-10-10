"""띄어쓰기 복원: 스트리밍 STT(Zipformer)는 "쇼크환자한테물줘도돼"처럼 붙여서 낸다.

사전 기반 동적계획법으로 '어간 + 조사·어미*' 단위로 나눈다 (형태소 분석기 없이, 오프라인, 수 ms).
  어간 사전 = 군 용어 + 교범 어휘(지식 데이터에서 추출) + 질문에 흔한 말
  조사·어미 = 교범 검색과 같은 목록 (squad.manual.search._SUFFIXES)
  수사+단위("삼백미터", "두시", "열한시")와 한 자리씩 읽은 숫자("삼이구구육육")는 따로 묶어서
  normalize()가 숫자로 바꿀 수 있게 띄운다.
점수: 긴 어간일수록 크게, 조사·어미는 어간 뒤에만, 사전에 없는 글자는 감점(앞말에 붙임).
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MAX_STEM = 8
STEM1 = 1.5
# 띄어 써야 하는 한 글자 낱말 (위치·시간 명사, 대명사, 신체·사물). 그 밖의 한 글자는 앞말에 붙인다
ONE_SYLLABLE = set("뒤 앞 위 옆 안 밖 속 밑 전 후 중 때 곳 나 너 저 몇 폭 물 피 팔 목 손 발 눈 입 적 몸 밤 낮 땅 길 차 총 탄 줄 끝 옷 등 수".split())

_NATIVE_NUM = sorted(["한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉", "열", "스무", "스물"]
                     + [f"열{w}" for w in ("한", "두", "세", "네", "다섯", "여섯", "일곱", "여덟", "아홉")]
                     + [f"스물{w}" for w in ("한", "두", "세", "네")], key=len, reverse=True)
_UNITS = sorted("킬로미터 킬로 미터 시 분 초 명 발 대 번 개 도 호 분대 소대 중대 곳 군데".split(), key=len, reverse=True)
_RE_SINO_NUM = re.compile(r"[일이삼사오육칠팔구]?(?:[일이삼사오육칠팔구]?[천백십])+[일이삼사오육칠팔구]?|[일이삼사오육칠팔구]")
_RE_DIGITS = re.compile(r"[영공일이삼사오육칠팔구]{3,}")


class Segmenter:
    def __init__(self, stems, suffixes):
        self.suffixes = sorted({s for s in suffixes if s}, key=len, reverse=True)
        self._suf_set = set(self.suffixes)
        # 조사·어미는 어간으로 쓰지 않는다 ("위협으로부터" → "위협으로 부터" 방지). 한 글자 낱말은 명시 목록만
        self.stems = {s for s in stems if s and re.fullmatch(r"[가-힣]+", s) and len(s) <= MAX_STEM
                      and s not in self._suf_set and len(s) >= 2} | ONE_SYLLABLE

    def _numeral(self, w: str, i: int) -> int:
        """i에서 시작하는 '수사+단위' 길이 (없으면 0)."""
        best = 0
        heads = [n for n in _NATIVE_NUM if w.startswith(n, i)]
        m = _RE_SINO_NUM.match(w, i)
        if m:
            heads.append(m.group(0))
        for h in heads:
            j = i + len(h)
            u = next((u for u in _UNITS if w.startswith(u, j)), None)
            if u is None:
                continue
            # 한 자리 한자어 수사 + 짧은 단위("이번", "구분", "일시")는 낱말일 가능성이 커서 제외
            if (len(h) == 1 and h in "일이삼사오육칠팔구" and len(u) == 1 and u not in "명발"
                    and not (u in "분초" and re.match(r"(후|뒤|전|간|동안|내)", w[j + 1:j + 3]))):
                continue
            best = max(best, len(h) + len(u))
        return best

    def segment_word(self, w: str) -> str:
        n = len(w)
        NEG = -1e9
        # best[i][t]: w[:i]를 마지막 토큰 종류 t로 끝냈을 때 최고 점수. t: 0=시작/어간·숫자, 1=조사·어미, 2=모름
        best = [[NEG] * 3 for _ in range(n + 1)]
        back: list[list[tuple | None]] = [[None] * 3 for _ in range(n + 1)]
        best[0][0] = 0.0
        for i in range(n):
            for t in range(3):
                cur = best[i][t]
                if cur == NEG:
                    continue

                def push(j, nt, sc, kind):
                    if cur + sc > best[j][nt]:
                        best[j][nt] = cur + sc
                        back[j][nt] = (i, t, kind)

                for L in range(1, min(MAX_STEM, n - i) + 1):
                    piece = w[i:i + L]
                    if piece in self.stems:
                        push(i + L, 0, (2.0 * L + 1) if L >= 2 else STEM1, "stem")
                    if i > 0 and t != 2 and piece in self._suf_set:
                        push(i + L, 1, 1.0 * L, "suf")
                if (L := self._numeral(w, i)):
                    push(i + L, 0, 3.0 * L, "num")
                if (m := _RE_DIGITS.match(w, i)) and not any(c in m.group(0) for c in "십백천"):
                    push(i + len(m.group(0)), 0, 2.5 * len(m.group(0)), "digits")
                push(i + 1, 2, -3.0, "unk")
        t = max(range(3), key=lambda k: best[n][k])
        toks = []
        j = n
        while j > 0:
            i, pt, kind = back[j][t]
            toks.append((w[i:j], kind, pt))
            j, t = i, pt
        toks.reverse()
        out = ""
        for k, (piece, kind, prev_t) in enumerate(toks):
            if kind == "digits":
                piece = " ".join(piece)
            after_digits = k and toks[k - 1][1] == "digits"      # "삼 이 구 구 육 육 으로": 마지막 숫자를 조사와 떼야 읽힌다
            sep = " " if k and (kind in ("stem", "num", "digits") or (kind == "unk" and prev_t == 1)
                                or after_digits) else ""
            out += sep + piece
        return out

    def segment(self, text: str, min_len: int = 4) -> str:
        """공백으로 나뉜 각 낱말 중 min_len글자 이상인 한글 덩어리만 다시 띄운다."""
        out = []
        for word in text.split():
            m = re.fullmatch(r"([^가-힣]*)([가-힣]+)([^가-힣]*)", word)
            if m and len(m.group(2)) >= min_len:
                out.append(m.group(1) + self.segment_word(m.group(2)) + m.group(3))
            else:
                out.append(word)
        return " ".join(out)


@lru_cache(maxsize=1)
def default_segmenter() -> Segmenter:
    """군 용어 + 교범 어휘(있으면) + 검색 사전으로 만든 기본 띄어쓰기 복원기."""
    from ..manual.search import _STOP, _SUFFIXES, CONJ, SYNONYMS, _strip
    from .lexicon import all_terms

    stems: set[str] = set()
    for t in all_terms():
        stems.update(t.split())
        stems.add(t.replace(" ", ""))
    stems.update(_STOP)
    stems.update(CONJ)
    stems.update(SYNONYMS)
    stems.update("부상자 환자 위치 병사 의무병 탄약 보급 요청 발생 이동 확인 응답 북쪽 남쪽 동쪽 서쪽 물체 의심 "
                 "줘도 돼 되나 해도 풀어도 감아도 써도 뭐야 뭐가 언제 어떻게 차이".split())
    units = ROOT / "data" / "manual_kb" / "units.jsonl"
    if units.exists():
        for line in units.open(encoding="utf-8"):
            for w in re.findall(r"[가-힣]+", json.loads(line)["text"]):
                s = _strip(w)
                if len(s) >= 2:
                    stems.add(s)
    # 검색용 어미 목록에 들어 있지만 띄어 쓰는 질문어
    question_words = set("어떻게 뭐야 뭐지 하지 있나 있어 없나 되나 하나 하나요 인가요 해야 해야해 해야지 해도 해도돼 해줘".split())
    stems.update(question_words)
    suffixes = [x for x in _SUFFIXES if x not in question_words] + ("랑 이랑 한테 에게 께 요 죠 지 니 냐 까 나요 는데 은데 줘 해 돼 도돼 어도 아도 이야 거야 "
                                  "하라 하여 바람").split()
    return Segmenter(stems, suffixes)
