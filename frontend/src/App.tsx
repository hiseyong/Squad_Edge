import { useState } from 'react'
import { useCopSocket } from './api'
import { useCop } from './store'
import TopBar from './components/TopBar'
import Roster from './components/Roster'
import FormationView from './components/FormationView'
import MapView from './components/MapView'
import ReportFeed from './components/ReportFeed'
import AlertPanel from './components/AlertPanel'
import BriefingPanel from './components/BriefingPanel'
import OrderPanel from './components/OrderPanel'
import { IconAlert, IconReport } from './components/icons'

function RightPanel() {
  const [tab, setTab] = useState<'reports' | 'alerts'>('reports')
  const reports = useCop((s) => s.reports)
  const alerts = useCop((s) => s.alerts)
  const nRep = Object.keys(reports).length
  const nAl = Object.values(alerts).filter((a) => !a.ack).length
  const nPend = Object.values(reports).filter((r) => r.status === 'pending').length
  const crit = Object.values(alerts).some((a) => !a.ack && a.level === 'crit')
  const tabs = [
    { k: 'reports' as const, label: `Reports ${nRep}${nPend ? ` · ${nPend}` : ''}`, Icon: IconReport },
    { k: 'alerts' as const, label: `Alerts ${nAl}`, Icon: IconAlert },
  ]
  return (
    <aside className="prisma-rail flex w-[360px] shrink-0 flex-col border-l">
      <div className="flex border-b border-prisma-border">
        {tabs.map(({ k, label, Icon }) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`prisma-tab ${tab === k ? 'on' : ''} ${
              k === 'alerts' && crit && tab !== 'alerts' ? 'animate-pulse !text-prisma-danger' : ''
            }`}
          >
            <Icon size={12} />
            {label}
          </button>
        ))}
      </div>
      {tab === 'reports' ? <ReportFeed /> : <AlertPanel />}
      <BriefingPanel />
    </aside>
  )
}

export default function App() {
  useCopSocket()
  return (
    <div className="prisma-shell flex h-screen flex-col text-prisma-fg">
      <TopBar />
      <div className="flex min-h-0 flex-1">
        <aside className="prisma-rail flex w-[280px] shrink-0 flex-col border-r">
          <Roster />
          <FormationView />
        </aside>
        <main className="relative flex min-w-0 flex-1 flex-col bg-prisma-void">
          <div className="pointer-events-none absolute inset-x-0 top-0 z-[5] h-px bg-gradient-to-r from-transparent via-prisma-accent/40 to-transparent" />
          <div className="min-h-0 flex-1">
            <MapView />
          </div>
          <OrderPanel />
        </main>
        <RightPanel />
      </div>
    </div>
  )
}
