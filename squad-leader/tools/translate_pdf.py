"""원본 PDF 디자인을 유지한 채 텍스트 블록만 번역문으로 교체.

    .venv/bin/python tools/translate_pdf.py manuals/src/tc3_21_75.pdf "manuals/src/ko_*.txt" out.pdf

번역 파일 형식: "@<원본 PDF 페이지 인덱스>-<블록 번호>" 줄 다음에 번역문(여러 줄 가능, 줄바꿈 유지).
번역이 없는 블록(쪽번호·날짜 등)은 원문 그대로 둔다. 그림·선·표 테두리는 건드리지 않는다.
페이지는 번역 파일에 나온 페이지만, 원본 순서대로 뽑는다.
"""
import glob
import html
import re
import sys
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = ROOT / "manuals" / "fonts"

CSS = """
@font-face { font-family: ko-serif; src: url(NanumMyeongjo-Regular.ttf); }
@font-face { font-family: ko-serif; src: url(NanumMyeongjo-Bold.ttf); font-weight: bold; }
@font-face { font-family: ko-sans; src: url(NanumGothic-Regular.ttf); }
@font-face { font-family: ko-sans; src: url(NanumGothic-Bold.ttf); font-weight: bold; }
* { margin: 0; padding: 0; }
"""


def load_translations(pattern: str) -> dict[str, str]:
    tr: dict[str, str] = {}
    for path in sorted(glob.glob(pattern)):
        key, buf = None, []
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            m = re.match(r"^@(\d+-\d+)\s*$", line)
            if m:
                if key:
                    tr[key] = "\n".join(buf).strip()
                key, buf = m.group(1), []
            elif key:
                buf.append(line)
        if key:
            tr[key] = "\n".join(buf).strip()
    return tr


def text_rect(block: dict) -> pymupdf.Rect:
    """빈 줄(공백만 있는 span)을 뺀 실제 글자 영역."""
    r = pymupdf.Rect()
    for l in block["lines"]:
        if "".join(sp["text"] for sp in l["spans"]).strip():
            r |= pymupdf.Rect(l["bbox"])
    return r if not r.is_empty else pymupdf.Rect(block["bbox"])


def block_style(block: dict) -> dict:
    spans = [s for l in block["lines"] for s in l["spans"] if s["text"].strip()]
    s = max(spans, key=lambda s: len(s["text"])) if spans else block["lines"][0]["spans"][0]
    font = s["font"]
    return {
        "size": s["size"],
        "bold": "Bold" in font or bool(s["flags"] & 16),
        "sans": "Arial" in font or "Helvetica" in font,
        "color": "#%06x" % s["color"],
    }


def align_of(block: dict, page: pymupdf.Page, text: str, cover: bool = False) -> str:
    """원문 블록의 정렬을 추정. 가운데: 모든 줄의 중심이 본문 중심과 같음. 오른쪽: 오른쪽 끝에 붙은 한 줄짜리(쪽 머리글)."""
    lines = [pymupdf.Rect(l["bbox"]) for l in block["lines"]
             if "".join(sp["text"] for sp in l["spans"]).strip()]
    if not lines:
        return "left"
    mid = page.rect.width / 2
    col_w = page.rect.width - 2 * 72
    centered = all(abs((r.x0 + r.x1) / 2 - mid) < 8 for r in lines) and lines[0].x0 > 90
    short = len(lines) >= 2 or lines[0].width < 0.65 * col_w
    if centered and short and "...." not in text:
        return "center"
    if len(lines) == 1 and lines[0].x0 > mid and page.rect.width - 72 - lines[0].x1 < 6:
        return "right"
    if cover:  # 표지는 제목·날짜·발행처 모두 가운데 정렬
        return "center"
    return "justify" if len(text) > 120 and "\n" not in text else "left"


def html_for(text: str, st: dict, align: str) -> str:
    lines = []
    for l in text.split("\n"):
        e = html.escape(l)
        e = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", e)                  # 본문 속 굵은 제목(run-in head)
        m = re.match(r"^(\d+-\d+\.) (.*)", e)
        if m:                                                              # 문단 번호 뒤 간격
            lines.append(f"<div>{m.group(1)}&#8195;&#8194;{m.group(2)}</div>")
        elif e.startswith("-- "):                                          # 하위 항목: 들여쓰기 + 내어쓰기
            lines.append(f'<div style="padding-left:3em; text-indent:-1.2em;">{e}</div>')
        elif re.match(r"^(• |\d+\. )", e):                                 # 글머리·번호 항목: 내어쓰기
            lines.append(f'<div style="padding-left:1em; text-indent:-1em;">{e}</div>')
        else:
            lines.append(f"<div>{e}</div>")
    body = "".join(lines)
    fam = "ko-sans" if st["sans"] else "ko-serif"
    weight = "bold" if st["bold"] else "normal"
    return (f'<div style="font-family:{fam}; font-size:{st["size"]:.1f}pt; font-weight:{weight}; '
            f'color:{st["color"]}; line-height:1.25; text-align:{align};">{body}</div>')


