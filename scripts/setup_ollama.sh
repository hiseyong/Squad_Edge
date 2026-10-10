#!/usr/bin/env bash
# 온디바이스 AI(로컬 LLM) 준비 스크립트 — macOS (Apple Silicon)
#   ./scripts/setup_ollama.sh            # RAM 기준 모델 자동 선택
#   ./scripts/setup_ollama.sh qwen2.5:3b # 모델 직접 지정
# 수행: Ollama 설치 확인 → 서버 기동 → 모델 다운로드 → 워밍업·한국어 추출 테스트 → 속도 측정
set -euo pipefail
URL="http://localhost:11434"

say() { printf "\033[1;32m[ollama]\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m[ollama]\033[0m %s\n" "$*"; }

# 1) 설치 확인
if ! command -v ollama >/dev/null 2>&1; then
  if command -v brew >/dev/null 2>&1; then
    say "Ollama 미설치 → brew install ollama"
    brew install ollama
  else
    warn "Ollama, Homebrew 모두 없음. https://ollama.com/download 에서 macOS 앱 설치 후 다시 실행"
    exit 1
  fi
fi
say "버전: $(ollama --version 2>/dev/null | tail -1)"

# 2) 서버 기동
if ! curl -sf "$URL/api/tags" >/dev/null; then
  if command -v brew >/dev/null 2>&1 && brew list ollama >/dev/null 2>&1; then
    say "서버 기동 (brew services)"
    brew services start ollama >/dev/null
  else
    say "서버 기동 (ollama serve, 로그: /tmp/ollama.log)"
    nohup ollama serve >/tmp/ollama.log 2>&1 &
  fi
  for i in $(seq 1 30); do curl -sf "$URL/api/tags" >/dev/null && break; sleep 1; done
fi
curl -sf "$URL/api/tags" >/dev/null || { warn "서버 응답 없음 (/tmp/ollama.log 확인)"; exit 1; }
say "서버 응답 OK ($URL)"

# 3) 모델 선택: 16GB 이상 → 7.8B, 미만 → 2.4B (EXAONE 3.5, 한국어 특화)
MEM_GB=$(( $(sysctl -n hw.memsize 2>/dev/null || echo 8589934592) / 1073741824 ))
if [ "${1:-}" != "" ]; then MODEL="$1"
elif [ "$MEM_GB" -ge 16 ]; then MODEL="exaone3.5:7.8b"
else MODEL="exaone3.5:2.4b"; fi
say "RAM ${MEM_GB}GB → 모델 $MODEL"
ollama pull "$MODEL"

# 4) 워밍업 + 한국어 SALUTE 추출 테스트 + 속도 측정
say "워밍업·테스트 (첫 호출은 모델 적재로 수 초 소요)"
python3 - "$URL" "$MODEL" <<'PY'
import json, sys, time, urllib.request
url, model = sys.argv[1], sys.argv[2]
prompt = ("다음 무전 보고를 SALUTE JSON으로 변환하라. 키: size, activity, location, unit, time, equipment. "
          "JSON만 출력.\n보고: \"1분대장 보고. 적 보병 3명, 2시 방향 약 150미터, 능선 따라 남쪽으로 이동 중. 소총 휴대.\"")
body = json.dumps({"model": model, "stream": False, "format": "json", "keep_alive": "30m",
                   "options": {"temperature": 0},
                   "messages": [{"role": "user", "content": prompt}]}).encode()
t = time.time()
r = json.loads(urllib.request.urlopen(urllib.request.Request(url + "/api/chat", data=body,
        headers={"Content-Type": "application/json"}), timeout=300).read())
wall = time.time() - t
print("응답:", r["message"]["content"].strip()[:400])
ev, ed = r.get("eval_count", 0), r.get("eval_duration", 1) / 1e9
pe, pd = r.get("prompt_eval_count", 0), r.get("prompt_eval_duration", 1) / 1e9
ld = r.get("load_duration", 0) / 1e9
print(f"모델 적재 {ld:.1f}s · 프롬프트 {pe}tok {pe/max(pd,1e-6):.0f}tok/s · 생성 {ev}tok {ev/max(ed,1e-6):.1f}tok/s · 총 {wall:.1f}s")
PY

say "완료. 대시보드 실행:  COP_LLM_MODEL=$MODEL ./run.sh"
say "브리핑 패널 배지가 'LLM · $MODEL' 로 바뀌면 연결된 상태"
