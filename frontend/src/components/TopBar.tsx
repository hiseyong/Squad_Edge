import { useEffect, useState, type ComponentType } from 'react'
import { api, type DemoMode, type ModeStatus } from '../api'
import { useCop } from '../store'
import { bytes, dtg } from '../lib/format'
import { effectiveStatus } from '../lib/unitDisplay'
import {
  IconCrosshair, IconEmcon, IconHostile, IconMesh, IconStatusNolink,
  IconStatusOk, IconStatusWia, IconUnknown,
} from './icons'

function Metric({
  label, value, cls, Icon,
}: {
  label: string
  value: number | string
  cls: string
  Icon?: ComponentType<{ size?: number; className?: string }>
}) {
  return (
    <div className="prisma-metric min-w-[44px]">
      <span className="lbl inline-flex items-center gap-1">
        {Icon && <Icon size={9} className={cls} />}
        {label}
      </span>
      <span className={`val ${cls}`}>{value}</span>
    </div>
  )
}

export default function TopBar() {
  const connected = useCop((s) => s.connected)
  const mission = useCop((s) => s.mission)
  const stats = useCop((s) => s.stats)
  const units = useCop((s) => s.units)
  const targets = useCop((s) => s.targets)
  const [clock, setClock] = useState(new Date())
  const [modeInfo, setModeInfo] = useState<ModeStatus | null>(null)

  const setDemoLink = useCop((s) => s.setDemoLink)
  const refreshMode = () => api.modeStatus().then((info) => {
    setModeInfo(info)
    setDemoLink(info.mode, !!info.router?.connected)
  }).catch(() => {})

  useEffect(() => {
    const tick = () => setClock(new Date())
    const t = setInterval(tick, 1000)
    const onVis = () => {
      if (document.visibilityState === 'visible') tick()
    }
    document.addEventListener('visibilitychange', onVis)
    refreshMode()
    const poll = setInterval(refreshMode, 3000)
    return () => {
      clearInterval(t)
      clearInterval(poll)
      document.removeEventListener('visibilitychange', onVis)
    }
  }, [])

  const demoMode = useCop((s) => s.demoMode)
  const routerConnected = useCop((s) => s.routerConnected)
  const list = Object.values(units)
  const linkOpts = { mode: demoMode, routerConnected }
  const count = (st: string) => list.filter((u) => {
    const eff = effectiveStatus(u, linkOpts)
    if (st === 'nolink') return eff === 'nolink'
    if (eff === 'nolink' && st !== 'nolink') return false
    if (u.lat == null && u.status !== 'kia') return false
    return eff === st
  }).length
  const hostile = Object.values(targets).filter((t) => t.affiliation === 'hostile' && t.status !== 'rejected').length
  const unknown = Object.values(targets).filter((t) => t.affiliation === 'unknown').length
  const ratio = stats && stats.voiceable_bytes > 0 ? stats.voice_equiv_bytes / stats.voiceable_bytes : 0
  const emcon = mission?.emcon ?? false
  const mode: DemoMode = modeInfo?.mode ?? 'scenario'
  const simRunning = modeInfo?.sim_running ?? modeInfo?.running ?? false
  const routerOk = modeInfo?.router?.connected ?? false

  const switchMode = (m: DemoMode) => {
    api.setMode(m).then((info) => {
      setModeInfo(info)
      setDemoLink(info.mode, !!info.router?.connected)
    }).catch(() => {})
  }

  return (
    <header className="flex h-14 shrink-0 items-stretch border-b border-prisma-border bg-prisma-panel/95 backdrop-blur-sm">
      <div className="flex items-center gap-3 border-r border-prisma-border px-4">
        <div className="relative flex h-8 w-8 items-center justify-center border border-prisma-accent/40 bg-prisma-void">
          <IconCrosshair size={18} className="text-prisma-accent" />
          <span className="absolute -right-px -bottom-px h-1.5 w-1.5 bg-prisma-accent" />
        </div>
        <div className="leading-none">
          <div className="text-[13px] font-bold tracking-[0.18em] text-prisma-fg">SQUAD EDGE</div>
          <div className="mt-1 text-[9px] font-medium uppercase tracking-[0.22em] text-prisma-accent">
            Common Operating Picture
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3 border-r border-prisma-border px-3">
        <span className={`prisma-chip ${connected ? 'prisma-chip-on' : ''}`}>
          <IconMesh size={11} className={connected ? 'text-prisma-ok' : 'animate-pulse text-prisma-danger'} />
          {connected ? 'MESH LINK' : 'NO LINK'}
        </span>
        <div className="prisma-seg" title={modeInfo?.note}>
          <button type="button" onClick={() => switchMode('scenario')} className={mode === 'scenario' ? 'on' : ''}>
            Scenario
          </button>
          <button type="button" onClick={() => switchMode('realtime')} className={mode === 'realtime' ? 'on' : ''}>
            Realtime
          </button>
        </div>
        {mode === 'realtime' && (
          <span
            className={`prisma-chip ${routerOk ? 'prisma-chip-on' : ''}`}
            title="1-1 GPS=COP mock(연결 시) · 1-2~1-4=단말 relpos · 연결 중 무좌표=측위대기 · SoftAP 단절=통신두절"
          >
            <span className={`h-1.5 w-1.5 ${routerOk ? 'bg-prisma-ok' : 'animate-pulse bg-prisma-warn'}`} />
            Router {routerOk ? 'ON' : 'WAIT'}
          </span>
        )}
      </div>

      <div className="hidden items-center gap-5 px-4 lg:flex">
        <Metric label="Ok" value={count('ok')} cls="text-prisma-ok" Icon={IconStatusOk} />
        <Metric label="WIA" value={count('wia')} cls="text-prisma-warn" Icon={IconStatusWia} />
        <Metric
          label={mode === 'realtime' && routerOk ? 'FixWait' : 'Nolink'}
          value={count('nolink')}
          cls="text-prisma-danger"
          Icon={IconStatusNolink}
        />
        <div className="h-6 w-px bg-prisma-border" />
        <Metric label="Hostile" value={hostile} cls="text-prisma-hostile" Icon={IconHostile} />
        <Metric label="Unk" value={unknown} cls="text-prisma-unknown" Icon={IconUnknown} />
      </div>

      <div className="ml-auto flex items-center gap-2 px-3">
        {stats && (
          <div className="hidden text-right leading-tight xl:block" title="구조화 보고 vs 음성 대비">
            <div className="font-mono text-[11px] text-prisma-fg">
              TX {bytes(stats.tx_bytes)} · {stats.tx_msgs}
            </div>
            <div className="text-[9px] uppercase tracking-wider text-prisma-dim">
              Voice ×{ratio ? ratio.toFixed(0) : '—'}
            </div>
          </div>
        )}
        <button
          type="button"
          onClick={() => api.setEmcon(!emcon)}
          className={`prisma-btn ${emcon ? 'border-prisma-warn/50 text-prisma-warn animate-pulse' : ''}`}
          title="전파 방출 통제"
        >
          <IconEmcon size={11} />
          EMCON {emcon ? 'ON' : 'OFF'}
        </button>
        <div className="prisma-seg">
          <button type="button" onClick={() => api.sim('restart').then(setModeInfo)} title={mode === 'realtime' ? 'realtime 재시작' : '시나리오 처음부터'}>
            ↻ Restart
          </button>
          <button type="button" onClick={() => api.sim(simRunning ? 'stop' : 'start').then(setModeInfo)}>
            {simRunning ? '■ Sim' : '▶ Sim'}
          </button>
        </div>
        <div className="border-l border-prisma-border pl-3 text-right leading-none">
          <div className="font-mono text-base font-semibold tabular-nums text-prisma-fg">
            {clock.toLocaleTimeString('ko-KR', { hour12: false })}
          </div>
          <div className="mt-1 font-mono text-[9px] tracking-wider text-prisma-dim">{dtg(clock)}</div>
        </div>
      </div>
    </header>
  )
}