def column_starts(block: dict) -> list[float]:
    """블록 안 표 열의 시작 x 좌표들 (줄 첫 span, 또는 앞 span과 8pt 이상 떨어진 span)."""
    xs = []
    for l in block["lines"]:
        prev_x1 = None
        for sp in l["spans"]:
            if not sp["text"].strip():
                continue
            if prev_x1 is None or sp["bbox"][0] - prev_x1 > 8:
                xs.append(sp["bbox"][0])
            prev_x1 = sp["bbox"][2]
    cols: list[float] = []
    for x in sorted(xs):
        if not cols or x - cols[-1] > 8:
            cols.append(x)
    return cols


def rules_of(page: pymupdf.Page) -> tuple[list, list]:
    """페이지에 그려진 세로선/가로선 (표 테두리, 상자). (x, y0, y1) / (y, x0, x1)."""
    vert, horiz = [], []
    for d in page.get_drawings():
        for it in d["items"]:
            if it[0] == "l":
                p1, p2 = it[1], it[2]
                if abs(p1.x - p2.x) < 1.5 and abs(p1.y - p2.y) > 5:
                    vert.append((p1.x, min(p1.y, p2.y), max(p1.y, p2.y)))
                elif abs(p1.y - p2.y) < 1.5 and abs(p1.x - p2.x) > 5:
                    horiz.append((p1.y, min(p1.x, p2.x), max(p1.x, p2.x)))
            elif it[0] == "re":
                r = it[1]
                if r.width <= 4.5 and r.height > 5:
                    vert.append((r.x0, r.y0, r.y1))
                elif r.height <= 4.5 and r.width > 5:
                    horiz.append((r.y0, r.x0, r.x1))
                elif r.width > 5 and r.height > 5:
                    vert += [(r.x0, r.y0, r.y1), (r.x1, r.y0, r.y1)]
                    horiz += [(r.y0, r.x0, r.x1), (r.y1, r.x0, r.x1)]
    return vert, horiz


RULES: tuple[list, list] = ([], [])


def expanded_rect(rect: pymupdf.Rect, others: list[pymupdf.Rect], page: pymupdf.Page,
                  align: str = "left") -> pymupdf.Rect:
    """한글이 넘칠 수 있으니 빈 공간까지 넓힌다: 아래로는 다음 블록 직전(본문 하단까지),
    옆으로는 같은 높이에 다른 블록이 없으면 본문 오른쪽 여백까지."""
    bottom = page.rect.height - 50
    for o in others:
        if o.y0 >= rect.y1 - 1 and o.x0 < rect.x1 and o.x1 > rect.x0:
            bottom = min(bottom, o.y0 - 2)
    right = page.rect.width - 60
    left = 60.0
    for o in others:
        if o.y0 < rect.y1 and o.y1 > rect.y0:  # 같은 높이
            if o.x0 >= rect.x1 - 1:
                right = min(right, o.x0 - 4)
            elif o.x1 <= rect.x0 + 1:
                left = max(left, o.x1 + 4)
    vert, horiz = RULES
    for x, y0, y1 in vert:  # 표 테두리·상자 선을 넘지 않게
        if y0 < rect.y1 and y1 > rect.y0:
            if x >= rect.x1 - 1:
                right = min(right, x - 3)
            elif x <= rect.x0 + 1:
                left = max(left, x + 3)
    for y, x0_, x1_ in horiz:
        if y >= rect.y1 - 1 and x0_ < rect.x1 and x1_ > rect.x0:
            bottom = min(bottom, y - 1)
    x0, x1 = rect.x0, max(rect.x1 + 1, right)
    if align == "center":
        grow = min(rect.x0 - left, right - rect.x1)
        x0, x1 = rect.x0 - max(grow, 0), rect.x1 + max(grow, 0)
    elif align == "right":
        x0, x1 = min(rect.x0, left), rect.x1 + 1
    return pymupdf.Rect(x0, rect.y0 - 2, x1, max(rect.y1, bottom))


