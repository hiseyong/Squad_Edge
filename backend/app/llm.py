"""로컬 LLM 클라이언트 (외부망 불필요).

지원
  - Ollama 네이티브 API  (기본: http://localhost:11434 자동 탐지)
  - OpenAI 호환 서버     (llama.cpp server, LM Studio, vLLM … URL이 /v1 로 끝나면)

환경변수
  COP_LLM_URL    기본 http://localhost:11434   ("off" 이면 비활성)
  COP_LLM_MODEL  선호 모델 (없으면 설치된 모델 중 PREFERRED 순서로 자동 선택)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
import urllib.request
from typing import AsyncIterator

log = logging.getLogger("cop.llm")

PREFERRED = [
    "exaone3.5:7.8b", "exaone3.5:2.4b", "qwen2.5:7b", "qwen2.5:3b", "gemma3:4b",
    "llama3.1:8b", "qwen2.5:1.5b",
]


class LLM:
    def __init__(self) -> None:
        self.url = os.getenv("COP_LLM_URL", "http://localhost:11434").rstrip("/")
        self.enabled = self.url.lower() != "off"
        self.openai = self.url.endswith("/v1")
        self.model: str | None = os.getenv("COP_LLM_MODEL") or None
        self.models: list[str] = []
        self.available = False
        self.error: str | None = None
        self.checked_at = 0.0

    # ------------------------------------------------------------------ 탐지
    def _probe(self) -> None:
        try:
            path = "/models" if self.openai else "/api/tags"
            with urllib.request.urlopen(self.url + path, timeout=2) as r:
                data = json.loads(r.read())
            if self.openai:
                self.models = [m["id"] for m in data.get("data", [])]
            else:
                self.models = [m["name"] for m in data.get("models", [])]
            self.available = bool(self.models)
            self.error = None if self.models else "모델 없음 (ollama pull 필요)"
            if self.models and self.model not in self.models:
                pick = next((p for p in PREFERRED if p in self.models), None)
                self.model = pick or self.models[0]
        except Exception as e:
            self.available = False
            self.error = f"{type(e).__name__}: 서버 미응답"
        self.checked_at = time.time()

    async def refresh(self, force: bool = False) -> dict:
        if self.enabled and (force or time.time() - self.checked_at > 15):
            await asyncio.to_thread(self._probe)
            if self.available:
                log.info("LLM ready url=%s model=%s models=%s", self.url, self.model, self.models)
            else:
                log.warning("LLM unavailable: %s", self.error)
        return self.status()

    async def warmup(self) -> None:
        """첫 브리핑 지연 완화 — 모델 로드 한 번 트리거."""
        if not self.enabled or not self.available or not self.model:
            return
        try:
            n = 0
            async for _ in self.stream(
                [{"role": "user", "content": "OK"}], temperature=0.0,
            ):
                n += 1
                if n >= 3:
                    break
            log.info("LLM warmup ok (%s)", self.model)
        except Exception as e:
            log.warning("LLM warmup failed: %s", e)

    def status(self) -> dict:
        return {"enabled": self.enabled, "available": self.available, "url": self.url,
                "api": "openai" if self.openai else "ollama", "model": self.model,
                "models": self.models, "error": self.error}

    def set_model(self, name: str) -> None:
        self.model = name

    # ------------------------------------------------------------------ 생성 (스트리밍)
    def _request(self, messages: list[dict], temperature: float):
        if self.openai:
            body = {"model": self.model, "messages": messages, "stream": True, "temperature": temperature}
            url = self.url + "/chat/completions"
        else:
            body = {"model": self.model, "messages": messages, "stream": True,
                    "options": {"temperature": temperature, "num_ctx": 4096}, "keep_alive": "30m"}
            url = self.url + "/api/chat"
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=180)

    def _parse(self, line: str) -> str | None:
        line = line.strip()
        if not line:
            return None
        if self.openai:
            if not line.startswith("data:"):
                return None
            payload = line[5:].strip()
            if payload == "[DONE]":
                return None
            delta = json.loads(payload)["choices"][0].get("delta", {})
            return delta.get("content")
        obj = json.loads(line)
        if obj.get("error"):
            raise RuntimeError(obj["error"])
        return obj.get("message", {}).get("content")

    async def stream(self, messages: list[dict], temperature: float = 0.2) -> AsyncIterator[str]:
        """토큰 단위 비동기 스트림. 블로킹 HTTP는 스레드에서 읽고 큐로 넘긴다."""
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        DONE = object()

        def worker():
            try:
                with self._request(messages, temperature) as resp:
                    for raw in resp:
                        tok = self._parse(raw.decode("utf-8", "ignore"))
                        if tok:
                            loop.call_soon_threadsafe(q.put_nowait, tok)
            except Exception as e:  # 오류도 큐로 전달
                loop.call_soon_threadsafe(q.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(q.put_nowait, DONE)

        threading.Thread(target=worker, daemon=True).start()
        while True:
            item = await q.get()
            if item is DONE:
                break
            if isinstance(item, Exception):
                raise item
            yield item


llm = LLM()
