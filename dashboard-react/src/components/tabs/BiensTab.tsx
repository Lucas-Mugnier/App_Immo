import { useState, useMemo } from 'react'
import {
  ExternalLink, TrendingDown, Layers, Tag, Gauge,
  Building2, Home, X, Bookmark, ArrowLeftRight, ArrowRight, Check,
} from 'lucide-react'
import { useStore } from '@/store/useStore'
import { ScoreBadge } from '@/components/shared/ScoreBadge'
import { AVMBadge } from '@/components/shared/AVMBadge'
import { AppartActions } from '@/components/shared/ActionButtons'
import { FilterPill, PopLabel, PopSlider, PopCheckRow, PopToggle } from '@/components/shared/FilterPill'
import { eur, pm2, num, daysAgo, cn, NEIGHBOURHOOD_ORDER } from '@/lib/utils'
import type { SortState, PriceHistory, WatchlistStatus, WatchlistEntry } from '@/types'
import { APPARTS, MAISONS } from '@/lib/data'

// Module-level lookup for compare bar previews
const BIEN_PREVIEW = new Map<string, { title: string; photo?: string; type: 'appart' | 'maison' }>()
APPARTS.forEach((r) => BIEN_PREVIEW.set(r.id, { title: r.title, photo: r.photos?.[0], type: 'appart' }))
MAISONS.forEach((m) => BIEN_PREVIEW.set(`m_${m.id}`, { title: m.titre ?? m.adresse_raw, photo: m.photos?.[0], type: 'maison' }))
import { YieldGauge } from '@/components/shared/YieldGauge'
import { DetailDrawer } from '@/components/shared/DetailDrawer'

export interface BienRow {
  _type: 'appart' | 'maison'
  _key: string
  title: string
  url: string | null
  price: number
  surface: number
  rooms: number
  neighbourhood: string
  score: number | null
  avm_pred: number | null
  avm_ratio: number | null
  is_structured: boolean
  first_seen: string
  photos: string[]
  surface_carrez?: number | null
  surf_terrain?: number | null
  needs_renovation?: boolean
  yield?: number | null
  price_drop?: number | null
  price_history: PriceHistory[]
  dpe?: string
  description?: string
  days_on_market?: number
  nb_baisses?: number
  charges?: number | null
  is_relisted?: boolean
  relisted_after_days?: number | null
  avm_suspect?: boolean
  avm_model?: 'chamonix_apt' | 'vallee_apt' | null
  _appart_id?: string
  _maison_id?: number
  _appart_surface?: number
  _appart_rooms?: number
  _appart_location?: string
}

const ALL_QUARTIERS = [
  ...new Set([
    ...APPARTS.map((r) => r.neighbourhood),
    ...MAISONS.map((m) => m.neighbourhood),
  ].filter(Boolean)),
].sort((a, b) => {
  const ia = NEIGHBOURHOOD_ORDER.indexOf(a)
  const ib = NEIGHBOURHOOD_ORDER.indexOf(b)
  return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
})

const SORT_OPTIONS: { key: string; dir: 'asc' | 'desc'; label: string }[] = [
  { key: 'score',     dir: 'desc', label: 'Score ↓' },
  { key: 'score',     dir: 'asc',  label: 'Score ↑' },
  { key: 'price',     dir: 'asc',  label: 'Prix ↑' },
  { key: 'price',     dir: 'desc', label: 'Prix ↓' },
  { key: 'surface',   dir: 'desc', label: 'Surface ↓' },
  { key: 'surface',   dir: 'asc',  label: 'Surface ↑' },
  { key: 'avm_ratio', dir: 'desc', label: 'AVM ↓' },
  { key: 'avm_ratio', dir: 'asc',  label: 'AVM ↑' },
  { key: 'yield',     dir: 'desc', label: 'Rendement ↓' },
  { key: 'yield',     dir: 'asc',  label: 'Rendement ↑' },
]

function BienTypeToggle() {
  const { bienTypes, toggleBienType } = useStore()
  return (
    <div className="bien-type-toggle">
      <button
        className={bienTypes.includes('apparts') ? 'active' : ''}
        onClick={() => toggleBienType('apparts')}
      >
        <Building2 size={12} /> Apparts
      </button>
      <button
        className={bienTypes.includes('maisons') ? 'active' : ''}
        onClick={() => toggleBienType('maisons')}
      >
        <Home size={12} /> Maisons
      </button>
    </div>
  )
}

