import { Fragment, useState, useMemo } from 'react'
import {
  ChevronUp, ChevronDown, ChevronsUpDown, ExternalLink, TrendingDown,
  Layers, Tag, Gauge, Ruler, LayoutList, LayoutGrid, Home, Building2,
} from 'lucide-react'
import { useStore } from '@/store/useStore'
import { ScoreBadge } from '@/components/shared/ScoreBadge'
import { AVMBadge } from '@/components/shared/AVMBadge'
import { MaisonActions } from '@/components/shared/ActionButtons'
import { FilterPill, PopLabel, PopSlider, PopCheckRow, PopToggle } from '@/components/shared/FilterPill'
import { eur, pm2, num, daysAgo, cn, NEIGHBOURHOOD_ORDER } from '@/lib/utils'
import type { SortState, Maison } from '@/types'
import { MAISONS } from '@/lib/data'

const maisons = MAISONS

const QUARTIERS = [...new Set(maisons.map((m) => m.neighbourhood).filter(Boolean))].sort((a, b) => {
  const ia = NEIGHBOURHOOD_ORDER.indexOf(a)
  const ib = NEIGHBOURHOOD_ORDER.indexOf(b)
  return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib)
})

const SORT_OPTIONS: { key: string; dir: 'asc' | 'desc'; label: string }[] = [
  { key: 'avm_score',    dir: 'desc', label: 'Score ↓' },
  { key: 'avm_score',    dir: 'asc',  label: 'Score ↑' },
  { key: 'prix',         dir: 'asc',  label: 'Prix ↑' },
  { key: 'prix',         dir: 'desc', label: 'Prix ↓' },
  { key: 'surface',      dir: 'desc', label: 'Surface ↓' },
  { key: 'surface',      dir: 'asc',  label: 'Surface ↑' },
  { key: 'surf_terrain', dir: 'desc', label: 'Terrain ↓' },
  { key: 'avm_ratio',    dir: 'desc', label: 'AVM ↓' },
  { key: 'avm_ratio',    dir: 'asc',  label: 'AVM ↑' },
]

function SortIcon({ col, sort }: { col: string; sort: SortState }) {
  if (sort.key !== col) return <ChevronsUpDown size={10} className="opacity-25 ml-0.5" />
  return sort.dir === 'asc'
    ? <ChevronUp size={10} className="ml-0.5" style={{ color: 'var(--accent)' }} />
    : <ChevronDown size={10} className="ml-0.5" style={{ color: 'var(--accent)' }} />
}

