"""교범 답변용 로컬 LLM (llama.cpp 서버, 127.0.0.1 전용, 오프라인).

역할을 좁게 둔다: 검색·판정·근거 선택은 기존 규칙(answer.py)이 하고, LLM은
  1) rewrite(): 이미 고른 근거 문장들을 질문에 맞춰 1~2문장으로 다듬기 (실시간)
  2) questions(): 문단마다 병사가 물을 법한 질문 생성 (사전 생성, 검색 보강용)
만 한다. rewrite 결과는 guard()로 검증해 근거에 없는 숫자나 뒤집힌 부정이 있으면 버린다.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "third_party" / "llama.cpp" / "build" / "bin" / "llama-server"
MODEL = ROOT / "models" / "llm" / "EXAONE-4.0-1.2B-Q4_K_M.gguf"
PORT = 8090

REWRITE_SYS = ("너는 군 교범 답변 정리기다. [근거]에 있는 내용만 써서 [질문]에 한국어로 답한다. "
               "1~2문장, 60자 안팎. 근거에 없는 내용, 추측, 인사말은 쓰지 않는다. "
               "금지·경고 내용이 있으면 반드시 포함한다. 숫자는 근거 그대로 쓴다.")
# 지시는 사용자 메시지에 넣는다 (EXAONE 4.0 1.2B는 시스템 지시를 무시했다). 예시를 주면 Gemma가 예시 주제를 따라 했다
QUESTION_PROMPT = ("다음 교범 문단을 읽고, 병사가 현장에서 물어볼 만한 짧은 질문 5개를 한 줄에 하나씩 써라. "
                   "각 질문은 물음표로 끝나고, 답이 이 문단에 있어야 한다.\n\n[제목] {heading}\n{text}")

RE_NUM = re.compile(r"\d+(?:\.\d+)?")
RE_NEG = re.compile(r"(않|안 |말아|금지|없|못)")


@dataclass
class Gen:
    text: str
    prompt_tokens: int
    prompt_ms: float
    gen_tokens: int
    gen_ms: float

    @property
    def total_s(self) -> float:
        return (self.prompt_ms + self.gen_ms) / 1000


class LocalLLM:
    def __init__(self, model: Path = MODEL, port: int = PORT, threads: int = 4, ctx: int = 2048,
                 start: bool = True):
        self.url = f"http://127.0.0.1:{port}"
        self.proc = None
        if start and not self._alive():
            self.proc = subprocess.Popen(
                [str(SERVER), "-m", str(model), "--host", "127.0.0.1", "--port", str(port), "-t", str(threads),
                 "-c", str(ctx), "--no-webui", "-np", "1",
                 "-lm", "none",             # 시작 때 모델 전체를 RAM에 읽어 둔다 (mmap 페이지 폴트로 인한 첫 답 지연 방지)
                 "-b", "512", "-ub", "512",  # 입력(프롬프트)을 한 번에 크게 처리
                 "-fa", "on"],
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            t = time.time()
            while not self._alive():
                if self.proc.poll() is not None or time.time() - t > 180:
                    err = self.proc.stderr.read()[-500:] if self.proc.poll() is not None else "시간 초과"
                    raise RuntimeError(f"llama-server 시작 실패: {err}")
                time.sleep(0.5)

    def _alive(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + "/health", timeout=1) as r:
                return json.load(r).get("status") == "ok"
        except Exception:  # noqa: BLE001
            return False

    def chat(self, system: str, user: str, max_tokens: int = 96, schema: dict | None = None,
             timeout: float = 300) -> Gen:
        """대화 기록 없음(매 질문 독립). 고정 지시문은 cache_prompt로 재사용된다."""
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
        body = {"messages": msgs,
                "max_tokens": max_tokens, "temperature": 0, "cache_prompt": True,
                "chat_template_kwargs": {"enable_thinking": False}}
        if schema is not None:          # 출력 형식 강제 (llama.cpp가 JSON 스키마를 문법으로 바꿔 디코딩을 제한)
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "schema": schema}}
        req = urllib.request.Request(self.url + "/v1/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.load(r)
        t = d.get("timings", {})
        text = d["choices"][0]["message"]["content"].strip()
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
        return Gen(text, t.get("prompt_n", 0), t.get("prompt_ms", 0.0), t.get("predicted_n", 0),
                   t.get("predicted_ms", 0.0))

    def rewrite(self, question: str, evidence: list[str], max_tokens: int = 80) -> Gen:
        ev = "\n".join(f"- {e}" for e in evidence)
        return self.chat(REWRITE_SYS, f"[근거]\n{ev}\n\n[질문] {question}", max_tokens)

    def questions(self, heading: str, text: str, max_tokens: int = 120) -> list[str]:
        g = self.chat("", QUESTION_PROMPT.format(heading=heading, text=text[:700]), max_tokens)
        qs = [re.sub(r"^[\s\-•*\d.)]+", "", l).strip() for l in g.text.splitlines()]
        return [q for q in qs if 4 <= len(q) <= 60 and q.endswith("?")][:5]

    def close(self) -> None:
        if self.proc is not None:
            self.proc.terminate()
            self.proc.wait(10)


def guard(answer: str, evidence: list[str]) -> str | None:
    """LLM 답 검증. 문제가 있으면 이유 문자열, 통과면 None.
    - 근거에 없는 숫자가 나오면 실패 (단위 환산·지어낸 수치 차단)
    - 근거에 금지·부정이 있는데 답에 부정 표현이 하나도 없으면 실패 ("올리지 않는다" → "올린다" 뒤집힘 차단)
    - 너무 길거나 비면 실패
    """
    ev = " ".join(evidence)
    if not answer or len(answer) > 160:
        return "길이"
    extra = set(RE_NUM.findall(answer)) - set(RE_NUM.findall(ev))
    if extra:
        return f"근거에 없는 숫자 {sorted(extra)}"
    if RE_NEG.search(ev) and not RE_NEG.search(answer):
        return "부정 누락"
    return None
