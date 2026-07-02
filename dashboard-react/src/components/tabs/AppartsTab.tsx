import { Fragment, useState, useMemo } from 'react'
import {
  ChevronUp, ChevronDown, ChevronsUpDown, ExternalLink,
  TrendingDown, RefreshCw, AlertTriangle, LayoutList, LayoutGrid,
  Layers, Tag, Gauge, Home, X, Building2,
} from 'lucide-react'
import { useStore } from '@/store/useStore'
import { ScoreBadge } from '@/components/shared/ScoreBadge'
import { AVMBadge } from '@/components/shared/AVMBadge'
import { AppartActions } from '@/components/shared/ActionButtons'
import { FilterPill, PopLabel, PopSlider, PopCheckRow, PopToggle } from '@/components/shared/FilterPill'
import { eur, pm2, num, pct, daysAgo, cn, NEIGHBOURHOOD_ORDER } from '@/lib/utils'
import type { Listing, SortState } from '@/types'
import { APPARTS } from '@/lib/data'

const listings = APPARTS

const LOCATIONS = [...new Set(listings.map((r) => r.neighbourhood))].sort((a, b) => {
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
  { key: 'yield',     dir: 'desc', label: 'Rendement ↓' },
  { key: 'avm_ratio', dir: 'desc', label: 'AVM ↓' },
  { key: 'avm_ratio', dir: 'asc',  label: 'AVM ↑' },
]

function SortIcon({ col, sort }: { col: string; sort: SortState }) {
  if (sort.key !== col) return <ChevronsUpDown size={10} className="opacity-25 ml-0.5" />
  return sort.dir === 'asc'
    ? <ChevronUp size={10} className="ml-0.5" style={{ color: 'var(--accent)' }} />
    : <ChevronDown size={10} className="ml-0.5" style={{ color: 'var(--accent)' }} />
}

function Th({
  col, label, sort, setSort, className,
}: {
  col: string; label: string; sort: SortState; setSort: (s: SortState) => void; className?: string
}) {
  const active = sort.key === col
  return (
    <th
      className={cn(active && 'sorted', className)}
      onClick={() => setSort({ key: col, dir: active && sort.dir === 'desc' ? 'asc' : 'desc' })}
    >
      <span className="flex items-center gap-0.5">
        {label}
        <SortIcon col={col} sort={sort} />
      </span>
    </th>
  )
}

function DPEBadge({ dpe }: { dpe: string }) {
  if (!dpe || dpe === 'N/C') return <span className="text-faint text-xs">—</span>
  const color =
    dpe === 'A' || dpe === 'B' ? 'var(--green)' :
    dpe === 'C' || dpe === 'D' ? 'var(--blue)' :
    dpe === 'E' ? 'var(--amber)' :
    'var(--red)'
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: 24, height: 24,
        borderRadius: 6,
        border: `1.5px solid ${color}`,
        color,
        fontSize: '0.65rem',
        fontWeight: 700,
        fontFamily: 'var(--font-mono)',
      }}
      title={`DPE ${dpe}${dpe >= 'F' ? ' — passoire thermique' : ''}`}
    >
      {dpe}
    </span>
  )
}

