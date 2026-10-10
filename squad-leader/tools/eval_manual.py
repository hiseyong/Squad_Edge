"""교범 질의응답 평가: 검색 정확도(1위/3위 안), 답변 보류 판정 정확도.

    .venv/bin/python tools/eval_manual.py [-v] [--holdout | --team] [--questions=파일.jsonl]
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from squad.manual.answer import answer  # noqa: E402
from squad.manual.schema import load_kb  # noqa: E402
from squad.manual.search import ManualIndex  # noqa: E402

import json  # noqa: E402

# --questions 파일: LLM이 사전 생성한 문단별 예상 질문으로 검색 보강 (비교 실험용)
qfile = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--questions=")), None)
questions = {}
if qfile:
    for line in open(qfile, encoding="utf-8"):
        d = json.loads(line)
        questions[d["id"]] = d["q"]
index = ManualIndex(*load_kb(ROOT / "data" / "manual_kb"), questions=questions)
verbose = "-v" in sys.argv
SETS = {"--holdout": "manual_eval_holdout.tsv", "--team": "manual_eval_team.tsv"}
EVAL = ROOT / "tests" / next((v for k, v in SETS.items() if k in sys.argv), "manual_eval.tsv")
rows = [l.rstrip("\n").split("\t") for l in open(EVAL, encoding="utf-8")
        if l.strip() and not l.startswith("#")]
n_in = top1 = top3 = answered_ok = 0
n_out = abstain_ok = 0
for q, gold in rows:
    a = answer(index, q)
    hits = [h.para.id for h in index.search(q, k=3)]
    if gold == "-":
        n_out += 1
        ok = a.status == "abstain"
        abstain_ok += ok
    else:
        n_in += 1
        g = set(gold.split("|"))
        top1 += hits[0] in g if hits else 0
        top3 += bool(g & set(hits))
        ok = a.status == "answer" and a.main.id in g
        answered_ok += ok
    if verbose or not ok:
        got = a.main.id if a.main else a.status
        print(f"{'OK ' if ok else 'XX '} {q:28s} 정답 {gold:22s} 답변 {got:14s} 검색 {hits} ({a.status} {a.score:.1f}/{a.coverage:.0%})")
print(f"\n범위 내 {n_in}문항: 검색 1위 {top1}/{n_in} ({top1 / n_in:.0%}), 3위 안 {top3}/{n_in} ({top3 / n_in:.0%}), "
      f"정답 문단으로 답변 {answered_ok}/{n_in} ({answered_ok / n_in:.0%})")
print(f"범위 밖 {n_out}문항: 올바르게 보류 {abstain_ok}/{n_out}")
