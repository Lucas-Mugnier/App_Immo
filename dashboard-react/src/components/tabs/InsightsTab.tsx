import { useMemo, useEffect, useRef, useState } from 'react'
import { BarChart, Bar as RBar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import { useStore, useHasPrivateData } from '@/store/useStore'
import { eur, num, pm2, median, daysAgo, cn, NEIGHBOURHOOD_ORDER } from '@/lib/utils'
import type { Listing, Maison, InsightType, MapMetric } from '@/types'
import { APPARTS, MAISONS, DVF_STATS, DVF_POINTS } from '@/lib/data'


// ── Geo: neighbourhood centroids ──────────────────────────────────────────────
const NB_GEO: Record<string, [number, number]> = {
  'Les Houches':     [45.8950, 6.8012],
  'Les Bossons':     [45.9039, 6.8512],
  'Les Pélerins':    [45.9112, 6.8650],
  'Les Gaillands':   [45.9150, 6.8580],
  'Chamonix Centre': [45.9237, 6.8694],
  'Les Praz':        [45.9391, 6.8989],
  'Les Tines':       [45.9480, 6.9123],
  'Le Lavancher':    [45.9650, 6.9250],
  'Argentière':      [45.9780, 6.9389],
  'Montroc':         [45.9880, 6.9700],
  'Le Tour':         [45.9950, 6.9820],
  'Servoz':          [45.9456, 6.7687],
  'Saint-Gervais':   [45.8928, 6.7072],
  'Sallanches':      [45.9318, 6.6336],
  'Passy':           [45.9194, 6.6905],
  'Domancy':         [45.9213, 6.6612],
}

// ── Geo: DVF commune centroids ────────────────────────────────────────────────
const DVF_GEO: Record<string, [number, number]> = {
  'CHAMONIX MONT BLANC':    [45.9237, 6.8694],
  'LES HOUCHES':            [45.8950, 6.7987],
  'SAINT GERVAIS LES BAINS':[45.8928, 6.7072],
  'SALLANCHES':             [45.9318, 6.6336],
  'PASSY':                  [45.9194, 6.6905],
  'SERVOZ':                 [45.9456, 6.7687],
  'DOMANCY':                [45.9213, 6.6612],
}

function haversineM(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371000
  const dLat = (lat2 - lat1) * Math.PI / 180
  const dLon = (lon2 - lon1) * Math.PI / 180
  const a = Math.sin(dLat / 2) ** 2
    + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a))
}

function jitter(idx: number, total: number, spread = 0.003): [number, number] {
  const r = spread * Math.sqrt(idx / Math.max(total, 1))
  const theta = idx * Math.PI * (3 - Math.sqrt(5))
  return [r * Math.cos(theta), r * Math.sin(theta)]
}

// ── KPI card ──────────────────────────────────────────────────────────────────
function Kpi({ label, value, sub, good }: {
  label: string; value: string; sub?: string; good?: boolean | null
}) {
  return (
    <div className="insight-kpi">
      <div className="insight-kpi-label">{label}</div>
      <div
        className="insight-kpi-value"
        style={good === true  ? { color: 'var(--green)' }
             : good === false ? { color: 'var(--red)'   } : undefined}
      >
        {value}
      </div>
      {sub && <div className="insight-kpi-sub">{sub}</div>}
    </div>
  )
}

// ── Horizontal bar ────────────────────────────────────────────────────────────
function Bar({ pct, color = 'var(--accent)' }: { pct: number; color?: string }) {
  return (
    <div className="insight-bar-track">
      <div className="insight-bar-fill" style={{ width: `${Math.max(pct, 2)}%`, background: color }} />
    </div>
  )
}

// ── DVF Trends ────────────────────────────────────────────────────────────────
const DVF_ORDER = [
  'CHAMONIX MONT BLANC', 'LES HOUCHES', 'SAINT GERVAIS LES BAINS',
  'SALLANCHES', 'PASSY', 'SERVOZ', 'DOMANCY',
]

