"""규칙만 vs 재순위 추가: 정답 문단 답변율, 간결 답변 핵심 구절 포함율, 응답 시간."""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from squad.manual.answer import answer  # noqa: E402
from squad.manual.rerank import Reranker  # noqa: E402
from squad.manual.schema import load_kb  # noqa: E402
from squad.manual.search import ManualIndex  # noqa: E402

idx = ManualIndex(*load_kb(ROOT / "data" / "manual_kb"))
rr = Reranker()


def rows(name):
    return [l.rstrip("\n").split("\t") for l in open(ROOT / "tests" / name, encoding="utf-8")
            if l.strip() and not l.startswith("#")]


for label, r in (("규칙만", None), ("재순위 추가", rr)):
    times = []
    res = {}
    for name in ("manual_eval.tsv", "manual_eval_holdout.tsv"):
        ok = n = 0
        for q, gold in rows(name):
            t = time.perf_counter(); a = answer(idx, q, reranker=r); times.append(time.perf_counter() - t)
            if gold == "-":
                ok += a.status == "abstain"
            else:
                ok += a.status == "answer" and a.main.id in gold.split("|")
            n += 1
        res[name] = f"{ok}/{n}"
    hit = 0
    bad = []
    br = rows("manual_brief_eval.tsv")
    for q, key in br:
        a = answer(idx, q, reranker=r)
        s = a.spoken()
        if key in s:
            hit += 1
        else:
            bad.append(q)
    times.sort()
    print(f"[{label}] 정답 문단: 조정세트 {res['manual_eval.tsv']}, held-out {res['manual_eval_holdout.tsv']} | "
          f"간결 답변 핵심 포함 {hit}/{len(br)} | 응답 중앙값 {1000 * times[len(times) // 2]:.0f}ms, "
          f"최대 {1000 * times[-1]:.0f}ms")
    print("   핵심 누락:", bad)
