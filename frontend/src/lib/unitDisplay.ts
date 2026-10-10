import type { Unit, UnitStatus } from '../types'
import { STATUS_LABEL } from './format'

export type LinkOpts = { mode?: 'scenario' | 'realtime'; routerConnected?: boolean }

/** 지도·대형에 그릴 수 있는 유효 좌표인지 */
export function hasFix(u: Unit): boolean {
  return typeof u.lat === 'number' && typeof u.lon === 'number'
    && Number.isFinite(u.lat) && Number.isFinite(u.lon)
}

/**
 * UI용 상태. 좌표 없으면 두절로 본다.
 * realtime에서 라우터/Arduino 미연결이면 1분대 전원(1-1 포함) 강제 두절.
 */
export function effectiveStatus(u: Unit, opts?: LinkOpts): UnitStatus {
  if (u.status === 'kia') return 'kia'
  if (opts?.mode === 'realtime' && !opts.routerConnected && u.squad === '1') {
    return 'nolink'
  }
  if (u.status === 'nolink' || !hasFix(u)) return 'nolink'
  return u.status
}

/**
 * SoftAP 연결 중 1분대 무좌표 = 측위대기 (통신두절과 구분).
 */
export function statusLabel(u: Unit, opts?: LinkOpts): string {
  const st = effectiveStatus(u, opts)
  if (
    st === 'nolink'
    && opts?.mode === 'realtime'
    && opts.routerConnected
    && u.squad === '1'
  ) {
    return '측위대기'
  }
  return STATUS_LABEL[st]
}

/** 지도 마커·궤적·링크 엔드포인트 표시 여부 */
export function unitOnMap(u: Unit, opts?: LinkOpts): boolean {
  const st = effectiveStatus(u, opts)
  return hasFix(u) && st !== 'nolink' && st !== 'kia'
}
