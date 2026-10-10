// 지도 아이콘: 아군=국군 육군 계급장, 표적=MIL-STD-2525 군대부호
import L from 'leaflet'
import ms from 'milsymbol'
import type { Target, Unit } from '../types'
import { rankMarkerHtml, rankOf } from './ranks'

const cache = new Map<string, L.DivIcon>()

function iconFrom(key: string, sidc: string, opts: Record<string, unknown>, extraClass = '') {
  const k = key + extraClass
  const hit = cache.get(k)
  if (hit) return hit
  let html = ''
  let w = 28
  let h = 28
  let ax = 14
  let ay = 14
  try {
    const sym = new ms.Symbol(sidc, { size: 22, outlineWidth: 3, outlineColor: 'rgba(0,0,0,0.85)', ...opts })
    const a = sym.getAnchor()
    const sz = sym.getSize()
    html = sym.asSVG()
    w = sz.width
    h = sz.height
    ax = a.x
    ay = a.y
  } catch {
    html = `<div style="width:24px;height:24px;border:2px solid #f55656;border-radius:50%;background:#f5565644"></div>`
  }
  const icon = L.divIcon({
    className: `milsym ${extraClass}`,
    html,
    iconSize: [w, h],
    iconAnchor: [ax, ay],
  })
  if (cache.size > 500) cache.clear()
  cache.set(k, icon)
  return icon
}

export function unitIcon(u: Unit, selected: boolean, showLabel: boolean) {
  const rank = rankOf(u)
  const leader = u.role === 'pl' || u.role === 'sl'
  const cls = [`st-${u.status}`, selected ? 'sel' : '', `role-${u.role}`].join(' ')
  const dir = Math.round(u.heading / 10) * 10
  const key = `rk:${u.role}:${u.callsign}:${dir}:${showLabel}:${selected}:${u.status}`
  const hit = cache.get(key + cls)
  if (hit) return hit

  const m = rankMarkerHtml(rank, {
    callsign: showLabel || leader ? u.callsign : undefined,
    heading: dir,
    selected,
  })
  const icon = L.divIcon({
    className: `rok-marker ${cls}`,
    html: m.html,
    iconSize: [m.w, m.h],
    iconAnchor: [m.anchorX, m.anchorY],
  })
  if (cache.size > 500) cache.clear()
  cache.set(key + cls, icon)
  return icon
}

export function isContactTarget(t: Target) {
  return t.kind === 'contact'
    || (t.label ?? '').includes('접적')
    || (t.activity ?? '').includes('접적')
}

export function targetSidc(t: Target) {
  const status = t.status === 'pending' ? 'A' : 'P' // A=추정(점선 프레임)
  if (t.affiliation === 'unknown') return `SUG${status}------------`.slice(0, 15)
  const aff = t.affiliation === 'hostile' ? 'H' : 'N'
  const fn = t.kind === 'vehicle' ? 'EVA---' : t.kind === 'sniper' ? 'UCIS--' : 'UCI---'
  return `S${aff}G${status}${fn}-----`
}

export function targetIcon(t: Target, selected: boolean) {
  const contact = isContactTarget(t)
  const opts: Record<string, unknown> = {
    size: contact ? 28 : 24,
    infoColor: '#fecaca',
    infoSize: 44,
  }
  if (t.count != null && t.count > 0) opts.quantity = String(t.count)
  // uniqueDesignation 등 텍스트 필드는 milsymbol이 undefined에 터질 수 있어 사용하지 않음
  const cls = [selected ? 'sel' : '', contact ? 'contact-tgt' : ''].filter(Boolean).join(' ')
  return iconFrom(
    `t:${t.id}:${t.status}:${t.count ?? ''}:${contact ? 'c' : ''}`,
    targetSidc(t),
    opts,
    cls,
  )
}

export function objectiveIcon(label = 'OBJ') {
  return L.divIcon({
    className: 'objective',
    html: `<div>${label}</div>`,
    iconSize: [48, 22],
    iconAnchor: [24, 11],
  })
}

export function orderPointIcon(label: string, pending = false) {
  return L.divIcon({
    className: `order-pt ${pending ? 'pending' : ''}`,
    html: `<div class="ring"></div><span>${label}</span>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  })
}
