"""교범 질의응답 (오프라인, LLM 없음).

    .venv/bin/python tools/ask_manual.py "지혈대 풀어도 돼?"
    .venv/bin/python tools/ask_manual.py            # 대화형
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from squad.manual.answer import answer  # noqa: E402
from squad.manual.schema import load_kb  # noqa: E402
from squad.manual.search import ManualIndex  # noqa: E402

index = ManualIndex(*load_kb(ROOT / "data" / "manual_kb"))


def ask(q: str):
    t = time.perf_counter()
    a = answer(index, q)
    print(a.render())
    print(f"(판정 {a.status}, 점수 {a.score:.1f}, 일치율 {a.coverage:.0%}, {1000 * (time.perf_counter() - t):.0f}ms)")
    print("낭독:", a.spoken())


if len(sys.argv) > 1:
    ask(" ".join(sys.argv[1:]))
else:
    while (q := input("\n질문> ").strip()):
        ask(q)
