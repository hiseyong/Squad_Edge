/** UI mockup용 API — fetch/WS 없이 스토어만 갱신 */
import { useCop } from '../store'
import type { DecisionAction, Order, OrderCode, Report, ServerMsg } from '../types'
import type { BriefEvent, DemoMode, LlmStatus, ModeStatus } from '../apiTypes'
import { MOCK_BRIEF } from './seed'
import { resetMockup } from './engine'

function uid(prefix: string) {
  return `${prefix}-${Math.random().toString(16).slice(2, 8)}`
}

function modeStatus(): ModeStatus {
  const { demoMode, routerConnected, mission } = useCop.getState()
  return {
    sim_running: true,
    running: true,
    mode: demoMode,
    live_squads: demoMode === 'realtime' ? ['1'] : [],
    mock_squads: demoMode === 'realtime' ? ['HQ', '2', '3'] : ['HQ', '1', '2', '3'],
    mock_gps: [],
    hw_relpos: demoMode === 'realtime' ? ['1-2', '1-3', '1-4'] : [],
    period_s: 1,
    note: 'UI MOCKUP — 백엔드 없음 · 로컬 시드 데이터',
    router: {
      connected: routerConnected,
      clients: routerConnected ? 1 : 0,
      last_rx: Date.now() / 1000,
      rx_count: 42,
      hw_squad: '1',
      hw_units: ['1-1', '1-2', '1-3', '1-4'],
      mock_gps: [],
      period_s: 1,
    },
  }
  void mission
}

const llm: LlmStatus = {
  enabled: true,
  available: false,
  url: 'mockup://local',
  api: 'mock',
  model: null,
  models: [],
  error: 'UI mockup — 규칙 기반 브리핑만',
}

