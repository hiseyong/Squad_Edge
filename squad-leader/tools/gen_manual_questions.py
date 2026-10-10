"""[보드, 사전 1회] 교범 문단마다 예상 질문을 로컬 LLM으로 생성 → data/manual_kb/questions.jsonl

    .venv/bin/python tools/gen_manual_questions.py [--model models/llm/...gguf] [--limit N]

이미 생성한 문단은 건너뛴다 (중간에 끊어도 이어서). 런타임에는 LLM이 필요 없다.
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from squad.manual.llm import MODEL, LocalLLM  # noqa: E402
from squad.manual.schema import Kind, load_kb  # noqa: E402

OUT = ROOT / "data" / "manual_kb" / "questions.jsonl"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default=str(MODEL))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    out = Path(a.out)
    paras, _, _ = load_kb(ROOT / "data" / "manual_kb")
    done = {json.loads(l)["id"] for l in out.open(encoding="utf-8")} if out.exists() else set()
    todo = [p for p in paras if p.text and len(p.text) >= 30 and p.kind != Kind.FIGURE and p.id not in done]
    if a.limit:
        todo = todo[:a.limit]
    print(f"생성할 문단 {len(todo)}개 (완료 {len(done)}개)")
    llm = LocalLLM(Path(a.model))
    t0 = time.time()
    with out.open("a", encoding="utf-8") as f:
        for i, p in enumerate(todo, 1):
            qs = llm.questions(" > ".join(p.headings) or p.chapter, p.text)
            f.write(json.dumps({"id": p.id, "q": qs}, ensure_ascii=False) + "\n")
            f.flush()
            el = time.time() - t0
            print(f"[{i}/{len(todo)}] {p.id} ({el / i:.0f}s/문단, 남은 {el / i * (len(todo) - i) / 60:.0f}분) {qs[:2]}",
                  flush=True)
    llm.close()


if __name__ == "__main__":
    main()