def main():
    src_path, pattern, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    tr = load_translations(pattern)
    pages = sorted({int(k.split("-")[0]) for k in tr})
    src = pymupdf.open(src_path)
    out = pymupdf.open()
    for pn in pages:
        out.insert_pdf(src, from_page=pn, to_page=pn)
    archive = pymupdf.Archive(str(FONT_DIR))
    missing = []
    for i, pn in enumerate(pages):
        page = out[i]
        blocks = [b for b in page.get_text("dict")["blocks"] if b["type"] == 0]
        index = {f"{pn}-{bi}": b for bi, b in enumerate(page.get_text("dict")["blocks"])}
        jobs = []
        for key, b in index.items():
            if b["type"] != 0 or key not in tr:
                if b["type"] == 0 and key not in tr:
                    t = "".join(s["text"] for l in b["lines"] for s in l["spans"]).strip()
                    if re.search(r"[A-Za-z]{4,}", t) and not re.search(r"TC 3-21\.75", t):
                        missing.append((key, t[:60]))
                continue
            jobs.append((key, text_rect(b), block_style(b)))
        rects = [pymupdf.Rect(b["bbox"]) for b in blocks]
        global RULES
        RULES = rules_of(page)
        for key, r, _ in jobs:
            page.add_redact_annot(r, fill=False)
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE,
                              graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                              text=pymupdf.PDF_REDACT_TEXT_REMOVE)
        for key, r, st in jobs:
            text = tr[key]
            align = align_of(index[key], page, text, cover=(pn == 0))
            box = expanded_rect(r, [o for o in rects if o != r], page, align)
            if "¶" in text:  # 줄 단위 배치: 원문의 비어 있지 않은 줄마다 한 조각 ("^"로 시작하면 가운데 정렬)
                lines = [l for l in index[key]["lines"] if "".join(sp["text"] for sp in l["spans"]).strip()]
                lrs = [pymupdf.Rect(l["bbox"]) for l in lines]
                for seg, lr in zip(text.split("¶"), lrs):
                    seg = seg.strip()
                    if not seg:
                        continue
                    if seg.startswith("^"):
                        sub = pymupdf.Rect(lr.x0 - 12, lr.y0 - 2, lr.x1 + 12, lr.y1 + 4)
                        seg_align = "center"
                        seg = seg[1:]
                    else:
                        nxt = [o.x0 for o in lrs if abs(o.y0 - lr.y0) < 3 and o.x0 > lr.x0 + 1]
                        x1 = min(nxt) - 3 if nxt else page.rect.width - 60
                        sub = pymupdf.Rect(lr.x0, lr.y0 - 2, x1, lr.y1 + 4)
                        seg_align = "left"
                    page.insert_htmlbox(sub, html_for(seg, st, seg_align), css=CSS, archive=archive, scale_low=0)
                continue
            if "¦" in text:  # 표 행: 열마다 원래 열 위치에 배치
                segs = text.split("¦")
                cols = column_starts(index[key])
                if len(cols) < len(segs):
                    print(f"  ! {key}: 열 {len(cols)}개인데 번역 칸 {len(segs)}개")
                    cols = [r.x0 + r.width * k / len(segs) for k in range(len(segs))]
                for k, seg in enumerate(segs):
                    x1 = cols[k + 1] - 4 if k + 1 < len(segs) else box.x1
                    sub = pymupdf.Rect(cols[k], box.y0, x1, box.y1)
                    spare, scale = page.insert_htmlbox(sub, html_for(seg.strip(), st, "left"),
                                                       css=CSS, archive=archive, scale_low=0)
                continue
            spare, scale = page.insert_htmlbox(box, html_for(text, st, align),
                                               css=CSS, archive=archive, scale_low=0)
            if spare < 0:
                print(f"  ! {key}: 넣지 못함")
            elif scale < 0.85:
                print(f"  · {key}: {scale:.2f}배로 축소됨")
    out.set_metadata({"title": "전사정신과 병사 전투기술 (TC 3-21.75 비공식 발췌 번역)",
                      "author": "Headquarters, Department of the Army (원문) / 비공식 번역",
                      "subject": "시연용 비공식 번역본. 대한민국 국군 공식 교범 아님."})
    out.save(out_path, garbage=4, deflate=True)
    print(f"{out_path}: {len(pages)}쪽")
    if missing:
        print(f"번역 없는 영문 블록 {len(missing)}개:")
        for k, t in missing:
            print(f"  {k}: {t}")


if __name__ == "__main__":
    main()
