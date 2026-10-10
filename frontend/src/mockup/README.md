# COP UI Mockup → Cloudflare Pages

백엔드 없이 COP UI만 시연. Cloudflare Pages 정적 배포용.

## 로컬

```bash
./run-mockup.sh                 # http://localhost:5174/index.mockup.html
./run-mockup.sh build           # → frontend/dist-mockup/index.html
./run-mockup.sh preview
```

## Cloudflare Pages (Git 연동)

Dashboard → Workers & Pages → Create → Connect repo:

| 항목 | 값 |
|---|---|
| **Root directory** | `frontend` |
| **Build command** | `npm run build:mockup` |
| **Build output directory** | `dist-mockup` |
| **Node version** | `20` (Environment variables → `NODE_VERSION=20`) |

배포 후 `https://<project>.pages.dev` 로 접속.

## CLI 배포

```bash
cd frontend
npm i -D wrangler          # 최초 1회
npx wrangler login
npm run deploy:mockup      # build + pages deploy
```

프로젝트 이름은 `wrangler.toml` / `deploy:mockup` 스크립트의 `squad-edge-cop` 입니다. 바꾸려면 둘 다 수정하세요.

## 구성

| 경로 | 역할 |
|---|---|
| `seed.ts` | 유닛·보고·경보·명령 시드 |
| `engine.ts` | 1초 틱 위치/링크 |
| `api.ts` | 로컬 API (fetch/WS 없음) |
| `../../vite.config.mockup.ts` | `VITE_COP_MOCKUP=1`, `dist-mockup` + `index.html` |
| `../../wrangler.toml` | Pages 출력 디렉터리 |
