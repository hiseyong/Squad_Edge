import { forward } from 'mgrs'

const R = 6371000
const rad = (d: number) => (d * Math.PI) / 180

export function enu(lat0: number, lon0: number, lat: number, lon: number): [number, number] {
  const n = rad(lat - lat0) * R
  const e = rad(lon - lon0) * R * Math.cos(rad(lat0))
  return [e, n]
}

export function distance(lat1: number, lon1: number, lat2: number, lon2: number) {
  const [e, n] = enu(lat1, lon1, lat2, lon2)
  return Math.hypot(e, n)
}

export function bearing(lat1: number, lon1: number, lat2: number, lon2: number) {
  const [e, n] = enu(lat1, lon1, lat2, lon2)
  return ((Math.atan2(e, n) * 180) / Math.PI + 360) % 360
}

export function clockDir(relBearing: number) {
  const h = Math.round((((relBearing % 360) + 360) % 360) / 30) % 12
  return h === 0 ? 12 : h
}

export function toMgrs(lat: number, lon: number, digits = 5) {
  try {
    const m = forward([lon, lat], digits)
    // 52SCF1234567890 → 52S CF 12345 67890
    const g = m.match(/^(\d{1,2}[A-Z])([A-Z]{2})(\d+)$/)
    if (!g) return m
    const half = g[3].length / 2
    return `${g[1]} ${g[2]} ${g[3].slice(0, half)} ${g[3].slice(half)}`
  } catch {
    return `${lat.toFixed(5)}, ${lon.toFixed(5)}`
  }
}
