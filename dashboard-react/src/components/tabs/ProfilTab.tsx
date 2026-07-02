import { useState, useMemo, useEffect } from 'react'
import {
  User, Bookmark, MapPin, ExternalLink,
  FileDown, StickyNote, Target, BarChart2, Trash2,
  Building2, Home, X, Sparkles, ChevronRight, MapPinned,
} from 'lucide-react'
import { useStore } from '@/store/useStore'
import type { WatchlistStatus, WatchlistEntry, InvestProfile } from '@/types'
import { APPARTS, MAISONS } from '@/lib/data'
import { eur, num, NEIGHBOURHOOD_ORDER } from '@/lib/utils'
import { ScoreBadge } from '@/components/shared/ScoreBadge'

// ── Constants ─────────────────────────────────────────────────────────────────

const STATUS_META: Record<WatchlistStatus, { label: string; color: string; bg: string }> = {
  a_visiter: { label: 'À visiter',   color: 'var(--accent)', bg: 'var(--accent-soft)' },
  visite:    { label: 'Visité',      color: 'var(--amber)',  bg: 'oklch(0.72 0.12 72 / 0.12)' },
  offre:     { label: 'Offre faite', color: 'var(--green)',  bg: 'oklch(0.52 0.155 152 / 0.10)' },
  refuse:    { label: 'Refusé',      color: 'var(--red)',    bg: 'oklch(0.64 0.17 40 / 0.10)' },
}

const STATUS_ORDER: WatchlistStatus[] = ['a_visiter', 'visite', 'offre', 'refuse']

const BUDGET_MAX = 3_000_000
const SURFACE_MAX = 300
const RENDEMENT_MAX = 20
const SCORE_MAX = 100

