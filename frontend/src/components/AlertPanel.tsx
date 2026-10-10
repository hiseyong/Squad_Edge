import { useMemo } from 'react'
import { api } from '../api'
import { useCop } from '../store'
import { useNow } from '../lib/useNow'
import { ago, ALERT_STYLE } from '../lib/format'
import { IconAlert } from './icons'

export default function AlertPanel() {
  const alerts = useCop((s) => s.alerts)
  const units = useCop((s) => s.units)
  const flyTo = useCop((s) => s.flyTo)
  const selectUnit = useCop((s) => s.selectUnit)
  const now = useNow()
  const list = useMemo(() => Object.values(alerts).sort((a, b) => Number(a.ack) - Number(b.ack) || b.ts - a.ts), [alerts])

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex justify-end border-b border-prisma-line px-2 py-1.5">
        <button type="button" className="text-[10px] uppercase tracking-wider text-prisma-dim hover:text-prisma-fg" onClick={() => api.ackAll()}>
          Ack all
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pb-2">
        {list.length === 0 && (
          <div className="p-6 text-center text-[11px] uppercase tracking-wider text-prisma-dim">No alerts</div>
        )}
        {list.map((a) => (
          <div
            key={a.id}
            className={`mx-2 mt-1.5 flex items-start gap-2 border-l-2 px-2 py-1.5 text-xs ${ALERT_STYLE[a.level]} ${a.ack ? 'opacity-40' : ''}`}
          >
            <IconAlert
              size={12}
              className={`mt-0.5 shrink-0 ${
                a.level === 'crit' ? 'text-prisma-danger' : a.level === 'warn' ? 'text-prisma-warn' : 'text-prisma-intent'
              }`}
            />
            <button
              type="button"
              className="flex-1 text-left text-prisma-fg"
              onClick={() => {
                const u = a.unit_id ? units[a.unit_id] : undefined
                if (u?.lat != null) { flyTo(u.lat, u.lon!); selectUnit(u.id) }
              }}
            >
              {a.msg}
              <div className="mt-0.5 font-mono text-[10px] text-prisma-dim">{ago(a.ts, now)}</div>
            </button>
            {!a.ack && (
              <button type="button" className="prisma-btn !px-1.5 !py-0.5 !text-[10px]" onClick={() => api.ackAlert(a.id)}>
                Ack
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}
