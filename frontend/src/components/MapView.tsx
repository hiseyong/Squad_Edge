import { Fragment, useEffect, useMemo, useRef, useState } from 'react'
import {
  Circle, LayersControl, MapContainer, Marker, Polyline, ScaleControl, TileLayer, Tooltip, useMap,
  useMapEvents,
} from 'react-leaflet'
import { useCop } from '../store'
import { toMgrs } from '../lib/geo'
import { isContactTarget, objectiveIcon, orderPointIcon, targetIcon, unitIcon } from '../lib/symbols'
import { ORDER_META, rssiColor } from '../lib/format'
import { statusLabel, unitOnMap } from '../lib/unitDisplay'
import { useNow } from '../lib/useNow'
import type { Layers } from '../store'

// CARTO 베이스맵은 2026-09-25부터 API 키 필수. frontend/.env.local 에 VITE_CARTO_KEY=... 설정 시 사용
const CARTO_KEY = import.meta.env.VITE_CARTO_KEY as string | undefined

const TARGET_FADE_SEC = 300 // 5분에 걸쳐 표적 흐려짐(정보 신선도)

/** SoftAP 등 오프라인: 미리 받아 둔 /tiles 가 있으면 기본 베이스맵으로 사용 */
function useOfflineTilesReady() {
  const [ready, setReady] = useState<boolean | null>(null)
  useEffect(() => {
    let cancelled = false
    // 시연 AOI 중심 (36.3005,127.4185) z=15 타일 — tools/fetch_offline_tiles.py
    const probe = '/tiles/15/27981/12833.jpg'
    fetch(probe, { method: 'GET', cache: 'force-cache' })
      .then((r) => {
        if (!cancelled) setReady(r.ok)
      })
      .catch(() => {
        if (!cancelled) setReady(false)
      })
    return () => { cancelled = true }
  }, [])
  return ready
}

function FlyController() {
  const map = useMap()
  const focus = useCop((s) => s.focus)
  useEffect(() => {
    if (focus) map.flyTo([focus.lat, focus.lon], focus.zoom ?? Math.max(map.getZoom(), 17), { duration: 0.6 })
  }, [focus, map])
  return null
}

function CursorReadout() {
  const [pos, setPos] = useState<[number, number] | null>(null)
  const [zoom, setZoom] = useState(17)
  useMapEvents({
    mousemove: (e) => setPos([e.latlng.lat, e.latlng.lng]),
    zoomend: (e) => setZoom(e.target.getZoom()),
  })
  return (
    <div className="pointer-events-none absolute bottom-2 left-1/2 z-[1000] -translate-x-1/2 border border-prisma-border bg-prisma-panel/90 px-2.5 py-1 font-mono text-[11px] text-prisma-muted backdrop-blur-sm">
      {pos ? `MGRS ${toMgrs(pos[0], pos[1])}  ·  ${pos[0].toFixed(5)}, ${pos[1].toFixed(5)}` : 'MGRS —'} · Z{zoom}
    </div>
  )
}

/** 오프라인에서도 보이는 미터 격자 (타일 없어도 거리감 제공) */
function MetricGrid({ origin }: { origin: [number, number] }) {
  const map = useMap()
  const [lines, setLines] = useState<[number, number][][]>([])
  useEffect(() => {
    const update = () => {
      const z = map.getZoom()
      const step = z >= 17 ? 100 : z >= 15 ? 500 : 1000
      const b = map.getBounds()
      const [lat0, lon0] = origin
      const mLat = 111320, mLon = 111320 * Math.cos((lat0 * Math.PI) / 180)
      const n0 = Math.floor(((b.getSouth() - lat0) * mLat) / step), n1 = Math.ceil(((b.getNorth() - lat0) * mLat) / step)
      const e0 = Math.floor(((b.getWest() - lon0) * mLon) / step), e1 = Math.ceil(((b.getEast() - lon0) * mLon) / step)
      if ((n1 - n0) * (e1 - e0) > 4000) return setLines([])
      const out: [number, number][][] = []
      for (let i = n0; i <= n1; i++) {
        const lat = lat0 + (i * step) / mLat
        out.push([[lat, b.getWest()], [lat, b.getEast()]])
      }
      for (let j = e0; j <= e1; j++) {
        const lon = lon0 + (j * step) / mLon
        out.push([[b.getSouth(), lon], [b.getNorth(), lon]])
      }
      setLines(out)
    }
    update()
    map.on('moveend', update)
    return () => { map.off('moveend', update) }
  }, [map, origin])
  return (
    <>
      {lines.map((l, i) => (
        <Polyline key={i} positions={l} interactive={false} pathOptions={{ color: '#2bb7c7', weight: 0.5, opacity: 0.16 }} />
      ))}
    </>
  )
}