function fmtBudget(v: number) {
  if (v === 0) return 'Pas de limite'
  if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(v % 1_000_000 === 0 ? 0 : 1)}M €`
  return `${Math.round(v / 1000)}k €`
}
function fmtSurface(v: number) { return v === 0 ? 'Pas de limite' : `${v} m²` }
function fmtRendement(v: number) { return v === 0 ? 'Pas de limite' : `${v.toFixed(1)} %` }
function fmtScore(v: number) { return v === 0 ? 'Tous les scores' : `≥ ${v} / 100` }

function sliderBg(val: number, max: number) {
  const pct = (val / max) * 100
  return `linear-gradient(to right, var(--accent) 0% ${pct}%, var(--border-strong) ${pct}% 100%)`
}

// ── Criteria modal ────────────────────────────────────────────────────────────

const SECTEURS = NEIGHBOURHOOD_ORDER.filter((n) =>
  APPARTS.some((r) => r.neighbourhood === n) || MAISONS.some((m) => m.neighbourhood === n)
)

function CriteresModal({ onClose }: { onClose: () => void }) {
  const { investProfile, setInvestProfile, setAppartFilters, setMaisonFilters, setBienTypes, setActiveTab } = useStore()
  const [draft, setDraft] = useState<InvestProfile>({ ...investProfile })

  // Close on Escape
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  function patch(p: Partial<InvestProfile>) { setDraft((d) => ({ ...d, ...p })) }

  function toggleType(t: 'appart' | 'maison') {
    const next = draft.types.includes(t)
      ? draft.types.filter((x) => x !== t)
      : [...draft.types, t]
    if (next.length > 0) patch({ types: next })
  }

  function toggleSecteur(n: string) {
    const next = draft.secteurs.includes(n)
      ? draft.secteurs.filter((s) => s !== n)
      : [...draft.secteurs, n]
    patch({ secteurs: next })
  }

  function apply() {
    // Save profile
    setInvestProfile(draft)
    // Apply to filters
    setAppartFilters({
      maxPrice:    draft.budgetMax  > 0 ? draft.budgetMax  : 2_000_000,
      minSurface:  draft.surfaceMin > 0 ? draft.surfaceMin : 0,
      minYield:    draft.rendementMin,
      minScore:    draft.scoreMin,
      location:    draft.secteurs,
    })
    setMaisonFilters({
      maxPrice:   draft.budgetMax  > 0 ? draft.budgetMax  : 5_000_000,
      minSurface: draft.surfaceMin > 0 ? draft.surfaceMin : 0,
    })
    // Apply types
    const bienTypes = draft.types.map((t) => (t + 's') as 'apparts' | 'maisons')
    setBienTypes(bienTypes)
    // Navigate
    setActiveTab('biens')
    onClose()
  }

  const hasFilters = draft.budgetMax > 0 || draft.surfaceMin > 0 || draft.rendementMin > 0
    || draft.scoreMin > 0 || draft.secteurs.length > 0 || draft.types.length < 2

  return (
    <div className="cq-overlay" onClick={onClose}>
      <div className="cq-panel" onClick={(e) => e.stopPropagation()}>

        {/* Header */}
        <div className="cq-header">
          <div className="cq-header-icon"><Target size={16} /></div>
          <div>
            <div className="cq-header-title">Mes critères</div>
            <div className="cq-header-sub">Définissez votre bien idéal</div>
          </div>
          <button className="cq-close" onClick={onClose}><X size={16} /></button>
        </div>

        <div className="cq-body">

          {/* Stratégie */}
          <div className="cq-field">
            <div className="cq-label">Stratégie d'investissement</div>
            <select
              className="cq-strat-select"
              value={draft.strategie ?? 'mixte'}
              onChange={(e) => patch({ strategie: e.target.value as InvestProfile['strategie'] })}
            >
              <option value="mixte">Mixte — équilibre rendement / valorisation</option>
              <option value="locatif">Locatif — rendement maximal</option>
              <option value="patrimonial">Patrimonial — valorisation long terme</option>
              <option value="rp">Résidence principale</option>
              <option value="potentiel">Potentiel — décote &amp; travaux</option>
            </select>
          </div>

          {/* Type */}
          <div className="cq-field">
            <div className="cq-label">Type de bien</div>
            <div className="cq-type-row">
              {(['appart', 'maison'] as const).map((t) => {
                const active = draft.types.includes(t)
                return (
                  <button key={t}
                    className={`cq-type-btn${active ? ' active' : ''}`}
                    onClick={() => toggleType(t)}
                  >
                    {t === 'appart' ? <Building2 size={14} /> : <Home size={14} />}
                    {t === 'appart' ? 'Appartements' : 'Maisons'}
                  </button>
                )
              })}
            </div>
          </div>

          {/* Secteurs */}
          <div className="cq-field">
            <div className="cq-label"><MapPinned size={12} /> Secteurs <span className="cq-label-hint">{draft.secteurs.length === 0 ? '(tous)' : `${draft.secteurs.length} sélectionné${draft.secteurs.length > 1 ? 's' : ''}`}</span></div>
            <div className="cq-chips">
              {SECTEURS.map((n) => (
                <button key={n}
                  className={`cq-chip${draft.secteurs.includes(n) ? ' active' : ''}`}
                  onClick={() => toggleSecteur(n)}
                >
                  {n}
                </button>
              ))}
            </div>
          </div>

          {/* Budget */}
          <div className="cq-field">
            <div className="cq-slider-header">
              <div className="cq-label">Budget maximum</div>
              <div className="cq-slider-val">{fmtBudget(draft.budgetMax)}</div>
            </div>
            <input type="range"
              className="cq-slider"
              min={0} max={BUDGET_MAX} step={50_000}
              value={draft.budgetMax}
              style={{ background: sliderBg(draft.budgetMax, BUDGET_MAX) }}
              onChange={(e) => patch({ budgetMax: Number(e.target.value) })}
            />
            <div className="cq-slider-ticks">
              <span>0</span><span>750k</span><span>1.5M</span><span>2.25M</span><span>3M</span>
            </div>
          </div>

          {/* Surface */}
          <div className="cq-field">
            <div className="cq-slider-header">
              <div className="cq-label">Surface minimum</div>
              <div className="cq-slider-val">{fmtSurface(draft.surfaceMin)}</div>
            </div>
            <input type="range"
              className="cq-slider"
              min={0} max={SURFACE_MAX} step={5}
              value={draft.surfaceMin}
              style={{ background: sliderBg(draft.surfaceMin, SURFACE_MAX) }}
              onChange={(e) => patch({ surfaceMin: Number(e.target.value) })}
            />
            <div className="cq-slider-ticks">
              <span>0</span><span>75m²</span><span>150m²</span><span>225m²</span><span>300m²</span>
            </div>
          </div>

          {/* Rendement */}
          <div className="cq-field">
            <div className="cq-slider-header">
              <div className="cq-label">Rendement brut cible</div>
              <div className="cq-slider-val">{fmtRendement(draft.rendementMin)}</div>
            </div>
            <input type="range"
              className="cq-slider"
              min={0} max={RENDEMENT_MAX} step={0.5}
              value={draft.rendementMin}
              style={{ background: sliderBg(draft.rendementMin, RENDEMENT_MAX) }}
              onChange={(e) => patch({ rendementMin: Number(e.target.value) })}
            />
            <div className="cq-slider-ticks">
              <span>0%</span><span>5%</span><span>10%</span><span>15%</span><span>20%</span>
            </div>
          </div>

          {/* Score AVM */}
          <div className="cq-field">
            <div className="cq-slider-header">
              <div className="cq-label">Score AVM minimum</div>
              <div className="cq-slider-val">{fmtScore(draft.scoreMin)}</div>
            </div>
            <input type="range"
              className="cq-slider"
              min={0} max={SCORE_MAX} step={5}
              value={draft.scoreMin}
              style={{ background: sliderBg(draft.scoreMin, SCORE_MAX) }}
              onChange={(e) => patch({ scoreMin: Number(e.target.value) })}
            />
            <div className="cq-slider-ticks">
              <span>0</span><span>25</span><span>50</span><span>75</span><span>100</span>
            </div>
          </div>

        </div>

        {/* Footer */}
        <div className="cq-footer">
          {hasFilters && (
            <button className="cq-reset" onClick={() => setDraft({
              budgetMax: 0, surfaceMin: 0, rendementMin: 0,
              scoreMin: 0, types: ['appart', 'maison'], secteurs: [], strategie: 'mixte',
            })}>
              Réinitialiser
            </button>
          )}
          <button className="cq-apply" onClick={apply}>
            <Sparkles size={14} />
            Trouver mon bonheur
            <ChevronRight size={14} />
          </button>
        </div>

      </div>
    </div>
  )
}

// ── Criteria summary chip ─────────────────────────────────────────────────────

function CriteriaSummary({ onOpen }: { onOpen: () => void }) {
  const { investProfile } = useStore()
  const p = investProfile
  const hasCriteria = p.budgetMax > 0 || p.surfaceMin > 0 || p.rendementMin > 0
    || p.scoreMin > 0 || p.secteurs.length > 0 || p.types.length < 2

  return (
    <div className="cq-summary-row">
      <div className="cq-summary-chips">
        {p.types.length < 2 && (
          <span className="cq-summary-chip">
            {p.types[0] === 'appart' ? <Building2 size={9} /> : <Home size={9} />}
            {p.types[0] === 'appart' ? 'Apparts seuls' : 'Maisons seules'}
          </span>
        )}
        {p.budgetMax > 0 && (
          <span className="cq-summary-chip">≤ {fmtBudget(p.budgetMax)}</span>
        )}
        {p.surfaceMin > 0 && (
          <span className="cq-summary-chip">≥ {p.surfaceMin}m²</span>
        )}
        {p.rendementMin > 0 && (
          <span className="cq-summary-chip">≥ {p.rendementMin}% rdt</span>
        )}
        {p.scoreMin > 0 && (
          <span className="cq-summary-chip">score ≥ {p.scoreMin}</span>
        )}
        {p.secteurs.map((s) => (
          <span key={s} className="cq-summary-chip"><MapPin size={8} />{s}</span>
        ))}
        {!hasCriteria && (
          <span className="cq-summary-empty">Aucun critère défini</span>
        )}
      </div>
      <button className="cq-open-btn" onClick={onOpen}>
        <Target size={12} /> Mes critères
      </button>
    </div>
  )
}

// ── Watchlist card ────────────────────────────────────────────────────────────

function WatchCard({
  id, entry, note,
  onStatus, onRemove,
}: {
  id: string
  entry: WatchlistEntry
  note?: string
  onStatus: (s: WatchlistStatus) => void
  onRemove: () => void
}) {
  const pm2v = entry.surface > 0 ? Math.round(entry.price / entry.surface) : null

  return (
    <div className="wl-card">
      <div className="wl-card-top">
        <span className="wl-card-type">
          {entry.type === 'appart' ? <Building2 size={10} /> : <Home size={10} />}
          {entry.type === 'appart' ? 'Appartement' : 'Maison'}
        </span>
        <span className="wl-card-hood"><MapPin size={9} />{entry.neighbourhood}</span>
        {entry.score != null && <ScoreBadge score={entry.score} />}
        <button className="wl-card-remove" onClick={onRemove} title="Retirer"><Trash2 size={11} /></button>
      </div>
      <div className="wl-card-title" title={entry.title}>{entry.title}</div>
      <div className="wl-card-prices">
        <span className="wl-card-price">{eur(entry.price)}</span>
        <span className="wl-card-meta">{entry.surface}m²{pm2v ? ` · ${num(pm2v)}€/m²` : ''}</span>
      </div>
      {note && <div className="wl-card-note"><StickyNote size={9} />{note}</div>}
      <div className="wl-card-statuses">
        {STATUS_ORDER.map((s) => {
          const m = STATUS_META[s]
          const active = entry.status === s
          return (
            <button
              key={s}
              className={`wl-status-pill${active ? ' active' : ''}`}
              style={active ? { background: m.bg, color: m.color, borderColor: m.color + '66' } : undefined}
              onClick={() => onStatus(s)}
            >
              {m.label}
            </button>
          )
        })}
      </div>
      {entry.url && (
        <a href={entry.url} target="_blank" rel="noopener noreferrer" className="wl-card-link">
          <ExternalLink size={10} /> Voir l'annonce
        </a>
      )}
    </div>
  )
}

// ── Section header ────────────────────────────────────────────────────────────

function SectionHeader({ icon, title, count }: { icon: React.ReactNode; title: string; count?: number }) {
  return (
    <div className="profil-section-header">
      {icon}
      <span className="profil-section-title">{title}</span>
      {count != null && <span className="profil-section-count">{count}</span>}
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export function ProfilTab() {
  const {
    watchlist, setWatchlist, updateWatchlistStatus,
    notes, seen, rejected,
  } = useStore()

  const [showCriteres, setShowCriteres] = useState(false)
  const [activeGroup, setActiveGroup] = useState<WatchlistStatus | 'all'>('all')

  const groups = useMemo(() => {
    const byStatus: Record<WatchlistStatus, Array<{ id: string; entry: WatchlistEntry }>> = {
      a_visiter: [], visite: [], offre: [], refuse: [],
    }
    Object.entries(watchlist).forEach(([id, e]) => byStatus[e.status].push({ id, entry: e }))
    Object.values(byStatus).forEach((arr) =>
      arr.sort((a, b) => b.entry.addedAt.localeCompare(a.entry.addedAt))
    )
    return byStatus
  }, [watchlist])

  const allWatchlist = useMemo(() =>
    [...groups.a_visiter, ...groups.visite, ...groups.offre, ...groups.refuse],
    [groups]
  )

  const displayedItems = activeGroup === 'all' ? allWatchlist : groups[activeGroup]

  const noteItems = useMemo(() => {
    return Object.entries(notes)
      .filter(([, n]) => n && n.trim())
      .map(([key, note]) => {
        if (watchlist[key]) {
          const e = watchlist[key]
          return { key, note, title: e.title, neighbourhood: e.neighbourhood, url: e.url }
        }
        const apt = APPARTS.find((r) => r.id === key)
        if (apt) return { key, note, title: apt.title, neighbourhood: apt.neighbourhood, url: apt.url }
        const m = MAISONS.find((m) => `m_${m.id}` === key)
        if (m) return { key, note, title: m.titre ?? m.adresse_raw, neighbourhood: m.neighbourhood, url: m.url }
        return { key, note, title: key, neighbourhood: '', url: null }
      })
  }, [notes, watchlist])

  const stats = useMemo(() => ({
    totalSeen:      Object.values(seen).filter(Boolean).length,
    totalRejected:  Object.values(rejected).filter(Boolean).length,
    totalWatchlist: Object.keys(watchlist).length,
    totalNotes:     Object.values(notes).filter((n) => n?.trim()).length,
    totalApparts:   APPARTS.length,
    totalMaisons:   MAISONS.length,
  }), [seen, rejected, watchlist, notes])

  function exportCSV() {
    const rows = [
      ['Statut', 'Type', 'Titre', 'Quartier', 'Prix', 'Surface', 'Score', 'Note', 'URL', 'Ajouté le'],
      ...allWatchlist.map(({ id, entry }) => [
        STATUS_META[entry.status].label,
        entry.type === 'appart' ? 'Appartement' : 'Maison',
        entry.title,
        entry.neighbourhood,
        String(entry.price),
        String(entry.surface),
        entry.score != null ? String(entry.score) : '',
        notes[id] ?? '',
        entry.url ?? '',
        new Date(entry.addedAt).toLocaleDateString('fr-FR'),
      ])
    ]
    const csv = rows.map((r) => r.map((c) => `"${String(c).replace(/"/g, '""')}"`).join(',')).join('\n')
    const a = document.createElement('a')
    a.href = 'data:text/csv;charset=utf-8,' + encodeURIComponent(csv)
    a.download = `alpestate-watchlist-${new Date().toISOString().slice(0, 10)}.csv`
    a.click()
  }

  return (
    <>
      {showCriteres && <CriteresModal onClose={() => setShowCriteres(false)} />}

      <div className="overflow-auto h-full">
        <div className="insight-page">

          {/* ── Header ── */}
          <div className="profil-header">
            <div className="profil-avatar"><User size={22} /></div>
            <div className="profil-header-info">
              <div className="profil-name">Lucas Mugnier</div>
              <div className="profil-sub">Investisseur · Chamonix / Argentière</div>
            </div>
            <div className="profil-header-stats">
              <div className="profil-stat-chip"><Bookmark size={10} />{stats.totalWatchlist} suivis</div>
              <div className="profil-stat-chip"><StickyNote size={10} />{stats.totalNotes} notes</div>
              <div className="profil-stat-chip"><BarChart2 size={10} />{stats.totalApparts + stats.totalMaisons} annonces</div>
            </div>
          </div>

          {/* ── Critères ── */}
          <div className="insight-card">
            <SectionHeader icon={<Target size={14} />} title="Critères d'investissement" />
            <CriteriaSummary onOpen={() => setShowCriteres(true)} />
          </div>

          {/* ── Watchlist ── */}
          <div className="insight-card">
            <div className="profil-wl-header">
              <SectionHeader icon={<Bookmark size={14} />} title="Suivi des biens" count={allWatchlist.length} />
              {allWatchlist.length > 0 && (
                <button className="profil-export-btn" onClick={exportCSV}>
                  <FileDown size={12} /> Export CSV
                </button>
              )}
            </div>
            <div className="profil-wl-tabs">
              <button className={`profil-wl-tab${activeGroup === 'all' ? ' active' : ''}`} onClick={() => setActiveGroup('all')}>
                Tous <span className="profil-wl-tab-count">{allWatchlist.length}</span>
              </button>
              {STATUS_ORDER.map((s) => {
                const m = STATUS_META[s]; const n = groups[s].length
                return (
                  <button key={s}
                    className={`profil-wl-tab${activeGroup === s ? ' active' : ''}`}
                    style={activeGroup === s ? { color: m.color, borderBottomColor: m.color } : undefined}
                    onClick={() => setActiveGroup(s)}
                  >
                    {m.label} {n > 0 && <span className="profil-wl-tab-count">{n}</span>}
                  </button>
                )
              })}
            </div>
            {displayedItems.length === 0 ? (
              <div className="profil-wl-empty">
                {allWatchlist.length === 0
                  ? 'Aucun bien suivi — clique sur l\'icône signet sur une annonce pour commencer'
                  : 'Aucun bien dans cette catégorie'
                }
              </div>
            ) : (
              <div className="profil-wl-grid">
                {displayedItems.map(({ id, entry }) => (
                  <WatchCard
                    key={id} id={id} entry={entry} note={notes[id]}
                    onStatus={(s) => updateWatchlistStatus(id, s)}
                    onRemove={() => setWatchlist(id, null)}
                  />
                ))}
              </div>
            )}
          </div>

          {/* ── Notes ── */}
          {noteItems.length > 0 && (
            <div className="insight-card">
              <SectionHeader icon={<StickyNote size={14} />} title="Mes notes" count={noteItems.length} />
              <div className="profil-notes-list">
                {noteItems.map(({ key, note, title, neighbourhood, url }) => (
                  <div key={key} className="profil-note-row">
                    <div className="profil-note-meta">
                      <span className="profil-note-title">{title}</span>
                      {neighbourhood && <span className="profil-note-hood"><MapPin size={8} />{neighbourhood}</span>}
                      {url && (
                        <a href={url} target="_blank" rel="noopener noreferrer" className="profil-note-link">
                          <ExternalLink size={9} />
                        </a>
                      )}
                    </div>
                    <div className="profil-note-text">{note}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* ── Stats ── */}
          <div className="insight-card">
            <SectionHeader icon={<BarChart2 size={14} />} title="Statistiques de recherche" />
            <div className="profil-stats-grid">
              <div className="profil-stats-item">
                <div className="profil-stats-val">{stats.totalApparts + stats.totalMaisons}</div>
                <div className="profil-stats-label">Annonces actives</div>
              </div>
              <div className="profil-stats-item">
                <div className="profil-stats-val" style={{ color: 'var(--text-faint)' }}>{stats.totalSeen}</div>
                <div className="profil-stats-label">Biens vus</div>
              </div>
              <div className="profil-stats-item">
                <div className="profil-stats-val" style={{ color: 'var(--red)' }}>{stats.totalRejected}</div>
                <div className="profil-stats-label">Rejetés</div>
              </div>
              <div className="profil-stats-item">
                <div className="profil-stats-val" style={{ color: 'var(--accent)' }}>{stats.totalWatchlist}</div>
                <div className="profil-stats-label">En watchlist</div>
              </div>
              <div className="profil-stats-item">
                <div className="profil-stats-val" style={{ color: 'var(--green)' }}>{groups.offre.length}</div>
                <div className="profil-stats-label">Offres faites</div>
              </div>
              <div className="profil-stats-item">
                <div className="profil-stats-val">{stats.totalNotes}</div>
                <div className="profil-stats-label">Notes</div>
              </div>
            </div>
          </div>

        </div>
      </div>
    </>
  )
}
