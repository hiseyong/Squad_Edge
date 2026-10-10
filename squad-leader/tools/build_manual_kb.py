"""교범 PDF → 지식 모델(JSONL 3종) 생성.

    .venv/bin/python tools/build_manual_kb.py [manuals/TC3-21.75_발췌번역_비공식.pdf] [data/manual_kb]
"""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from squad.manual.parse import parse  # noqa: E402
from squad.manual.schema import save_jsonl  # noqa: E402
from squad.manual.units import build_units  # noqa: E402

pdf = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "manuals" / "TC3-21.75_발췌번역_비공식.pdf"
out = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "data" / "manual_kb"
out.mkdir(parents=True, exist_ok=True)
paras = parse(pdf)
units, rels = build_units(paras)
save_jsonl(out / "paragraphs.jsonl", paras)
save_jsonl(out / "units.jsonl", units)
save_jsonl(out / "relations.jsonl", rels)
print(f"문단 {len(paras)}  {dict(Counter(p.kind.value for p in paras))}")
print(f"단위 {len(units)}  {dict(Counter(u.type.value for u in units))}")
print(f"관계 {len(rels)}  {dict(Counter(r.type.value for r in rels))}")
print(f"→ {out}")
