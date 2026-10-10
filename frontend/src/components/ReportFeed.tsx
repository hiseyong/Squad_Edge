import { useMemo, useState } from 'react'
import { api } from '../api'
import { useCop } from '../store'
import { useNow } from '../lib/useNow'
import { ago, DECISION_LABEL, hhmmss, REPORT_STYLE } from '../lib/format'
import { toMgrs } from '../lib/geo'
import type { DecisionAction, Report } from '../types'
import { IconReportType } from './icons'

const FIELD_KO: Record<string, string> = {
  size: '규모(S)', activity: '활동(A)', location: '위치(L)', unit: '부대(U)', time: '시간(T)', equipment: '장비(E)',
  kind: '유형', position: '위치', casualties: '인원손실', ammo: '탄약', intent: '의도',
  friendly: '아군', enemy: '적', action: '조치', requests: '요청', judgment: '판단', points: '요점',
  battle_id: '전투ID', result: '결과',
}
const KIND_KO: Record<string, string> = { infantry: '보병', vehicle: '차량', sniper: '저격수', movement: '움직임' }
const EDITABLE_SALUTE = ['size', 'activity', 'unit', 'equipment'] as const
const HIDDEN_FIELDS = new Set(['_format', 'points', 'judgment', 'battle'])

type BattlePayload = {
  battle_id?: string
  unit?: string
  summary?: string
  result?: Record<string, number>
  enemy?: Array<{
    tid?: number; count?: number; reporters?: string[]
    first?: string; last?: string
    loc?: { mgrs?: string; err_m?: number }
  }>
  soldiers?: Record<string, {
    casualty?: boolean; ammo_issue?: boolean; last_report?: string | null
    pos?: { mgrs?: string }
  }>
  leader_track?: Array<{ t?: string; mgrs?: string }>
  minutes?: string[]
}

