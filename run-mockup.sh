#!/usr/bin/env bash
# COP UI Mockup — 백엔드 없이 프론트만 시연 (Cloudflare Pages 배포용)
#   ./run-mockup.sh           개발 서버 :5174
#   ./run-mockup.sh build     → frontend/dist-mockup/index.html
#   ./run-mockup.sh preview   빌드 미리보기 :4174
#   ./run-mockup.sh deploy    wrangler pages deploy (로그인 필요)
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT/frontend"

if [ ! -d node_modules ]; then
  echo "[setup] npm install"
  npm install
fi

case "${1:-}" in
  build)
    npm run build:mockup
    echo "▶ Cloudflare Pages output: frontend/dist-mockup/index.html"
    echo "  Dashboard: Root=frontend  Build=npm run build:mockup  Output=dist-mockup"
    ;;
  preview)
    npm run build:mockup
    echo "▶ http://0.0.0.0:4174/"
    npm run preview:mockup
    ;;
  deploy)
    if ! npx wrangler --version >/dev/null 2>&1; then
      echo "[setup] wrangler 설치"
      npm i -D wrangler
    fi
    npm run deploy:mockup
    ;;
  *)
    echo "▶ UI Mockup (no backend)  http://localhost:5174/index.mockup.html"
    echo "  CF Pages: ./run-mockup.sh build | deploy"
    npm run mockup
    ;;
esac
