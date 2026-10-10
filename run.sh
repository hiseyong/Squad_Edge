#!/usr/bin/env bash
# Squad Edge C2 COP 실행 스크립트
#   ./run.sh                    개발 모드 (백엔드 :8000 + Vite :5173, 핫리로드)
#   ./run.sh prod               프론트 빌드 후 백엔드 하나로 서빙 (:8000) — 데모용
#   COP_MODE=realtime ./run.sh  1분대=단말 HW · HQ·2·3 mock
#   COP_MODE=realtime COP_Q3=1 ./run.sh   분대장1 SoftAP(192.168.4.1:9000) 연동
#   COP_SIM=0 ./run.sh          시뮬레이터 끄고 실제 하드웨어 입력만
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# realtime + SoftAP: COP_Q3 미지정 시 기본 활성 (노트북이 보드 AP에 조인한 경우)
if [ "${COP_MODE:-}" = "realtime" ] && [ -z "${COP_Q3+x}" ]; then
  export COP_Q3=1
  export COP_Q3_HOST="${COP_Q3_HOST:-192.168.4.1}"
  echo "[cop] COP_Q3=1 → ${COP_Q3_HOST}:9000 (끄려면 COP_Q3=0)"
fi

if [ ! -d backend/.venv ]; then
  echo "[setup] python venv 생성"
  python3 -m venv backend/.venv
  backend/.venv/bin/pip install -q -r backend/requirements.txt
fi
if [ ! -d frontend/node_modules ]; then
  echo "[setup] npm install"
  (cd frontend && npm install)
fi

LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || hostname -I 2>/dev/null | awk '{print $1}' || true)"

# 온디바이스 LLM(Ollama) — 있으면 브리핑에 자동 연결, 없으면 규칙 기반
LLM_URL="${COP_LLM_URL:-http://localhost:11434}"
if [ "${LLM_URL}" != "off" ] && curl -sf "${LLM_URL%/v1}/api/tags" >/dev/null 2>&1; then
  if [ -z "${COP_LLM_MODEL:-}" ]; then
    COP_LLM_MODEL="$(curl -sf "${LLM_URL%/v1}/api/tags" | python3 -c '
import sys, json
prefs = ["exaone3.5:7.8b","exaone3.5:2.4b","qwen2.5:7b","qwen2.5:3b","gemma3:4b","llama3.1:8b"]
names = [m["name"] for m in json.load(sys.stdin).get("models", [])]
print(next((p for p in prefs if p in names), names[0] if names else ""), end="")
')"
    export COP_LLM_MODEL
  fi
  export COP_LLM_URL="${COP_LLM_URL:-http://localhost:11434}"
  echo "[cop] LLM 연결 → ${COP_LLM_URL}  model=${COP_LLM_MODEL:-auto}"
else
  echo "[warn] Ollama 미실행: AI 브리핑은 규칙 기반 (준비: ./scripts/setup_ollama.sh)"
fi

if [ "$1" = "prod" ]; then
  (cd frontend && npm run build)
  echo "▶ http://0.0.0.0:8000  (local: http://localhost:8000${LAN_IP:+  lan: http://$LAN_IP:8000})"
  cd backend && exec .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
fi

(cd backend && .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload) &
BE=$!
trap "kill $BE 2>/dev/null" EXIT
echo "▶ backend  http://0.0.0.0:8000${LAN_IP:+  lan: http://$LAN_IP:8000}"
echo "▶ frontend http://0.0.0.0:5173${LAN_IP:+  lan: http://$LAN_IP:5173}"
cd frontend && npm run dev
