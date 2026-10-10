import { useMemo } from 'react'
import { useCop } from '../store'
import { useNow } from '../lib/useNow'
import { ago, STATUS_COLOR } from '../lib/format'
import { toMgrs } from '../lib/geo'
import { effectiveStatus, hasFix, statusLabel, unitOnMap } from '../lib/unitDisplay'
import type { Unit } from '../types'
import { IconFriendly, RankGlyph } from './icons'
import { RANK_SHORT, rankOf } from '../lib/ranks'

const SQUAD_NAME: Record<string, string> = { HQ: '소대본부', '1': '1분대', '2': '2분대', '3': '3분대' }
const ROLE: Record<Unit['role'], string> = {
  pl: '소대장', sl: '분대장', rifleman: '소총수', gunner: '기관총', medic: '의무', radio: '통신',
}

function Battery({ v }: { v: number }) {
  const c = v > 50 ? 'bg-prisma-ok' : v > 20 ? 'bg-prisma-warn' : 'bg-prisma-danger'
  return (
    <div className="h-1 w-7 bg-prisma-void" title={`배터리 ${v.toFixed(0)}%`}>
      <div className={`h-full ${c}`} style={{ width: `${v}%` }} />
    </div>
  )
}

function Detail({
  u, now, status, label,
}: { u: Unit; now: number; status: Unit['status']; label: string }) {
  return (
    <div className="prisma-card mx-2 mb-2 p-2 text-[11px] text-prisma-muted">
      <div className="mb-1.5 flex items-center justify-between">
        <b className="font-mono text-prisma-fg">{u.callsign}</b>
        <span className={`text-[10px] font-semibold uppercase tracking-wider ${STATUS_COLOR[status]}`}>
          {label}
        </span>
      </div>
      <div className="grid grid-cols-[56px_1fr] gap-y-1">
        <span className="text-prisma-dim">계급</span><span className="text-prisma-fg">{rankOf(u)} · {ROLE[u.role]}</span>
        <span className="text-prisma-dim">MGRS</span>
        <span className="font-mono text-prisma-fg">{hasFix(u) ? toMgrs(u.lat!, u.lon!) : '—'}</span>
        <span className="text-prisma-dim">측위</span>
        <span>{!hasFix(u) ? '—' : u.pos_source === 'ble-rel' ? `BLE 상대 ±${u.pos_err.toFixed(1)}m` : `${u.pos_source.toUpperCase()} ±${u.pos_err.toFixed(0)}m`}</span>
        <span className="text-prisma-dim">방위</span><span className="font-mono">{u.heading.toFixed(0)}°</span>
        <span className="text-prisma-dim">배터리</span><span className="font-mono">{u.battery.toFixed(0)}%</span>
        <span className="text-prisma-dim">RSSI</span><span className="font-mono">{u.rssi != null ? `${u.rssi.toFixed(0)} dBm` : '—'}</span>
        <span className="text-prisma-dim">수신</span><span>{ago(u.last_seen, now)}</span>
      </div>
    </div>
  )
}

export default function Roster() {
  const units = useCop((s) => s.units)
  const selected = useCop((s) => s.selectedUnit)
  const selectUnit = useCop((s) => s.selectUnit)
  const flyTo = useCop((s) => s.flyTo)
  const demoMode = useCop((s) => s.demoMode)
  const routerConnected = useCop((s) => s.routerConnected)
  const now = useNow()
  const linkOpts = useMemo(() => ({ mode: demoMode, routerConnected }), [demoMode, routerConnected])

  const groups = useMemo(() => {
    const g: Record<string, Unit[]> = {}
    for (const u of Object.values(units)) (g[u.squad] ??= []).push(u)
    for (const k in g) g[k].sort((a, b) => a.id.localeCompare(b.id))
    return Object.entries(g).sort(([a], [b]) => (a === 'HQ' ? -1 : b === 'HQ' ? 1 : a.localeCompare(b)))
  }, [units])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="panel-title">
        <IconFriendly size={11} className="text-prisma-intent" />
        Force Roster
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {groups.map(([sq, list]) => {
          const statuses = list.map((u) => effectiveStatus(u, linkOpts))
          const bad = statuses.filter((st) => st !== 'ok').length
          return (
            <div key={sq} className="border-b border-prisma-line">
              <div className="flex items-center justify-between px-3 py-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-prisma-dim">
                <span>{SQUAD_NAME[sq] ?? `${sq}분대`}</span>
                <span className={`font-mono ${bad ? 'text-prisma-warn' : 'text-prisma-dim'}`}>
                  {list.length - bad}/{list.length}
                </span>
              </div>
              {list.map((u) => {
                const st = effectiveStatus(u, linkOpts)
                const onMap = unitOnMap(u, linkOpts)
                return (
                  <div key={u.id}>
                    <button
                      type="button"
                      onClick={() => {
                        selectUnit(u.id === selected ? null : u.id)
                        if (onMap) flyTo(u.lat!, u.lon!)
                      }}
                      className={`prisma-row ${u.id === selected ? 'sel' : ''} ${st === 'nolink' ? 'opacity-45' : ''}`}
                    >
                      <RankGlyph unit={{ ...u, status: st }} size={18} />
                      <span className="w-14 truncate font-medium text-prisma-fg" title={`${RANK_SHORT[rankOf(u)]} · ${ROLE[u.role]}`}>
                        {u.callsign}
                      </span>
                      <span className="w-8 font-mono text-[10px] text-prisma-warn/80">{RANK_SHORT[rankOf(u)]}</span>
                      <span className="w-9 text-[10px] text-prisma-dim">{ROLE[u.role]}</span>
                      <span className={`w-8 text-[10px] font-medium ${STATUS_COLOR[st]}`}>
                        {statusLabel(u, linkOpts)}
                      </span>
                      <span className="ml-auto font-mono text-[9px] text-prisma-dim">
                        {!onMap ? '—' : u.pos_source === 'ble-rel' ? 'BLE' : 'GPS'}
                      </span>
                      <Battery v={u.battery} />
                    </button>
                    {u.id === selected && (
                      <Detail u={u} now={now} status={st} label={statusLabel(u, linkOpts)} />
                    )}
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
    </div>
  )
}
