/** 대시보드용 전술/군 관련 아이콘. 메시지·말풍선 계열은 사용하지 않음. */
import type { ReactElement, ReactNode, SVGProps } from 'react'
import { RANK_SHORT, rankMarkSvg, rankOf } from '../lib/ranks'
import type { ReportType, Unit } from '../types'

type IconProps = SVGProps<SVGSVGElement> & { size?: number }

function base({ size = 14, className, children, ...rest }: IconProps & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden
      {...rest}
    >
      {children}
    </svg>
  )
}

/** 조준십자 — 브랜드 / COP */
export function IconCrosshair(p: IconProps) {
  return base({
    ...p,
    children: (
      <>
        <circle cx="12" cy="12" r="7" />
        <path d="M12 2v4M12 18v4M2 12h4M18 12h4" />
        <circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none" />
      </>
    ),
  })
}

/** 아군 부대 — 부대 현황 */
export function IconFriendly(p: IconProps) {
  return base({
    ...p,
    children: (
      <>
        <rect x="5" y="5" width="14" height="14" rx="1" />
        <path d="M12 8v8M8 12h8" />
      </>
    ),
  })
}

/** 적 표적 — 마름모 */
export function IconHostile(p: IconProps) {
  return base({
    ...p,
    children: <path d="M12 3l9 9-9 9-9-9z" />,
  })
}

/** 미확인 */
export function IconUnknown(p: IconProps) {
  return base({
    ...p,
    children: (
      <>
        <path d="M12 3l9 9-9 9-9-9z" strokeDasharray="2.5 2" />
        <path d="M12 9.5a2 2 0 0 1 2 2c0 1.2-2 1.5-2 3" />
        <circle cx="12" cy="17" r="0.8" fill="currentColor" stroke="none" />
      </>
    ),
  })
}

/** 대형 / 진형 */
export function IconFormation(p: IconProps) {
  return base({
    ...p,
    children: (
      <>
        <circle cx="12" cy="7" r="2" />
        <circle cx="6" cy="16" r="2" />
        <circle cx="18" cy="16" r="2" />
        <path d="M12 9v3M10.5 13.5l-2.5 1.5M13.5 13.5l2.5 1.5" />
      </>
    ),
  })
}

/** 전술 보고(클립보드) — 메시지 아이콘 대신 사용 */
export function IconReport(p: IconProps) {
  return base({
    ...p,
    children: (
      <>
        <path d="M9 4h6a1 1 0 0 1 1 1v1H8V5a1 1 0 0 1 1-1z" />
        <rect x="6" y="6" width="12" height="14" rx="1.5" />
        <path d="M9 11h6M9 14h6M9 17h4" />
      </>
    ),
  })
}

/** 경보 */
export function IconAlert(p: IconProps) {
  return base({
    ...p,
    children: (
      <>
        <path d="M12 4l9 16H3z" />
        <path d="M12 10v4" />
        <circle cx="12" cy="16.5" r="0.8" fill="currentColor" stroke="none" />
      </>
    ),
  })
}

/** AI 브리핑 / 헤드셋 */
export function IconBriefing(p: IconProps) {
  return base({
    ...p,
    children: (
      <>
        <path d="M4 12a8 8 0 0 1 16 0" />
        <path d="M4 12v4a2 2 0 0 0 2 2h1v-6H6a2 2 0 0 0-2 2zM20 12v4a2 2 0 0 1-2 2h-1v-6h1a2 2 0 0 1 2 2z" />
        <path d="M12 19v1a2 2 0 0 0 2 2h1" />
      </>
    ),
  })
}

/** 메시 링크 / 안테나 */
export function IconMesh(p: IconProps) {
  return base({
    ...p,
    children: (
      <>
        <circle cx="12" cy="18" r="1.5" fill="currentColor" stroke="none" />
        <path d="M12 16v-3" />
        <path d="M8 9a5.5 5.5 0 0 1 8 0" />
        <path d="M5.5 6a9 9 0 0 1 13 0" />
      </>
    ),
  })
}

/** EMCON — 방출 통제 */
export function IconEmcon(p: IconProps) {
  return base({
    ...p,
    children: (
      <>
        <circle cx="12" cy="18" r="1.5" fill="currentColor" stroke="none" />
        <path d="M12 16v-3" />
        <path d="M8 9a5.5 5.5 0 0 1 8 0" />
        <path d="M4 4l16 16" />
      </>
    ),
  })
}

/** 의무 / MEDEVAC */
export function IconMedic(p: IconProps) {
  return base({
    ...p,
    children: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v10M7 12h10" />
      </>
    ),
  })
}

/** 정상 상태 */
export function IconStatusOk(p: IconProps) {
  return base({
    ...p,
    children: (
      <>
        <circle cx="12" cy="12" r="8" />
        <path d="M8 12l2.5 2.5L16 9" />
      </>
    ),
  })
}

/** 부상 */
export function IconStatusWia(p: IconProps) {
  return base({
    ...p,
    children: (
      <>
        <path d="M12 3l9 16H3z" />
        <path d="M12 9v4" />
        <circle cx="12" cy="15.5" r="0.8" fill="currentColor" stroke="none" />
      </>
    ),
  })
}

/** 통신 두절 */
export function IconStatusNolink(p: IconProps) {
  return base({
    ...p,
    children: (
      <>
        <circle cx="12" cy="18" r="1.5" fill="currentColor" stroke="none" />
        <path d="M12 16v-2" />
        <path d="M5.5 6a9 9 0 0 1 13 0" opacity={0.35} />
        <path d="M4 4l16 16" />
      </>
    ),
  })
}

const REPORT_ICON: Record<ReportType, (p: IconProps) => ReactElement> = {
  SALUTE: IconHostile,
  SPOT: IconCrosshair,
  CONTACT: IconHostile,
  MEDEVAC: IconMedic,
  SITREP: IconReport,
  'SPOTREP+SITREP': IconHostile,
  FREE: IconReport,
  BATTLE_DATA: IconReport,
}

export function IconReportType({ type, ...p }: IconProps & { type: ReportType }) {
  const C = REPORT_ICON[type] ?? IconReport
  return <C {...p} />
}

/** 부대현황용 국군 육군 계급장 */
export function RankGlyph({ unit, size = 18 }: { unit: Unit; size?: number }) {
  const rank = rankOf(unit)
  const { svg, w, h } = rankMarkSvg(rank)
  const scale = size / Math.max(w, h * 0.55)
  return (
    <span
      className={`rank-glyph inline-flex shrink-0 items-center justify-center st-${unit.status}`}
      title={rank}
      style={{ width: w * scale, height: h * scale }}
      dangerouslySetInnerHTML={{
        __html: svg.replace(`width="${w}"`, `width="${w * scale}"`).replace(`height="${h}"`, `height="${h * scale}"`),
      }}
      aria-label={RANK_SHORT[rank]}
    />
  )
}

/** @deprecated RankGlyph 사용 */
export const MilUnitGlyph = RankGlyph
