/** 백엔드 없이 스토어를 움직이는 UI 데모 엔진 */
import { useEffect } from 'react'
import { useCop } from '../store'
import type { ServerMsg, Unit } from '../types'
import { buildSeed } from './seed'

function offset(lat: number, lon: number, east: number, north: number): [number, number] {
  const R = 6_371_000
  return [
    lat + (north / R) * (180 / Math.PI),
    lon + (east / (R * Math.cos((lat * Math.PI) / 180))) * (180 / Math.PI),
  ]
}

let started = false
let tick = 0
let timer: ReturnType<typeof setInterval> | undefined

function snapshotMsg(): ServerMsg {
  const s = buildSeed()
  return {
    t: 'snapshot',
    v: {
      units: s.units,
      targets: s.targets,
      reports: s.reports,
      sensors: s.sensors,
      links: s.links,
      alerts: s.alerts,
      orders: s.orders,
      mission: s.mission,
      stats: s.stats,
      server_time: s.server_time,
    },
  }
}

function stepUnits() {
  const { units, applyBatch, mission } = useCop.getState()
  if (!mission) return
  tick += 1
  const ts = Date.now() / 1000
  const patches: ServerMsg[] = []
  const speed = 0.35 // m/tick
  const hdg = (42 + Math.sin(tick / 40) * 8 + 360) % 360
  const rad = (hdg * Math.PI) / 180

  for (const u of Object.values(units) as Unit[]) {
    if (u.lat == null || u.lon == null || u.status === 'nolink' || u.status === 'kia') continue
    // 본부·분대장은 천천히 전진, 대원은 상대 유지용 미세 흔들림
    const step = u.role === 'rifleman' || u.role === 'gunner' ? speed * 0.3 : speed
    const east = Math.sin(rad) * step + (Math.random() - 0.5) * 0.4
    const north = Math.cos(rad) * step + (Math.random() - 0.5) * 0.4
    const [lat, lon] = offset(u.lat, u.lon, east, north)
    const trail = u.trail.length > 40 ? u.trail.slice(-40) : [...u.trail]
    if (tick % 3 === 0) trail.push([u.lat, u.lon])
    patches.push({
      t: 'patch',
      c: 'units',
      op: 'upsert',
      v: {
        ...u,
        lat, lon,
        heading: hdg + (Math.random() - 0.5) * 4,
        last_seen: ts,
        battery: Math.max(20, u.battery - 0.002),
        trail,
      },
    } as ServerMsg)
  }

  // 링크 RSSI 흔들림
  if (tick % 2 === 0) {
    for (const l of Object.values(useCop.getState().links)) {
      patches.push({
        t: 'patch', c: 'links', op: 'upsert',
        v: { ...l, rssi: -55 - Math.random() * 20, ts },
      } as ServerMsg)
    }
  }

  if (patches.length) applyBatch(patches)
}

export function bootMockup() {
  if (started) return
  started = true
  const { apply, setConnected, setDemoLink } = useCop.getState()
  apply(snapshotMsg())
  setConnected(true)
  setDemoLink('scenario', true)
  timer = setInterval(stepUnits, 1000)
}

export function stopMockup() {
  if (timer) clearInterval(timer)
  timer = undefined
  started = false
}

/** App에서 호출 — 실 WebSocket 대신 로컬 시드+틱 */
export function useMockupEngine() {
  useEffect(() => {
    bootMockup()
    return () => stopMockup()
  }, [])
}

export function resetMockup() {
  stopMockup()
  started = false
  bootMockup()
}
