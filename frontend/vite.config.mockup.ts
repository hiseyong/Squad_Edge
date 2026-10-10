import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { defineConfig, type Plugin } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

/** Cloudflare Pages는 dist 루트에 index.html 필요 */
function emitIndexHtml(): Plugin {
  return {
    name: 'emit-index-html',
    closeBundle() {
      const out = path.resolve(__dirname, 'dist-mockup')
      const from = path.join(out, 'index.mockup.html')
      const to = path.join(out, 'index.html')
      if (fs.existsSync(from)) {
        fs.renameSync(from, to)
      }
      // SPA 폴백 (CF Pages)
      fs.writeFileSync(path.join(out, '_redirects'), '/*    /index.html   200\n')
      fs.writeFileSync(
        path.join(out, '_headers'),
        `/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin

/assets/*
  Cache-Control: public, max-age=31536000, immutable
`,
      )
    },
  }
}

/** 백엔드 없이 COP UI만 — Cloudflare Pages 배포용 */
export default defineConfig({
  plugins: [react(), tailwindcss(), emitIndexHtml()],
  define: {
    'import.meta.env.VITE_COP_MOCKUP': JSON.stringify('1'),
  },
  base: '/',
  build: {
    outDir: 'dist-mockup',
    emptyOutDir: true,
    chunkSizeWarningLimit: 2000,
    rollupOptions: {
      input: path.resolve(__dirname, 'index.mockup.html'),
    },
  },
  server: {
    host: '0.0.0.0',
    port: 5174,
    allowedHosts: true,
    open: '/index.mockup.html',
  },
  preview: {
    host: '0.0.0.0',
    port: 4174,
    allowedHosts: true,
  },
})
