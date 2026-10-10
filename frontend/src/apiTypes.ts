export interface LlmStatus {
  enabled: boolean
  available: boolean
  url: string
  api: string
  model: string | null
  models: string[]
  error: string | null
}

export type BriefEvent =
  | { type: 'meta'; engine: string; facts: string; reason?: string | null }
  | { type: 'token'; text: string }
  | { type: 'done'; text: string; latency: number }
  | { type: 'error'; message: string }

export type DemoMode = 'scenario' | 'realtime'

export interface ModeStatus {
  running?: boolean
  sim_running?: boolean
  mode: DemoMode
  live_squads: string[]
  mock_squads: string[]
  mock_gps?: string[]
  hw_relpos?: string[]
  period_s: number
  note: string
  router: {
    connected: boolean
    clients: number
    last_rx: number | null
    rx_count: number
    hw_squad: string
    hw_units: string[]
    mock_gps?: string[]
    period_s: number
  }
}