function BattleBody({ battle, rawText }: { battle: BattlePayload; rawText: string }) {
  const res = battle.result ?? {}
  const enemies = Array.isArray(battle.enemy) ? battle.enemy : []
  const soldiers = battle.soldiers && typeof battle.soldiers === 'object' ? Object.entries(battle.soldiers) : []
  const minutes = Array.isArray(battle.minutes) ? battle.minutes : []
  const track = Array.isArray(battle.leader_track) ? battle.leader_track : []

  return (
    <div className="mt-1.5 space-y-2 text-[11px]">
      {(battle.battle_id || battle.unit) && (
        <div className="flex flex-wrap gap-2 text-[10px] text-prisma-dim">
          {battle.battle_id && <span className="font-mono">{battle.battle_id}</span>}
          {battle.unit && <span>{battle.unit}</span>}
        </div>
      )}
      {Object.keys(res).length > 0 && (
        <div className="flex flex-wrap gap-1">
          {[
            ['적표적', res.enemy_tracks],
            ['접적보고', res.contact_reports_up ?? res.soldier_reports],
            ['명령', res.commands],
            ['부상', res.casualties],
            ['미ACK', res.unacked],
          ].filter(([, v]) => v != null).map(([k, v]) => (
            <span key={String(k)} className="border border-prisma-border bg-prisma-void/60 px-1.5 font-mono text-[10px] text-prisma-muted">
              {k} {v}
            </span>
          ))}
        </div>
      )}
      {enemies.length > 0 && (
        <div>
          <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-prisma-dim">적</div>
          <ul className="space-y-0.5 text-prisma-muted">
            {enemies.map((e, i) => (
              <li key={e.tid ?? i}>
                적{e.tid ?? i + 1}: {e.count ?? '?'}명
                {e.reporters?.length ? ` (${e.reporters.join(', ')})` : ''}
                {e.first || e.last ? ` ${e.first ?? ''}~${e.last ?? ''}` : ''}
                {e.loc?.mgrs ? ` / ${e.loc.mgrs}` : ''}
                {e.loc?.err_m != null ? ` ±${e.loc.err_m}m` : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
      {soldiers.length > 0 && (
        <div>
          <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-prisma-dim">아군</div>
          <ul className="space-y-0.5 font-mono text-[10px] text-prisma-muted">
            {soldiers.map(([id, s]) => (
              <li key={id}>
                {id}{s.pos?.mgrs ? ` @${s.pos.mgrs}` : ''}
                {s.casualty ? ' · 부상' : ''}
                {s.ammo_issue ? ' · 탄약' : ''}
              </li>
            ))}
          </ul>
        </div>
      )}
      {track.length > 0 && (
        <div className="text-[10px] text-prisma-dim">
          분대장 위치: {track[track.length - 1]?.mgrs ?? '—'}
          <span className="text-prisma-dim"> (기록 {track.length}점)</span>
        </div>
      )}
      {minutes.length > 0 && (
        <div>
          <div className="mb-0.5 text-[10px] font-semibold uppercase tracking-wider text-prisma-dim">무전 회의록</div>
          <ol className="max-h-40 space-y-0.5 overflow-y-auto border-l border-prisma-border pl-2 font-mono text-[10px] text-prisma-muted">
            {minutes.map((m, i) => <li key={i} className="whitespace-pre-wrap">{m}</li>)}
          </ol>
        </div>
      )}
      {rawText && (
        <details className="group">
          <summary className="cursor-pointer text-[10px] text-prisma-dim hover:text-prisma-fg">전문 텍스트</summary>
          <pre className="mt-1 max-h-48 overflow-y-auto whitespace-pre-wrap bg-prisma-void/70 px-2 py-1 text-[10px] text-prisma-muted">
            {rawText}
          </pre>
        </details>
      )}
    </div>
  )
}

function fieldValue(k: string, v: unknown) {
  if (v === null || v === undefined || v === '') return <span className="text-prisma-danger">누락</span>
  if (k === 'location' && typeof v === 'object') {
    const l = v as { lat?: number; lon?: number; bearing?: number; dist?: number; err?: number; mgrs?: string }
    if (l.mgrs) return <span className="font-mono">{l.mgrs}{l.err ? ` ±${l.err}m` : ''}</span>
    if (l.lat != null) return <span className="font-mono">{toMgrs(l.lat, l.lon!)}{l.err ? ` ±${l.err}m` : ''}</span>
    return `${l.bearing?.toFixed?.(0) ?? l.bearing}° ${l.dist}m`
  }
  if (k === 'friendly' && typeof v === 'object' && v) {
    const f = v as { available?: number; total?: number; casualties?: number[]; mgrs?: string; heading?: number; ammo_issue?: unknown[] }
    const cas = (f.casualties ?? []).length ? ` · 부상 ${(f.casualties ?? []).join(',')}` : ''
    const ammo = (f.ammo_issue ?? []).length ? ' · 탄약문제' : ''
    return `${f.available ?? '?'}/${f.total ?? '?'} 가용${cas}${ammo}${f.mgrs ? ` · ${f.mgrs}` : ''}`
  }
  if (k === 'enemy' && Array.isArray(v)) {
    return (
      <ul className="space-y-0.5">
        {v.map((e, i) => {
          const o = e as { count?: number; activity?: string[]; mgrs?: string; err_m?: number; basis?: string }
          const act = Array.isArray(o.activity) ? o.activity.join(', ') : ''
          return (
            <li key={i} className="text-prisma-muted">
              {o.count ?? '?'}명 {act}{o.mgrs ? ` · ${o.mgrs}` : ''}{o.err_m != null ? ` ±${o.err_m}m` : ''}
              {o.basis ? <span className="text-prisma-dim"> ({o.basis})</span> : null}
            </li>
          )
        })}
      </ul>
    )
  }
  if ((k === 'action' || k === 'requests') && Array.isArray(v)) return v.join(' · ')
  if (k === 'kind') return KIND_KO[String(v)] ?? String(v)
  if (typeof v === 'object') return <span className="font-mono text-[10px]">{JSON.stringify(v)}</span>
  return String(v)
}

/** 승인 전 AI 추출값 수정 폼 */
function EditForm({ r, onCancel, onSubmit, busy }: {
  r: Report; busy: boolean
  onCancel: () => void
  onSubmit: (edits: Record<string, unknown>, note: string) => void
}) {
  const [summary, setSummary] = useState(r.summary)
  const [priority, setPriority] = useState(r.priority)
  const [fields, setFields] = useState<Record<string, unknown>>(() => {
    if (r.type === 'MEDEVAC' || r.type === 'SITREP' || r.type === 'FREE')
      return Object.fromEntries(Object.entries(r.fields).filter(([k]) => k !== 'location'))
    const o: Record<string, unknown> = {}
    for (const k of [...EDITABLE_SALUTE, 'kind']) o[k] = r.fields[k] ?? ''
    return o
  })
  const [note, setNote] = useState('')
  const set = (k: string, v: unknown) => setFields((f) => ({ ...f, [k]: v }))

  const submit = () => {
    const changed: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(fields)) {
      const nv = k === 'size' && v !== '' && v !== null ? Number(v) : v === '' ? null : v
      if (JSON.stringify(nv) !== JSON.stringify(r.fields[k] ?? null)) changed[k] = nv
    }
    const edits: Record<string, unknown> = {}
    if (Object.keys(changed).length) edits.fields = changed
    if (summary !== r.summary) edits.summary = summary
    if (priority !== r.priority) edits.priority = priority
    onSubmit(edits, note)
  }

  const input = 'prisma-input !text-[11px]'
  return (
    <div className="prisma-card mt-2 space-y-1.5 border-prisma-accent/40 bg-prisma-accent/5 p-2">
      <div className="text-[10px] font-semibold uppercase tracking-wider text-prisma-accent">AI 추출값 수정 후 승인</div>
      <label className="block text-[10px] text-prisma-dim">요약
        <input className={input} value={summary} onChange={(e) => setSummary(e.target.value)} />
      </label>
      <div className="grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-1">
        {Object.entries(fields).map(([k, v]) => (
          <div key={k} className="contents">
            <span className="text-[10px] text-prisma-dim">{FIELD_KO[k] ?? k}</span>
            {k === 'kind' ? (
              <select className={input} value={String(v ?? 'infantry')} onChange={(e) => set(k, e.target.value)}>
                {Object.entries(KIND_KO).map(([val, l]) => <option key={val} value={val}>{l}</option>)}
              </select>
            ) : (
              <input className={`${input} ${v === null || v === '' ? '!border-prisma-danger/60' : ''}`}
                type={k === 'size' ? 'number' : 'text'} value={v == null ? '' : String(v)}
                placeholder={v === null ? '누락 — 입력' : ''} onChange={(e) => set(k, e.target.value)} />
            )}
          </div>
        ))}
        <span className="text-[10px] text-prisma-dim">우선순위</span>
        <select className={input} value={priority} onChange={(e) => setPriority(e.target.value as Report['priority'])}>
          <option value="routine">일반</option><option value="priority">우선</option><option value="urgent">긴급</option>
        </select>
      </div>
      <input className={input} value={note} onChange={(e) => setNote(e.target.value)} placeholder="결심 메모 (선택)" />
      <div className="flex justify-end gap-1.5">
        <button type="button" className="prisma-btn !py-0.5" onClick={onCancel}>취소</button>
        <button type="button" disabled={busy} className="prisma-btn-primary prisma-btn !py-0.5" onClick={submit}>
          수정 반영 + 승인
        </button>
      </div>
    </div>
  )
}

function ReportCard({ r, now }: { r: Report; now: number }) {
  const isBattle = r.type === 'BATTLE_DATA' || r.fields['_format'] === 'sq-battle/0.1'
  const battle = (r.fields.battle && typeof r.fields.battle === 'object'
    ? r.fields.battle : null) as BattlePayload | null
  const [open, setOpen] = useState(
    r.type === 'MEDEVAC' || r.type === 'SPOTREP+SITREP' || r.status === 'pending' || isBattle,
  )
  const [mode, setMode] = useState<'view' | 'edit' | 'note'>('view')
  const [pendingAction, setPendingAction] = useState<DecisionAction | null>(null)
  const [note, setNote] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [showHist, setShowHist] = useState(false)
  const units = useCop((s) => s.units)
  const targets = useCop((s) => s.targets)
  const flyTo = useCop((s) => s.flyTo)
  const selectTarget = useCop((s) => s.selectTarget)
  const st = REPORT_STYLE[r.type] ?? REPORT_STYLE.FREE
  const name = (id: string | null) => (id ? units[id]?.callsign ?? id : '—')
  const tgt = r.target_id ? targets[r.target_id] : undefined
  const isDraft = r.type === 'SPOTREP+SITREP' || r.fields['_format'] === 'draft-1'

  const act = async (action: DecisionAction, n = '', edits?: Record<string, unknown>) => {
    setBusy(true); setErr(null)
    try {
      await api.decide(r.id, action, n, edits)
      setMode('view'); setNote(''); setPendingAction(null)
    } catch (e) {
      setErr((e as Error).message)
    } finally {
      setBusy(false)
    }
  }
  /** 기각·재확인은 사유 입력 단계를 거친다 */
  const ask = (a: DecisionAction) => { setPendingAction(a); setMode('note') }

  const decisionColor = r.status === 'confirmed' ? 'text-prisma-ok' : r.status === 'rejected' ? 'text-prisma-dim' : 'text-prisma-warn'

  return (
    <div className={`prisma-card mx-2 mb-2 p-2 text-xs ${
      r.priority === 'urgent' && r.status !== 'rejected' ? 'border-prisma-hostile/60' : r.status === 'pending' ? 'border-prisma-warn/50 border-dashed' : ''
    } ${r.status === 'rejected' ? 'opacity-50' : ''}`}>
      <div className="flex items-center gap-1.5">
        <span className={`inline-flex items-center gap-1 border px-1.5 py-px text-[10px] font-bold tracking-wide ${st.cls}`}>
          <IconReportType type={r.type} size={10} />
          {st.label}
        </span>
        {r.priority !== 'routine' && (
          <span className={`text-[10px] font-bold uppercase tracking-wider ${r.priority === 'urgent' ? 'text-prisma-hostile' : 'text-orange-300'}`}>
            {r.priority === 'urgent' ? '긴급' : '우선'}
          </span>
        )}
        <span className="text-prisma-muted">{name(r.sender)}</span>
        {r.recheck_count > 0 && <span className="bg-prisma-elevated px-1 font-mono text-[9px] text-prisma-muted">재확인 {r.recheck_count}</span>}
        <span className="ml-auto font-mono text-[10px] text-prisma-dim" title={hhmmss(r.ts)}>{ago(r.ts, now)}</span>
      </div>

      <button type="button" className={`mt-1 block w-full text-left font-medium hover:text-prisma-accent ${r.status === 'rejected' ? 'text-prisma-dim line-through' : 'text-prisma-fg'}`}
        onClick={() => {
          setOpen(!open)
          if (tgt) { flyTo(tgt.lat, tgt.lon); selectTarget(tgt.id) }
        }}>
        {r.summary || r.raw_text}
      </button>

      {open && mode !== 'edit' && (
        <div className="mt-1.5 space-y-1.5">
          {isBattle && battle ? (
            <BattleBody battle={battle} rawText={r.raw_text} />
          ) : (
            <>
              {r.raw_text && (
                <div className="bg-prisma-void/70 px-2 py-1 text-[11px] italic text-prisma-muted">
                  <span className="mr-1 not-italic text-prisma-dim">STT</span>“{r.raw_text}”
                </div>
              )}
              {Object.keys(r.fields).length > 0 && (
                <div className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5 text-[11px]">
                  {Object.entries(r.fields)
                    .filter(([k]) => !HIDDEN_FIELDS.has(k))
                    .map(([k, v]) => (
                    <div key={k} className="contents">
                      <span className="text-prisma-dim">{FIELD_KO[k] ?? k}</span>
                      <span className="text-prisma-muted">{fieldValue(k, v)}</span>
                    </div>
                  ))}
                </div>
              )}
              {isDraft && (
                <div className="text-[9px] uppercase tracking-wider text-prisma-dim">분대장 draft-1</div>
              )}
              {r.missing.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  {r.missing.map((m) => (
                    <span key={m} className="border border-prisma-danger/40 bg-prisma-danger/10 px-1.5 text-[10px] text-prisma-danger">누락: {m}</span>
                  ))}
                </div>
              )}
              <div className="flex items-center gap-2">
                <div className="h-1 flex-1 bg-prisma-void" title="AI 추출 신뢰도">
                  <div className={`h-full ${r.conf >= 0.7 ? 'bg-prisma-ok' : 'bg-prisma-warn'}`} style={{ width: `${r.conf * 100}%` }} />
                </div>
                <span className="font-mono text-[10px] text-prisma-dim">신뢰도 {(r.conf * 100).toFixed(0)}%</span>
              </div>
            </>
          )}
          {isBattle && !battle && r.raw_text && (
            <pre className="max-h-56 overflow-y-auto whitespace-pre-wrap bg-prisma-void/70 px-2 py-1 text-[10px] text-prisma-muted">
              {r.raw_text}
            </pre>
          )}
        </div>
      )}

      {mode === 'edit' && (
        <EditForm r={r} busy={busy} onCancel={() => setMode('view')} onSubmit={(edits, n) => act('confirm', n, edits)} />
      )}

      {/* 결심 상태 */}
      {r.status !== 'pending' && r.decided_at && (
        <div className="mt-1.5 flex items-center gap-1.5 text-[10px]">
          <span className={decisionColor}>{r.status === 'confirmed' ? '✔ 승인' : '✖ 기각'}</span>
          <span className="text-prisma-dim">{name(r.decided_by)} · {hhmmss(r.decided_at)}</span>
          {r.decision_note && <span className="truncate text-prisma-muted">“{r.decision_note}”</span>}
          <span className={`ml-auto ${r.sender_acked ? 'text-prisma-ok' : 'text-prisma-dim'}`}
            title="결심 결과가 보고자 단말에 도달했는지">
            {r.sender_acked ? '단말 수신 ✓' : '단말 전송 중…'}
          </span>
        </div>
      )}

      {mode === 'note' && pendingAction && (
        <div className="mt-2 flex gap-1">
          <input autoFocus value={note} onChange={(e) => setNote(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') act(pendingAction, note) }}
            placeholder={pendingAction === 'reject' ? '기각 사유 (예: 중복 보고, 오인)' : '재확인 요청 내용 (예: 차량 종류 확인)'}
            className="prisma-input min-w-0 flex-1 !text-[11px]" />
          <button type="button" disabled={busy} onClick={() => act(pendingAction, note)}
            className={`prisma-btn !py-0.5 ${pendingAction === 'reject' ? 'prisma-btn-danger' : 'prisma-btn-primary'}`}>
            {pendingAction === 'reject' ? '기각' : '요청'}
          </button>
          <button type="button" onClick={() => { setMode('view'); setPendingAction(null) }} className="px-1 text-[11px] text-prisma-dim hover:text-prisma-fg">✕</button>
        </div>
      )}

      {mode === 'view' && !isBattle && (
        <div className="mt-2 flex flex-wrap items-center gap-1">
          {r.status === 'pending' ? (
            <>
              <span className="mr-auto text-[10px] text-prisma-warn">
                {r.conf < 0.7 ? '신뢰도 낮음 — 판단 필요' : '승인 대기'}
              </span>
              <button type="button" disabled={busy} className="prisma-btn prisma-btn-primary !py-0.5" onClick={() => act('confirm')}>승인</button>
              <button type="button" disabled={busy} className="prisma-btn !py-0.5" onClick={() => { setOpen(true); setMode('edit') }}>수정·승인</button>
              <button type="button" disabled={busy} className="prisma-btn !py-0.5" onClick={() => ask('recheck')}>재확인</button>
              <button type="button" disabled={busy} className="prisma-btn prisma-btn-danger !py-0.5" onClick={() => ask('reject')}>기각</button>
            </>
          ) : (
            <>
              {r.history.length > 0 && (
                <button type="button" className="text-[10px] text-prisma-dim hover:text-prisma-fg" onClick={() => setShowHist(!showHist)}>
                  이력 {r.history.length}
                </button>
              )}
              <span className="ml-auto" />
              {r.status === 'confirmed' && (
                <>
                  {r.missing.length > 0 && (
                    <button type="button" className="prisma-btn !px-1.5 !py-0.5 !text-[10px]" onClick={() => ask('recheck')}>
                      누락 재요청
                    </button>
                  )}
                  <button type="button" className="prisma-btn !px-1.5 !py-0.5 !text-[10px]" onClick={() => ask('reject')}>
                    오보 처리
                  </button>
                </>
              )}
              <button type="button" className="prisma-btn !px-1.5 !py-0.5 !text-[10px]" onClick={() => act('reopen')}>
                되돌리기
              </button>
            </>
          )}
        </div>
      )}
      {r.status === 'pending' && r.history.length > 0 && mode === 'view' && (
        <button type="button" className="mt-1 text-[10px] text-prisma-dim hover:text-prisma-fg" onClick={() => setShowHist(!showHist)}>
          이력 {r.history.length}
        </button>
      )}
      {showHist && (
        <ol className="mt-1 space-y-0.5 border-l border-prisma-border pl-2 text-[10px] text-prisma-muted">
          {r.history.map((h, i) => (
            <li key={i}>
              <span className="font-mono text-prisma-dim">{hhmmss(h.ts)}</span> {name(h.by)} — {DECISION_LABEL[h.action] ?? h.action}
              {h.note && <> · “{h.note}”</>}
              {h.edits && Object.keys(h.edits).length > 0 && <span className="text-prisma-accent"> · 수정 {Object.keys((h.edits.fields as object) ?? h.edits).join(', ')}</span>}
            </li>
          ))}
        </ol>
      )}
      {err && <div className="mt-1 text-[10px] text-prisma-danger">오류: {err}</div>}
    </div>
  )
}

const FILTERS = ['ALL', 'PENDING', 'SALUTE', 'MEDEVAC', 'SITREP', 'COMBINED', 'BATTLE'] as const

export default function ReportFeed() {
  const reports = useCop((s) => s.reports)
  const now = useNow()
  const [f, setF] = useState<(typeof FILTERS)[number]>('ALL')
  const list = useMemo(() => {
    let l = Object.values(reports).sort((a, b) => {
      // 승인 대기 → 긴급 → 최신
      const pa = Number(b.status === 'pending') - Number(a.status === 'pending')
      return pa || b.ts - a.ts
    })
    if (f === 'PENDING') l = l.filter((r) => r.status === 'pending')
    else if (f === 'SALUTE') l = l.filter((r) => ['SALUTE', 'SPOT', 'CONTACT'].includes(r.type))
    else if (f === 'COMBINED') l = l.filter((r) => r.type === 'SPOTREP+SITREP')
    else if (f === 'SITREP') l = l.filter((r) => r.type === 'SITREP' || r.type === 'SPOTREP+SITREP')
    else if (f === 'BATTLE') l = l.filter((r) => r.type === 'BATTLE_DATA')
    else if (f !== 'ALL') l = l.filter((r) => r.type === f)
    return l
  }, [reports, f])
  const pending = Object.values(reports).filter((r) => r.status === 'pending').length

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-wrap gap-1 border-b border-prisma-line px-2 py-1.5">
        {FILTERS.map((k) => (
          <button
            key={k}
            type="button"
            onClick={() => setF(k)}
            className={`prisma-chip ${f === k ? 'prisma-chip-on' : ''} ${k === 'PENDING' && pending ? '!text-prisma-warn' : ''}`}
          >
            {k === 'ALL' ? '전체' : k === 'PENDING' ? `승인대기${pending ? ` ${pending}` : ''}` : k === 'SALUTE' ? '적정보' : k === 'COMBINED' ? '적정·상황' : k === 'BATTLE' ? '전투데이터' : k}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pb-2 pt-1">
        {list.length === 0 && <div className="p-6 text-center text-[11px] uppercase tracking-wider text-prisma-dim">No reports</div>}
        {list.map((r) => <ReportCard key={r.id} r={r} now={now} />)}
      </div>
    </div>
  )
}
