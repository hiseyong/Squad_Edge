"""[보드] 보고 칸 추출 평가: 규칙 vs LLM(기본 few-shot 또는 미세조정) — data/finetune/eval.jsonl.

    .venv/bin/python tools/finetune/eval_nlu.py                          # 규칙만
    .venv/bin/python tools/finetune/eval_nlu.py --model models/llm/X.gguf --mode fewshot
    .venv/bin/python tools/finetune/eval_nlu.py --model models/llm/X-ft.gguf --mode ft

점수: 코드 칸(a/c/r) 미시 F1, 발화 전체 정답률(a·c·r·n·w 모두 일치), 부정 사례 정답률, 응답 시간.
입력은 원문(text)과 STT 흉내(text_stt) 두 가지로 따로 잰다.
"""
import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from squad.report.nlu import FEWSHOT, PROMPT, SCHEMA, label_from_dataset, merge, parse_output, rule_nlu  # noqa: E402


def score(pairs):
    tp = fp = fn = 0
    exact = 0
    by_hard = defaultdict(lambda: [0, 0])
    for gold, pred, hard in pairs:
        ok = True
        for k in ("a", "c", "r"):
            g, p = set(gold[k]), set((pred or {}).get(k) or [])
            tp += len(g & p); fp += len(p - g); fn += len(g - p)
            ok &= g == p
        ok &= (pred or {}).get("n") == gold["n"] and sorted((pred or {}).get("w") or []) == sorted(gold["w"])
        exact += ok
        by_hard[hard or "보통"][0] += ok
        by_hard[hard or "보통"][1] += 1
    f1 = 2 * tp / max(1, 2 * tp + fp + fn)
    return f1, exact / max(1, len(pairs)), {k: f"{a}/{b}" for k, (a, b) in by_hard.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", default=str(ROOT / "data" / "finetune" / "eval.jsonl"))
    ap.add_argument("--model")
    ap.add_argument("--mode", choices=("fewshot", "ft"), default="ft")
    ap.add_argument("--merge", action="store_true", help="LLM + 규칙 합집합도 채점")
    ap.add_argument("--schema", action="store_true", help="JSON 스키마 문법 강제 (느려질 수 있음)")
    ap.add_argument("-v", action="store_true")
    ap.add_argument("--stt-only", action="store_true", help="음성 인식 흉내 입력만 (시간 절반)")
    a = ap.parse_args()
    rows = [json.loads(l) for l in open(a.test, encoding="utf-8") if l.strip()]
    systems = {"규칙": None}
    llm = None
    if a.model:
        from squad.manual.llm import LocalLLM
        llm = LocalLLM(Path(a.model))
        llm.chat("", "안녕", 4)
        systems[f"LLM({Path(a.model).stem},{a.mode})"] = llm
    for name, m in systems.items():
        for field in (("text_stt",) if a.stt_only else ("text", "text_stt")):
            pairs, times, pairs_m = [], [], []
            for r in rows:
                t = time.perf_counter()
                if m is None:
                    pred = rule_nlu(r[field])
                else:
                    prompt = (FEWSHOT.replace("{text}", r[field]) if a.mode == "fewshot"
                              else PROMPT.format(text=r[field]))
                    g = m.chat("", prompt, max_tokens=80, schema=SCHEMA if a.schema else None, timeout=120)
                    pred = parse_output(g.text)
                    if a.merge:
                        o = pred or {}
                        pairs_m.append((label_from_dataset(r), merge(o, rule_nlu(r[field])), r.get("hard")))
                times.append(time.perf_counter() - t)
                gold = label_from_dataset(r)
                pairs.append((gold, pred, r.get("hard")))
                if a.v and (pred is None or any(set(gold[k]) != set(pred.get(k) or []) for k in "acr")):
                    print(f"  ✗ {r[field]}\n     정답 {gold}\n     출력 {pred}")
            f1, ex, hard = score(pairs)
            times.sort()
            print(f"{name:32s} [{field:8s}] 코드 F1 {f1:.2f} | 발화 정답 {ex:.0%} | 어려운 경우 {hard} | "
                  f"중앙 {times[len(times) // 2]:.2f}s 최대 {times[-1]:.1f}s", flush=True)
            if pairs_m:
                f1, ex, hard = score(pairs_m)
                print(f"{name + '+규칙':32s} [{field:8s}] 코드 F1 {f1:.2f} | 발화 정답 {ex:.0%} | 어려운 경우 {hard}", flush=True)
    if llm:
        llm.close()


if __name__ == "__main__":
    main()
