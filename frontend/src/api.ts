import { useEffect } from 'react'
import { useCop } from './store'
import type { DecisionAction, Order, OrderCode, Report, ServerMsg } from './types'

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

export interface LlmStatus {
  enabled: boolean
  available: boolean
  url: string
  api: string
  model: string | null
  models: string[]
  error: string | null
}

export type BriefEvent =
  | { type: 'meta'; engine: string; facts: string; reason?: string | null }
  | { type: 'token'; text: string }
  | { type: 'done'; text: string; latency: number }
  | { type: 'error'; message: string }

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

export const api = {
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
  /** 탭 복귀 시 전체 상태 재동기화 */
  state: () => fetch('/api/state').then((r) => r.json()),
}

export type DemoMode = 'scenario' | 'realtime'

export interface ModeStatus {
  running?: boolean
  sim_running?: boolean
  mode: DemoMode
  live_squads: string[]
  mock_squads: string[]
  mock_gps?: string[]
  hw_relpos?: string[]
  period_s: number
  note: string
  router: {
    connected: boolean
    clients: number
    last_rx: number | null
    rx_count: number
    hw_squad: string
    hw_units: string[]
    mock_gps?: string[]
    period_s: number
  }
}

/**
 * WebSocket 연결 + 자동 재접속.
 * - 프레임마다 패치를 병합해 렌더 폭풍 방지
 * - 백그라운드 탭에서는 적용을 건너뛰고, 복귀 시 /api/state 로 재동기화
 *   (숨김 중 쌓인 수천 개 위치 패치가 메인 스레드를 멈추는 문제 방지)
 */
export function useCopSocket() {
  useEffect(() => {
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
      // rAF는 백그라운드에서 멈추므로 setTimeout 사용. 한 프레임 분량으로 묶음.
      flushTimer = setTimeout(flush, 50)
    }

    const enqueue = (m: ServerMsg) => {
      if (document.visibilityState !== 'visible') {
        dirtyWhileHidden = true
        return
      }
      queue.push(m)
      // 스냅샷은 즉시 (앞에 쌓인 패치 폐기)
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
        // fetch 실패 시 WS 재연결로 스냅샷 수신
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
        } catch { /* ignore malformed */ }
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
        // 숨김 전환: 대기열 비우고 이후 메시지는 dirty 플래그만
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
