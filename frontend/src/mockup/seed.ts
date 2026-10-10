/** UI 데모용 정적 시드 — 백엔드/시뮬과 무관 */
import type {
  Alert, Link, Mission, Order, Report, Sensor, Stats, Target, Unit,
} from '../types'

const ORIGIN: [number, number] = [36.3005, 127.4185]
const ROUTE: [number, number][] = [
  [36.3005, 127.4185], [36.3028, 127.4200], [36.3046, 127.4228],
  [36.3062, 127.4246], [36.3080, 127.4262],
]
const OBJECTIVE: [number, number] = [36.3095, 127.4290]

function now() {
  return Date.now() / 1000
}

function offset(lat: number, lon: number, east: number, north: number): [number, number] {
  const R = 6_371_000
  return [
    lat + (north / R) * (180 / Math.PI),
    lon + (east / (R * Math.cos((lat * Math.PI) / 180))) * (180 / Math.PI),
  ]
}

const t0 = now()

function unit(
  id: string, callsign: string, role: Unit['role'], squad: string,
  east: number, north: number, status: Unit['status'] = 'ok',
): Unit {
  const [lat, lon] = offset(ORIGIN[0], ORIGIN[1], east, north)
  return {
    id, callsign, role, squad, lat, lon,
    heading: 42, pos_err: role === 'rifleman' || role === 'gunner' ? 5 : 3,
    pos_source: role === 'rifleman' || role === 'gunner' ? 'ble-rel' : 'gps',
    status, battery: 70 + Math.random() * 25, rssi: -55 - Math.random() * 25,
    last_seen: t0, trail: [],
  }
}