/** 소대장 자동 추적: 최초 1회 중심 이동 + follow 모드 */
function Follow({ follow }: { follow: boolean }) {
  const map = useMap()
  const pl = useCop((s) => s.units['PL'])
  const [init, setInit] = useState(false)
  useEffect(() => {
    if (!pl?.lat) return
    if (!init) { map.setView([pl.lat, pl.lon!], 17); setInit(true) }
    else if (follow) map.panTo([pl.lat, pl.lon!], { animate: true, duration: 0.5 })
  }, [pl?.lat, pl?.lon, follow, init, map])
  return null
}

/** 명령 목표 지점 지정: pickMode일 때 지도 클릭 → orderPoint */
function PickHandler() {
  const map = useMap()
  const pickMode = useCop((s) => s.pickMode)
  const setOrderPoint = useCop((s) => s.setOrderPoint)
  useEffect(() => {
    const el = map.getContainer()
    el.classList.toggle('pick-mode', pickMode)
  }, [pickMode, map])
  useMapEvents({ click: (e) => { if (useCop.getState().pickMode) setOrderPoint([e.latlng.lat, e.latlng.lng]) } })
  return null
}

function ZoomWatcher({ onZoom }: { onZoom: (z: number) => void }) {
  useMapEvents({ zoomend: (e) => onZoom(e.target.getZoom()) })
  return null
}

const LAYER_LABEL: Record<keyof Layers, string> = {
  links: '메시 링크', trails: '이동 궤적', errors: '위치 오차', route: '경로/통제선',
}

function LayerToggles() {
  const layers = useCop((s) => s.layers)
  const toggle = useCop((s) => s.toggleLayer)
  return (
    <div className="absolute top-2 left-12 z-[1000] flex flex-wrap gap-1">
      {(Object.keys(layers) as (keyof Layers)[]).map((k) => (
        <button
          key={k}
          type="button"
          onClick={() => toggle(k)}
          className={`prisma-map-ctl ${layers[k] ? 'on' : ''}`}
        >
          {LAYER_LABEL[k]}
        </button>
      ))}
    </div>
  )
}