const STATUS_META: Record<WatchlistStatus, { label: string; color: string }> = {
  a_visiter: { label: 'À visiter',   color: 'var(--accent)' },
  visite:    { label: 'Visité',      color: 'var(--amber)'  },
  offre:     { label: 'Offre faite', color: 'var(--green)'  },
  refuse:    { label: 'Refusé',      color: 'var(--red)'    },
}

function BookmarkBtn({ row }: { row: BienRow }) {
  const { watchlist, setWatchlist } = useStore()
  const [open, setOpen] = useState(false)
  const entry = watchlist[row._key]

  function save(status: WatchlistStatus) {
    const e: WatchlistEntry = {
      status, addedAt: new Date().toISOString(),
      title: row.title, price: row.price, surface: row.surface,
      neighbourhood: row.neighbourhood, type: row._type,
      score: row.score, url: row.url,
    }
    setWatchlist(row._key, e)
    setOpen(false)
  }

  return (
    <div className="bookmark-wrap" onClick={(e) => e.stopPropagation()}>
      <button
        className={`bookmark-btn${entry ? ' saved' : ''}`}
        style={entry ? { color: STATUS_META[entry.status].color, borderColor: STATUS_META[entry.status].color + '66' } : undefined}
        title={entry ? STATUS_META[entry.status].label : 'Ajouter à la watchlist'}
        onClick={() => { if (!entry) { save('a_visiter') } else { setOpen((o) => !o) } }}
      >
        <Bookmark size={12} fill={entry ? 'currentColor' : 'none'} />
      </button>
      {open && (
        <div className="bookmark-menu">
          {(Object.entries(STATUS_META) as [WatchlistStatus, { label: string; color: string }][]).map(([s, m]) => (
            <button key={s}
              className={`bookmark-menu-item${entry?.status === s ? ' active' : ''}`}
              style={{ color: m.color }}
              onClick={() => save(s)}
            >
              {m.label}
            </button>
          ))}
          <div className="bookmark-menu-sep" />
          <button className="bookmark-menu-item bookmark-menu-remove"
            onClick={() => { setWatchlist(row._key, null); setOpen(false) }}>
            Retirer de la watchlist
          </button>
        </div>
      )}
    </div>
  )
}