export function buildSeed() {
  const ts = now()
  const units: Unit[] = [
    unit('PL', '소대장', 'pl', 'HQ', 0, 0),
    unit('HQ-R', '통신병', 'radio', 'HQ', -6, -5),
    unit('HQ-M', '의무병', 'medic', 'HQ', 6, -5),
    unit('1-1', '1분대장', 'sl', '1', -35, 35),
    unit('1-2', '1-2', 'rifleman', '1', -44, 27),
    unit('1-3', '1-3', 'gunner', '1', -26, 27),
    unit('1-4', '1-4', 'rifleman', '1', -53, 19),
    unit('2-1', '2분대장', 'sl', '2', 35, 35),
    unit('2-2', '2-2', 'rifleman', '2', 26, 27),
    unit('2-3', '2-3', 'gunner', '2', 44, 27),
    unit('2-4', '2-4', 'rifleman', '2', 53, 19, 'wia'),
    unit('3-1', '3분대장', 'sl', '3', 0, -35),
    unit('3-2', '3-2', 'rifleman', '3', -9, -43),
    unit('3-3', '3-3', 'gunner', '3', 9, -43),
    unit('3-4', '3-4', 'rifleman', '3', -18, -51, 'nolink'),
  ]
  // 두절 유닛은 지도에서 숨김 (좌표 제거)
  for (const u of units) {
    if (u.status === 'nolink') { u.lat = null; u.lon = null }
  }

  const [tLat, tLon] = offset(ORIGIN[0], ORIGIN[1], 80, 120)
  const targets: Target[] = [
    {
      id: 'T-demo1', affiliation: 'hostile', kind: 'infantry', label: '적 보병',
      lat: tLat, lon: tLon, count: 4, activity: '경계 중', err_m: 25, conf: 0.86,
      reported_by: '1-1', source: 'voice', status: 'confirmed',
      first_seen: ts - 120, last_seen: ts - 40,
    },
    {
      id: 'T-demo2', affiliation: 'unknown', kind: 'vehicle', label: '미확인 차량',
      lat: tLat + 0.0012, lon: tLon - 0.0008, count: 1, activity: '정차', err_m: 40, conf: 0.62,
      reported_by: '2-1', source: 'voice', status: 'pending',
      first_seen: ts - 45, last_seen: ts - 20,
    },
  ]

  const reports: Report[] = [
    {
      id: 'R-demo1', type: 'SALUTE', sender: '1-1', ts: ts - 110, priority: 'priority',
      raw_text: '전방 약 백이십 미터 적 보병 사 명 경계 중',
      summary: '적 보병 4명 경계 — 1분대 전방',
      fields: {
        size: 4, activity: '경계 중',
        location: { lat: tLat, lon: tLon, err: 25 },
        unit: '적 보병', time: '약 2분 전', equipment: '소총',
      },
      missing: [], conf: 0.86, status: 'confirmed', target_id: 'T-demo1', bytes: 72,
      decided_by: 'PL', decided_at: ts - 90, decision_note: '', recheck_count: 0,
      sender_acked: true,
      history: [{ ts: ts - 90, action: 'confirm', by: 'PL', note: '' }],
    },
    {
      id: 'R-demo2', type: 'SPOT', sender: '2-1', ts: ts - 40, priority: 'priority',
      raw_text: '우측 전방 차량 한 대 정차 추정',
      summary: '미확인 차량 1대 정차 (승인 대기)',
      fields: {
        size: 1, activity: '정차', kind: 'vehicle',
        location: { lat: tLat + 0.0012, lon: tLon - 0.0008, err: 40 },
      },
      missing: ['unit'], conf: 0.62, status: 'pending', target_id: 'T-demo2', bytes: 64,
      decided_by: null, decided_at: null, decision_note: '', recheck_count: 0,
      sender_acked: false, history: [],
    },
    {
      id: 'R-demo3', type: 'SITREP', sender: '3-1', ts: ts - 25, priority: 'routine',
      raw_text: '삼분대 현 위치 이상 없음. 이 사 부상으로 후송 대기.',
      summary: '3분대 SITREP — 2-4 부상, 대형 유지',
      fields: { casualties: '2-4 WIA', ammo: '녹', intent: '현 위치 경계' },
      missing: [], conf: 0.91, status: 'pending', target_id: null, bytes: 58,
      decided_by: null, decided_at: null, decision_note: '', recheck_count: 0,
      sender_acked: false, history: [],
    },
  ]

  const [s1lat, s1lon] = offset(ORIGIN[0], ORIGIN[1], -20, 60)
  const [s2lat, s2lon] = offset(ORIGIN[0], ORIGIN[1], 50, 90)
  const sensors: Sensor[] = [
    { id: 'S-1', kind: 'pir', lat: s1lat, lon: s1lon, status: 'idle', last_trigger: null, battery: 88, last_seen: ts },
    { id: 'S-2', kind: 'acoustic', lat: s2lat, lon: s2lon, status: 'triggered', last_trigger: ts - 15, battery: 76, last_seen: ts },
  ]

  const links: Link[] = [
    { id: 'PL|1-1', a: 'PL', b: '1-1', rssi: -62, ts },
    { id: '1-1|1-2', a: '1-1', b: '1-2', rssi: -58, ts },
    { id: '1-1|1-3', a: '1-1', b: '1-3', rssi: -61, ts },
    { id: 'PL|2-1', a: 'PL', b: '2-1', rssi: -68, ts },
    { id: '2-1|2-2', a: '2-1', b: '2-2', rssi: -55, ts },
  ]

  const alerts: Alert[] = [
    {
      id: 'A-demo1', level: 'warn', kind: 'link_lost', msg: '3-4 통신 두절 (42초)',
      unit_id: '3-4', ts: ts - 40, ack: false,
    },
    {
      id: 'A-demo2', level: 'crit', kind: 'casualty', msg: '2-4 부상 (WIA)',
      unit_id: '2-4', ts: ts - 200, ack: true,
    },
    {
      id: 'A-demo3', level: 'info', kind: 'order', msg: '명령 하달 [정지] → 전 소대',
      unit_id: null, ts: ts - 70, ack: true,
    },
  ]

  const [rLat, rLon] = offset(ORIGIN[0], ORIGIN[1], 40, 80)
  const orders: Order[] = [
    {
      id: 'O-demo1', code: 'HALT', text: '전 소대 현 위치 정지', to: ['*'],
      recipients: units.filter((u) => u.role !== 'pl').map((u) => u.id),
      params: {}, priority: 'priority', issuer: 'PL', ts: ts - 70,
      acks: Object.fromEntries(
        units.filter((u) => u.status !== 'nolink' && u.role !== 'pl').slice(0, 10).map((u) => [u.id, ts - 65]),
      ),
      status: 'partial', ref_report: null, tx_count: 2, last_tx: ts - 60,
    },
    {
      id: 'O-demo2', code: 'RALLY', text: '1·2분대 지정 지점 집결', to: ['1', '2'],
      recipients: ['1-1', '1-2', '1-3', '1-4', '2-1', '2-2', '2-3', '2-4'],
      params: { lat: rLat, lon: rLon }, priority: 'urgent', issuer: 'PL', ts: ts - 30,
      acks: { '1-1': ts - 28, '2-1': ts - 27 },
      status: 'sent', ref_report: null, tx_count: 1, last_tx: ts - 30,
    },
  ]

  const mission: Mission = {
    name: 'UI Mockup · 정찰 시연',
    emcon: false,
    origin: ORIGIN,
    objective: OBJECTIVE,
    route: ROUTE,
    phase_lines: [
      { name: 'PL 알파', coords: [[36.3020, 127.4170], [36.3010, 127.4235]] },
      { name: 'PL 브라보', coords: [[36.3060, 127.4210], [36.3040, 127.4275]] },
    ],
  }

  const stats: Stats = {
    started: ts - 600,
    tx_bytes: 18420,
    tx_msgs: 312,
    tx_by_type: { 'unit.position': 9000, 'unit.relpos': 5200, 'report.new': 2200, 'link.update': 2020 },
    voice_equiv_bytes: 480_000,
    voiceable_bytes: 2400,
  }

  return { units, targets, reports, sensors, links, alerts, orders, mission, stats, server_time: ts }
}

export const MOCK_BRIEF = `■ 상황 브리핑 (데모)
시각 기준 소대는 정찰 축선을 따라 북동진 중.
아군: 정상 다수, 부상 1(2-4), 통신두절 1(3-4).
적: 확인된 보병 4명(1분대 전방), 미확인 차량 1대 승인 대기.
센서 S-2 음향 감지 활성. 집결 명령 일부 수신 확인 중.
권고: 3-4 링크 복구 확인, SPOT 보고 결심, 부상 후송 경로 확보.`