export default function MapView() {
  const units = useCop((s) => s.units)
  const targets = useCop((s) => s.targets)
  const links = useCop((s) => s.links)
  const mission = useCop((s) => s.mission)
  const orders = useCop((s) => s.orders)
  const orderPoint = useCop((s) => s.orderPoint)
  const layers = useCop((s) => s.layers)
  const selectedUnit = useCop((s) => s.selectedUnit)
  const selectedTarget = useCop((s) => s.selectedTarget)
  const selectUnit = useCop((s) => s.selectUnit)
  const selectTarget = useCop((s) => s.selectTarget)
  const flyTo = useCop((s) => s.flyTo)
  const now = useNow()
  const [zoom, setZoom] = useState(17)
  const [follow, setFollow] = useState(false)
  const [grid, setGrid] = useState(true)
  const offlineReady = useOfflineTilesReady()
  const seenContacts = useRef(new Set<string>())

  const center: [number, number] = mission?.origin ?? [36.3005, 127.4185]
  const demoMode = useCop((s) => s.demoMode)
  const routerConnected = useCop((s) => s.routerConnected)
  const linkOpts = useMemo(() => ({ mode: demoMode, routerConnected }), [demoMode, routerConnected])
  // 두절·좌표없음·realtime 분대원 미연결 → 지도 비표시 (1-1은 mock)
  const unitList = useMemo(
    () => Object.values(units).filter((u) => unitOnMap(u, linkOpts)),
    [units, linkOpts],
  )

  // 신규 접적 → 지도 중심 이동
  useEffect(() => {
    for (const t of Object.values(targets)) {
      if (!isContactTarget(t) || seenContacts.current.has(t.id)) continue
      seenContacts.current.add(t.id)
      if (now - t.first_seen < 30) {
        flyTo(t.lat, t.lon, Math.max(zoom, 17))
        selectTarget(t.id)
      }
    }
  }, [targets, now, flyTo, selectTarget, zoom])

  return (
    <div className="relative h-full w-full">
      <MapContainer center={center} zoom={17} maxZoom={20} className="h-full w-full" zoomControl preferCanvas>
        {/* 기본 = 위성(온라인). mockup·실프론트 공통. SoftAP는 레이어에서 오프라인 위성 선택 */}
        <LayersControl position="topright">
          <LayersControl.BaseLayer checked name="위성 (온라인)">
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}"
              attribution="Esri World Imagery"
              className="tiles-imagery-dim"
              maxNativeZoom={19}
              maxZoom={20}
              keepBuffer={4}
              updateWhenZooming={false}
            />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="오프라인 위성 (시연 AOI)">
            <TileLayer
              url="/tiles/{z}/{x}/{y}.jpg"
              attribution="offline Esri Imagery · tools/fetch_offline_tiles.py"
              className="tiles-imagery-dim"
              maxZoom={20}
              maxNativeZoom={19}
              keepBuffer={4}
              updateWhenZooming={false}
              errorTileUrl="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
            />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Esri 스트리트 (온라인)">
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}"
              attribution="Esri, HERE, Garmin contributors"
              maxNativeZoom={19}
              maxZoom={20}
              keepBuffer={4}
            />
          </LayersControl.BaseLayer>
          <LayersControl.BaseLayer name="Esri 다크 그레이 (온라인)">
            <TileLayer
              url="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}"
              attribution="Esri, HERE, Garmin contributors"
              maxNativeZoom={16}
              maxZoom={18}
              keepBuffer={4}
            />
          </LayersControl.BaseLayer>
          {CARTO_KEY && (
            <LayersControl.BaseLayer name="CARTO 다크 (키)">
              <TileLayer
                url={`https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}{r}.png?key=${CARTO_KEY}`}
                attribution="&copy; OpenStreetMap &copy; CARTO"
                maxZoom={20}
                detectRetina
              />
            </LayersControl.BaseLayer>
          )}
        </LayersControl>
        <ScaleControl position="bottomleft" imperial={false} />
        <FlyController />
        <CursorReadout />
        <ZoomWatcher onZoom={setZoom} />
        <Follow follow={follow} />
        <PickHandler />
        {grid && <MetricGrid origin={center} />}

        {/* 경로 / 통제선 / 목표 */}
        {layers.route && mission && (
          <>
            {mission.route.length > 1 && (
              <Polyline positions={mission.route} pathOptions={{ color: '#2bb7c7', weight: 2, dashArray: '6 6', opacity: 0.7 }} />
            )}
            {mission.phase_lines.map((pl) => (
              <Polyline key={pl.name} positions={pl.coords} pathOptions={{ color: '#48aff0', weight: 2, opacity: 0.75 }}>
                <Tooltip permanent direction="center" className="pl-label">{pl.name}</Tooltip>
              </Polyline>
            ))}
            {mission.objective && <Marker position={mission.objective} icon={objectiveIcon('OBJ')} />}
          </>
        )}

        {/* 명령 지점 (이동·집결) */}
        {Object.values(orders)
          .filter((o) => o.params.lat != null && o.status !== 'cancelled' && o.status !== 'superseded' && now - o.ts < 900)
          .map((o) => (
            <Marker key={`op-${o.id}`} position={[o.params.lat!, o.params.lon!]}
              icon={orderPointIcon(`${ORDER_META[o.code]?.label ?? o.code} ${Object.keys(o.acks).length}/${o.recipients.length}`)}>
              <Tooltip direction="top">{o.text}<br />{toMgrs(o.params.lat!, o.params.lon!)}</Tooltip>
            </Marker>
          ))}
        {orderPoint && <Marker position={orderPoint} icon={orderPointIcon('지정 지점', true)} />}

        {/* 메시 링크 */}
        {layers.links &&
          Object.values(links).map((l) => {
            const a = units[l.a], b = units[l.b]
            if (!a || !b || !unitOnMap(a, linkOpts) || !unitOnMap(b, linkOpts)) return null
            return (
              <Polyline
                key={l.id}
                positions={[[a.lat!, a.lon!], [b.lat!, b.lon!]]}
                pathOptions={{ color: rssiColor(l.rssi), weight: 1, opacity: 0.35 }}
              />
            )
          })}

        {/* 궤적 */}
        {layers.trails &&
          unitList
            .filter((u) => u.role === 'pl' || u.role === 'sl' || u.id === selectedUnit)
            .map((u) => (
              <Polyline key={`tr-${u.id}`} positions={[...u.trail, [u.lat!, u.lon!]]}
                pathOptions={{ color: '#48aff0', weight: 1.5, opacity: 0.4 }} />
            ))}

        {/* 위치 오차 원 (BLE 상대측위) */}
        {layers.errors &&
          unitList
            .filter((u) => u.pos_err > 3.5 && u.status !== 'kia')
            .map((u) => (
              <Circle key={`er-${u.id}`} center={[u.lat!, u.lon!]} radius={u.pos_err}
                pathOptions={{ color: '#48aff0', weight: 0.5, fillOpacity: 0.08, opacity: 0.4 }} />
            ))}

        {/* 표적 · 접적 */}
        {Object.values(targets)
          .filter((t) => t.status !== 'rejected')
          .map((t) => {
            const age = now - t.last_seen
            const contact = isContactTarget(t)
            // 접적은 5분간 선명하게 유지
            const fadeSec = contact ? Math.max(TARGET_FADE_SEC, 300) : TARGET_FADE_SEC
            const opacity = Math.max(contact ? 0.55 : 0.25, 1 - age / fadeSec) * (t.status === 'pending' ? 0.85 : 1)
            const color = contact ? '#ff3b3b' : t.affiliation === 'hostile' ? '#f55656' : '#f5c842'
            return (
              <Fragment key={t.id}>
                {contact && age < 90 && (
                  <Circle center={[t.lat, t.lon]} radius={Math.max(t.err_m * 1.4, 40)}
                    pathOptions={{ color, weight: 2, fillOpacity: 0.12, opacity: 0.85, className: 'contact-pulse' }} />
                )}
                <Circle center={[t.lat, t.lon]} radius={t.err_m}
                  pathOptions={{
                    color, weight: contact ? 2 : 1,
                    dashArray: t.status === 'pending' ? '4 4' : undefined,
                    fillOpacity: (contact ? 0.14 : 0.07) * opacity,
                    opacity: 0.7 * opacity,
                  }} />
                <Marker
                  position={[t.lat, t.lon]}
                  icon={targetIcon(t, t.id === selectedTarget)}
                  opacity={opacity}
                  zIndexOffset={contact ? 800 : 200}
                  eventHandlers={{ click: () => selectTarget(t.id) }}
                >
                  <Tooltip direction="top" offset={[0, -14]} permanent={contact && age < 45}>
                    <div className="text-xs">
                      {contact && <b className="text-prisma-danger">접적 </b>}
                      <b>{t.label || t.kind}</b> {t.count ? `· ${t.count}` : ''} {t.status === 'pending' && '(미확인)'}
                      <br />{t.activity}<br />{toMgrs(t.lat, t.lon)} · ±{t.err_m}m · 신뢰도 {(t.conf * 100).toFixed(0)}%
                      <br />{Math.floor(age)}초 전 · {t.reported_by ?? t.source}
                    </div>
                  </Tooltip>
                </Marker>
              </Fragment>
            )
          })}

        {/* 아군 */}
        {unitList.map((u) => (
          <Marker
            key={`${u.id}:${u.status}:${u.lat?.toFixed(5)}:${u.lon?.toFixed(5)}`}
            position={[u.lat!, u.lon!]}
            icon={unitIcon(u, u.id === selectedUnit, zoom >= 18)}
            zIndexOffset={u.role === 'pl' ? 1000 : u.role === 'sl' ? 500 : 0}
            eventHandlers={{ click: () => selectUnit(u.id) }}
          >
            <Tooltip direction="top" offset={[0, -10]}>
              <div className="text-xs">
                <b>{u.callsign}</b> · {statusLabel(u, linkOpts)} · 배터리 {u.battery.toFixed(0)}%
                <br />{u.pos_source === 'ble-rel' ? `BLE 상대측위 ±${u.pos_err.toFixed(1)}m` : `GPS ±${u.pos_err.toFixed(0)}m`}
                <br />{toMgrs(u.lat!, u.lon!)}
              </div>
            </Tooltip>
          </Marker>
        ))}
      </MapContainer>
      <LayerToggles />
      <div className="absolute bottom-8 right-2 z-[1000] flex flex-col gap-1">
        <button type="button" onClick={() => setFollow(!follow)} className={`prisma-map-ctl ${follow ? 'on' : ''}`}>
          Follow PL {follow ? 'ON' : 'OFF'}
        </button>
        <button type="button" onClick={() => setGrid(!grid)} className={`prisma-map-ctl ${grid ? 'on' : ''}`}>
          Grid {grid ? 'ON' : 'OFF'}
        </button>
        {offlineReady === false && (
          <div className="max-w-[11rem] border border-prisma-warn/50 bg-prisma-panel/95 px-2 py-1 text-[10px] text-prisma-warn">
            오프라인 타일 없음 · SoftAP 전에<br />
            <span className="font-mono text-prisma-muted">python3 tools/fetch_offline_tiles.py</span>
          </div>
        )}
        {offlineReady === true && (
          <div className="border border-prisma-ok/40 bg-prisma-panel/90 px-2 py-0.5 text-[10px] text-prisma-ok">
            오프라인 지도 준비됨
          </div>
        )}
      </div>
    </div>
  )
}
