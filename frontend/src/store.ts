import { create } from 'zustand'
import type { CollectionName, Collections, Mission, ServerMsg, Stats } from './types'

export type MapFocus = { lat: number; lon: number; zoom?: number; key: number }

export interface Layers {
  links: boolean
  trails: boolean
  errors: boolean
  route: boolean
}

export type DemoMode = 'scenario' | 'realtime'

interface CopState extends Collections {
  connected: boolean
  mission: Mission | null
  stats: Stats | null
  clockSkew: number // server - client [s]
  demoMode: DemoMode
  routerConnected: boolean

  // UI
  selectedUnit: string | null
  selectedTarget: string | null
  focus: MapFocus | null
  layers: Layers
  pickMode: boolean                       // 지도 클릭으로 명령 목표 지정 중
  orderPoint: [number, number] | null

  apply: (m: ServerMsg) => void
  /** 여러 패치를 한 번에 병합 적용 (동일 id는 마지막 것만) */
  applyBatch: (msgs: ServerMsg[]) => void
  setConnected: (c: boolean) => void
  setDemoLink: (mode: DemoMode, routerConnected: boolean) => void
  selectUnit: (id: string | null) => void
  selectTarget: (id: string | null) => void
  flyTo: (lat: number, lon: number, zoom?: number) => void
  toggleLayer: (k: keyof Layers) => void
  setPickMode: (b: boolean) => void
  setOrderPoint: (p: [number, number] | null) => void
}

const emptyCollections = (): Collections => ({
  units: {}, targets: {}, reports: {}, sensors: {}, links: {}, alerts: {}, orders: {},
})

const toMap = <T extends { id: string }>(arr: T[]) =>
  Object.fromEntries(arr.map((x) => [x.id, x])) as Record<string, T>

type DataSlice = Collections & {
  mission: Mission | null
  stats: Stats | null
  clockSkew: number
}

function applyOne(s: DataSlice, m: ServerMsg): DataSlice {
  switch (m.t) {
    case 'snapshot': {
      const v = m.v
      return {
        units: toMap(v.units), targets: toMap(v.targets), reports: toMap(v.reports),
        sensors: toMap(v.sensors), links: toMap(v.links), alerts: toMap(v.alerts),
        orders: toMap(v.orders ?? []),
        mission: v.mission, stats: v.stats, clockSkew: v.server_time - Date.now() / 1000,
      }
    }
    case 'patch': {
      const c = m.c
      const coll = { ...s[c] } as Record<string, { id: string }>
      if (m.op === 'upsert') coll[m.v.id] = m.v as { id: string }
      else delete coll[m.id]
      return { ...s, [c]: coll }
    }
    case 'mission':
      return { ...s, mission: m.v }
    case 'stats':
      return { ...s, stats: m.v }
  }
}

/** 동일 엔티티 패치를 합쳐 렌더 폭풍을 막는다 */
function mergeMsgs(s: DataSlice, msgs: ServerMsg[]): DataSlice {
  if (msgs.length === 0) return s
  let start = 0
  for (let i = 0; i < msgs.length; i++) if (msgs[i].t === 'snapshot') start = i
  let next: DataSlice = msgs[start].t === 'snapshot' ? applyOne(s, msgs[start]) : {
    units: s.units, targets: s.targets, reports: s.reports, sensors: s.sensors,
    links: s.links, alerts: s.alerts, orders: s.orders,
    mission: s.mission, stats: s.stats, clockSkew: s.clockSkew,
  }
  const from = msgs[start].t === 'snapshot' ? start + 1 : start

  const upserts = new Map<string, { c: CollectionName; v: { id: string } }>()
  const removes = new Set<string>()
  let mission = next.mission
  let stats = next.stats

  for (let i = from; i < msgs.length; i++) {
    const m = msgs[i]
    if (m.t === 'snapshot') {
      next = applyOne(next, m)
      upserts.clear()
      removes.clear()
      mission = next.mission
      stats = next.stats
    } else if (m.t === 'patch') {
      const id = m.op === 'upsert' ? m.v.id : m.id
      const key = `${m.c}\0${id}`
      if (m.op === 'upsert') {
        upserts.set(key, { c: m.c, v: m.v })
        removes.delete(key)
      } else {
        removes.add(key)
        upserts.delete(key)
      }
    } else if (m.t === 'mission') {
      mission = m.v
    } else if (m.t === 'stats') {
      stats = m.v
    }
  }

  if (upserts.size === 0 && removes.size === 0) {
    return { ...next, mission, stats }
  }

  const cloned = new Map<CollectionName, Record<string, unknown>>()
  const touch = (c: CollectionName) => {
    let col = cloned.get(c)
    if (!col) {
      col = { ...(next[c] as Record<string, unknown>) }
      cloned.set(c, col)
    }
    return col
  }
  for (const { c, v } of upserts.values()) touch(c)[v.id] = v
  for (const key of removes) {
    const sep = key.indexOf('\0')
    const c = key.slice(0, sep) as CollectionName
    const id = key.slice(sep + 1)
    delete touch(c)[id]
  }
  const out = { ...next, mission, stats } as DataSlice
  for (const [c, col] of cloned) {
    ;(out as unknown as Record<string, unknown>)[c] = col
  }
  return out
}

export const useCop = create<CopState>((set) => ({
  ...emptyCollections(),
  connected: false,
  mission: null,
  stats: null,
  clockSkew: 0,
  demoMode: 'scenario',
  routerConnected: false,
  selectedUnit: null,
  selectedTarget: null,
  focus: null,
  layers: { links: true, trails: true, errors: true, route: true },
  pickMode: false,
  orderPoint: null,

  apply: (m) => set((s) => applyOne(s, m)),
  applyBatch: (msgs) => {
    if (msgs.length === 0) return
    set((s) => mergeMsgs(s, msgs))
  },
  setConnected: (connected) => set({ connected }),
  setDemoLink: (demoMode, routerConnected) => set({ demoMode, routerConnected }),
  selectUnit: (selectedUnit) => set({ selectedUnit, selectedTarget: null }),
  selectTarget: (selectedTarget) => set({ selectedTarget, selectedUnit: null }),
  flyTo: (lat, lon, zoom) => set({ focus: { lat, lon, zoom, key: Date.now() } }),
  toggleLayer: (k) => set((s) => ({ layers: { ...s.layers, [k]: !s.layers[k] } })),
  setPickMode: (pickMode) => set({ pickMode }),
  setOrderPoint: (orderPoint) => set({ orderPoint, pickMode: false }),
}))

/** 서버 기준 현재 시각 [s] */
export const serverNow = () => Date.now() / 1000 + useCop.getState().clockSkew