function Th({ col, label, sort, setSort, className }: {
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

function MaisonCard({ m }: { m: Maison }) {
  const { seen, rejected } = useStore()
  const key = `m_${m.id}`
  const isSeen = !!seen[key]
  const isRejected = !!rejected[key]
  const pm2v = pm2(m.prix, m.surface)

  return (
    <div className={`deal-card ${isSeen ? 'seen' : ''} ${isRejected ? 'rejected' : ''}`}>
      {/* Photo or placeholder */}
      {m.photos && m.photos.length > 0 ? (
        <img src={m.photos[0]} alt="" className="deal-card-img" />
      ) : (
        <div className="deal-card-img-placeholder">
          <Home size={28} />
        </div>
      )}

      <div className="deal-card-body">
        <div className="deal-card-top">
          <div style={{ flex: 1 }}>
            <div className="deal-card-title">
              {m.titre || m.adresse_raw || `Maison #${m.id}`}
            </div>
            <div className="mt-1 flex gap-1 flex-wrap">
              {m.neighbourhood && (
                <span className="chip" style={{ background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text-faint)' }}>
                  {m.neighbourhood}
                </span>
              )}
              {m.needs_renovation && (
                <span className="chip" style={{ background: 'oklch(0.68 0.155 70 / 0.12)', borderColor: 'oklch(0.68 0.155 70 / 0.35)', color: 'var(--amber)' }}>
                  🔧 travaux
                </span>
              )}
            </div>
          </div>
          <ScoreBadge score={m.avm_score} />
        </div>

        <div className="deal-card-price">{eur(m.prix)}</div>

        <div className="deal-card-chips">
          {m.surface > 0 && (
            <span className="chip" style={{ background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text-dim)' }}>
              {m.surface}m² hab.
            </span>
          )}
          {m.surf_terrain && (
            <span className="chip" style={{ background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text-dim)' }}>
              {num(m.surf_terrain)}m² terrain
            </span>
          )}
          {m.pieces > 0 && (
            <span className="chip" style={{ background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text-dim)' }}>
              {m.pieces}p
            </span>
          )}
          {pm2v && (
            <span className="chip" style={{ background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text-dim)' }}>
              {num(pm2v)}€/m²
            </span>
          )}
        </div>
      </div>

      <div className="deal-card-footer">
        <AVMBadge pred={m.avm_pred} ratio={m.avm_ratio} />
        <div className="flex gap-1" onClick={(e) => e.stopPropagation()}>
          <MaisonActions id={m.id} />
          {m.url && (
            <a
              href={m.url}
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

export function MaisonsTab() {
  const {
    maisonFilters, setMaisonFilters,
    maisonSort, setMaisonSort,
    seen, rejected,
  } = useStore()

  const [view, setView] = useState<'table' | 'cards'>('cards')
  const [expandedId, setExpandedId] = useState<number | null>(null)
  const [openPill, setOpenPill] = useState<string | null>(null)
  const pillProps = (name: string) => ({
    open: openPill === name,
    onToggle: () => setOpenPill(openPill === name ? null : name),
    onClose: () => setOpenPill(null),
  })

  const filtered = useMemo(() => {
    return maisons.filter((m) => {
      const key = `m_${m.id}`
      if (!maisonFilters.showRejected && rejected[key]) return false
      if (maisonFilters.hideStructured && m.is_structured) return false
      if (m.avm_score != null && m.avm_score < maisonFilters.minScore) return false
      if (maisonFilters.minPrice > 0 && m.prix < maisonFilters.minPrice) return false
      if (m.prix > maisonFilters.maxPrice) return false
      if (m.surface && m.surface < maisonFilters.minSurface) return false
      if (maisonFilters.minTerrain > 0 && (m.surf_terrain == null || m.surf_terrain < maisonFilters.minTerrain)) return false
      if (maisonFilters.minRooms > 0 && m.pieces < maisonFilters.minRooms) return false
      if (maisonFilters.renovationFilter === 'only' && !m.needs_renovation) return false
      if (maisonFilters.renovationFilter === 'exclude' && m.needs_renovation) return false
      if (maisonFilters.section.length > 0 && !maisonFilters.section.includes(m.neighbourhood)) return false
      if (maisonFilters.search) {
        const q = maisonFilters.search.toLowerCase()
        const hay = `${m.adresse_raw} ${m.neighbourhood} ${m.prix} ${m.surface}`.toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [maisons, maisonFilters, rejected])

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const key = maisonSort.key
      const av = (a as unknown as Record<string, number | null>)[key]
      const bv = (b as unknown as Record<string, number | null>)[key]
      if (av == null && bv == null) return 0
      if (av == null) return 1
      if (bv == null) return -1
      return maisonSort.dir === 'desc' ? bv - av : av - bv
    })
  }, [filtered, maisonSort])

  // KPI stats
  const stats = useMemo(() => {
    const active = sorted.filter((m) => !rejected[`m_${m.id}`])
    const pm2s = active.map((m) => pm2(m.prix, m.surface)).filter(Boolean) as number[]
    const medPm2 = pm2s.length ? pm2s.sort((a, b) => a - b)[Math.floor(pm2s.length / 2)] : null
    const terrains = active.map((m) => m.surf_terrain).filter(Boolean) as number[]
    const medTerrain = terrains.length ? terrains.sort((a, b) => a - b)[Math.floor(terrains.length / 2)] : null
    const bonnes = active.filter((m) => (m.avm_ratio ?? 0) >= 1.1).length
    const fresh = active.filter((m) => daysAgo(m.first_seen) <= 7).length
    return { n: active.length, medPm2, medTerrain, bonnes, fresh }
  }, [sorted, rejected])

  return (
    <div className="flex flex-col h-full">

      {/* KPI row */}
      <div className="kpi-row">
        <div className="kpi-cell">
          <div className="kpi-label"><Layers size={11} /> En vue</div>
          <div className="kpi-value">
            {stats.n}
            <span className="unit"> / {maisons.length}</span>
          </div>
          <div className="kpi-foot">maisons actives</div>
        </div>
        <div className="kpi-cell">
          <div className="kpi-label"><Tag size={11} /> Méd. €/m²</div>
          <div className="kpi-value">
            {stats.medPm2 ? num(stats.medPm2) : '—'}
            <span className="unit">€</span>
          </div>
          <div className="kpi-foot">surface habitable</div>
        </div>
        <div className="kpi-cell">
          <div className="kpi-label"><Ruler size={11} /> Méd. terrain</div>
          <div className="kpi-value">
            {stats.medTerrain ? num(stats.medTerrain) : '—'}
            <span className="unit">m²</span>
          </div>
          <div className="kpi-foot">
            {stats.fresh > 0 ? `${stats.fresh} nouvelles 7j` : 'surface terrain'}
          </div>
        </div>
        <div className="kpi-cell">
          <div className="kpi-label"><Gauge size={11} /> Bonnes affaires</div>
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
          value={maisonFilters.search}
          onChange={(e) => setMaisonFilters({ search: e.target.value })}
        />

        {/* Quartier */}
        <FilterPill
          label="Quartier"
          active={maisonFilters.section.length > 0}
          count={maisonFilters.section.length || undefined}
          {...pillProps('section')}
        >
          <PopLabel>Quartier</PopLabel>
          <PopCheckRow
            label="Tous"
            checked={maisonFilters.section.length === 0}
            onChange={() => setMaisonFilters({ section: [] })}
          />
          {QUARTIERS.map((q) => (
            <PopCheckRow
              key={q}
              label={q}
              checked={maisonFilters.section.includes(q)}
              onChange={() => {
                const next = maisonFilters.section.includes(q)
                  ? maisonFilters.section.filter((s) => s !== q)
                  : [...maisonFilters.section, q]
                setMaisonFilters({ section: next })
              }}
            />
          ))}
        </FilterPill>

        {/* Prix */}
        <FilterPill
          label="Prix"
          active={maisonFilters.minPrice > 0 || maisonFilters.maxPrice < 5_000_000}
          {...pillProps('prix')}
        >
          <PopSlider
            label="Prix minimum"
            value={maisonFilters.minPrice}
            min={0} max={4_000_000} step={50_000}
            format={(v) => v === 0 ? 'Aucun' : `${(v / 1000).toFixed(0)}k€`}
            onChange={(v) => setMaisonFilters({ minPrice: v })}
          />
          <PopSlider
            label="Prix maximum"
            value={maisonFilters.maxPrice}
            min={200_000} max={5_000_000} step={50_000}
            format={(v) => v >= 5_000_000 ? 'Tous' : `${(v / 1000).toFixed(0)}k€`}
            onChange={(v) => setMaisonFilters({ maxPrice: v })}
          />
        </FilterPill>

        {/* Score */}
        <FilterPill label="Score" active={maisonFilters.minScore > 0} {...pillProps('score')}>
          <PopSlider
            label="Score AVM minimum"
            value={maisonFilters.minScore}
            min={0} max={90} step={5}
            onChange={(v) => setMaisonFilters({ minScore: v })}
          />
        </FilterPill>

        {/* Surface */}
        <FilterPill label="Surface" active={maisonFilters.minSurface > 0} {...pillProps('surface')}>
          <PopSlider
            label="Surface habitable min."
            value={maisonFilters.minSurface}
            min={0} max={400} step={20}
            format={(v) => v === 0 ? 'Tous' : `${v}m²`}
            onChange={(v) => setMaisonFilters({ minSurface: v })}
          />
        </FilterPill>

        {/* Terrain */}
        <FilterPill label="Terrain" active={maisonFilters.minTerrain > 0} {...pillProps('terrain')}>
          <PopSlider
            label="Surface terrain min."
            value={maisonFilters.minTerrain}
            min={0} max={5000} step={200}
            format={(v) => v === 0 ? 'Tous' : `${v}m²`}
            onChange={(v) => setMaisonFilters({ minTerrain: v })}
          />
        </FilterPill>

        {/* Pièces */}
        <FilterPill label="Pièces" active={maisonFilters.minRooms > 0} {...pillProps('pieces')}>
          <PopLabel>Pièces minimum</PopLabel>
          {[0, 2, 3, 4, 5, 6].map((n) => (
            <PopCheckRow
              key={n}
              label={n === 0 ? 'Toutes' : `${n}+ pièces`}
              checked={maisonFilters.minRooms === n}
              onChange={() => setMaisonFilters({ minRooms: n })}
            />
          ))}
        </FilterPill>

        {/* Rénovation */}
        <FilterPill
          label="Rénovation"
          active={maisonFilters.renovationFilter !== 'all'}
          {...pillProps('renov')}
        >
          <PopLabel>Travaux / rénovation</PopLabel>
          <PopCheckRow
            label="Toutes"
            checked={maisonFilters.renovationFilter === 'all'}
            onChange={() => setMaisonFilters({ renovationFilter: 'all' })}
          />
          <PopCheckRow
            label="Avec travaux seulement"
            checked={maisonFilters.renovationFilter === 'only'}
            onChange={() => setMaisonFilters({ renovationFilter: 'only' })}
          />
          <PopCheckRow
            label="Sans travaux"
            checked={maisonFilters.renovationFilter === 'exclude'}
            onChange={() => setMaisonFilters({ renovationFilter: 'exclude' })}
          />
        </FilterPill>

        {/* Options */}
        <FilterPill
          label="Options"
          active={maisonFilters.showRejected || !maisonFilters.hideStructured}
          align="right"
          {...pillProps('options')}
        >
          <PopLabel>Visibilité</PopLabel>
          <PopToggle
            label="Masquer produits structurés"
            checked={maisonFilters.hideStructured}
            onChange={(v) => setMaisonFilters({ hideStructured: v })}
          />
          <PopToggle
            label="Afficher rejetés"
            checked={maisonFilters.showRejected}
            onChange={(v) => setMaisonFilters({ showRejected: v })}
          />
        </FilterPill>

        <div className="flex-1" />

        <span className="cap" style={{ color: 'var(--text-dim)' }}>
          <b style={{ color: 'var(--text)', fontFamily: 'var(--font-mono)' }}>{sorted.length}</b> résultat{sorted.length !== 1 ? 's' : ''}
        </span>

        {/* Sort pill */}
        <FilterPill
          label={SORT_OPTIONS.find(s => s.key === maisonSort.key && s.dir === maisonSort.dir)?.label ?? 'Trier'}
          active={!(maisonSort.key === 'avm_score' && maisonSort.dir === 'desc')}
          align="right"
          {...pillProps('sort')}
        >
          <PopLabel>Trier par</PopLabel>
          {SORT_OPTIONS.map((s) => (
            <PopCheckRow
              key={`${s.key}-${s.dir}`}
              label={s.label}
              checked={maisonSort.key === s.key && maisonSort.dir === s.dir}
              onChange={() => { setMaisonSort({ key: s.key, dir: s.dir }); setOpenPill(null) }}
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
            <p className="cap">Aucune maison correspondant aux filtres</p>
          </div>
        ) : view === 'cards' ? (
          <div className="card-grid">
            {sorted.map((m) => <MaisonCard key={m.id} m={m} />)}
          </div>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <Th col="avm_score"   label="Score"   sort={maisonSort} setSort={setMaisonSort} />
                <th>Adresse / Section</th>
                <Th col="prix"        label="Prix"    sort={maisonSort} setSort={setMaisonSort} />
                <Th col="surface"     label="Hab."    sort={maisonSort} setSort={setMaisonSort} />
                <th>Terrain</th>
                <th>€/m²</th>
                <Th col="pieces"      label="Pièces"  sort={maisonSort} setSort={setMaisonSort} />
                <Th col="avm_ratio"   label="AVM"     sort={maisonSort} setSort={setMaisonSort} />
                <Th col="nb_baisses"  label="Baisses" sort={maisonSort} setSort={setMaisonSort} />
                <th>Vu le</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((m) => {
                const key = `m_${m.id}`
                const isSeen     = !!seen[key]
                const isRejected = !!rejected[key]
                const pm2v = pm2(m.prix, m.surface)
                const isExpanded = expandedId === m.id

                return (
                  <Fragment key={m.id}>
                    <tr
                      className={cn(
                        'row-active cursor-pointer',
                        isSeen && 'row-seen',
                        isRejected && 'row-rejected',
                      )}
                      onClick={() => setExpandedId(isExpanded ? null : m.id)}
                    >
                      {/* Score */}
                      <td>
                        {m.avm_score != null
                          ? <ScoreBadge score={m.avm_score} />
                          : <span className="text-faint text-xs">—</span>
                        }
                      </td>

                      {/* Address */}
                      <td style={{ maxWidth: 220 }}>
                        <div>
                          <span style={{ fontSize: '0.8rem', color: 'var(--text)', fontWeight: 500 }}>
                            {m.adresse_raw ?? m.titre ?? `Maison #${m.id}`}
                          </span>
                          <div className="flex gap-1 mt-1 flex-wrap">
                            {m.neighbourhood && (
                              <span className="chip" style={{ background: 'var(--surface-2)', borderColor: 'var(--border)', color: 'var(--text-faint)', fontSize: '0.6rem' }}>
                                {m.neighbourhood}
                              </span>
                            )}
                            {m.needs_renovation && (
                              <span className="chip" style={{ background: 'oklch(0.68 0.155 70 / 0.12)', borderColor: 'oklch(0.68 0.155 70 / 0.35)', color: 'var(--amber)', fontSize: '0.6rem' }}
                                title="Travaux / rénovation à prévoir — score AVM non ajusté">
                                🔧 travaux
                              </span>
                            )}
                            {(m.nb_baisses ?? 0) > 0 && (
                              <span className="chip" style={{ background: 'oklch(0.64 0.17 40 / 0.1)', borderColor: 'oklch(0.64 0.17 40 / 0.3)', color: 'var(--orange)', fontSize: '0.6rem' }}>
                                <TrendingDown size={8} />{m.nb_baisses}
                              </span>
                            )}
                          </div>
                        </div>
                      </td>

                      {/* Prix */}
                      <td>
                        <div>
                          <span className="num font-600" style={{ fontSize: '0.85rem' }}>{eur(m.prix)}</span>
                          {m.prix_initial && m.prix_initial > m.prix && (
                            <div className="num text-faint" style={{ fontSize: '0.68rem', textDecoration: 'line-through' }}>{eur(m.prix_initial)}</div>
                          )}
                        </div>
                      </td>

                      {/* Surface hab */}
                      <td>
                        <span className="num">{m.surface ? `${m.surface}m²` : '—'}</span>
                      </td>

                      {/* Terrain */}
                      <td>
                        <span className="num text-sub">{m.surf_terrain ? `${num(m.surf_terrain)}m²` : '—'}</span>
                      </td>

                      {/* PM2 */}
                      <td>
                        <span className="num text-sub">{pm2v ? `${num(pm2v)}€` : '—'}</span>
                      </td>

                      {/* Pièces */}
                      <td>
                        <span className="num text-sub">{m.pieces ?? '—'}</span>
                      </td>

                      {/* AVM */}
                      <td>
                        <AVMBadge pred={m.avm_pred} ratio={m.avm_ratio} />
                      </td>

                      {/* Baisses */}
                      <td>
                        {(m.nb_baisses ?? 0) > 0 ? (
                          <span className="chip" style={{ background: 'oklch(0.64 0.17 40 / 0.1)', borderColor: 'oklch(0.64 0.17 40 / 0.3)', color: 'var(--orange)' }}>
                            {m.nb_baisses}×
                          </span>
                        ) : <span className="text-faint text-xs">—</span>}
                      </td>

                      {/* Date */}
                      <td>
                        <span className="num text-faint" style={{ fontSize: '0.72rem' }}>
                          {m.first_seen?.slice(0, 10) ?? '—'}
                        </span>
                      </td>

                      {/* Actions */}
                      <td onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center gap-1">
                          <MaisonActions id={m.id} />
                          {m.url && (
                            <a
                              href={m.url}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="action-btn"
                              onClick={(e) => e.stopPropagation()}
                              title="Voir l'annonce"
                            >
                              <ExternalLink size={11} />
                            </a>
                          )}
                        </div>
                      </td>
                    </tr>

                    {/* Expanded row */}
                    {isExpanded && (
                      <tr>
                        <td colSpan={11} style={{ background: 'var(--surface-2)', padding: '16px 20px' }}>
                          <div className="space-y-3">
                            {/* Photos */}
                            {(m.photos?.length ?? 0) > 0 && (
                              <div className="flex gap-2 overflow-x-auto pb-1">
                                {(m.photos ?? []).slice(0, 8).map((src, i) => (
                                  <img
                                    key={i}
                                    src={src}
                                    alt=""
                                    style={{ height: 88, width: 128, objectFit: 'cover', borderRadius: 8, opacity: 0.9, flexShrink: 0 }}
                                    className="hover:opacity-100 transition-opacity"
                                  />
                                ))}
                              </div>
                            )}

                            <div className="flex gap-6 flex-wrap">
                              {/* AVM detail */}
                              {m.avm_pred && (
                                <div>
                                  <p className="cap mb-2">Estimation AVM</p>
                                  <div className="flex flex-col gap-0.5" style={{ fontSize: '0.72rem' }}>
                                    <div className="flex gap-2">
                                      <span className="text-faint" style={{ width: 96 }}>Valeur estimée</span>
                                      <span className="num" style={{ color: 'var(--blue)' }}>{eur(m.avm_pred)}</span>
                                    </div>
                                    <div className="flex gap-2">
                                      <span className="text-faint" style={{ width: 96 }}>Ratio AVM</span>
                                      <span className="num" style={{ color: m.avm_ratio && m.avm_ratio >= 1 ? 'var(--green)' : 'var(--red)' }}>
                                        ×{m.avm_ratio?.toFixed(3)}
                                      </span>
                                    </div>
                                    <div className="flex gap-2">
                                      <span className="text-faint" style={{ width: 96 }}>Modèle</span>
                                      <span className="text-sub">Maison Chamonix (±15%)</span>
                                    </div>
                                  </div>
                                </div>
                              )}

                              {/* Price history */}
                              {(m.historique_prix?.length ?? 0) > 1 && (
                                <div>
                                  <p className="cap mb-2">Historique prix</p>
                                  <div className="flex flex-col gap-0.5">
                                    {(m.historique_prix ?? []).slice().reverse().map((h, i) => (
                                      <div key={i} className="flex gap-2 items-center" style={{ fontSize: '0.72rem' }}>
                                        <span className="num text-faint" style={{ width: 64 }}>{h.date?.slice(0, 10)}</span>
                                        <span className="num text-sub">{eur(h.prix ?? h.price)}</span>
                                      </div>
                                    ))}
                                  </div>
                                </div>
                              )}

                              {/* Notes */}
                              {m.notes && (
                                <div>
                                  <p className="cap mb-2">Notes</p>
                                  <p className="text-sub italic" style={{ fontSize: '0.75rem' }}>{m.notes}</p>
                                </div>
                              )}
                            </div>

                            {/* Description */}
                            {m.description && (
                              <p className="text-sub leading-relaxed" style={{ fontSize: '0.72rem', maxWidth: '64ch', borderTop: '1px solid var(--border)', paddingTop: 12, marginTop: 4 }}>
                                {m.description}
                              </p>
                            )}
                          </div>
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
              {sorted.length === 0 && (
                <tr>
                  <td colSpan={11} style={{ textAlign: 'center', color: 'var(--text-faint)', padding: '48px 0', fontSize: '0.8rem' }}>
                    Aucune maison correspondant aux filtres
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
