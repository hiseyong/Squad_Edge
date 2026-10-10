import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const BACKEND = process.env.COP_BACKEND ?? 'http://localhost:8000'
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const TILES_DIR = path.join(ROOT, 'tiles')

/** SoftAP(오프라인)에서도 Vite 개발 서버가 /tiles 를 직접 서빙 */
function serveOfflineTiles(): Plugin {
  return {
    name: 'serve-offline-tiles',
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        if (!req.url?.startsWith('/tiles/')) return next()
        const rel = decodeURIComponent(req.url.slice('/tiles/'.length).split('?')[0])
        if (!rel || rel.includes('..')) return next()
        const file = path.join(TILES_DIR, rel)
        if (!file.startsWith(TILES_DIR) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
          return next()
        }
        res.setHeader('Content-Type', 'image/png')
        res.setHeader('Cache-Control', 'public, max-age=86400')
        fs.createReadStream(file).pipe(res)
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), serveOfflineTiles()],
  build: { chunkSizeWarningLimit: 2000 },
  server: {
    host: '0.0.0.0', // AP/LAN 접속 (localhost만 아님)
    allowedHosts: true,
    proxy: {
      '/api': BACKEND,
      // /tiles 는 위 플러그인이 로컬 tiles/ 를 우선 서빙. 없으면 백엔드로.
      '/tiles': BACKEND,
      '/ws': { target: BACKEND.replace('http', 'ws'), ws: true },
    },
  },
  preview: {
    host: '0.0.0.0',
    allowedHosts: true,
  },
})
