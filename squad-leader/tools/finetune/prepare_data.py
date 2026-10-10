"""[보드] 변형 발화 데이터(utterances.jsonl) → 미세조정·평가 데이터.

    .venv/bin/python tools/finetune/prepare_data.py data/utterances/utterances.jsonl

결과 data/finetune/
  train.jsonl, valid.jsonl   MLX 학습용 채팅 형식 {"messages": [user, assistant]}
  eval.jsonl                 평가 전용 원본 줄 (학습·규칙 수정에 쓰지 않는다)
  test.jsonl                 같은 평가 세트의 채팅 형식 (MLX --test 손실 계산용)
  report.txt                 검사 결과 (형식 오류, 코드 오류, 분포)
분할: 무작위(고정 시드) 학습 70% / 검증 10% / 평가 20%. 학습에는 음성 인식 흉내 사본(띄어쓰기 제거 →
우리 띄어쓰기 복원기 → 숫자 정규화)도 함께 넣는다. 평가 세트는 원문과 STT 흉내 두 가지로 따로 채점한다.
"""
import json
import random
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from squad.report.nlu import PROMPT, dumps, label_from_dataset  # noqa: E402
from squad.report.sqrpt import ACTION_CODES, ACTIVITY_CODES, REQUEST_CODES  # noqa: E402
from squad.text.normalize import normalize  # noqa: E402
from squad.text.spacing import default_segmenter  # noqa: E402

OUT = Path(__import__("os").environ.get("FT_OUT", ROOT / "data" / "finetune"))
CODES = {"activity": set(ACTIVITY_CODES), "action": set(ACTION_CODES), "requests": set(REQUEST_CODES)}


def stt_like(text: str) -> str:
    """Zipformer 출력 흉내: 문장부호·띄어쓰기 없이 → 우리 후처리(띄어쓰기 복원, 숫자 정규화)."""
    glued = re.sub(r"[\s,.?!~·]", "", text)
    return normalize(default_segmenter().segment(glued))


def check(rows: list[dict]) -> tuple[list[dict], list[str]]:
    ok, errs, seen = [], [], set()
    for r in rows:
        t = (r.get("text") or "").strip()
        if not t:
            errs.append(f"{r.get('id')}: text 없음"); continue
        if t in seen:
            errs.append(f"{r.get('id')}: 중복 '{t}'"); continue
        bad = [c for k, s in CODES.items() for c in (r.get(k) or []) if c not in s]
        if bad:
            errs.append(f"{r.get('id')}: 모르는 코드 {bad}"); continue
        seen.add(t)
        ok.append(r)
    return ok, errs


def chat(text: str, label: dict) -> dict:
    return {"messages": [{"role": "user", "content": PROMPT.format(text=text)},
                         {"role": "assistant", "content": dumps(label)}]}


def main():
    src = Path(sys.argv[1])
    rows = []
    for i, line in enumerate(src.open(encoding="utf-8"), 1):
        line = line.strip()
        if not line or line.startswith(("```", "#")):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            print(f"줄 {i}: JSON 아님 → 건너뜀: {line[:60]}")
    rows, errs = check(rows)
    random.Random(7).shuffle(rows)
    n = len(rows)
    test, valid, train = rows[: n // 5], rows[n // 5: n // 5 + n // 10], rows[n // 5 + n // 10:]
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "train.jsonl").open("w", encoding="utf-8") as f:
        for r in train:
            lab = label_from_dataset(r)
            f.write(json.dumps(chat(r["text"], lab), ensure_ascii=False) + "\n")
            s = stt_like(r["text"])
            if s != r["text"]:
                f.write(json.dumps(chat(s, lab), ensure_ascii=False) + "\n")
    with (OUT / "valid.jsonl").open("w", encoding="utf-8") as f:
        for r in valid:
            f.write(json.dumps(chat(r["text"], label_from_dataset(r)), ensure_ascii=False) + "\n")
    # eval.jsonl: 평가 원본 (보드 eval_nlu.py용). test.jsonl: 같은 평가 세트를 학습 형식으로 (MLX --test용)
    # (MLX는 데이터 폴더의 test.jsonl도 읽으므로 반드시 채팅 형식이어야 한다)
    with (OUT / "eval.jsonl").open("w", encoding="utf-8") as f:
        for r in test:
            f.write(json.dumps({**r, "text_stt": stt_like(r["text"])}, ensure_ascii=False) + "\n")
    with (OUT / "test.jsonl").open("w", encoding="utf-8") as f:
        for r in test:
            f.write(json.dumps(chat(r["text"], label_from_dataset(r)), ensure_ascii=False) + "\n")
    dist = Counter(c for r in rows for k in CODES for c in (r.get(k) or []))
    hard = Counter(r.get("hard") for r in rows)
    rep = [f"유효 {n}줄 (오류 {len(errs)}): 학습 {len(train)}(+STT 흉내 사본) / 검증 {len(valid)} / 평가 {len(test)}",
           f"어려운 경우: {dict(hard)}", f"코드 분포: {dict(dist.most_common())}", "오류:"] + errs
    (OUT / "report.txt").write_text("\n".join(rep), encoding="utf-8")
    print("\n".join(rep[:3]))
    if errs:
        print(f"오류 {len(errs)}건 → {OUT / 'report.txt'}")


if __name__ == "__main__":
    main()
