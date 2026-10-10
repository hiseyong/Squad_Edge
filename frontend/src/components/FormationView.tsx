import { useMemo, useState } from 'react'
import { useCop } from '../store'
import { enu } from '../lib/geo'
import { unitOnMap } from '../lib/unitDisplay'
import type { Unit } from '../types'
import { IconFormation } from './icons'

const W = 260
const H = 200
const CX = W / 2
const CY = H * 0.62
const FORMATION_MAX_M = 60

const STATUS_FILL: Record<Unit['status'], string> = {
  ok: '#48aff0', wia: '#f2b824', kia: '#5c687a', nolink: '#eb532d',
}

/** BLE 상대측위 결과를 지도 없이 '대형'으로 보여주는 뷰 (기준자 진행방향 = 위) */
export default function FormationView() {
  const units = useCop((s) => s.units)
  const selected = useCop((s) => s.selectedUnit)
  const selectUnit = useCop((s) => s.selectUnit)
  const demoMode = useCop((s) => s.demoMode)
  const routerConnected = useCop((s) => s.routerConnected)
  const linkOpts = useMemo(() => ({ mode: demoMode, routerConnected }), [demoMode, routerConnected])
  const [scope, setScope] = useState<'PLT' | '1' | '2' | '3'>('PLT')

  const ref = scope === 'PLT' ? units['PL'] : units[`${scope}-1`]
  const refOk = !!ref && unitOnMap(ref, linkOpts)
  const members = Object.values(units).filter(
    (u) => (scope === 'PLT' ? true : u.squad === scope) && unitOnMap(u, linkOpts),
  )
  const range = scope === 'PLT' ? 80 : 65
  const scale = (H - CY - 6) / range
  const rings = scope === 'PLT' ? [25, 50, 75] : [20, 40, 60]

  const project = (u: Unit) => {
    if (!refOk || !ref || ref.lat == null) return null
    const [e, n] = enu(ref.lat, ref.lon!, u.lat!, u.lon!)
    const h = (-ref.heading * Math.PI) / 180
    const x = e * Math.cos(h) - n * Math.sin(h)
    const y = e * Math.sin(h) + n * Math.cos(h)
    const d = Math.hypot(x, y)
    return { x: CX + x * scale, y: CY - y * scale, d, out: d > range }
  }

  return (
    <div className="border-t border-prisma-border">
      <div className="panel-title !justify-between">
        <span className="inline-flex items-center gap-1.5">
          <IconFormation size={11} className="text-prisma-intent" />
          Formation
        </span>
        <div className="prisma-seg !normal-case" style={{ letterSpacing: 0 }}>
          {(['PLT', '1', '2', '3'] as const).map((k) => (
            <button key={k} type="button" onClick={() => setScope(k)} className={scope === k ? 'on' : ''}>
              {k === 'PLT' ? 'PLT' : `${k}`}
            </button>
          ))}
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full bg-prisma-void">
        {rings.map((r) => (
          <g key={r}>
            <circle cx={CX} cy={CY} r={r * scale} fill="none"
              stroke={scope !== 'PLT' && r === 60 ? '#f2b82455' : '#2a3544'}
              strokeDasharray={scope !== 'PLT' && r === 60 ? '3 3' : undefined} />
            <text x={CX + r * scale * 0.71 + 2} y={CY - r * scale * 0.71}
              fill="#5c687a" fontSize="8" fontFamily="IBM Plex Mono, monospace">{r}m</text>
          </g>
        ))}
        <line x1={CX} y1={CY} x2={CX} y2={6} stroke="#2a3544" strokeDasharray="2 3" />
        <text x={CX + 3} y={12} fill="#8a96a8" fontSize="8" fontFamily="IBM Plex Mono, monospace">
          HDG {ref ? `${ref.heading.toFixed(0)}°` : '—'}
        </text>

        {refOk && ref && members.map((u) => {
          const p = project(u)
          if (!p) return null
          const px = p.out ? CX + ((p.x - CX) * range) / p.d : p.x
          const py = p.out ? CY + ((p.y - CY) * range) / p.d : p.y
          const isRef = u.id === ref.id
          const breach = scope !== 'PLT' && !isRef && p.d > FORMATION_MAX_M
          return (
            <g key={u.id} onClick={() => selectUnit(u.id)} className="cursor-pointer">
              {u.pos_err > 3.5 && <circle cx={px} cy={py} r={u.pos_err * scale} fill="#48aff014" stroke="#48aff033" />}
              <circle cx={px} cy={py} r={isRef ? 5 : 3.5} fill={STATUS_FILL[u.status]}
                stroke={u.id === selected ? '#e7edf5' : breach ? '#f2b824' : '#080b10'}
                strokeWidth={u.id === selected || breach ? 1.5 : 1} />
              <text x={px + 6} y={py + 3} fill={breach ? '#f2b824' : '#c5ced9'} fontSize="8"
                fontFamily="IBM Plex Mono, monospace">
                {u.callsign}{breach ? ` ${p.d.toFixed(0)}m` : ''}
              </text>
            </g>
          )
        })}
        {!refOk && (
          <text x={CX} y={CY} textAnchor="middle" fill="#5c687a" fontSize="10">
            {ref ? 'NO LINK' : 'NO REFERENCE'}
          </text>
        )}
      </svg>
    </div>
  )
}
