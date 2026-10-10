/**
 * 국군 육군 계급장 기호 (전투복 약장 스타일 간략화)
 * 병=지각(가로줄), 부사관=나뭇가지(셰브론), 위관=금강석(마름모)
 */
import type { Unit } from '../types'

export type RokRank =
  | '이등병' | '일병' | '상병' | '병장'
  | '하사' | '중사'
  | '소위' | '중위' | '대위'

/** 소대 전술 역할 → 전형적인 육군 계급 */
export const ROLE_RANK: Record<Unit['role'], RokRank> = {
  pl: '중위',
  sl: '하사',
  gunner: '병장',
  medic: '상병',
  radio: '상병',
  rifleman: '일병',
}

export const RANK_SHORT: Record<RokRank, string> = {
  이등병: '이병', 일병: '일병', 상병: '상병', 병장: '병장',
  하사: '하사', 중사: '중사',
  소위: '소위', 중위: '중위', 대위: '대위',
}

const BG = '#1a2e1a'       // 육군 포제 계급장 바탕
const MARK = '#e8c547'     // 금색 표지
const OUT = '#0a140a'

function diamond(cx: number, cy: number, s: number) {
  return `<path d="M${cx},${cy - s} L${cx + s},${cy} L${cx},${cy + s} L${cx - s},${cy} Z" fill="${MARK}" stroke="${OUT}" stroke-width="0.8"/>`
}

function bar(y: number, w: number, h = 3.2) {
  const x = (32 - w) / 2
  // 사다리꼴(아래가 조금 더 넓음) — 병 계급 '지각' 형태
  return `<path d="M${x + 1},${y} L${x + w - 1},${y} L${x + w},${y + h} L${x},${y + h} Z" fill="${MARK}" stroke="${OUT}" stroke-width="0.6"/>`
}

function chevron(y: number, scale = 1) {
  // 부사관 나뭇가지(∧) — 위로 열린 셰브론
  const cx = 16
  const w = 11 * scale
  const h = 7 * scale
  const t = 2.4 * scale
  return `<path d="M${cx - w},${y + h} L${cx},${y} L${cx + w},${y + h}
    L${cx + w - t * 0.7},${y + h} L${cx},${y + t} L${cx - w + t * 0.7},${y + h} Z"
    fill="${MARK}" stroke="${OUT}" stroke-width="0.7"/>`
}

function mugunghwa(cx: number, cy: number, r = 3.2) {
  // 간부 계급장 상단 무궁화 받침 간략형
  const petals = 5
  let d = ''
  for (let i = 0; i < petals; i++) {
    const a = (i * 2 * Math.PI) / petals - Math.PI / 2
    const x = cx + Math.cos(a) * r
    const y = cy + Math.sin(a) * r
    d += `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)} `
  }
  return `<path d="${d}Z" fill="${MARK}" stroke="${OUT}" stroke-width="0.5"/>
    <circle cx="${cx}" cy="${cy}" r="${r * 0.35}" fill="${BG}" stroke="${OUT}" stroke-width="0.4"/>`
}

function board(inner: string, h = 36) {
  return `<rect x="1" y="1" width="30" height="${h - 2}" rx="3" ry="3" fill="${BG}" stroke="#3d5c3d" stroke-width="1.2"/>${inner}`
}

/** 계급장 본체 SVG 조각 (viewBox 0 0 32 H) */
export function rankMarkSvg(rank: RokRank): { svg: string; w: number; h: number } {
  const w = 32
  let h = 36
  let inner = ''

  switch (rank) {
    case '이등병': {
      h = 22
      inner = board(bar(9, 18), h)
      break
    }
    case '일병': {
      h = 28
      inner = board(`${bar(7, 16)}${bar(13.5, 20)}`, h)
      break
    }
    case '상병': {
      h = 34
      inner = board(`${bar(5.5, 14)}${bar(11.5, 18)}${bar(17.5, 22)}`, h)
      break
    }
    case '병장': {
      h = 40
      inner = board(`${bar(4, 12)}${bar(10, 16)}${bar(16, 20)}${bar(22, 24)}`, h)
      break
    }
    case '하사': {
      h = 40
      inner = board(`${mugunghwa(16, 9, 3.4)}${chevron(16, 1)}`, h)
      break
    }
    case '중사': {
      h = 46
      inner = board(`${mugunghwa(16, 8, 3.2)}${chevron(14, 0.92)}${chevron(22, 1.05)}`, h)
      break
    }
    case '소위': {
      h = 34
      inner = board(`${mugunghwa(16, 7, 2.8)}${diamond(16, 20, 7)}`, h)
      break
    }
    case '중위': {
      h = 44
      inner = board(`${mugunghwa(16, 7, 2.8)}${diamond(16, 18, 6)}${diamond(16, 32, 6)}`, h)
      break
    }
    case '대위': {
      h = 54
      inner = board(
        `${mugunghwa(16, 7, 2.6)}${diamond(16, 17, 5.5)}${diamond(16, 29, 5.5)}${diamond(16, 41, 5.5)}`,
        h,
      )
      break
    }
  }

  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}">${inner}</svg>`
  return { svg, w, h }
}

/** 지도 마커용: 계급장 + 방향 화살표 + 콜사인 */
export function rankMarkerHtml(
  rank: RokRank,
  opts: { callsign?: string; heading?: number; selected?: boolean },
) {
  const { svg, w, h } = rankMarkSvg(rank)
  const label = opts.callsign
    ? `<div class="rk-label">${opts.callsign}</div>`
    : ''
  const dir = opts.heading != null
    ? `<div class="rk-dir" style="transform:rotate(${opts.heading}deg)"></div>`
    : ''
  const sel = opts.selected ? ' sel' : ''
  // 앵커: 계급장 중심
  return {
    html: `<div class="rok-rank${sel}">${dir}<div class="rk-badge">${svg}</div>${label}</div>`,
    w: Math.max(w + 8, 48),
    h: h + (opts.callsign ? 16 : 4) + 10,
    anchorX: Math.max(w + 8, 48) / 2,
    anchorY: h / 2 + 5,
  }
}

export function rankOf(u: Unit): RokRank {
  return ROLE_RANK[u.role]
}
