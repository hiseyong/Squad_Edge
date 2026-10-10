// backend/app/models.py 와 1:1 대응

export type UnitStatus = 'ok' | 'wia' | 'kia' | 'nolink'
export type LatLon = [number, number]

export interface Unit {
  id: string
  callsign: string
  role: 'pl' | 'sl' | 'rifleman' | 'gunner' | 'medic' | 'radio'
  squad: string
  lat: number | null
  lon: number | null
  heading: number
  pos_err: number
  pos_source: 'gps' | 'ble-rel' | 'manual' | 'dr' | 'demo'
  status: UnitStatus
  battery: number
  rssi: number | null
  last_seen: number
  trail: LatLon[]
}

export interface Target {
  id: string
  affiliation: 'hostile' | 'unknown' | 'neutral'
  kind: string
  label: string
  lat: number
  lon: number
  count: number | null
  activity: string
  err_m: number
  conf: number
  reported_by: string | null
  source: 'voice' | 'sensor' | 'manual' | 'fusion'
  status: 'pending' | 'confirmed' | 'rejected'
  first_seen: number
  last_seen: number
}

export type ReportType =
  | 'SALUTE' | 'SPOT' | 'MEDEVAC' | 'SITREP' | 'CONTACT' | 'FREE' | 'SPOTREP+SITREP' | 'BATTLE_DATA'

export interface Report {
  id: string
  type: ReportType
  sender: string
  ts: number
  priority: 'routine' | 'priority' | 'urgent'
  raw_text: string
  summary: string
  fields: Record<string, unknown>
  missing: string[]
  conf: number
  status: 'pending' | 'confirmed' | 'rejected'
  target_id: string | null
  bytes: number
  decided_by: string | null
  decided_at: number | null
  decision_note: string
  recheck_count: number
  sender_acked: boolean
  history: { ts: number; action: string; by: string; note: string; edits?: Record<string, unknown> }[]
}

export type DecisionAction = 'confirm' | 'reject' | 'recheck' | 'reopen'

export type OrderCode =
  | 'HALT' | 'MOVE' | 'RALLY' | 'TAKE_COVER' | 'WEAPONS_HOLD' | 'WEAPONS_FREE' | 'RECHECK' | 'FRAGO'

export interface Order {
  id: string
  code: OrderCode
  text: string
  to: string[]
  recipients: string[]
  params: { lat?: number; lon?: number; [k: string]: unknown }
  priority: 'routine' | 'priority' | 'urgent'
  issuer: string
  ts: number
  acks: Record<string, number>
  status: 'sent' | 'partial' | 'acked' | 'cancelled' | 'expired' | 'superseded'
  ref_report: string | null
  tx_count: number
  last_tx: number
}

export interface Sensor {
  id: string
  kind: 'pir' | 'acoustic' | 'ultrasonic' | 'seismic'
  lat: number
  lon: number
  status: 'idle' | 'triggered' | 'offline'
  last_trigger: number | null
  battery: number
  last_seen: number
}

export interface Link {
  id: string
  a: string
  b: string
  rssi: number
  ts: number
}

export interface Alert {
  id: string
  level: 'info' | 'warn' | 'crit'
  kind: string
  msg: string
  unit_id: string | null
  ts: number
  ack: boolean
}

export interface Stats {
  started: number
  tx_bytes: number
  tx_msgs: number
  tx_by_type: Record<string, number>
  voice_equiv_bytes: number
  voiceable_bytes: number
}

export interface Mission {
  name: string
  emcon: boolean
  origin: LatLon
  objective: LatLon | null
  route: LatLon[]
  phase_lines: { name: string; coords: LatLon[] }[]
}

export interface Collections {
  units: Record<string, Unit>
  targets: Record<string, Target>
  reports: Record<string, Report>
  sensors: Record<string, Sensor>
  links: Record<string, Link>
  alerts: Record<string, Alert>
  orders: Record<string, Order>
}
export type CollectionName = keyof Collections

export type ServerMsg =
  | { t: 'snapshot'; v: { [K in CollectionName]: Collections[K][string][] } & { mission: Mission; stats: Stats; server_time: number } }
  | { t: 'patch'; c: CollectionName; op: 'upsert'; v: { id: string } }
  | { t: 'patch'; c: CollectionName; op: 'remove'; id: string }
  | { t: 'mission'; v: Mission }
  | { t: 'stats'; v: Stats }