function BienCard({ row, onOpen }: { row: BienRow; onOpen: (r: BienRow) => void }) {
  const { seen, rejected, compareIds, toggleCompare } = useStore()
  const isSeen      = !!seen[row._key]
  const isRejected  = !!rejected[row._key]
  const isCompared  = compareIds.includes(row._key)
  const isFull      = compareIds.length >= 4 && !isCompared
  const pm2v = pm2(row.price, row.surface)

  return (
    <div
      className={cn('deal-card', isSeen && 'seen', isRejected && 'rejected', isCompared && 'comparing')}
      onClick={() => onOpen(row)}
      style={{ cursor: 'pointer' }}
    >
      {isCompared && (
        <div className="compare-card-badge">
          <Check size={9} strokeWidth={3} />
          {compareIds.indexOf(row._key) + 1}
        </div>
      )}
      {/* Photo */}
      {row.photos.length > 0 ? (
        row.url ? (
          <a href={row.url} target="_blank" rel="noopener noreferrer" onClick={(e) => e.stopPropagation()}>
            <img src={row.photos[0]} alt="" className="deal-card-img" />
          </a>
        ) : (
          <img src={row.photos[0]} alt="" className="deal-card-img" />
        )
      ) : (
        <div className="deal-card-img-placeholder">
          {row._type === 'appart' ? <Building2 size={28} /> : <Home size={28} />}
        </div>
      )}

      <div className="deal-card-body">
        <div className="deal-card-top">
          <div style={{ flex: 1 }}>
            {row.url ? (
              <a
                href={row.url}
                target="_blank"
                rel="noopener noreferrer"
                className="deal-card-title block"
                onClick={(e) => e.stopPropagation()}
              >
                {row.title}
              </a>
            ) : (
              <span className="deal-card-title">{row.title}</span>
            )}
            <div className="text-sub text-xs mt-1 font-mono">{row.neighbourhood}</div>
          </div>
          <div className="flex flex-col items-end gap-1">
            <ScoreBadge score={row.score} />
            <span
              className="chip"
              style={{ background: 'var(--accent-soft)', borderColor: 'oklch(0.72 0.095 72 / 0.4)', color: 'var(--accent)' }}
            >
              {row._type === 'appart' ? <Building2 size={9} /> : <Home size={9} />}
              {row._type === 'appart' ? 'Appartement' : 'Maison'}
            </span>
          </div>
        </div>

        <div className="deal-card-price">{eur(row.price)}</div>

        <div className="deal-card-chips">
          {(row.surface_carrez ?? row.surface) > 0 && (
            <span
              className="chip"
              style={{ background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text-dim)' }}
              title={row.surface_carrez ? `Loi Carrez — surface effective scoring : ${Math.round(row.surface)}m²` : undefined}
            >
              {row.surface_carrez ?? row.surface}m²
              {row.surface_carrez && <span style={{ fontSize: '0.6rem', opacity: 0.6, marginLeft: 2 }}>C</span>}
            </span>
          )}
          {row.rooms > 0 && (
            <span className="chip" style={{ background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text-dim)' }}>
              {row.rooms === 1 ? 'Studio' : `${row.rooms}p`}
            </span>
          )}
          {pm2v && (
            <span className="chip" style={{ background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text-dim)' }}>
              {num(pm2v)}€/m²
            </span>
          )}
          {(row.surf_terrain ?? 0) > 0 && (
            <span className="chip" style={{ background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text-dim)' }}>
              {num(row.surf_terrain!)}m² terrain
            </span>
          )}
          {row.needs_renovation && (
            <span className="chip" style={{ background: 'oklch(0.64 0.17 40 / 0.12)', borderColor: 'oklch(0.64 0.17 40 / 0.35)', color: 'var(--orange)' }}>
              à rénover
            </span>
          )}
          {(row.price_drop ?? 0) > 0 && row.price > 0 && (() => {
            const pct = Math.round(row.price_drop! / (row.price + row.price_drop!) * 100)
            return (
              <span className="chip" style={{ background: 'oklch(0.64 0.17 40 / 0.1)', borderColor: 'oklch(0.64 0.17 40 / 0.3)', color: 'var(--orange)' }}>
                <TrendingDown size={8} />
                -{pct}%
              </span>
            )
          })()}
        </div>
      </div>

      <div className="deal-card-footer">
        <AVMBadge pred={row.avm_pred} ratio={row.avm_ratio} />
        {row.yield != null && (
          <YieldGauge value={row.yield} isEstimate={row._type === 'maison'} />
        )}
        <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
          <BookmarkBtn row={row} />
          <button
            className={cn('action-btn has-tooltip', isCompared && 'compare-active')}
            data-tip={isCompared ? 'Retirer de la comparaison' : isFull ? '4 biens max' : 'Ajouter à la comparaison'}
            disabled={isFull}
            onClick={(e) => { e.stopPropagation(); toggleCompare(row._key) }}
          >
            <ArrowLeftRight size={12} />
          </button>
          <AppartActions
            id={row._key}
            surface={row._appart_surface ?? row.surface}
            rooms={row._appart_rooms ?? row.rooms}
            location={row._appart_location}
            price={row.price}
          />
          {row.url && (
            <a
              href={row.url}
              target="_blank"
              rel="noopener noreferrer"
              className="action-btn"
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink size={11} />
            </a>
          )}
        </div>
      </div>
    </div>
  )
}

function CompareBar() {
  const { compareIds, clearCompare, toggleCompare, setActiveTab } = useStore()
  if (compareIds.length === 0) return null

  return (
    <div className="compare-bar">
      <div className="compare-bar-thumbs">
        {compareIds.map((key) => {
          const p = BIEN_PREVIEW.get(key)
          return (
            <div key={key} className="compare-bar-thumb" title={p?.title ?? key}>
              {p?.photo
                ? <img src={p.photo} alt="" />
                : <div className="compare-bar-thumb-ph">{p?.type === 'maison' ? <Home size={14} /> : <Building2 size={14} />}</div>
              }
              <button className="compare-bar-thumb-rm" onClick={() => toggleCompare(key)}>
                <X size={9} />
              </button>
            </div>
          )
        })}
        {Array.from({ length: 4 - compareIds.length }).map((_, i) => (
          <div key={i} className="compare-bar-slot" />
        ))}
      </div>
      <span className="compare-bar-count">{compareIds.length} / 4</span>
      <button className="compare-bar-go" onClick={() => setActiveTab('comparateur')}>
        Comparer <ArrowRight size={13} />
      </button>
      <button className="compare-bar-clear" onClick={clearCompare} title="Effacer la sélection">
        <X size={13} />
      </button>
    </div>
  )
}

export function BiensTab() {
  const { bienTypes, rejected, hidden, appartFilters } = useStore()
  const profileMinYield = appartFilters.minYield

  const [sort, setSort]                 = useState<SortState>({ key: 'score', dir: 'desc' })
  const [openPill, setOpenPill]         = useState<string | null>(null)
  const pillProps = (name: string) => ({
    open: openPill === name,
    onToggle: () => setOpenPill(openPill === name ? null : name),
    onClose: () => setOpenPill(null),
  })

  const [search, setSearch]             = useState('')
  const [quartiers, setQuartiers]       = useState<string[]>([])
  const [minScore, setMinScore]         = useState(0)
  const [minPrice, setMinPrice]         = useState(0)
  const [maxPrice, setMaxPrice]         = useState(5_000_000)
  const [minSurface, setMinSurface]     = useState(0)
  const [minRooms, setMinRooms]         = useState(0)
  const [hideStructured, setHideStructured] = useState(true)
  const [showRejected, setShowRejected] = useState(false)
  const [drawerRow, setDrawerRow] = useState<BienRow | null>(null)

  const hasFilters = !!(search || quartiers.length > 0 || minScore > 0 || minPrice > 0
    || maxPrice < 5_000_000 || minSurface > 0 || minRooms > 0)

  const allRows = useMemo<BienRow[]>(() => {
    const rows: BienRow[] = []

    if (bienTypes.includes('apparts')) {
      for (const r of APPARTS) {
        rows.push({
          _type: 'appart',
          _key: r.id,
          title: r.title,
          url: r.url,
          price: r.price,
          surface: r.surface,
          rooms: r.rooms,
          neighbourhood: r.neighbourhood,
          score: r.score,
          avm_pred: r.avm_pred,
          avm_ratio: r.avm_ratio,
          is_structured: !!r.is_structured,
          first_seen: r.first_seen,
          photos: r.photos ?? [],
          surface_carrez: r.surface_carrez,
          yield: r.yield,
          price_drop: r.price_drop,
          price_history: r.price_history ?? [],
          dpe: r.dpe,
          days_on_market: r.days_on_market,
          nb_baisses: r.nb_baisses,
          charges: r.charges,
          is_relisted: r.is_relisted,
          relisted_after_days: r.relisted_after_days,
          avm_suspect: !!r.avm_suspect,
          avm_model: r.avm_model,
          description: r.description,
          _appart_id: r.id,
          _appart_surface: r.surface,
          _appart_rooms: r.rooms,
          _appart_location: r.location,
        })
      }
    }

    if (bienTypes.includes('maisons')) {
      for (const m of MAISONS) {
        rows.push({
          _type: 'maison',
          _key: `m_${m.id}`,
          title: m.titre ?? m.adresse_raw,
          url: m.url,
          price: m.prix,
          surface: m.surface,
          rooms: m.pieces,
          neighbourhood: m.neighbourhood,
          score: m.avm_score,
          avm_pred: m.avm_pred,
          avm_ratio: m.avm_ratio,
          is_structured: !!m.is_structured,
          first_seen: m.first_seen,
          photos: m.photos ?? [],
          surf_terrain: m.surf_terrain,
          needs_renovation: m.needs_renovation,
          yield: m.yield,
          price_history: m.historique_prix ?? [],
          description: m.description,
          nb_baisses: m.nb_baisses,
          avm_suspect: !!m.avm_suspect,
          avm_model: m.avm_model,
          _maison_id: m.id,
          _appart_location: m.neighbourhood,
        })
      }
    }

    return rows
  }, [bienTypes])

  const filtered = useMemo(() => {
    return allRows.filter((r) => {
      if (!showRejected && rejected[r._key]) return false
      if (hidden[r._key]) return false
      if (hideStructured && r.is_structured) return false
      if (r.score != null && r.score < minScore) return false
      if (minPrice > 0 && r.price < minPrice) return false
      if (r.price > maxPrice) return false
      if (minSurface > 0 && r.surface < minSurface) return false
      if (minRooms > 0 && r.rooms < minRooms) return false
      if (profileMinYield > 0 && (r.yield == null || r.yield < profileMinYield)) return false
      if (quartiers.length > 0 && !quartiers.includes(r.neighbourhood)) return false
      if (search) {
        const q = search.toLowerCase()
        if (!(r.title + ' ' + r.neighbourhood).toLowerCase().includes(q)) return false
      }
      return true
    })
  }, [allRows, search, quartiers, minScore, minPrice, maxPrice, minSurface, minRooms, profileMinYield, hideStructured, showRejected, rejected, hidden])

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const av = (a as unknown as Record<string, number | null>)[sort.key]
      const bv = (b as unknown as Record<string, number | null>)[sort.key]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      return sort.dir === 'desc' ? bv - av : av - bv
    })
  }, [filtered, sort])

  const stats = useMemo(() => {
    const active = sorted.filter((r) => !rejected[r._key])
    const pm2s = active.map((r) => pm2(r.price, r.surface)).filter(Boolean) as number[]
    const medPm2 = pm2s.length ? pm2s.sort((a, b) => a - b)[Math.floor(pm2s.length / 2)] : null
    const scores = active.map((r) => r.score).filter((s) => s != null) as number[]
    const avgScore = scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null
    const bonnes = active.filter((r) => (r.avm_ratio ?? 2) <= 0.90).length
    const fresh = active.filter((r) => daysAgo(r.first_seen) <= 7).length
    return { n: active.length, total: allRows.length, medPm2, avgScore, bonnes, fresh }
  }, [sorted, rejected, allRows.length])

  const resetFilters = () => {
    setSearch(''); setQuartiers([]); setMinScore(0)
    setMinPrice(0); setMaxPrice(5_000_000); setMinSurface(0); setMinRooms(0)
  }

  return (
    <div className="flex flex-col h-full">

      {/* KPI row */}
      <div className="kpi-row">
        <div className="kpi-cell">
          <div className="kpi-label"><Layers size={11} /> En vue</div>
          <div className="kpi-value">
            {stats.n}<span className="unit"> / {stats.total}</span>
          </div>
          <div className="kpi-foot">biens actifs</div>
        </div>
        <div className="kpi-cell">
          <div className="kpi-label"><Tag size={11} /> Méd. €/m²</div>
          <div className="kpi-value">
            {stats.medPm2 ? num(stats.medPm2) : '—'}<span className="unit">€</span>
          </div>
          <div className="kpi-foot">sur la sélection</div>
        </div>
        <div className="kpi-cell">
          <div className="kpi-label"><Gauge size={11} /> Score moyen</div>
          <div className="kpi-value" style={{
            color: stats.avgScore == null ? 'var(--text-faint)' : (() => {
              const s = stats.avgScore
              // Interpolation oklch : rouge (27) → amber (70) → vert (152) selon le score
              const hue = 27 + (s / 100) * (152 - 27)
              const chroma = s >= 50 ? 0.155 : 0.17
              const lightness = s >= 70 ? 0.52 : s >= 50 ? 0.58 : 0.64
              return `oklch(${lightness} ${chroma} ${Math.round(hue)})`
            })(),
          }}>
            {stats.avgScore ?? '—'}
            {stats.avgScore != null && <span className="unit">/100</span>}
          </div>
          <div className="kpi-foot">
            {stats.fresh > 0 ? `${stats.fresh} nouvelles 7j` : 'apparts + maisons'}
          </div>
        </div>
        <div className="kpi-cell">
          <div className="kpi-label"><TrendingDown size={11} /> Bonnes affaires</div>
          <div className="kpi-value" style={{ color: stats.bonnes > 0 ? 'var(--green)' : 'var(--text-faint)' }}>
            {stats.bonnes}
          </div>
          <div className="kpi-foot">AVM ratio ≥ 1.10</div>
        </div>
      </div>

      {/* Filter bar */}
      <div className="filter-bar">
        <BienTypeToggle />

        <input
          className="filter-input w-40"
          placeholder="Rechercher…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {search && (
          <button className="btn-ghost px-1" onClick={() => setSearch('')}>
            <X size={12} />
          </button>
        )}

        <FilterPill
          label="Quartier"
          active={quartiers.length > 0}
          count={quartiers.length > 0 ? quartiers.length : undefined}
          {...pillProps('quartier')}
        >
          <PopLabel>Quartier</PopLabel>
          {ALL_QUARTIERS.map((q) => (
            <PopCheckRow
              key={q}
              label={q}
              checked={quartiers.includes(q)}
              onChange={() =>
                setQuartiers(quartiers.includes(q)
                  ? quartiers.filter((x) => x !== q)
                  : [...quartiers, q])
              }
            />
          ))}
          {quartiers.length > 0 && (
            <button className="btn-ghost w-full mt-1 text-xs" onClick={() => setQuartiers([])}>
              Tout décocher
            </button>
          )}
        </FilterPill>

        <FilterPill label="Prix" active={minPrice > 0 || maxPrice < 5_000_000} {...pillProps('prix')}>
          <PopSlider
            label="Prix minimum"
            value={minPrice}
            min={0} max={2_000_000} step={50_000}
            format={(v) => v === 0 ? 'Tous' : `${Math.round(v / 1000)}k€`}
            onChange={setMinPrice}
          />
          <PopSlider
            label="Prix maximum"
            value={maxPrice}
            min={200_000} max={5_000_000} step={100_000}
            format={(v) => v >= 5_000_000 ? 'Tous' : `${Math.round(v / 1000)}k€`}
            onChange={setMaxPrice}
          />
        </FilterPill>

        <FilterPill label="Score" active={minScore > 0} {...pillProps('score')}>
          <PopSlider
            label="Score minimum"
            value={minScore}
            min={0} max={90} step={5}
            onChange={setMinScore}
          />
        </FilterPill>

        <FilterPill label="Surface" active={minSurface > 0} {...pillProps('surface')}>
          <PopSlider
            label="Surface minimum"
            value={minSurface}
            min={0} max={200} step={10}
            format={(v) => v === 0 ? 'Tous' : `${v}m²`}
            onChange={setMinSurface}
          />
        </FilterPill>

        <FilterPill label="Pièces" active={minRooms > 0} {...pillProps('pieces')}>
          <PopLabel>Pièces minimum</PopLabel>
          {[0, 1, 2, 3, 4, 5].map((n) => (
            <PopCheckRow
              key={n}
              label={n === 0 ? 'Toutes' : `${n}+ pièce${n > 1 ? 's' : ''}`}
              checked={minRooms === n}
              onChange={() => setMinRooms(n)}
            />
          ))}
        </FilterPill>

        <FilterPill
          label="Options"
          active={showRejected || !hideStructured}
          align="right"
          {...pillProps('options')}
        >
          <PopLabel>Visibilité</PopLabel>
          <PopToggle
            label="Masquer produits structurés"
            checked={hideStructured}
            onChange={setHideStructured}
          />
          <PopToggle
            label="Afficher rejetés"
            checked={showRejected}
            onChange={setShowRejected}
          />
        </FilterPill>

        <div className="flex-1" />

        <span className="cap" style={{ color: 'var(--text-dim)' }}>
          <b style={{ color: 'var(--text)', fontFamily: 'var(--font-mono)' }}>{sorted.length}</b> résultat{sorted.length !== 1 ? 's' : ''}
        </span>

        <FilterPill
          label={SORT_OPTIONS.find((s) => s.key === sort.key && s.dir === sort.dir)?.label ?? 'Trier'}
          active={!(sort.key === 'score' && sort.dir === 'desc')}
          align="right"
          {...pillProps('sort')}
        >
          <PopLabel>Trier par</PopLabel>
          {SORT_OPTIONS.map((s) => (
            <PopCheckRow
              key={`${s.key}-${s.dir}`}
              label={s.label}
              checked={sort.key === s.key && sort.dir === s.dir}
              onChange={() => { setSort({ key: s.key, dir: s.dir }); setOpenPill(null) }}
            />
          ))}
        </FilterPill>
      </div>

      {/* Cards */}
      <div className="flex-1 overflow-auto">
        {sorted.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 gap-3" style={{ color: 'var(--text-faint)' }}>
            <Layers size={28} strokeWidth={1} />
            <p className="cap">Aucun bien correspondant aux filtres</p>
            {hasFilters && (
              <button className="btn-ghost" onClick={resetFilters}>Effacer les filtres</button>
            )}
          </div>
        ) : (
          <div className="card-grid">
            {sorted.map((row) => (
              <BienCard key={row._key} row={row} onOpen={setDrawerRow} />
            ))}
          </div>
        )}
      </div>

      <CompareBar />
      <DetailDrawer row={drawerRow} onClose={() => setDrawerRow(null)} />
    </div>
  )
}
