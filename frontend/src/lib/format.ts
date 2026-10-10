import type { Alert, ReportType, UnitStatus } from '../types'

export function ago(ts: number, now: number) {
  const s = Math.max(0, Math.floor(now - ts))
  if (s < 60) return `${s}초 전`
  if (s < 3600) return `${Math.floor(s / 60)}분 전`
  return `${Math.floor(s / 3600)}시간 전`
}

export function hhmmss(ts: number) {
  return new Date(ts * 1000).toLocaleTimeString('ko-KR', { hour12: false })
}

/** 군 DTG 형식: 101502K OCT 26 (K = UTC+9) */
export function dtg(d = new Date()) {
  const mon = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getDate())}${p(d.getHours())}${p(d.getMinutes())}K ${mon[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`
}

export function bytes(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`
  return `${(n / 1024 / 1024).toFixed(2)} MB`
}

export const STATUS_LABEL: Record<UnitStatus, string> = {
  ok: '정상', wia: '부상', kia: '전사', nolink: '두절',
}
export const STATUS_COLOR: Record<UnitStatus, string> = {
  ok: 'text-prisma-ok', wia: 'text-prisma-warn', kia: 'text-prisma-dim', nolink: 'text-prisma-danger',
}
export const STATUS_DOT: Record<UnitStatus, string> = {
  ok: 'bg-prisma-ok', wia: 'bg-prisma-warn', kia: 'bg-prisma-dim', nolink: 'bg-prisma-danger',
}

export const REPORT_STYLE: Record<ReportType, { label: string; cls: string }> = {
  SALUTE: { label: 'SALUTE', cls: 'border-prisma-hostile/50 bg-prisma-hostile/10 text-prisma-hostile' },
  SPOT: { label: 'SPOT', cls: 'border-orange-400/40 bg-orange-500/10 text-orange-300' },
  CONTACT: { label: '접적', cls: 'border-prisma-danger/60 bg-prisma-danger/15 text-red-200' },
  MEDEVAC: { label: 'MEDEVAC', cls: 'border-prisma-warn/50 bg-prisma-warn/10 text-prisma-warn' },
  SITREP: { label: 'SITREP', cls: 'border-prisma-intent/50 bg-prisma-intent/10 text-prisma-intent' },
  'SPOTREP+SITREP': { label: '적정·상황', cls: 'border-prisma-hostile/60 bg-prisma-hostile/15 text-red-100' },
  FREE: { label: '일반', cls: 'border-prisma-border bg-prisma-elevated text-prisma-muted' },
  BATTLE_DATA: { label: '전투데이터', cls: 'border-prisma-accent/50 bg-prisma-accent/10 text-prisma-accent' },
}

export const ALERT_STYLE: Record<Alert['level'], string> = {
  crit: 'border-l-prisma-danger bg-prisma-danger/10',
  warn: 'border-l-prisma-warn bg-prisma-warn/5',
  info: 'border-l-prisma-intent bg-prisma-intent/5',
}

export const rssiColor = (rssi: number) => (rssi > -70 ? '#3dcc91' : rssi > -80 ? '#f2b824' : '#eb532d')

export const ORDER_META: Record<string, { label: string; cls: string; needsPoint?: boolean; hint: string }> = {
  HALT: { label: '정지', cls: 'bg-prisma-danger/80 hover:bg-prisma-danger', hint: '현 위치 정지' },
  MOVE: { label: '이동', cls: 'bg-prisma-intent/80 hover:bg-prisma-intent', needsPoint: true, hint: '지정 지점으로 이동' },
  RALLY: { label: '집결', cls: 'bg-prisma-accent/80 hover:bg-prisma-accent', needsPoint: true, hint: '지정 지점에 집결' },
  TAKE_COVER: { label: '엄폐', cls: 'bg-prisma-warn/80 hover:bg-prisma-warn text-prisma-void', hint: '즉시 엄폐' },
  WEAPONS_HOLD: { label: '사격중지', cls: 'bg-prisma-elevated hover:bg-prisma-hover', hint: '사격 중지' },
  WEAPONS_FREE: { label: '사격자유', cls: 'bg-prisma-hostile/80 hover:bg-prisma-hostile', hint: '사격 자유' },
  FRAGO: { label: '단편명령', cls: 'bg-prisma-ok/80 hover:bg-prisma-ok text-prisma-void', hint: '자유 텍스트 명령' },
  RECHECK: { label: '재확인', cls: 'bg-prisma-elevated', hint: '보고 재확인 요청' },
}

export const ORDER_STATUS: Record<string, { label: string; cls: string }> = {
  sent: { label: '송신', cls: 'text-prisma-intent' },
  partial: { label: '일부수신', cls: 'text-prisma-warn' },
  acked: { label: '전원수신', cls: 'text-prisma-ok' },
  expired: { label: '미수신', cls: 'text-prisma-danger' },
  cancelled: { label: '철회', cls: 'text-prisma-dim' },
  superseded: { label: '무효', cls: 'text-prisma-dim' },
}

export const DECISION_LABEL: Record<string, string> = {
  confirm: '승인', reject: '기각', recheck: '재확인 요청', reopen: '되돌림', amend: '보완 보고',
}
