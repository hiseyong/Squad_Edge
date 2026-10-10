import { useMemo, useState } from 'react'
import { api } from '../api'
import { useCop } from '../store'
import { useNow } from '../lib/useNow'
import { ago, ORDER_META, ORDER_STATUS } from '../lib/format'
import { toMgrs } from '../lib/geo'
import type { Order, OrderCode } from '../types'

const CODES: OrderCode[] = ['HALT', 'MOVE', 'RALLY', 'TAKE_COVER', 'WEAPONS_HOLD', 'WEAPONS_FREE', 'FRAGO']
const GROUPS: { key: string; label: string }[] = [
  { key: '*', label: '전 소대' }, { key: 'HQ', label: '본부' },
  { key: '1', label: '1분대' }, { key: '2', label: '2분대' }, { key: '3', label: '3분대' },
]

function toLabel(to: string[], name: (id: string) => string) {
  if (to.includes('*')) return '전 소대'
  return to.map((x) => (x === 'HQ' ? '본부' : /^\d$/.test(x) ? `${x}분대` : name(x))).join(', ')
}

function OrderRow({ o, now }: { o: Order; now: number }) {
  const units = useCop((s) => s.units)
  const flyTo = useCop((s) => s.flyTo)
  const name = (id: string) => units[id]?.callsign ?? id
  const meta = ORDER_META[o.code]
  const st = ORDER_STATUS[o.status]
  const n = o.recipients.length
  const k = Object.keys(o.acks).length
  const missing = o.recipients.filter((r) => !(r in o.acks))
  const live = o.status === 'sent' || o.status === 'partial' || o.status === 'expired'
  const canRevoke = o.status === 'sent' || o.status === 'partial' || o.status === 'acked' || o.status === 'expired'
  const dead = o.status === 'cancelled' || o.status === 'superseded'

  return (
    <div className={`prisma-card px-2 py-1.5 text-[11px] ${dead ? 'opacity-40' : ''}`}>
      <div className="flex items-center gap-1.5">
        <span className={`px-1.5 text-[10px] font-bold text-white ${meta?.cls.split(' ')[0] ?? 'bg-prisma-elevated'}`}>
          {meta?.label ?? o.code}
        </span>
        <span className="truncate text-prisma-fg" title={o.text}>{o.text}</span>
        <span className="ml-auto shrink-0 font-mono text-[10px] text-prisma-dim">{ago(o.ts, now)}</span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <span className="shrink-0 text-[10px] text-prisma-dim">→ {toLabel(o.to, name)}</span>
        <div className="h-1 flex-1 overflow-hidden bg-prisma-void" title={`수신 확인 ${k}/${n}`}>
          <div
            className={`h-full ${o.status === 'acked' ? 'bg-prisma-ok' : o.status === 'expired' ? 'bg-prisma-danger' : 'bg-prisma-intent'}`}
            style={{ width: `${n ? (k / n) * 100 : 0}%` }}
          />
        </div>
        <span className={`shrink-0 font-mono text-[10px] ${st.cls}`}>{st.label} {k}/{n}</span>
      </div>
      {live && missing.length > 0 && (
        <div className="mt-1 flex items-center gap-1 text-[10px]">
          <span className="text-prisma-dim">미수신</span>
          <span className="truncate text-prisma-warn">{missing.map(name).join(', ')}</span>
          {o.tx_count > 1 && <span className="shrink-0 text-prisma-dim">· 재전송 {o.tx_count - 1}</span>}
          <span className="ml-auto" />
          <button type="button" className="prisma-btn !px-1.5 !py-0 !text-[10px]" onClick={() => api.resendOrder(o.id)}>재하달</button>
        </div>
      )}
      <div className="mt-0.5 flex items-center gap-2 text-[10px]">
        {o.params.lat != null && (
          <button type="button" className="font-mono text-prisma-accent hover:text-prisma-fg" onClick={() => flyTo(o.params.lat!, o.params.lon!)}>
            ◎ {toMgrs(o.params.lat, o.params.lon!)}
          </button>
        )}
        {canRevoke && (
          <button
            type="button"
            className="ml-auto text-prisma-dim hover:text-prisma-danger"
            onClick={() => api.cancelOrder(o.id)}
            title={o.code === 'RALLY' ? '집결 명령 철회' : '명령 철회 / 무효화'}
          >
            철회
          </button>
        )}
      </div>
    </div>
  )
}