export const mockApi = {
  async decide(id: string, action: DecisionAction, note = '', edits?: Record<string, unknown>) {
    const { reports, apply } = useCop.getState()
    const r = reports[id]
    if (!r) throw new Error('report not found')
    const ts = Date.now() / 1000
    let next: Report = { ...r }
    if (edits?.summary && typeof edits.summary === 'string') next.summary = edits.summary
    if (edits?.priority && typeof edits.priority === 'string') {
      next.priority = edits.priority as Report['priority']
    }
    if (edits?.fields && typeof edits.fields === 'object') {
      next.fields = { ...next.fields, ...(edits.fields as Record<string, unknown>) }
    }
    if (action === 'confirm') {
      next = { ...next, status: 'confirmed', decided_by: 'PL', decided_at: ts, decision_note: note, sender_acked: true }
    } else if (action === 'reject') {
      next = { ...next, status: 'rejected', decided_by: 'PL', decided_at: ts, decision_note: note }
    } else if (action === 'recheck') {
      next = { ...next, recheck_count: next.recheck_count + 1, decision_note: note }
    } else if (action === 'reopen') {
      next = { ...next, status: 'pending', decided_by: null, decided_at: null, decision_note: '' }
    }
    next.history = [...next.history, { ts, action, by: 'PL', note, edits }]
    apply({ t: 'patch', c: 'reports', op: 'upsert', v: next } as ServerMsg)
    return next
  },

  async issueOrder(o: {
    code: OrderCode; to: string[]; text?: string; params?: Record<string, unknown>; priority?: string
  }) {
    const { units, apply } = useCop.getState()
    const ts = Date.now() / 1000
    const recipients = Object.values(units)
      .filter((u) => {
        if (o.to.includes('*')) return u.role !== 'pl'
        if (o.to.includes(u.squad)) return true
        return o.to.includes(u.id)
      })
      .map((u) => u.id)
    const order: Order = {
      id: uid('O'),
      code: o.code,
      text: o.text || o.code,
      to: o.to,
      recipients,
      params: (o.params ?? {}) as Order['params'],
      priority: (o.priority as Order['priority']) || 'priority',
      issuer: 'PL',
      ts,
      acks: {},
      status: 'sent',
      ref_report: null,
      tx_count: 1,
      last_tx: ts,
    }
    apply({ t: 'patch', c: 'orders', op: 'upsert', v: order } as ServerMsg)
    // 데모: 잠시 후 일부 ACK
    setTimeout(() => {
      const cur = useCop.getState().orders[order.id]
      if (!cur || cur.status === 'cancelled') return
      const acks = { ...cur.acks }
      for (const id of recipients.slice(0, Math.ceil(recipients.length * 0.7))) {
        if (useCop.getState().units[id]?.status !== 'nolink') acks[id] = Date.now() / 1000
      }
      const n = Object.keys(acks).length
      useCop.getState().apply({
        t: 'patch', c: 'orders', op: 'upsert',
        v: {
          ...cur, acks,
          status: n >= recipients.length ? 'acked' : n ? 'partial' : 'sent',
        },
      } as ServerMsg)
    }, 1500)
    return order
  },

  async cancelOrder(id: string) {
    const { orders, apply } = useCop.getState()
    const o = orders[id]
    if (!o) throw new Error('order not found')
    const next = { ...o, status: 'cancelled' as const }
    apply({ t: 'patch', c: 'orders', op: 'upsert', v: next } as ServerMsg)
    return next
  },

  async resendOrder(id: string) {
    const { orders, apply } = useCop.getState()
    const o = orders[id]
    if (!o) throw new Error('order not found')
    const next = { ...o, tx_count: o.tx_count + 1, last_tx: Date.now() / 1000, status: 'sent' as const }
    apply({ t: 'patch', c: 'orders', op: 'upsert', v: next } as ServerMsg)
    return next
  },

  async llmStatus() { return { ...llm } },
  async setModel(model: string) { return { ...llm, model } },

  async *briefStream(question: string | undefined, _useLlm: boolean, signal?: AbortSignal): AsyncGenerator<BriefEvent> {
    yield { type: 'meta', engine: 'mockup-rules', facts: '시드 유닛/보고/경보 요약', reason: 'UI mockup' }
    const text = question?.trim()
      ? `Q. ${question}\n\n(데모) 로컬 시드 기준 답변입니다. 아군 다수 정상, 부상·두절 각 1, 적 표적 2건.`
      : MOCK_BRIEF
    const parts = text.match(/.{1,12}/g) ?? [text]
    let acc = ''
    for (const p of parts) {
      if (signal?.aborted) throw new DOMException('aborted', 'AbortError')
      acc += p
      yield { type: 'token', text: p }
      await new Promise((r) => setTimeout(r, 28))
    }
    yield { type: 'done', text: acc, latency: 0.4 }
  },

  async ackAlert(id: string) {
    const a = useCop.getState().alerts[id]
    if (a) useCop.getState().apply({ t: 'patch', c: 'alerts', op: 'upsert', v: { ...a, ack: true } } as ServerMsg)
  },

  async ackAll() {
    const { alerts, applyBatch } = useCop.getState()
    applyBatch(Object.values(alerts).map((a) => ({
      t: 'patch' as const, c: 'alerts' as const, op: 'upsert' as const, v: { ...a, ack: true },
    } as ServerMsg)))
  },

  async setEmcon(on: boolean) {
    const m = useCop.getState().mission
    if (m) useCop.getState().apply({ t: 'mission', v: { ...m, emcon: on } })
  },

  async sim(action: 'start' | 'stop' | 'restart') {
    if (action === 'restart' || action === 'start') resetMockup()
    return modeStatus()
  },

  async simStatus() { return modeStatus() },
  async modeStatus() { return modeStatus() },

  async setMode(mode: DemoMode) {
    const router = mode === 'realtime' ? false : true
    useCop.getState().setDemoLink(mode, router)
    // realtime 데모: 1분대를 두절로 보여 줌
    if (mode === 'realtime') {
      const { units, applyBatch } = useCop.getState()
      applyBatch(
        Object.values(units)
          .filter((u) => u.squad === '1')
          .map((u) => ({
            t: 'patch' as const, c: 'units' as const, op: 'upsert' as const,
            v: { ...u, status: 'nolink' as const, lat: null, lon: null },
          } as ServerMsg)),
      )
    } else {
      resetMockup()
    }
    return modeStatus()
  },

  async briefing(question?: string) {
    return { text: question ? `(데모) ${question}` : MOCK_BRIEF, engine: 'mockup' }
  },

  async ingest() { return { ok: true } },
  async state() {
    const s = useCop.getState()
    return {
      units: Object.values(s.units),
      targets: Object.values(s.targets),
      reports: Object.values(s.reports),
      sensors: Object.values(s.sensors),
      links: Object.values(s.links),
      alerts: Object.values(s.alerts),
      orders: Object.values(s.orders),
      mission: s.mission,
      stats: s.stats,
      server_time: Date.now() / 1000,
    }
  },
}