function AppartCard({ row, onOpen }: { row: Listing; onOpen: (id: string) => void }) {
  const { seen, rejected } = useStore()
  const isSeen = !!seen[row.id]
  const isRejected = !!rejected[row.id]
  const pm2v = pm2(row.price, row.surface)
  const age = daysAgo(row.first_seen)

  return (
    <div
      className={`deal-card ${isSeen ? 'seen' : ''} ${isRejected ? 'rejected' : ''}`}
      onClick={() => onOpen(row.id)}
    >
      {/* Photo or placeholder */}
      {row.photos && row.photos.length > 0 ? (
        <img src={row.photos[0]} alt="" className="deal-card-img" />
      ) : (
        <div className="deal-card-img-placeholder">
          <Home size={28} />
        </div>
      )}

      <div className="deal-card-body">
        <div className="deal-card-top">
          <div style={{ flex: 1 }}>
            <a
              href={row.url}
              target="_blank"
              rel="noopener noreferrer"
              className="deal-card-title block"
              onClick={(e) => e.stopPropagation()}
            >
              {row.title}
            </a>
            <div className="text-sub text-xs mt-1 font-mono">{row.location}</div>
          </div>
          <ScoreBadge score={row.score} />
        </div>

        <div className="deal-card-price">{eur(row.price)}</div>

        <div className="deal-card-chips">
          {row.surface > 0 && (
            <span className="chip" style={{ background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text-dim)' }}>
              {row.surface}m²
            </span>
          )}
          {row.rooms > 0 && (
            <span className="chip" style={{ background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text-dim)' }}>
              {row.rooms === 1 ? 'Studio' : `${row.rooms}p`}
            </span>
          )}
          {row.dpe && row.dpe !== 'N/C' && (
            <span className="chip" style={{ background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text-dim)' }}>
              DPE {row.dpe}
            </span>
          )}
          {pm2v && (
            <span className="chip" style={{ background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text-dim)' }}>
              {num(pm2v)}€/m²
            </span>
          )}
          {age <= 3 && (
            <span className="chip" style={{ background: 'oklch(0.54 0.175 234 / 0.1)', borderColor: 'oklch(0.54 0.175 234 / 0.3)', color: 'var(--blue)' }}>
              nouveau
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
        <AVMBadge pred={row.avm_pred} ratio={row.avm_ratio} model={row.avm_model} />
        {row.yield ? (
          <span className="num text-xs" style={{ color: row.yield >= 7 ? 'var(--green)' : row.yield >= 5 ? 'var(--blue)' : 'var(--text-faint)' }}>
            {row.yield.toFixed(1)}% rdt
          </span>
        ) : null}
        <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
          <AppartActions
            id={row.id}
            surface={row.surface}
            rooms={row.rooms}
            location={row.location}
            price={row.price}
          />
          <a
            href={row.url}
            target="_blank"
            rel="noopener noreferrer"
            className="action-btn"
            onClick={(e) => e.stopPropagation()}
          >
            <ExternalLink size={11} />
          </a>
        </div>
      </div>
    </div>
  )
}

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

export function AppartsTab() {
  const {
    appartFilters, setAppartFilters,
    appartSort, setAppartSort,
    seen, rejected, hidden,
  } = useStore()

  const [view, setView] = useState<'table' | 'cards'>('cards')
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [openPill, setOpenPill] = useState<string | null>(null)
  const pillProps = (name: string) => ({
    open: openPill === name,
    onToggle: () => setOpenPill(openPill === name ? null : name),
    onClose: () => setOpenPill(null),
  })

  const filtered = useMemo(() => {
    return listings.filter((r) => {
      const id = r.id
      if (!appartFilters.showHidden && hidden[id]) return false
      if (!appartFilters.showRejected && rejected[id]) return false
      if (appartFilters.hideStructured && r.is_structured) return false
      if (r.score !== null && r.score < appartFilters.minScore) return false
      if (appartFilters.minPrice > 0 && r.price < appartFilters.minPrice) return false
      if (r.price > appartFilters.maxPrice) return false
      if (r.surface && r.surface < appartFilters.minSurface) return false
      if (appartFilters.minRooms > 0 && r.rooms < appartFilters.minRooms) return false
      if (appartFilters.minYield > 0 && (r.yield == null || r.yield < appartFilters.minYield)) return false
      if (appartFilters.maxDpe && r.dpe && r.dpe !== 'N/C' && r.dpe > appartFilters.maxDpe) return false
      if (appartFilters.location.length > 0 && !appartFilters.location.includes(r.neighbourhood)) return false
      if (appartFilters.priceDropOnly && (r.nb_baisses ?? 0) === 0) return false
      if (appartFilters.freshOnly && daysAgo(r.first_seen) > 7) return false
      if (appartFilters.search) {
        const q = appartFilters.search.toLowerCase()
        const haystack = `${r.title} ${r.location} ${r.neighbourhood} ${r.price} ${r.surface}`.toLowerCase()
        if (!haystack.includes(q)) return false
      }
      return true
    })
  }, [listings, appartFilters, hidden, rejected])

  const sorted = useMemo(() => {
    const key = appartSort.key as keyof Listing
    return [...filtered].sort((a, b) => {
      let av = a[key] as number | null
      let bv = b[key] as number | null
      if (key === 'avm_ratio') { av = a.avm_ratio; bv = b.avm_ratio }
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      return appartSort.dir === 'desc' ? (bv as number) - (av as number) : (av as number) - (bv as number)
    })
  }, [filtered, appartSort])

  // KPI stats
  const stats = useMemo(() => {
    const active = sorted.filter((r) => !rejected[r.id])
    const pm2s = active.map((r) => pm2(r.price, r.surface)).filter(Boolean) as number[]
    const medPm2 = pm2s.length ? pm2s.sort((a, b) => a - b)[Math.floor(pm2s.length / 2)] : null
    const scores = active.map((r) => r.score).filter((s) => s != null) as number[]
    const avgScore = scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : null
    const bonnes = active.filter((r) => (r.avm_ratio ?? 0) >= 1.1).length
    const fresh = active.filter((r) => daysAgo(r.first_seen) <= 7).length
    return { n: active.length, medPm2, avgScore, bonnes, fresh }
  }, [sorted, rejected])

  const handleOpen = (id: string) => setExpandedId(expandedId === id ? null : id)

  return (
    <div className="flex flex-col h-full">

      {/* KPI row */}
      <div className="kpi-row">
        <div className="kpi-cell">
          <div className="kpi-label"><Layers size={11} /> En vue</div>
          <div className="kpi-value">
            {stats.n}
            <span className="unit"> / {listings.length}</span>
          </div>
          <div className="kpi-foot">annonces actives</div>
        </div>
        <div className="kpi-cell">
          <div className="kpi-label"><Tag size={11} /> Méd. €/m²</div>
          <div className="kpi-value">
            {stats.medPm2 ? num(stats.medPm2) : '—'}
            <span className="unit">€</span>
          </div>
          <div className="kpi-foot">sur la sélection</div>
        </div>
        <div className="kpi-cell">
          <div className="kpi-label"><Gauge size={11} /> Score moyen</div>
          <div className="kpi-value" style={{
            color: stats.avgScore == null ? 'var(--text-faint)' :
              stats.avgScore >= 70 ? 'var(--green)' :
              stats.avgScore >= 50 ? 'var(--blue)' :
              'var(--amber)'
          }}>
            {stats.avgScore ?? '—'}
            {stats.avgScore != null && <span className="unit">/100</span>}
          </div>
          <div className="kpi-foot">
            {stats.fresh > 0 ? `${stats.fresh} nouvelles 7j` : 'ratio prix / AVM'}
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
        {/* Category toggle */}
        <BienTypeToggle />

        <input
          className="filter-input w-40"
          placeholder="Rechercher…"
          value={appartFilters.search}
          onChange={(e) => setAppartFilters({ search: e.target.value })}
        />
        {appartFilters.search && (
          <button className="action-btn" onClick={() => setAppartFilters({ search: '' })}>
            <X size={12} />
          </button>
        )}

        {/* Quartier */}
        <FilterPill
          label="Quartier"
          active={appartFilters.location.length > 0}
          count={appartFilters.location.length || undefined}
          {...pillProps('commune')}
        >
          <PopLabel>Quartier</PopLabel>
          <PopCheckRow
            label="Tous"
            checked={appartFilters.location.length === 0}
            onChange={() => setAppartFilters({ location: [] })}
          />
          {LOCATIONS.map((loc) => (
            <PopCheckRow
              key={loc}
              label={loc}
              checked={appartFilters.location.includes(loc)}
              onChange={() => {
                const next = appartFilters.location.includes(loc)
                  ? appartFilters.location.filter((l) => l !== loc)
                  : [...appartFilters.location, loc]
                setAppartFilters({ location: next })
              }}
            />
          ))}
        </FilterPill>

        {/* Prix */}
        <FilterPill
          label="Prix"
          active={appartFilters.minPrice > 0 || appartFilters.maxPrice < 2_000_000}
          {...pillProps('prix')}
        >
          <PopSlider
            label="Prix minimum"
            value={appartFilters.minPrice}
            min={0} max={1_500_000} step={25_000}
            format={(v) => v === 0 ? 'Aucun' : `${(v / 1000).toFixed(0)}k€`}
            onChange={(v) => setAppartFilters({ minPrice: v })}
          />
          <PopSlider
            label="Prix maximum"
            value={appartFilters.maxPrice}
            min={100_000} max={2_000_000} step={25_000}
            format={(v) => v >= 2_000_000 ? 'Tous' : `${(v / 1000).toFixed(0)}k€`}
            onChange={(v) => setAppartFilters({ maxPrice: v })}
          />
        </FilterPill>

        {/* Score */}
        <FilterPill label="Score" active={appartFilters.minScore > 0} {...pillProps('score')}>
          <PopSlider
            label="Score minimum"
            value={appartFilters.minScore}
            min={0} max={90} step={5}
            onChange={(v) => setAppartFilters({ minScore: v })}
          />
        </FilterPill>

        {/* Surface */}
        <FilterPill label="Surface" active={appartFilters.minSurface > 0} {...pillProps('surface')}>
          <PopSlider
            label="Surface minimum"
            value={appartFilters.minSurface}
            min={0} max={150} step={10}
            format={(v) => v === 0 ? 'Tous' : `${v}m²`}
            onChange={(v) => setAppartFilters({ minSurface: v })}
          />
        </FilterPill>

        {/* Pièces */}
        <FilterPill label="Pièces" active={appartFilters.minRooms > 0} {...pillProps('pieces')}>
          <PopLabel>Pièces minimum</PopLabel>
          {[0, 1, 2, 3, 4, 5].map((n) => (
            <PopCheckRow
              key={n}
              label={n === 0 ? 'Toutes' : `${n}+ pièce${n > 1 ? 's' : ''}`}
              checked={appartFilters.minRooms === n}
              onChange={() => setAppartFilters({ minRooms: n })}
            />
          ))}
        </FilterPill>

        {/* Rendement */}
        <FilterPill label="Rendement" active={appartFilters.minYield > 0} {...pillProps('rendement')}>
          <PopSlider
            label="Rendement minimum"
            value={appartFilters.minYield}
            min={0} max={10} step={0.5}
            format={(v) => v === 0 ? 'Tous' : `${v.toFixed(1)}%`}
            onChange={(v) => setAppartFilters({ minYield: v })}
          />
        </FilterPill>

        {/* DPE */}
        <FilterPill label="DPE" active={!!appartFilters.maxDpe} {...pillProps('dpe')}>
          <PopLabel>DPE maximum autorisé</PopLabel>
          {(['', 'A', 'B', 'C', 'D', 'E', 'F'] as const).map((d) => (
            <PopCheckRow
              key={d || 'all'}
              label={d === '' ? 'Tous' : `≤ ${d}`}
              checked={appartFilters.maxDpe === d}
              onChange={() => setAppartFilters({ maxDpe: d })}
            />
          ))}
        </FilterPill>

        {/* État */}
        <FilterPill
          label="État"
          active={appartFilters.priceDropOnly || appartFilters.freshOnly}
          count={(appartFilters.priceDropOnly ? 1 : 0) + (appartFilters.freshOnly ? 1 : 0) || undefined}
          {...pillProps('etat')}
        >
          <PopLabel>Filtres état</PopLabel>
          <PopToggle
            label="Baisses de prix"
            checked={appartFilters.priceDropOnly}
            onChange={(v) => setAppartFilters({ priceDropOnly: v })}
          />
          <PopToggle
            label="Nouvelles (≤ 7 jours)"
            checked={appartFilters.freshOnly}
            onChange={(v) => setAppartFilters({ freshOnly: v })}
          />
        </FilterPill>

        {/* Options */}
        <FilterPill
          label="Options"
          active={appartFilters.showHidden || appartFilters.showRejected || !appartFilters.hideStructured}
          align="right"
          {...pillProps('options')}
        >
          <PopLabel>Visibilité</PopLabel>
          <PopToggle
            label="Masquer produits structurés"
            checked={appartFilters.hideStructured}
            onChange={(v) => setAppartFilters({ hideStructured: v })}
          />
          <PopToggle
            label="Afficher cachés"
            checked={appartFilters.showHidden}
            onChange={(v) => setAppartFilters({ showHidden: v })}
          />
          <PopToggle
            label="Afficher rejetés"
            checked={appartFilters.showRejected}
            onChange={(v) => setAppartFilters({ showRejected: v })}
          />
        </FilterPill>

        <div className="flex-1" />

        {/* Result count */}
        <span className="cap" style={{ color: 'var(--text-dim)' }}>
          <b style={{ color: 'var(--text)', fontFamily: 'var(--font-mono)' }}>{sorted.length}</b> résultat{sorted.length !== 1 ? 's' : ''}
        </span>

        {/* Sort pill */}
        <FilterPill
          label={SORT_OPTIONS.find(s => s.key === appartSort.key && s.dir === appartSort.dir)?.label ?? 'Trier'}
          active={!(appartSort.key === 'score' && appartSort.dir === 'desc')}
          align="right"
          {...pillProps('sort')}
        >
          <PopLabel>Trier par</PopLabel>
          {SORT_OPTIONS.map((s) => (
            <PopCheckRow
              key={`${s.key}-${s.dir}`}
              label={s.label}
              checked={appartSort.key === s.key && appartSort.dir === s.dir}
              onChange={() => { setAppartSort({ key: s.key, dir: s.dir }); setOpenPill(null) }}
            />
          ))}
        </FilterPill>

        {/* Table / Cards toggle */}
        <div className="segment">
          <button className={view === 'table' ? 'on' : ''} onClick={() => setView('table')}>
            <LayoutList size={13} />
            Liste
          </button>
          <button className={view === 'cards' ? 'on' : ''} onClick={() => setView('cards')}>
            <LayoutGrid size={13} />
            Cartes
          </button>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto">
        {sorted.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 gap-3" style={{ color: 'var(--text-faint)' }}>
            <Layers size={28} strokeWidth={1} />
            <p className="cap">Aucune annonce correspondant aux filtres</p>
            <button
              className="btn-ghost"
              onClick={() => setAppartFilters({ search: '', location: [], minScore: 0, minPrice: 0, maxPrice: 2_000_000, minSurface: 0, minRooms: 0, minYield: 0, maxDpe: '', priceDropOnly: false, freshOnly: false })}
            >
              Effacer les filtres
            </button>
          </div>
        ) : view === 'cards' ? (
          <div className="card-grid">
            {sorted.map((row) => (
              <AppartCard key={row.id} row={row} onOpen={handleOpen} />
            ))}
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <Th col="score"   label="Score"   sort={appartSort} setSort={setAppartSort} />
                <th>Bien</th>
                <Th col="price"   label="Prix"    sort={appartSort} setSort={setAppartSort} />
                <Th col="surface" label="Surface" sort={appartSort} setSort={setAppartSort} />
                <th>DPE</th>
                <th>€/m²</th>
                <Th col="location" label="Commune" sort={appartSort} setSort={setAppartSort} />
                <Th col="yield"   label="Rdt%"   sort={appartSort} setSort={setAppartSort} />
                <Th col="avm_ratio" label="AVM"  sort={appartSort} setSort={setAppartSort} />
                <th>Âge</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((row) => {
                const id = row.id
                const isSeen     = !!seen[id]
                const isRejected = !!rejected[id]
                const age = daysAgo(row.first_seen)
                const pm2v = pm2(row.price, row.surface)
                const isExpanded = expandedId === id

                return (
                  <Fragment key={id}>
                    <tr
                      className={cn(
                        'row-active cursor-pointer',
                        isSeen && 'row-seen',
                        isRejected && 'row-rejected',
                      )}
                      onClick={() => handleOpen(id)}
                    >
                      {/* Score */}
                      <td>
                        <ScoreBadge score={row.score} />
                      </td>

                      {/* Title + flags */}
                      <td className="max-w-[240px]">
                        <div>
                          <a
                            href={row.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="block text-sub hover:text-accent text-xs leading-tight line-clamp-2"
                            style={{ fontSize: '0.8rem', color: 'var(--text)' }}
                            onClick={(e) => e.stopPropagation()}
                          >
                            {row.title}
                            <ExternalLink size={9} className="inline ml-1 opacity-40" />
                          </a>
                          <div className="flex gap-1 mt-1 flex-wrap">
                            {(row.price_drop ?? 0) > 0 && row.price > 0 && (() => {
                              const drop = row.price_drop!
                              const p = Math.round(drop / (row.price + drop) * 100)
                              return (
                                <span
                                  className="chip"
                                  style={{ background: 'oklch(0.64 0.17 40 / 0.1)', borderColor: 'oklch(0.64 0.17 40 / 0.3)', color: 'var(--orange)' }}
                                  title={`Baisse de ${Math.round(drop/1000)}k€`}
                                >
                                  <TrendingDown size={8} />
                                  -{p}%
                                </span>
                              )
                            })()}
                            {row.is_relisted && (
                              <span className="chip" style={{ background: 'oklch(0.52 0.18 300 / 0.1)', borderColor: 'oklch(0.52 0.18 300 / 0.3)', color: 'var(--violet)' }}>
                                <RefreshCw size={8} />
                                relisté
                              </span>
                            )}
                            {age <= 3 && (
                              <span className="chip" style={{ background: 'oklch(0.54 0.175 234 / 0.1)', borderColor: 'oklch(0.54 0.175 234 / 0.3)', color: 'var(--blue)' }}>
                                nouveau
                              </span>
                            )}
                          </div>
                        </div>
                      </td>

                      {/* Price */}
                      <td>
                        <span className="num font-600" style={{ fontSize: '0.88rem' }}>{eur(row.price)}</span>
                      </td>

                      {/* Surface */}
                      <td>
                        <span className="num">{row.surface ? `${row.surface}m²` : '—'}</span>
                        {row.rooms ? <span className="text-faint text-xs ml-1">{row.rooms}p</span> : null}
                      </td>

                      {/* DPE */}
                      <td><DPEBadge dpe={row.dpe} /></td>

                      {/* PM2 */}
                      <td>
                        <span className="num text-sub">{pm2v ? `${num(pm2v)}€` : '—'}</span>
                      </td>

                      {/* Location */}
                      <td>
                        <span style={{ fontSize: '0.78rem', color: 'var(--text-dim)' }}>{row.location}</span>
                      </td>

                      {/* Yield */}
                      <td>
                        {row.yield ? (
                          <span className="num" style={{
                            fontSize: '0.82rem', fontWeight: 600,
                            color: row.yield >= 7 ? 'var(--green)' : row.yield >= 5 ? 'var(--blue)' : 'var(--text-dim)',
                          }}>
                            {row.yield.toFixed(1)}%
                          </span>
                        ) : <span className="text-faint">—</span>}
                      </td>

                      {/* AVM */}
                      <td>
                        <AVMBadge pred={row.avm_pred} ratio={row.avm_ratio} model={row.avm_model} />
                      </td>

                      {/* Age */}
                      <td>
                        <span className="num" style={{
                          fontSize: '0.72rem',
                          color: age <= 7 ? 'var(--blue)' : age <= 30 ? 'var(--text-dim)' : 'var(--text-faint)',
                        }}>
                          {age <= 0 ? 'auj.' : `${age}j`}
                        </span>
                      </td>

                      {/* Actions */}
                      <td onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center gap-1">
                          <AppartActions
                            id={id}
                            surface={row.surface}
                            rooms={row.rooms}
                            location={row.location}
                            price={row.price}
                          />
                          <a
                            href={row.url}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="action-btn"
                            onClick={(e) => e.stopPropagation()}
                            title="Voir l'annonce"
                          >
                            <ExternalLink size={11} />
                          </a>
                        </div>
                      </td>
                    </tr>

                    {/* Expanded row */}
                    {isExpanded && (
                      <tr>
                        <td colSpan={11} style={{ background: 'var(--surface-2)', padding: '16px 20px' }}>
                          <div className="flex gap-6 flex-wrap">
                            {/* Price history */}
                            {row.price_history?.length > 1 && (
                              <div>
                                <p className="cap mb-2">Historique prix</p>
                                <div className="flex flex-col gap-0.5">
                                  {row.price_history.slice().reverse().map((h, i) => (
                                    <div key={i} className="flex gap-2 items-center" style={{ fontSize: '0.72rem' }}>
                                      <span className="num text-faint" style={{ width: 64 }}>{h.date?.slice(0, 10)}</span>
                                      <span className="num text-sub">{eur(h.price ?? h.prix)}</span>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {/* AVM detail */}
                            {row.avm_pred && (
                              <div>
                                <p className="cap mb-2">Estimation AVM</p>
                                <div className="flex flex-col gap-0.5" style={{ fontSize: '0.72rem' }}>
                                  <div className="flex gap-2">
                                    <span className="text-faint" style={{ width: 80 }}>Valeur est.</span>
                                    <span className="num" style={{ color: 'var(--blue)' }}>{eur(row.avm_pred)}</span>
                                  </div>
                                  <div className="flex gap-2">
                                    <span className="text-faint" style={{ width: 80 }}>Ratio AVM</span>
                                    <span className="num" style={{ color: row.avm_ratio && row.avm_ratio >= 1 ? 'var(--green)' : 'var(--red)' }}>
                                      ×{row.avm_ratio?.toFixed(3)}
                                    </span>
                                  </div>
                                  <div className="flex gap-2">
                                    <span className="text-faint" style={{ width: 80 }}>Modèle</span>
                                    <span className="text-sub">
                                      {row.avm_model === 'chamonix_apt' ? 'Chamonix appt (±8.8%)' : 'Vallée (~±15%)'}
                                    </span>
                                  </div>
                                  {row.avm_model !== 'chamonix_apt' && (
                                    <div className="flex items-center gap-1 mt-1" style={{ color: 'var(--amber)' }}>
                                      <AlertTriangle size={11} />
                                      <span>Modèle vallée — précision réduite</span>
                                    </div>
                                  )}
                                </div>
                              </div>
                            )}

                            {/* Photos */}
                            {row.photos && row.photos.length > 0 && (
                              <div className="w-full">
                                <p className="cap mb-2">Photos</p>
                                <div className="flex gap-2 overflow-x-auto pb-1">
                                  {row.photos.slice(0, 8).map((src, i) => (
                                    <a
                                      key={i}
                                      href={src}
                                      target="_blank"
                                      rel="noopener noreferrer"
                                      className="flex-shrink-0"
                                      onClick={(e) => e.stopPropagation()}
                                    >
                                      <img
                                        src={src}
                                        alt=""
                                        style={{ height: 80, width: 112, objectFit: 'cover', borderRadius: 8, opacity: 0.85 }}
                                        className="hover:opacity-100 transition-opacity"
                                      />
                                    </a>
                                  ))}
                                </div>
                              </div>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
