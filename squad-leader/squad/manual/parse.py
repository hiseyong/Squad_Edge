"""교범 PDF → 원본 문단(Paragraph) 목록. 규칙 기반, 글꼴·위치·번호 체계를 이용한다.

판별 규칙 (TC 계열 교범 + 이 번역본의 글꼴 기준. 다른 교범은 PATTERNS/글꼴 기준만 바꾸면 된다)
- 쪽 머리글(y < 50)·바닥글(y > 735): 바닥글에서 교범 쪽번호("3-21")만 읽고 버린다.
- "제N장 ..." = 장, "제N절 ..." = 절, "제N부" = 부(무시)
- 굵은 글꼴 + 짧은 줄 + 번호로 시작하지 않음 = 제목 (크기로 단계 구분)
- "경고/주의/위험" 단독 줄 = 상자 시작. 이어지는 고딕(상자 글꼴) 블록 = 상자 내용
- "위험 ..."처럼 라벨이 본문과 한 줄이면 그 자체가 상자
- "N-N. " = 번호 문단 시작. 번호 없는 본문 블록 = 앞 문단에 이어 붙임(목록·쪽 넘김)
- "그림 N-N." = 그림 설명, "표 N-N." = 표 제목 + 이어지는 고딕 블록 = 표 행
- "참고:" = 참고
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from .schema import Kind, Paragraph, Source

DOC = "TC 3-21.75"
RE_CHAPTER = re.compile(r"^제\s*(\d+)\s*장\s*(.*)")
RE_SECTION = re.compile(r"^제\s*(\d+)\s*절\s*(.*)")
RE_PART = re.compile(r"^제\s*\d+\s*부$")
RE_PARA = re.compile(r"^(\d+-\d+)\.\s*(.*)", re.S)
RE_FIG = re.compile(r"^그림\s*(\d+-\d+)\.?\s*(.*)")
RE_TAB = re.compile(r"^표\s*(\d+-\d+)\.?\s*(.*)")
RE_PAGE_LABEL = re.compile(r"(?<![\d-])(\d{1,2}-\d{1,3})(?![\d-])")
BOX_LABELS = {"경고": "warning", "주의": "caution", "위험": "danger"}
# 다음 줄이 이것으로 시작하면 앞 줄과 붙인다(줄바꿈이 단어 중간에서 일어난 경우)
# (단어 첫머리에 올 수 없는 조사·어미만. "한다" 같은 낱말은 "되어야 한다"처럼 띄어 쓰는 경우가 있어 제외)
JOIN_HEADS = re.compile(r"^(다[.,]|다$|고 |고,|는 |는$|을 |를 |에 |의 |로 |으로 |만 |만$|며 |면 |서 |니다|"
                        r"지 |게 |기 |요[.,]|[.,)」』])")


@dataclass
class Block:
    text: str
    lines: list[str]
    x0: float
    y0: float
    size: float
    bold: bool
    sans: bool
    pdf_page: int


def _clean(s: str) -> str:
    return s.replace("\xa0", " ").replace(" ", " ").replace(" ", " ")


RE_WORD_EDGE = re.compile(r"^[^가-힣A-Za-z0-9]+|[^가-힣A-Za-z0-9]+$")


class Spacer:
    """줄바꿈 지점을 붙일지 띄울지 판정. 한국어는 음절 사이 어디서나 줄이 바뀌므로 (예: "엄 / 폐물이"),
    같은 문서의 줄 *안쪽* 띄어쓰기(줄바꿈과 무관하므로 믿을 수 있음)에서 배운 통계로 정한다.
      1) 조사·어미로 시작(JOIN_HEADS) → 붙임
      2) 어절 사전: 붙인 말만 문서에 있으면 붙임, 따로 쓴 두 말만 있으면 띄움
      3) 조각 통계: 앞 조각이 어절 끝에 오는 비율 × 뒤 조각이 어절 처음에 오는 비율
         (예: "대한"은 대개 어절 끝 → 띄움, "왔"은 늘 뒤에 글자가 이어짐 → 붙임, "거나"는 어절 처음에 안 옴)
      4) 음절 쌍 (앞 줄 끝 글자, 다음 줄 첫 글자)이 붙어 나온 횟수 vs 띄어 나온 횟수
      3)·4)는 로그 오즈로 합산한다."""

    def __init__(self, lines: list[str] = ()):
        self.words: dict[str, int] = {}
        self.pair: dict[tuple[str, str], list[int]] = {}    # (x, y) → [붙음, 띄움]
        self.uni: dict[str, list[int]] = {}                 # 음절 → [어절 끝, 어절 처음, 전체]
        self.sub: dict[str, list[int]] = {}                 # 어절 속 조각 → [전체, 어절 끝, 어절 처음]
        for l in lines:
            # 줄의 첫·끝 어절은 줄바꿈에 잘린 조각일 수 있어 사전·음절 통계에서 뺀다
            ws = [w for w in (self._core(w) for w in _clean(l).split()[1:-1]) if w]
            for w in ws:
                self.words[w] = self.words.get(w, 0) + 1
            for w in (w for w in _clean(l).split()[1:-1] if re.search("[가-힣]", w)):
                for a, b in zip(w, w[1:]):
                    if "가" <= a <= "힣" and "가" <= b <= "힣":
                        self.pair.setdefault((a, b), [0, 0])[0] += 1
            toks = _clean(l).split()
            for w1, w2 in zip(toks, toks[1:]):
                if "가" <= w1[-1] <= "힣" and "가" <= w2[0] <= "힣":
                    self.pair.setdefault((w1[-1], w2[0]), [0, 0])[1] += 1
            for w in ws:
                h = [c for c in w if "가" <= c <= "힣"]
                for i, c in enumerate(h):
                    u = self.uni.setdefault(c, [0, 0, 0])
                    u[2] += 1
                    u[0] += i == len(h) - 1
                    u[1] += i == 0
                for i in range(len(w)):
                    for j in range(i + 1, min(len(w), i + 6) + 1):
                        c = self.sub.setdefault(w[i:j], [0, 0, 0])
                        c[0] += 1
                        c[1] += j == len(w)
                        c[2] += i == 0

    @staticmethod
    def _core(w: str) -> str:
        return RE_WORD_EDGE.sub("", w)

    def join(self, left: str, right: str) -> bool:
        """left 끝과 right 처음 사이를 붙이면 True."""
        if not (re.search(r"[가-힣]$", left) and re.match(r"^[가-힣]", right)):
            return False
        if JOIN_HEADS.match(right):
            return True
        a, b = self._core(left.split()[-1]), self._core(right.split()[0])
        has = lambda w: w in self.words
        if has(a + b) != (has(a) and has(b)):
            return has(a + b)
        # 남은 근거를 로그 오즈로 합산 (양수 = 붙임). 근거가 없는 쪽은 0
        score = 0.0
        ea = next((c for k in range(min(len(a), 6), 0, -1) if (c := self.sub.get(a[-k:])) and c[0] >= 3), None)
        sb = next((c for k in range(min(len(b), 6), 0, -1) if (c := self.sub.get(b[:k])) and c[0] >= 3), None)
        if ea:
            score += math.log((ea[0] - ea[1] + .5) / (ea[1] + .5))     # 앞 조각 뒤에 글자가 더 이어진 횟수 vs 끝난 횟수
        if sb:
            score += math.log((sb[0] - sb[2] + .5) / (sb[2] + .5))     # 뒤 조각 앞에 글자가 있던 횟수 vs 처음이던 횟수
        j, sp = self.pair.get((left[-1], right[0]), [0, 0])
        score += math.log((j + .5) / (sp + .5))
        return score > SPACE_BIAS


SPACE_BIAS = 1.0   # 근거가 약하면 띄운다 (잘못 붙이면 낱말 검색이 깨지므로)
_NO_STATS = Spacer()


def join_lines(lines: list[str], spacer: Spacer = _NO_STATS) -> str:
    """PDF 줄들을 문장으로. 목록 항목(•, --, 1.)은 줄바꿈 유지, 그 밖은 이어 붙인다."""
    out = ""
    for raw in lines:
        l = re.sub(r"\s+", " ", _clean(raw)).strip()
        if not l:
            continue
        if not out:
            out = l
        elif re.match(r"^(•|--|\d+\.\s)", l):
            out += "\n" + l
        else:
            out += ("" if spacer.join(out, l) else " ") + l
    return out


def _split_block(lines: list[dict]) -> list[list[dict]]:
    """PDF 추출기가 붙여 버린 블록을 줄 단위로 다시 나눈다: 글꼴(굵기·크기·계열)이 바뀌거나
    줄 간격이 문단 간격만큼 벌어지면 새 블록. (예: 문단 끝 줄 + 다음 제목 줄이 한 블록으로 묶인 경우)"""
    def sig(l):
        sp = [s for s in l["spans"] if s["text"].strip()]
        if not sp:
            return None
        m = max(sp, key=lambda s: len(s["text"]))
        return ("Bold" in m["font"], "Gothic" in m["font"] or "Arial" in m["font"], round(m["size"]))
    out: list[list[dict]] = []
    prev = None
    for l in lines:
        sg = sig(l)
        if sg is None:
            continue
        if prev is not None and out:
            gap = l["bbox"][1] - prev["bbox"][3]
            if sg != sig(prev) or gap > 0.35 * (prev["bbox"][3] - prev["bbox"][1]):
                out.append([])
        if not out:
            out.append([])
        out[-1].append(l)
        prev = l
    return out


def read_blocks(pdf: Path) -> tuple[list[tuple[list[Block], str, str]], Spacer]:
    """쪽마다 (본문 블록들, 교범 쪽번호, 쪽 머리글) + 문서에서 배운 띄어쓰기 판정기."""
    doc = pymupdf.open(pdf)
    spacer = Spacer(l for page in doc for l in page.get_text("text").split("\n"))
    pages = []
    for pi, page in enumerate(doc):
        h = page.rect.height
        blocks, label, header = [], "", ""
        for b in page.get_text("dict")["blocks"]:
            if b["type"] != 0:
                continue
            for seg in _split_block(b["lines"]):
                lines = ["".join(s["text"] for s in l["spans"]) for l in seg]
                spans = [s for l in seg for s in l["spans"] if s["text"].strip()]
                if not spans:
                    continue
                x0 = min(l["bbox"][0] for l in seg)
                y0 = min(l["bbox"][1] for l in seg)
                if y0 > h - 57:
                    m = RE_PAGE_LABEL.findall(" ".join(lines).replace(DOC, " "))
                    label = m[-1] if m else label
                    continue
                if y0 < 50:
                    header = _clean(" ".join(lines)).strip()
                    continue
                main = max(spans, key=lambda s: len(s["text"]))
                blocks.append(Block(text=join_lines(lines, spacer), lines=lines, x0=x0, y0=y0,
                                    size=round(main["size"], 1), bold="Bold" in main["font"],
                                    sans="Gothic" in main["font"] or "Arial" in main["font"], pdf_page=pi + 1))
        pages.append((blocks, label, header))
    return pages, spacer


def parse(pdf: Path) -> list[Paragraph]:
    paras: list[Paragraph] = []
    chapter = section = ""
    chap_no = ""
    headings: list[tuple[float, str]] = []      # (글꼴 크기, 제목)
    cur: Paragraph | None = None                # 이어 붙일 대상
    mode = ""                                   # "", "box", "table"
    counters: dict[str, int] = {}
    pending: list[str] = []                     # 그림 내부 글자

    def new(kind: Kind, pid: str, text: str, src: Source, label: str = "") -> Paragraph:
        p = Paragraph(id=pid, kind=kind, chapter=chapter, section=section,
                      headings=[t for _, t in headings], text=text, source=src, label=label, order=len(paras))
        paras.append(p)
        return p

    def synth_id(base: str) -> str:
        counters[base] = counters.get(base, 0) + 1
        return f"{base}{counters[base]}"

    chap_titles: dict[str, str] = {}

    def flush_pending():
        target = cur if cur is not None and cur.kind in (Kind.PARA, Kind.INTRO) else next(
            (p for p in reversed(paras) if p.kind in (Kind.PARA, Kind.INTRO)), None)
        if pending and target is not None:
            target.text = (target.text + "\n" + "\n".join(pending)).strip()
        pending.clear()

    def set_chapter(no: str, title: str = "", keep: bool = False):
        nonlocal chap_no, chapter, section, headings, cur, mode
        if title:
            chap_titles[no] = title
        if no != chap_no:
            chap_no = no
            if not keep:        # 같은 쪽에서 문단 번호로 장이 바뀐 경우엔 이미 읽은 절·제목을 유지
                section, headings, cur, mode = "", [], None, ""
        chapter = f"제{no}장 {chap_titles.get(no, '')}".strip()

    pending_title = ""
    pages, spacer = read_blocks(pdf)
    for blocks, label, header in pages:
        page_start = len(paras)
        if m := re.match(r"^제\s*(\d+)\s*장$", header):
            set_chapter(m[1])
        elif header and chap_no:
            title = header.strip("'\"")
            if chap_no not in chap_titles:
                chap_titles[chap_no] = title
            elif chap_titles[chap_no] != title:
                pending_title = title      # 새 장의 첫 쪽일 수 있음 → 번호 문단을 보고 확정
        for b in blocks:
            src = Source(DOC, label, b.pdf_page)
            t = b.text.strip()
            if RE_PART.match(t) or (t == "병사 전투기술" and b.size >= 14):
                continue
            if m := RE_CHAPTER.match(t):
                if b.size >= 13 or b.bold:
                    flush_pending()
                    set_chapter(m[1], m[2].strip("'\" "))
                    continue
            if (m := RE_SECTION.match(t)) and b.bold:
                flush_pending()
                section, headings, cur, mode = t, [], None, ""
                continue
            if t in BOX_LABELS or t in ("경고들",):
                cur = new(Kind.BOX, synth_id(f"{last_para_id(paras, chap_no)}.box"), "", src,
                          label=t if t in BOX_LABELS else "경고")
                mode = "box"
                continue
            if m := re.match(r"^(위험|경고|주의) (.+)", t, re.S):
                if b.sans and b.bold:
                    cur = new(Kind.BOX, synth_id(f"{last_para_id(paras, chap_no)}.box"), m[2], src, label=m[1])
                    mode = "box"
                    continue
            if mode == "box" and b.sans and cur is not None:
                cur.text = (cur.text + "\n" + t).strip()
                continue
            if m := RE_FIG.match(t):
                new(Kind.FIGURE, f"그림{m[1]}", "\n".join(pending), src, label=t)
                pending.clear()
                mode = ""
                continue
            if m := RE_TAB.match(t):
                cur = new(Kind.TABLE, f"표{m[1]}", "", src, label=t)
                mode = "table"
                continue
            if mode == "table" and b.sans and cur is not None:
                cur.text = (cur.text + "\n" + t).strip()
                continue
            # 그림 안의 글자(상자·표 밖의 고딕 블록): 모아 두었다가 뒤따르는 그림 설명에 붙인다
            if b.sans and not mode and not RE_PARA.match(t):
                pending.append(t)
                continue
            if t.startswith("참고:"):
                new(Kind.NOTE, synth_id(f"{last_para_id(paras, chap_no)}.note"), t[3:].strip(), src)
                mode = ""
                continue
            # 제목: 왼쪽 여백에서 시작(목록은 들여씀) + 짧고 문장 끝이 아님 + (굵거나 매우 짧음)
            if (b.x0 < 100 and not b.sans and len(t) <= 40 and "\n" not in t and not RE_PARA.match(t)
                    and not t.endswith((".", "다", ":")) and (b.bold or len(t) <= 25)):
                flush_pending()
                t = t.rstrip("-").strip()
                headings = [(sz, h) for sz, h in headings if sz > b.size] + [(b.size, t)]
                cur, mode = None, ""
                continue
            mode = ""
            if m := RE_PARA.match(t):
                flush_pending()
                no = m[1].split("-")[0]
                if no != chap_no:          # 문단 번호가 장의 기준: 이 쪽에서 만든 항목까지 소급 수정
                    old = chap_no
                    set_chapter(no, pending_title, keep=True)
                    for q in paras[page_start:]:
                        q.chapter = chapter
                        if q.id.startswith(f"{old}."):
                            q.id = f"{no}." + q.id[len(old) + 1:]
                    pending_title = ""
                cur = new(Kind.PARA, m[1], m[2].strip(), src)
                continue
            # 번호 없는 본문: 앞 문단에 이어 붙이거나(목록·쪽 넘김) 도입문
            if cur is not None and cur.kind in (Kind.PARA, Kind.INTRO):
                sep = "\n" if re.match(r"^(•|--|\d+\.\s|\*\*|[가-힣]+--)", t) else (
                    "" if spacer.join(cur.text, t) else " ")
                cur.text = (cur.text + sep + t).strip()
            else:
                base = f"{chap_no}.intro" if not headings else f"{chap_no}.{headings[-1][1]}"
                cur = new(Kind.INTRO, synth_id(base), t, src)
        flush_pending()   # 쪽 끝까지 그림 설명이 안 나왔으면 본문(예: 거리 측정 요인 표)이다
    for q in paras:       # 장 제목은 뒤쪽 머리글에서 알게 되는 경우가 있어 마지막에 채운다
        if m := re.match(r"^제(\d+)장", q.chapter):
            q.chapter = f"제{m[1]}장 {chap_titles.get(m[1], '')}".strip()
    return paras


def last_para_id(paras: list[Paragraph], chap_no: str) -> str:
    for p in reversed(paras):
        if p.kind == Kind.PARA:
            return p.id
    return f"{chap_no}.0"