function DvfTrends() {
  const communes = DVF_ORDER.filter((k) => DVF_STATS.communes?.[k])
  const years    = (DVF_STATS.annees ?? []).map(String)
  const W = 100; const H = 28

  function Spark({ byYear }: { byYear: Record<string, { median_m2: number }> }) {
    const pts = years.map((y) => byYear[y]?.median_m2 ?? null).filter(Boolean) as number[]
    if (pts.length < 2) return null
    const lo = Math.min(...pts), hi = Math.max(...pts)
    const xs = pts.map((_, i) => (i / (pts.length - 1)) * (W - 6) + 3)
    const ys = pts.map((v) => H - 3 - ((v - lo) / (hi - lo || 1)) * (H - 6))
    const d  = xs.map((x, i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(' ')
    return (
      <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} style={{ display: 'block' }}>
        <path d={d} fill="none" stroke="var(--accent)" strokeWidth="1.5"
          strokeLinecap="round" strokeLinejoin="round" />
        <circle cx={xs[xs.length - 1]} cy={ys[ys.length - 1]} r="2" fill="var(--accent)" />
      </svg>
    )
  }

  if (!communes.length || !years.length) return null
  const maxCagr = Math.max(...communes.map((k) => DVF_STATS.communes[k].cagr_pct))
  return (
    <div className="insight-card">
      <div className="insight-card-header">
        <span className="insight-card-title">Tendances DVF 2021–2025</span>
        <span className="insight-card-sub">{num(DVF_STATS.total_transactions)} transactions réelles</span>
      </div>
      <div className="insight-dvf-grid">
        {communes.map((key) => {
          const c   = DVF_STATS.communes[key]
          const pct = (c.cagr_pct / maxCagr) * 100
          return (
            <div key={key} className="insight-dvf-row">
              <span className="insight-dvf-name">{c.display}</span>
              <span className="insight-dvf-pm2">{num(c.median_m2)}€/m²</span>
              <div className="insight-dvf-bar-wrap"><Bar pct={pct} /></div>
              <span className="insight-dvf-cagr"
                style={{ color: c.cagr_pct >= 7 ? 'var(--green)' : c.cagr_pct >= 4 ? 'var(--accent)' : 'var(--text-faint)' }}>
                +{c.cagr_pct.toFixed(1)}%/an
              </span>
              <div className="insight-dvf-spark"><Spark byYear={c.by_year} /></div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── PM² En vente vs DVF par secteur ──────────────────────────────────────────
function Pm2VsDvf({ insightType, sector }: { insightType: InsightType; sector: string }) {
  const zones = useMemo(() => {
    const nbs = sector !== 'all'
      ? [sector]
      : NEIGHBOURHOOD_ORDER.filter((nb) =>
          APPARTS.some((r) => r.neighbourhood === nb) || MAISONS.some((m) => m.neighbourhood === nb)
        )
    return nbs.map((nb) => {
      const center = NB_GEO[nb]
      const aptPm2s = insightType !== 'maisons'
        ? APPARTS.filter((r) => r.neighbourhood === nb).map((r) => pm2(r.price, r.surface)).filter(Boolean) as number[]
        : []
      const maiPm2s = insightType !== 'apparts'
        ? MAISONS.filter((m) => m.neighbourhood === nb).map((m) => pm2(m.prix, m.surface)).filter(Boolean) as number[]
        : []
      const listingPm2 = median([...aptPm2s, ...maiPm2s])
      const dvfPts = center
        ? DVF_POINTS.filter((pt) => {
            if (haversineM(center[0], center[1], pt.lat, pt.lon) > 900) return false
            if (insightType === 'apparts') return pt.t === 'appart'
            if (insightType === 'maisons') return pt.t === 'maison'
            return true
          })
        : []
      const dvfPm2 = median(dvfPts.map((pt) => pt.m2).filter(Boolean) as number[])
      if (!listingPm2 || !dvfPm2) return null
      return { nb, listingPm2, dvfPm2, delta: ((listingPm2 - dvfPm2) / dvfPm2) * 100, n: aptPm2s.length + maiPm2s.length }
    }).filter(Boolean) as { nb: string; listingPm2: number; dvfPm2: number; delta: number; n: number }[]
  }, [insightType, sector])

  const maxPm2 = Math.max(...zones.map((z) => Math.max(z.listingPm2, z.dvfPm2)), 1)

  return (
    <div className="insight-card">
      <div className="insight-card-header">
        <span className="insight-card-title">PM² En vente vs Transactions DVF</span>
        <span className="insight-card-sub">annonces actuelles vs ventes réelles 2021–2025</span>
      </div>
      {zones.length === 0 ? <div className="insight-empty">Pas de données communes</div> : (
        <div className="insight-pm2dvf-grid">
          {zones.map((z) => {
            const color = z.delta > 15 ? 'var(--red)' : z.delta < -5 ? 'var(--green)' : 'var(--accent)'
            return (
              <div key={z.nb} className="insight-pm2dvf-row">
                <span className="insight-pm2dvf-name">{z.nb}</span>
                <div className="insight-pm2dvf-bars">
                  <div className="insight-pm2dvf-bar-wrap">
                    <div className="insight-pm2dvf-bar dvf-bar" style={{ width: `${(z.dvfPm2 / maxPm2) * 100}%` }} />
                    <span className="insight-pm2dvf-val">{num(Math.round(z.dvfPm2))}€</span>
                  </div>
                  <div className="insight-pm2dvf-bar-wrap">
                    <div className="insight-pm2dvf-bar listing-bar" style={{ width: `${(z.listingPm2 / maxPm2) * 100}%` }} />
                    <span className="insight-pm2dvf-val">{num(Math.round(z.listingPm2))}€</span>
                  </div>
                </div>
                <span className="insight-pm2dvf-delta" style={{ color }}>
                  {z.delta > 0 ? '+' : ''}{z.delta.toFixed(0)}%
                </span>
              </div>
            )
          })}
          <div className="insight-pm2dvf-legend">
            <span><span className="insight-pm2dvf-dot dvf-dot" />DVF réel</span>
            <span><span className="insight-pm2dvf-dot listing-dot" />En vente</span>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Distribution PM² ──────────────────────────────────────────────────────────
function Pm2Distribution({ insightType }: { insightType: InsightType }) {
  const data = useMemo(() => {
    const BINS: { lo: number; hi: number; label: string; apt: number; mai: number }[] = []
    for (let lo = 3000; lo < 26000; lo += 2000) {
      BINS.push({ lo, hi: lo + 2000, label: `${lo / 1000}k`, apt: 0, mai: 0 })
    }
    if (insightType !== 'maisons') {
      APPARTS.forEach((r) => {
        const v = pm2(r.price, r.surface); if (!v) return
        const b = BINS.find((b) => v >= b.lo && v < b.hi); if (b) b.apt++
      })
    }
    if (insightType !== 'apparts') {
      MAISONS.forEach((m) => {
        const v = pm2(m.prix, m.surface); if (!v) return
        const b = BINS.find((b) => v >= b.lo && v < b.hi); if (b) b.mai++
      })
    }
    return BINS.filter((b) => b.apt + b.mai > 0)
  }, [insightType])

  return (
    <div className="insight-card">
      <div className="insight-card-header">
        <span className="insight-card-title">Distribution PM²</span>
        <span className="insight-card-sub">annonces actives</span>
      </div>
      <ResponsiveContainer width="100%" height={150}>
        <BarChart data={data} margin={{ top: 4, right: 4, bottom: 0, left: -16 }} barCategoryGap="20%">
          <XAxis dataKey="label" tick={{ fontSize: 10, fill: 'var(--text-faint)' }} tickLine={false} axisLine={false} />
          <YAxis tick={{ fontSize: 10, fill: 'var(--text-faint)' }} tickLine={false} axisLine={false} />
          <Tooltip
            contentStyle={{ fontSize: '0.75rem', borderRadius: 8, border: '1px solid var(--border)', background: 'var(--surface)' }}
            formatter={(val: number, name: string) => [val, name === 'apt' ? 'Apparts' : 'Maisons']}
            labelFormatter={(l) => `${l} – ${parseInt(l as string) + 2}k €/m²`}
          />
          {insightType !== 'maisons' && <RBar dataKey="apt" fill="#c49a3a" name="apt" radius={[3, 3, 0, 0]} />}
          {insightType !== 'apparts' && <RBar dataKey="mai" fill="#64748b" name="mai" radius={[3, 3, 0, 0]} />}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

// ── Ancienneté des annonces ───────────────────────────────────────────────────
function AnciennetePanel({ insightType, sector }: { insightType: InsightType; sector: string }) {
  const items = useMemo(() => {
    let apt = insightType !== 'maisons' ? APPARTS : []
    let mai = insightType !== 'apparts' ? MAISONS : []
    if (sector !== 'all') {
      apt = apt.filter((r) => r.neighbourhood === sector)
      mai = mai.filter((m) => m.neighbourhood === sector)
    }
    return [
      ...apt.map((r) => ({
        id: r.id, label: r.neighbourhood || r.location,
        price: r.price, surface: r.surface,
        days: daysAgo(r.first_seen), baisses: r.price_drop ?? 0, type: 'appart' as const,
      })),
      ...mai.map((m) => ({
        id: m.id, label: m.adresse_raw || m.neighbourhood,
        price: m.prix, surface: m.surface,
        days: daysAgo(m.first_seen), baisses: m.nb_baisses ?? 0, type: 'maison' as const,
      })),
    ].sort((a, b) => b.days - a.days || b.baisses - a.baisses)
  }, [insightType, sector])

  const medDays  = items.length ? Math.round(median(items.map((i) => i.days))) : 0
  const maxDays  = items.length ? Math.max(...items.map((i) => i.days)) : 0
  const nbBaisses = items.filter((i) => i.baisses > 0).length

  return (
    <div className="insight-card">
      <div className="insight-card-header">
        <span className="insight-card-title">Ancienneté des annonces</span>
        <span className="insight-card-sub">médiane {medDays}j · max {maxDays}j · {nbBaisses} baisses</span>
      </div>
      <div className="insight-deals-list">
        {items.slice(0, 8).map((item) => (
          <div key={item.id} className="insight-deal-row">
            <div className="insight-deal-left">
              <span className="insight-deal-loc">{item.label}</span>
              <span className="insight-deal-meta">{eur(item.price)} · {item.surface}m²</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 2 }}>
              <span style={{ fontSize: '0.8rem', fontWeight: 700,
                color: item.days >= 60 ? 'var(--red)' : item.days >= 30 ? 'var(--accent)' : 'var(--text-faint)' }}>
                {item.days}j
              </span>
              {item.baisses > 0 && (
                <span style={{ fontSize: '0.68rem', color: 'var(--green)', fontWeight: 600 }}>↓{item.baisses}×</span>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Map ───────────────────────────────────────────────────────────────────────
type MapLayer  = 'sale' | 'dvf'
type MapBien   = 'all' | 'apparts' | 'maisons'

interface MapViewProps {
  insightType: InsightType
  metric: MapMetric
  sector: string
  dark: boolean
  layers: Set<MapLayer>
  bienFilter: MapBien
}

function MapView({ insightType, metric, sector, dark, layers, bienFilter }: MapViewProps) {
  const mapRef      = useRef<HTMLDivElement>(null)
  const mapInstance = useRef<unknown>(null)

  useEffect(() => {
    if (!mapRef.current) return
    async function initMap() {
      if (mapInstance.current) {
        // @ts-expect-error leaflet
        mapInstance.current.remove(); mapInstance.current = null
      }
      const L = (await import('leaflet')).default
      // @ts-expect-error
      delete L.Icon.Default.prototype._getIconUrl
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
        iconUrl:       'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
        shadowUrl:     'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
      })
      if (!mapRef.current) return

      // Zoom to sector if selected
      const center: [number, number] = sector !== 'all' && NB_GEO[sector]
        ? NB_GEO[sector]
        : [45.935, 6.885]
      const zoom = sector !== 'all' ? 14 : 12

      const map = L.map(mapRef.current, { center, zoom })
      mapInstance.current = map

      // Tile layer — dark or light
      if (dark) {
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
          attribution: '© OpenStreetMap © CartoDB', opacity: 0.85,
        }).addTo(map)
      } else {
        L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
          attribution: '© OpenStreetMap © CartoDB', opacity: 1,
        }).addTo(map)
        L.tileLayer('https://tiles.opensnowmap.org/pistes/{z}/{x}/{y}.png', {
          attribution: '© OpenSnowMap.org', opacity: 0.8, maxZoom: 18,
        }).addTo(map)
      }

      const DVF_COLOR  = '#6b8cba'                          // muted blue — DVF transactions

      // ── Icon helpers ──────────────────────────────────────────────────────
      function saleColor(pm2v: number | null, ratio: number | null, score: number | null, isApt: boolean): string {
        if (metric === 'pm2') {
          const v = pm2v ?? 0
          return isApt
            ? (v >= 14000 ? '#c94040' : v >= 10000 ? '#c49a3a' : '#3a7a4a')
            : (v >= 6000  ? '#c94040' : v >= 4000  ? '#c49a3a' : '#3a7a4a')
        }
        if (metric === 'ratio') {
          const r = ratio ?? 0
          return r <= 0.90 ? '#3a7a4a' : r <= 1.05 ? '#c49a3a' : '#c94040'
        }
        const s = score ?? 0
        return s >= 70 ? '#3a7a4a' : s >= 45 ? '#c49a3a' : '#c94040'
      }

      function makeIcon(type: 'appart' | 'maison', fill: string): L.DivIcon {
        const houseSvg = `<svg width="22" height="22" viewBox="0 0 22 22" xmlns="http://www.w3.org/2000/svg">
          <polygon points="11,2 20,10 17,10 17,20 5,20 5,10 2,10" fill="${fill}" stroke="white" stroke-width="1.5" stroke-linejoin="round"/>
          <rect x="8" y="13" width="6" height="7" fill="rgba(255,255,255,0.4)"/>
        </svg>`
        const aptSvg = `<svg width="16" height="22" viewBox="0 0 16 22" xmlns="http://www.w3.org/2000/svg">
          <rect x="1" y="5" width="14" height="16" fill="${fill}" stroke="white" stroke-width="1.5" rx="1"/>
          <polygon points="8,1 15,5 1,5" fill="${fill}" stroke="white" stroke-width="1.5"/>
          <rect x="3" y="8" width="3" height="3" fill="rgba(255,255,255,0.55)"/>
          <rect x="10" y="8" width="3" height="3" fill="rgba(255,255,255,0.55)"/>
          <rect x="3" y="13" width="3" height="3" fill="rgba(255,255,255,0.55)"/>
          <rect x="10" y="13" width="3" height="3" fill="rgba(255,255,255,0.55)"/>
          <rect x="5" y="18" width="6" height="3" fill="rgba(255,255,255,0.3)"/>
        </svg>`
        const w = type === 'maison' ? 22 : 16
        return L.divIcon({
          className: '',
          html: type === 'maison' ? houseSvg : aptSvg,
          iconSize:    [w, 22],
          iconAnchor:  [w / 2, 22],
          popupAnchor: [0, -22],
        })
      }

      // ── For-sale listings ────────────────────────────────────────────────
      if (layers.has('sale')) {
        // Apartments — grouped at neighbourhood centroid with jitter
        if (insightType !== 'maisons' && bienFilter !== 'maisons') {
          const filtered = sector !== 'all'
            ? APPARTS.filter((r) => r.neighbourhood === sector)
            : APPARTS
          const byNb: Record<string, Listing[]> = {}
          filtered.forEach((r) => {
            const nb = r.neighbourhood || r.location || 'Chamonix Centre'
            ;(byNb[nb] = byNb[nb] ?? []).push(r)
          })
          Object.entries(byNb).forEach(([nb, arr]) => {
            const center = NB_GEO[nb]; if (!center) return
            arr.forEach((r, i) => {
              const [dl, dn] = jitter(i, arr.length, 0.004)
              const pm2v = pm2(r.price, r.surface)
              const color = saleColor(pm2v, r.avm_ratio, r.score, true)
              L.marker([center[0] + dl, center[1] + dn], { icon: makeIcon('appart', color) })
              .bindPopup(`<div style="font-size:0.78rem;min-width:140px">
                  <div style="font-size:0.68rem;color:#888;margin-bottom:3px">Appartement</div>
                  <div style="font-weight:600">${nb}</div>
                  <div style="margin-top:4px">${eur(r.price)} · ${r.surface}m²</div>
                  ${pm2v ? `<div style="color:#888">${num(pm2v)}€/m²</div>` : ''}
                  ${r.avm_ratio != null ? `<div style="color:${color}">AVM ×${r.avm_ratio.toFixed(2)}</div>` : ''}
                </div>`)
              .addTo(map)
            })
          })
        }

        // Maisons — use actual lat/lon when available, else neighbourhood centroid
        if (insightType !== 'apparts' && bienFilter !== 'apparts') {
          const filtered = sector !== 'all'
            ? MAISONS.filter((m) => m.neighbourhood === sector)
            : MAISONS
          filtered.forEach((m, i) => {
            const lat = m.lat ?? NB_GEO[m.neighbourhood]?.[0] ?? 45.923
            const lon = m.lon ?? NB_GEO[m.neighbourhood]?.[1] ?? 6.869
            const pm2v = pm2(m.prix, m.surface)
            const [dl, dn] = m.lat ? [0, 0] : jitter(i, filtered.length, 0.005)
            const color = saleColor(pm2v, m.avm_ratio, m.avm_score, false)
            L.marker([lat + dl, lon + dn], { icon: makeIcon('maison', color) })
            .bindPopup(`<div style="font-size:0.78rem;min-width:140px">
                <div style="font-size:0.68rem;color:#888;margin-bottom:3px">Maison · §${m.section}</div>
                <div style="font-weight:600">${m.neighbourhood || m.section}</div>
                <div style="margin-top:4px">${eur(m.prix)} · ${m.surface}m²</div>
                ${pm2v ? `<div style="color:#888">${num(pm2v)}€/m²</div>` : ''}
                ${m.avm_ratio != null ? `<div style="color:${color}">AVM ×${m.avm_ratio.toFixed(2)}</div>` : ''}
              </div>`)
            .addTo(map)
          })
        }
      }

      // ── DVF individual points ─────────────────────────────────────────────
      if (layers.has('dvf')) {
        function dvfPm2Color(pm2v: number | null): string {
          if (!pm2v) return DVF_COLOR
          if (pm2v >= 15000) return '#c94040'
          if (pm2v >= 10000) return '#c49a3a'
          return '#4a9a6a'
        }

        const sectorCenter = sector !== 'all' ? NB_GEO[sector] : null
        const filteredPts = DVF_POINTS.filter((pt) => {
          if (bienFilter === 'apparts' && pt.t !== 'appart') return false
          if (bienFilter === 'maisons' && pt.t !== 'maison') return false
          if (sectorCenter) {
            if (haversineM(sectorCenter[0], sectorCenter[1], pt.lat, pt.lon) > 900) return false
          }
          return true
        })

        filteredPts.forEach((pt) => {
          const color = dvfPm2Color(pt.m2)
          const addrLine = pt.a ?? `Section ${pt.sec}`
          const pm2Line  = pt.m2 ? `${num(pt.m2)}€/m²` : ''
          const typLabel = pt.t === 'appart' ? 'Appartement' : 'Maison'
          L.circleMarker([pt.lat, pt.lon], {
            radius: 4,
            fillColor: color,
            color: color,
            weight: 0,
            opacity: 0.9,
            fillOpacity: 0.65,
          })
          .bindPopup(`<div style="font-size:0.78rem;min-width:150px">
              <div style="font-size:0.68rem;color:#6b8cba;margin-bottom:3px;font-weight:600">DVF ${pt.y} · ${typLabel}</div>
              <div style="font-weight:600;margin-bottom:2px">${addrLine}</div>
              <div>${eur(pt.p)} · ${pt.s}m²${pt.ter ? ` · ${num(pt.ter)}m² terrain` : ''}</div>
              ${pm2Line ? `<div style="color:${color};font-weight:600">${pm2Line}</div>` : ''}
            </div>`)
          .addTo(map)
        })
      }
    }

    initMap()
    return () => {
      if (mapInstance.current) {
        // @ts-expect-error
        mapInstance.current.remove(); mapInstance.current = null
      }
    }
  }, [insightType, metric, sector, dark, layers, bienFilter])

  return <div ref={mapRef} style={{ height: 360, borderRadius: 'var(--radius-sm)', overflow: 'hidden' }} />
}

// ── Main ──────────────────────────────────────────────────────────────────────
export function InsightsTab() {
  const { insightType, setInsightType, mapMetric, setMapMetric, dark } = useStore()
  const [sector,     setSector]     = useState<string>('all')
  const hasData = useHasPrivateData()
  const setLoginOpen = useStore((s) => s.setLoginOpen)
  const [mapLayers,  setMapLayers]  = useState<Set<MapLayer>>(new Set([hasData ? 'sale' : 'dvf']))
  const [mapBien,    setMapBien]    = useState<MapBien>('all')

  const availableNeighbourhoods = useMemo(() => {
    const fromApt = insightType !== 'maisons'
      ? APPARTS.map((r) => r.neighbourhood).filter(Boolean)
      : []
    const fromMai = insightType !== 'apparts'
      ? MAISONS.map((m) => m.neighbourhood).filter(Boolean)
      : []
    return NEIGHBOURHOOD_ORDER.filter((n) => new Set([...fromApt, ...fromMai]).has(n))
  }, [insightType])

  useEffect(() => {
    if (sector !== 'all' && !availableNeighbourhoods.includes(sector)) setSector('all')
  }, [insightType, availableNeighbourhoods, sector])

  const data = useMemo(() => {
    let apt = insightType !== 'maisons' ? APPARTS : []
    let mai = insightType !== 'apparts' ? MAISONS : []
    if (sector !== 'all') {
      apt = apt.filter((r) => r.neighbourhood === sector)
      mai = mai.filter((m) => m.neighbourhood === sector)
    }

    const prices  = [...apt.map((r) => r.price), ...mai.map((m) => m.prix)].filter(Boolean)
    const pm2s_a  = apt.map((r) => pm2(r.price, r.surface)).filter(Boolean) as number[]
    const pm2s_m  = mai.map((m) => pm2(m.prix, m.surface)).filter(Boolean) as number[]
    const medPrice  = median(prices)
    const medPm2a   = median(pm2s_a)
    const medPm2m   = median(pm2s_m)
    const fresh     = apt.filter((r) => daysAgo(r.first_seen) <= 7).length
                    + mai.filter((m) => daysAgo(m.first_seen) <= 7).length
    const baisses   = apt.filter((r) => (r.price_drop ?? 0) > 0).length
                    + mai.filter((m) => (m.nb_baisses ?? 0) > 0).length

    const avmApt  = apt.filter((r) => r.avm_model === 'chamonix_apt' && r.avm_ratio != null)
    const avmMai  = mai.filter((m) => m.avm_ratio != null)
    const topDeals = [...avmApt, ...avmMai]
      .sort((a, b) => {
        const ar = 'title' in a ? (a as Listing).avm_ratio! : (a as Maison).avm_ratio!
        const br = 'title' in b ? (b as Listing).avm_ratio! : (b as Maison).avm_ratio!
        return ar - br  // ascending: lowest ratio = best deal first
      })
      .slice(0, 5)
    const ratios   = [...avmApt, ...avmMai].map((x) => 'title' in x ? (x as Listing).avm_ratio! : (x as Maison).avm_ratio!)
    const medRatio = median(ratios)

    const zones = sector === 'all'
      ? NEIGHBOURHOOD_ORDER.filter((n) => APPARTS.some((r) => r.neighbourhood === n) || MAISONS.some((m) => m.neighbourhood === n))
      : [sector]
    const pm2Zone = zones.map((nb) => {
      const srcApt = sector === 'all' ? APPARTS : apt
      const srcMai = sector === 'all' ? MAISONS : mai
      const ps = [
        ...srcApt.filter((r) => r.neighbourhood === nb).map((r) => pm2(r.price, r.surface)),
        ...srcMai.filter((m) => m.neighbourhood === nb).map((m) => pm2(m.prix, m.surface)),
      ].filter(Boolean) as number[]
      const n = srcApt.filter((r) => r.neighbourhood === nb).length
      return { label: nb, val: ps.length ? median(ps) : null, n }
    }).filter((z) => z.val != null && (z.n >= 1 || z.val))
    const pm2Max = Math.max(...pm2Zone.map((z) => z.val!), 1)

    return { apt, mai, medPrice, medPm2a, medPm2m, fresh, baisses, topDeals, medRatio, pm2Zone, pm2Max, n: apt.length + mai.length }
  }, [insightType, sector])

  function toggleLayer(l: MapLayer) {
    setMapLayers((prev) => {
      const next = new Set(prev)
      if (next.has(l)) { if (next.size > 1) next.delete(l) } // keep at least one
      else next.add(l)
      return next
    })
  }

  // ── Version publique : uniquement les données ouvertes DVF ─────────────────
  if (!hasData) {
    return (
      <div className="overflow-auto h-full">
        <div className="insight-page">
          <div className="insight-card public-intro">
            <div>
              <h1 className="public-intro-title">Le marché immobilier de Chamonix, en données réelles</h1>
              <p className="public-intro-text">
                Prix au m² et tendances issus des ventes réellement enregistrées (DVF),
                carte des transactions et estimateur de valeur. Le suivi des annonces en
                cours est réservé aux comptes invités.
              </p>
            </div>
            <div className="public-intro-actions">
              <button className="login-btn-primary" onClick={() => useStore.getState().openEstimateur({})}>
                Estimer un bien
              </button>
              <button className="login-btn-secondary" onClick={() => setLoginOpen(true)}>
                Accès invité
              </button>
            </div>
          </div>

          <DvfTrends />

          <div className="insight-card">
            <div className="insight-card-header">
              <span className="insight-card-title">Carte des ventes (DVF)</span>
            </div>
            <div className="insight-map-controls">
              <div className="insight-map-ctrl-group">
                <span className="insight-sector-label">Type</span>
                <div className="insight-filter-group">
                  {(['all', 'apparts', 'maisons'] as MapBien[]).map((b) => (
                    <button key={b}
                      className={cn('insight-filter-btn', mapBien === b && 'active')}
                      onClick={() => setMapBien(b)}>
                      {b === 'all' ? 'Tout' : b === 'apparts' ? 'Apparts' : 'Maisons'}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <MapView insightType={insightType} metric={mapMetric} sector="all" dark={dark}
              layers={mapLayers} bienFilter={mapBien} />
            <div className="insight-map-legend">
              <div className="insight-legend-item"><span className="insight-legend-dot" style={{ background: '#4a9a6a' }} /><span>&lt;10k€/m²</span></div>
              <div className="insight-legend-item"><span className="insight-legend-dot" style={{ background: '#c49a3a' }} /><span>10–15k€/m²</span></div>
              <div className="insight-legend-item"><span className="insight-legend-dot" style={{ background: '#c94040' }} /><span>&gt;15k€/m²</span></div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="overflow-auto h-full">
      <div className="insight-page">

        {/* Type filter + sector */}
        <div className="insight-filters">
          <div className="insight-filter-group">
            {(['all', 'apparts', 'maisons'] as InsightType[]).map((t) => (
              <button key={t}
                className={cn('insight-filter-btn', insightType === t && 'active')}
                onClick={() => setInsightType(t)}>
                {t === 'all' ? 'Tout' : t === 'apparts' ? 'Appartements' : 'Maisons'}
              </button>
            ))}
          </div>

          {availableNeighbourhoods.length > 0 && (
            <div className="insight-sector-group">
              <span className="insight-sector-label">Secteur</span>
              <div className="insight-sector-scroll">
                <button className={cn('insight-sector-btn', sector === 'all' && 'active')} onClick={() => setSector('all')}>Tous</button>
                {availableNeighbourhoods.map((n) => (
                  <button key={n} className={cn('insight-sector-btn', sector === n && 'active')} onClick={() => setSector(n === sector ? 'all' : n)}>{n}</button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* KPIs */}
        <div className="insight-kpis">
          <Kpi label="Annonces actives" value={String(data.n)} sub={`${data.fresh} nouvelles cette semaine`} />
          <Kpi label="Prix médian" value={data.medPrice ? `${Math.round(data.medPrice / 1000)}k€` : '—'} />
          {data.medPm2a > 0 && <Kpi label="PM² médian apparts" value={`${num(data.medPm2a)}€/m²`} />}
          {data.medPm2m > 0 && insightType !== 'apparts' && <Kpi label="PM² médian maisons" value={`${num(data.medPm2m)}€/m²`} />}
          {data.medRatio > 0 && (
            <Kpi label="Ratio AVM médian" value={`×${data.medRatio.toFixed(2)}`} sub="prix / valeur estimée"
              good={data.medRatio < 0.95 ? true : data.medRatio >= 1.05 ? false : null} />
          )}
          <Kpi label="Baisses de prix" value={String(data.baisses)} sub="depuis mise en ligne" />
        </div>

        {/* PM² par quartier + Top deals */}
        <div className="insight-two-col">
          <div className="insight-card">
            <div className="insight-card-header">
              <span className="insight-card-title">PM² médian par quartier</span>
              <span className="insight-card-sub">clic pour filtrer</span>
            </div>
            {data.pm2Zone.length === 0 ? (
              <div className="insight-empty">Données insuffisantes</div>
            ) : (
              <div className="insight-pm2-list">
                {data.pm2Zone.map((z) => (
                  <div key={z.label}
                    className={cn('insight-pm2-row', sector === z.label && 'active')}
                    onClick={() => setSector(z.label === sector ? 'all' : z.label)}
                    role="button" tabIndex={0}
                    onKeyDown={(e) => e.key === 'Enter' && setSector(z.label === sector ? 'all' : z.label)}>
                    <span className="insight-pm2-label">{z.label}</span>
                    <div className="insight-pm2-bar"><Bar pct={(z.val! / data.pm2Max) * 100} /></div>
                    <span className="insight-pm2-val">{num(z.val!)}€</span>
                    <span className="insight-pm2-n">{z.n}</span>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div className="insight-card">
            <div className="insight-card-header">
              <span className="insight-card-title">Meilleures opportunités AVM</span>
              <span className="insight-card-sub">prix vs valeur estimée</span>
            </div>
            <div className="insight-deals-list">
              {data.topDeals.length === 0 ? (
                <div className="insight-empty">Données AVM insuffisantes pour ce secteur</div>
              ) : data.topDeals.map((item, i) => {
                const isApt   = 'title' in item
                const ratio   = isApt ? (item as Listing).avm_ratio! : (item as Maison).avm_ratio!
                const price   = isApt ? (item as Listing).price       : (item as Maison).prix
                const surface = isApt ? (item as Listing).surface     : (item as Maison).surface
                const pred    = isApt ? (item as Listing).avm_pred    : (item as Maison).avm_pred
                const loc     = isApt ? ((item as Listing).neighbourhood || (item as Listing).location) : (item as Maison).neighbourhood
                const pct     = ((1 - ratio) * 100)
                const color   = ratio <= 0.90 ? 'var(--green)' : ratio <= 1.05 ? 'var(--accent)' : 'var(--red)'
                return (
                  <div key={i} className="insight-deal-row">
                    <div className="insight-deal-left">
                      <span className="insight-deal-loc">{loc}</span>
                      <span className="insight-deal-price">{eur(price)}</span>
                      <span className="insight-deal-meta">{surface}m² · estimé {eur(pred)}</span>
                    </div>
                    <span className="insight-deal-ratio" style={{ color }}>
                      {pct >= 0 ? '+' : ''}{pct.toFixed(0)}%
                    </span>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        {/* PM² En vente vs DVF */}
        <Pm2VsDvf insightType={insightType} sector={sector} />

        {/* Distribution + Ancienneté */}
        <div className="insight-two-col">
          <Pm2Distribution insightType={insightType} />
          <AnciennetePanel insightType={insightType} sector={sector} />
        </div>

        {/* DVF Trends */}
        <DvfTrends />

        {/* Map */}
        <div className="insight-card">
          <div className="insight-card-header">
            <span className="insight-card-title">Carte</span>
          </div>

          {/* Map controls */}
          <div className="insight-map-controls">
            {/* Layer toggles */}
            <div className="insight-map-ctrl-group">
              <span className="insight-sector-label">Afficher</span>
              <div className="insight-filter-group">
                {(['sale', 'dvf'] as MapLayer[]).map((l) => (
                  <button key={l}
                    className={cn('insight-filter-btn', mapLayers.has(l) && 'active')}
                    onClick={() => toggleLayer(l)}>
                    {l === 'sale' ? 'En vente' : 'DVF'}
                  </button>
                ))}
              </div>
            </div>
            {/* Type filter */}
            <div className="insight-map-ctrl-group">
              <span className="insight-sector-label">Type</span>
              <div className="insight-filter-group">
                {(['all', 'apparts', 'maisons'] as MapBien[]).map((b) => (
                  <button key={b}
                    className={cn('insight-filter-btn', mapBien === b && 'active')}
                    onClick={() => setMapBien(b)}>
                    {b === 'all' ? 'Tout' : b === 'apparts' ? 'Apparts' : 'Maisons'}
                  </button>
                ))}
              </div>
            </div>
            {/* Metric — only relevant for "En vente" */}
            {mapLayers.has('sale') && (
              <div className="insight-map-ctrl-group">
                <span className="insight-sector-label">Métrique</span>
                <div className="insight-filter-group">
                  {(['pm2', 'ratio', 'score'] as MapMetric[]).map((m) => (
                    <button key={m}
                      className={cn('insight-filter-btn', mapMetric === m && 'active')}
                      onClick={() => setMapMetric(m)}>
                      {m === 'pm2' ? 'PM²' : m === 'ratio' ? 'Ratio AVM' : 'Score'}
                    </button>
                  ))}
                </div>
              </div>
            )}
          </div>

          <MapView
            insightType={insightType}
            metric={mapMetric}
            sector={sector}
            dark={dark}
            layers={mapLayers}
            bienFilter={mapBien}
          />

          {/* Legend */}
          <div className="insight-map-legend">
            {mapLayers.has('sale') && (
              <>
                <div className="insight-legend-item">
                  <span style={{ fontSize: '0.85rem', lineHeight: 1 }}>🏠</span>
                  <span>Maison</span>
                </div>
                <div className="insight-legend-item">
                  <span style={{ fontSize: '0.85rem', lineHeight: 1 }}>🏢</span>
                  <span>Appartement</span>
                </div>
                {[
                  { color: 'var(--green)', label: mapMetric === 'pm2' ? 'PM² bas' : mapMetric === 'ratio' ? 'Sous-évalué' : 'Score 70+' },
                  { color: 'var(--accent)', label: mapMetric === 'pm2' ? 'PM² moyen' : mapMetric === 'ratio' ? 'Dans le marché' : 'Score 45–70' },
                  { color: 'var(--red)',   label: mapMetric === 'pm2' ? 'PM² élevé' : mapMetric === 'ratio' ? 'Surévalué' : 'Score < 45' },
                ].map(({ color, label }) => (
                  <div key={label} className="insight-legend-item">
                    <span className="insight-legend-dot" style={{ background: color }} />
                    <span>{label}</span>
                  </div>
                ))}
              </>
            )}
            {mapLayers.has('dvf') && (
              <>
                <div className="insight-legend-item">
                  <span className="insight-legend-dot" style={{ background: '#4a9a6a' }} />
                  <span>DVF &lt;10k€/m²</span>
                </div>
                <div className="insight-legend-item">
                  <span className="insight-legend-dot" style={{ background: '#c49a3a' }} />
                  <span>DVF 10–15k€/m²</span>
                </div>
                <div className="insight-legend-item">
                  <span className="insight-legend-dot" style={{ background: '#c94040' }} />
                  <span>DVF &gt;15k€/m²</span>
                </div>
              </>
            )}
          </div>
        </div>

      </div>
    </div>
  )
}