/** 지도 하단 명령 하달 패널: 수신 대상 · 명령 · 지점 · 내용 → 하달, 오른쪽에 수신 확인(ACK) 현황 */
export default function OrderPanel() {
  const orders = useCop((s) => s.orders)
  const units = useCop((s) => s.units)
  const selectedUnit = useCop((s) => s.selectedUnit)
  const pickMode = useCop((s) => s.pickMode)
  const setPickMode = useCop((s) => s.setPickMode)
  const point = useCop((s) => s.orderPoint)
  const setPoint = useCop((s) => s.setOrderPoint)
  const now = useNow()

  const [open, setOpen] = useState(true)
  const [to, setTo] = useState<string[]>(['*'])
  const [code, setCode] = useState<OrderCode>('HALT')
  const [text, setText] = useState('')
  const [urgent, setUrgent] = useState(false)
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const meta = ORDER_META[code]
  const sel = selectedUnit ? units[selectedUnit] : undefined
  const list = useMemo(() => Object.values(orders).filter((o) => o.code !== 'RECHECK' || o.status !== 'acked')
    .sort((a, b) => b.ts - a.ts).slice(0, 30), [orders])
  const activeCount = Object.values(orders).filter((o) => o.status === 'sent' || o.status === 'partial').length

  const toggleTo = (k: string) => {
    if (k === '*') return setTo(['*'])
    setTo((cur) => {
      const base = cur.filter((x) => x !== '*')
      const next = base.includes(k) ? base.filter((x) => x !== k) : [...base, k]
      return next.length ? next : ['*']
    })
  }

  const canSend = to.length > 0 && (!meta.needsPoint || point) && (code !== 'FRAGO' || text.trim())

  const send = async () => {
    if (!canSend) return
    setBusy(true); setMsg(null)
    try {
      const o = await api.issueOrder({
        code, to, text: text.trim() || `${toLabel(to, (id) => units[id]?.callsign ?? id)} ${meta.hint}`,
        params: meta.needsPoint && point ? { lat: point[0], lon: point[1] } : {},
        priority: urgent ? 'urgent' : 'priority',
      })
      setMsg({
        ok: true,
        text: `하달 완료 — 분대장 ${o.recipients.length}명에게 송신 (분대원 개별 전송 없음)`,
      })
      setText('')
      if (meta.needsPoint) setPoint(null)
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message })
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="shrink-0 border-t border-prisma-border bg-prisma-panel">
      <button type="button" className="flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-prisma-hover" onClick={() => setOpen(!open)}>
        <span className="panel-title !border-0 !bg-transparent !p-0">Orders</span>
        {activeCount > 0 && (
          <span className="prisma-chip prisma-chip-on">{activeCount} pending ack</span>
        )}
        <span className="ml-auto text-[10px] uppercase tracking-wider text-prisma-dim">{open ? 'Collapse' : 'Expand'}</span>
      </button>
      {open && (
        <div className="grid h-[178px] grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] gap-3 border-t border-prisma-line px-3 pb-2 pt-2">
          <div className="flex min-w-0 flex-col gap-1.5">
            <div className="flex flex-wrap items-center gap-1">
              <span className="w-8 text-[10px] uppercase tracking-wider text-prisma-dim">To</span>
              {GROUPS.map((g) => (
                <button
                  key={g.key}
                  type="button"
                  onClick={() => toggleTo(g.key)}
                  className={`prisma-chip ${to.includes(g.key) ? 'prisma-chip-on' : ''}`}
                >
                  {g.label}
                </button>
              ))}
              {sel && sel.role !== 'pl' && (
                <button
                  type="button"
                  onClick={() => toggleTo(sel.id)}
                  className={`prisma-chip border-dashed ${to.includes(sel.id) ? 'prisma-chip-on' : ''}`}
                >
                  선택: {sel.callsign}
                </button>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-1">
              <span className="w-8 text-[10px] uppercase tracking-wider text-prisma-dim">Cmd</span>
              {CODES.map((c) => (
                <button
                  key={c}
                  type="button"
                  onClick={() => setCode(c)}
                  className={`px-2 py-0.5 text-[11px] font-semibold text-white transition ${ORDER_META[c].cls} ${
                    code === c ? 'outline outline-1 outline-offset-1 outline-prisma-fg/70' : 'opacity-55 hover:opacity-90'
                  }`}
                >
                  {ORDER_META[c].label}
                </button>
              ))}
            </div>
            {meta.needsPoint && (
              <div className="flex items-center gap-1.5 text-[11px]">
                <span className="w-8 text-[10px] uppercase tracking-wider text-prisma-dim">Pt</span>
                <button
                  type="button"
                  onClick={() => setPickMode(!pickMode)}
                  className={`prisma-btn ${pickMode ? 'prisma-btn-primary animate-pulse' : ''}`}
                >
                  {pickMode ? '지도를 클릭하세요…' : point ? '다시 지정' : '지도에서 지정'}
                </button>
                {point && <span className="font-mono text-prisma-accent">{toMgrs(point[0], point[1])}</span>}
                {point && (
                  <button type="button" className="text-prisma-dim hover:text-prisma-fg" onClick={() => setPoint(null)}>✕</button>
                )}
              </div>
            )}
            <div className="flex items-center gap-1.5">
              <span className="w-8 text-[10px] uppercase tracking-wider text-prisma-dim">Txt</span>
              <input
                value={text}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => { if (e.key === 'Enter') send() }}
                placeholder={code === 'FRAGO' ? '단편명령 내용 입력 (필수)' : `${meta.hint} (비우면 기본 문구)`}
                className="prisma-input min-w-0 flex-1"
              />
              <label className="flex items-center gap-1 text-[10px] text-prisma-dim">
                <input type="checkbox" checked={urgent} onChange={(e) => setUrgent(e.target.checked)} className="accent-prisma-danger" />
                긴급
              </label>
              <button type="button" disabled={!canSend || busy} onClick={send} className="prisma-btn prisma-btn-primary !px-3 !font-bold">
                {busy ? '송신…' : '하달'}
              </button>
            </div>
            {msg && <div className={`text-[10px] ${msg.ok ? 'text-prisma-ok' : 'text-prisma-danger'}`}>{msg.text}</div>}
          </div>
          <div className="min-h-0 space-y-1 overflow-y-auto pr-1">
            {list.length === 0 && (
              <div className="pt-6 text-center text-[11px] uppercase tracking-wider text-prisma-dim">No orders</div>
            )}
            {list.map((o) => <OrderRow key={o.id} o={o} now={now} />)}
          </div>
        </div>
      )}
    </section>
  )
}
