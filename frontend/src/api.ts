import { useEffect } from 'react'
import { useCop } from './store'
import type { DecisionAction, Order, OrderCode, Report, ServerMsg } from './types'
import type { BriefEvent, DemoMode, LlmStatus, ModeStatus } from './apiTypes'
import { mockApi } from './mockup/api'
import { bootMockup, stopMockup } from './mockup/engine'

export type { BriefEvent, DemoMode, LlmStatus, ModeStatus } from './apiTypes'

/** Vite `--mode mockup` 또는 VITE_COP_MOCKUP=1 */
export const IS_MOCKUP = import.meta.env.VITE_COP_MOCKUP === '1'

const post = async (url: string, body?: unknown) => {
  const r = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) throw new Error(data?.detail ?? `HTTP ${r.status}`)
  return data
}

/** SSE(POST) 스트림 파서 */
async function* sse(url: string, body: unknown, signal?: AbortSignal): AsyncGenerator<BriefEvent> {
  const r = await fetch(url, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal,
  })
  if (!r.ok || !r.body) throw new Error(`HTTP ${r.status}`)
  const reader = r.body.getReader()
  const dec = new TextDecoder()
  let buf = ''
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += dec.decode(value, { stream: true })
    let i
    while ((i = buf.indexOf('\n\n')) >= 0) {
      const chunk = buf.slice(0, i)
      buf = buf.slice(i + 2)
      const line = chunk.split('\n').find((l) => l.startsWith('data:'))
      if (line) yield JSON.parse(line.slice(5)) as BriefEvent
    }
  }
}

const liveApi = {
  decide: (id: string, action: DecisionAction, note = '', edits?: Record<string, unknown>) =>
    post(`/api/reports/${id}/decision`, { action, note, edits }) as Promise<Report>,
  issueOrder: (o: { code: OrderCode; to: string[]; text?: string; params?: Record<string, unknown>; priority?: string }) =>
    post('/api/orders', o) as Promise<Order>,
  cancelOrder: (id: string) => post(`/api/orders/${id}/cancel`) as Promise<Order>,
  resendOrder: (id: string) => post(`/api/orders/${id}/resend`) as Promise<Order>,
  llmStatus: (refresh = false) => fetch(`/api/llm/status?refresh=${refresh}`).then((r) => r.json()) as Promise<LlmStatus>,
  setModel: (model: string) => post('/api/llm/model', { model }) as Promise<LlmStatus>,
  briefStream: (question: string | undefined, useLlm: boolean, signal?: AbortSignal) =>
    sse('/api/briefing/stream', { question: question || null, use_llm: useLlm }, signal),
  ackAlert: (id: string) => post(`/api/alerts/${id}/ack`),
  ackAll: () => post('/api/alerts/ack_all'),
  setEmcon: (on: boolean) => post('/api/emcon', { on }),
  sim: (action: 'start' | 'stop' | 'restart') => post('/api/sim', { action }) as Promise<ModeStatus>,
  simStatus: () => fetch('/api/sim').then((r) => r.json()) as Promise<ModeStatus>,
  modeStatus: () => fetch('/api/mode').then((r) => r.json()) as Promise<ModeStatus>,
  setMode: (mode: DemoMode) => post('/api/mode', { mode }) as Promise<ModeStatus>,
  briefing: (question?: string) =>
    post('/api/briefing', { question: question || null }) as Promise<{ text: string; engine: string }>,
  ingest: (ev: unknown) => post('/api/ingest', ev),
  state: () => fetch('/api/state').then((r) => r.json()),
}

export const api = IS_MOCKUP ? mockApi : liveApi

/**
 * 실서버: WebSocket + 자동 재접속
 * Mockup: 로컬 시드 + 1초 틱 (백엔드 불필요)
 */
export function useCopSocket() {
  useEffect(() => {
    if (IS_MOCKUP) {
      bootMockup()
      return () => stopMockup()
    }

    let ws: WebSocket | null = null
    let timer: ReturnType<typeof setTimeout> | undefined
    let closed = false
    let queue: ServerMsg[] = []
    let flushTimer: ReturnType<typeof setTimeout> | undefined
    let dirtyWhileHidden = false
    let resyncing = false
    const { applyBatch, apply, setConnected } = useCop.getState()

    const flush = () => {
      flushTimer = undefined
      if (queue.length === 0) return
      const batch = queue
      queue = []
      applyBatch(batch)
    }

    const scheduleFlush = () => {
      if (flushTimer !== undefined) return
      flushTimer = setTimeout(flush, 50)
    }

    const enqueue = (m: ServerMsg) => {
      if (document.visibilityState !== 'visible') {
        dirtyWhileHidden = true
        return
      }
      queue.push(m)
      if (m.t === 'snapshot') {
        queue = [m]
        if (flushTimer !== undefined) {
          clearTimeout(flushTimer)
          flushTimer = undefined
        }
        flush()
        return
      }
      scheduleFlush()
    }

    const resync = async () => {
      if (resyncing || closed) return
      resyncing = true
      dirtyWhileHidden = false
      queue = []
      if (flushTimer !== undefined) {
        clearTimeout(flushTimer)
        flushTimer = undefined
      }
      try {
        const v = await api.state()
        if (!closed) apply({ t: 'snapshot', v })
      } catch {
        if (!closed) ws?.close()
      } finally {
        resyncing = false
      }
    }

    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws`)
      ws.onopen = () => setConnected(true)
      ws.onmessage = (e) => {
        try {
          enqueue(JSON.parse(e.data) as ServerMsg)
        } catch { /* ignore */ }
      }
      ws.onclose = () => {
        setConnected(false)
        if (!closed) timer = setTimeout(connect, 1500)
      }
      ws.onerror = () => ws?.close()
    }

    const onVisibility = () => {
      if (document.visibilityState === 'visible') {
        if (dirtyWhileHidden || queue.length > 50) resync()
        else scheduleFlush()
      } else {
        queue = []
        if (flushTimer !== undefined) {
          clearTimeout(flushTimer)
          flushTimer = undefined
        }
        dirtyWhileHidden = true
      }
    }

    connect()
    document.addEventListener('visibilitychange', onVisibility)
    return () => {
      closed = true
      clearTimeout(timer)
      if (flushTimer !== undefined) clearTimeout(flushTimer)
      document.removeEventListener('visibilitychange', onVisibility)
      ws?.close()
    }
  }, [])
}
