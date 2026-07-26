import { useMemo, useState } from 'react'
import {
  ExternalLink, X, ArrowLeftRight, Building2, Home,
  TrendingDown, Check, Calculator, ChevronDown, SlidersHorizontal,
} from 'lucide-react'
import { useStore } from '@/store/useStore'
import { APPARTS, MAISONS } from '@/lib/data'
import { eur, pm2, num, cn, daysAgo } from '@/lib/utils'
import type { InvestStrategie } from '@/types'
import { ScoreBadge } from '@/components/shared/ScoreBadge'
import { AVMBadge } from '@/components/shared/AVMBadge'

// ── Data lookup ───────────────────────────────────────────────────────────────

interface CmpRow {
  key: string; type: 'appart' | 'maison'
  title: string; url: string | null
  price: number; surface: number
  surface_carrez: number | null; surf_terrain: number | null
  rooms: number; neighbourhood: string
  score: number | null; avm_pred: number | null; avm_ratio: number | null
  yield: number | null; dpe: string | null
  photos: string[]; first_seen: string
  price_drop: number | null; nb_baisses: number; needs_renovation: boolean
}

function buildMap(): Map<string, CmpRow> {
  const m = new Map<string, CmpRow>()
  for (const r of APPARTS) {
    m.set(r.id, {
      key: r.id, type: 'appart', title: r.title, url: r.url,
      price: r.price, surface: r.surface, surface_carrez: r.surface_carrez ?? null,
      surf_terrain: null, rooms: r.rooms, neighbourhood: r.neighbourhood,
      score: r.score, avm_pred: r.avm_pred, avm_ratio: r.avm_ratio,
      yield: r.yield ?? null, dpe: r.dpe ?? null, photos: r.photos ?? [],
      first_seen: r.first_seen, price_drop: r.price_drop ?? null,
      nb_baisses: r.nb_baisses ?? 0, needs_renovation: false,
    })
  }
  for (const r of MAISONS) {
    m.set(`m_${r.id}`, {
      key: `m_${r.id}`, type: 'maison', title: r.titre ?? r.adresse_raw, url: r.url,
      price: r.prix, surface: r.surface, surface_carrez: null,
      surf_terrain: r.surf_terrain ?? null, rooms: r.pieces, neighbourhood: r.neighbourhood,
      score: r.avm_score, avm_pred: r.avm_pred, avm_ratio: r.avm_ratio,
      yield: r.yield ?? null, dpe: null, photos: r.photos ?? [],
      first_seen: r.first_seen, price_drop: null,
      nb_baisses: r.nb_baisses ?? 0, needs_renovation: r.needs_renovation ?? false,
    })
  }
  return m
}
const DATA_MAP = buildMap()

// ── Strategies ────────────────────────────────────────────────────────────────

const STRATEGIES: { id: InvestStrategie; label: string; desc: string }[] = [
  { id: 'mixte',       label: 'Mixte',              desc: 'Équilibre rendement / valorisation' },
  { id: 'locatif',     label: 'Locatif',            desc: 'Rendement locatif maximal'          },
  { id: 'patrimonial', label: 'Patrimonial',        desc: 'Valorisation long terme'            },
  { id: 'rp',          label: 'Rés. principale',    desc: 'Confort et cadre de vie'            },
  { id: 'potentiel',   label: 'Potentiel',          desc: 'Décote et travaux'                  },
]

const DPE_SCORE: Record<string, number> = { A:100, B:85, C:68, D:50, E:30, F:12, G:0 }

function strategyScore(b: CmpRow, strat: InvestStrategie, adjRatio: number | null, effYield?: number | null): number {
  const ratio    = adjRatio ?? b.avm_ratio ?? 1
  const yVal     = effYield !== undefined ? effYield : b.yield
  const ys       = yVal != null ? Math.min(100, (yVal / 9) * 100) : 35
  const bs       = b.score   ?? 40
  const rs       = Math.min(100, Math.max(0, (ratio - 0.6) / 0.8 * 100))
  const ds       = b.dpe && DPE_SCORE[b.dpe] != null ? DPE_SCORE[b.dpe] : 50
  const ss       = Math.min(100, (b.surface / 140) * 100)
  const reno     = b.needs_renovation ? 20 : 0
  switch (strat) {
    case 'locatif':     return Math.round(ys * 0.55 + bs * 0.18 + rs * 0.22 + ds * 0.05)
    case 'patrimonial': return Math.round(bs * 0.50 + rs * 0.30 + ys * 0.10 + ds * 0.10)
    case 'rp':          return Math.round(bs * 0.30 + rs * 0.18 + ds * 0.28 + ys * 0.04 + ss * 0.20)
    case 'potentiel':   return Math.round(rs * 0.50 + reno + bs * 0.12 + ys * 0.08)
    default:            return Math.round(ys * 0.33 + bs * 0.34 + rs * 0.23 + ds * 0.10)
  }
}

// ── Affinage ──────────────────────────────────────────────────────────────────

interface AfinageState { travaux: number; vue: number; exterieur: number }
const DEFAULT_AFI: AfinageState = { travaux: 0, vue: 0, exterieur: 0 }

const TRAVAUX_ADJ = [0, -0.06, -0.14, -0.24]
const VUE_ADJ     = [0,  0.05,  0.12]
const EXT_ADJ     = [0,  0.03,  0.07]

function afinageFactor(a: AfinageState): number {
  return 1 + TRAVAUX_ADJ[a.travaux] + VUE_ADJ[a.vue] + EXT_ADJ[a.exterieur]
}
function adjustedRatio(b: CmpRow, a: AfinageState): number | null {
  if (b.avm_pred == null) return b.avm_ratio
  return (b.avm_pred * afinageFactor(a)) / b.price
}
function adjustedPred(b: CmpRow, a: AfinageState): number | null {
  if (b.avm_pred == null) return null
  return b.avm_pred * afinageFactor(a)
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function bestIdx(vals: (number | null)[], dir: 'min' | 'max'): number | null {
  const valid = vals.map((v, i) => ({ v, i })).filter((x) => x.v != null) as { v: number; i: number }[]
  if (valid.length < 2) return null
  return dir === 'min'
    ? valid.reduce((a, b) => (a.v <= b.v ? a : b)).i
    : valid.reduce((a, b) => (a.v >= b.v ? a : b)).i
}

function DpeBadge({ dpe }: { dpe: string | null }) {
  if (!dpe || dpe === 'N/C') return <span style={{ color: 'var(--text-faint)' }}>—</span>
  const color = dpe <= 'B' ? 'var(--green)' : dpe <= 'D' ? 'var(--blue)' : dpe === 'E' ? 'var(--amber)' : 'var(--red)'
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      width: 26, height: 26, borderRadius: 7, border: `1.5px solid ${color}`, color,
      fontSize: '0.7rem', fontWeight: 700, fontFamily: 'var(--font-mono)',
    }}>{dpe}</span>
  )
}

// ── Yield segmented gauge — gradient rouge→vert ───────────────────────────────

const SEGS = 8
const YIELD_MAX = 9
const SEG_COLORS = [
  'oklch(0.56 0.195 27)',
  'oklch(0.60 0.185 38)',
  'oklch(0.64 0.17 52)',
  'oklch(0.68 0.155 70)',
  'oklch(0.65 0.14 100)',
  'oklch(0.60 0.150 125)',
  'oklch(0.54 0.155 140)',
  'oklch(0.52 0.155 152)',
]

function YieldSegGauge({ value }: { value: number | null }) {
  if (value == null) {
    return (
      <div className="ysg-wrap">
        <div className="ysg-track">{Array.from({ length: SEGS }).map((_, i) => <div key={i} className="ysg-seg" />)}</div>
        <div className="ysg-scale"><span>0 %</span><span>4.5 %</span><span>{YIELD_MAX} %</span></div>
      </div>
    )
  }
  const filled = Math.max(0, Math.min(SEGS, Math.round((value / YIELD_MAX) * SEGS)))
  // Color derived from segment position so text always matches gauge visual
  const overallColor = filled > 0 ? SEG_COLORS[Math.min(filled - 1, SEGS - 1)] : 'var(--red)'
  const label = value >= 7 ? 'Excellent' : value >= 5 ? 'Bon' : value >= 3.5 ? 'Correct' : value >= 2 ? 'Moyen' : 'Faible'
  return (
    <div className="ysg-wrap">
      <div className="ysg-header">
        <span className="ysg-val" style={{ color: overallColor }}>{value.toFixed(1)}<span className="ysg-unit">%</span></span>
        <span className="ysg-label-tag" style={{ color: overallColor }}>{label}</span>
      </div>
      <div className="ysg-track">
        {Array.from({ length: SEGS }).map((_, i) => (
          <div key={i} className="ysg-seg" style={i < filled ? { background: SEG_COLORS[i] } : undefined} />
        ))}
      </div>
      <div className="ysg-scale"><span>0 %</span><span>4.5 %</span><span>{YIELD_MAX} %</span></div>
    </div>
  )
}

// ── Strategy score gauge ──────────────────────────────────────────────────────

function StratScoreBar({ score, isBest }: { score: number; isBest: boolean }) {
  const color = score >= 70 ? 'var(--green)' : score >= 50 ? 'var(--blue)' : score >= 35 ? 'var(--amber)' : 'var(--red)'
  return (
    <div className="strat-score-wrap">
      <div className="strat-score-top">
        <span className="strat-score-val" style={{ color }}>{score}</span>
        <span className="strat-score-denom">/100</span>
        {isBest && <span className="strat-score-best">Meilleur</span>}
      </div>
      <div className="strat-score-track">
        <div className="strat-score-fill" style={{ width: `${score}%`, background: color }} />
      </div>
    </div>
  )
}


// ── Quick simulation ──────────────────────────────────────────────────────────

type SimMode = 'lmnp_reel' | 'lmnp_micro' | 'ir_nu' | 'sci_is'
const SIM_MODES: { id: SimMode; label: string }[] = [
  { id: 'lmnp_reel',  label: 'LMNP Réel'     },
  { id: 'lmnp_micro', label: 'LMNP Micro 50%' },
  { id: 'ir_nu',      label: 'IR Nu'          },
  { id: 'sci_is',     label: 'SCI IS'         },
]

function quickCashflow(prix: number, apport: number, loyer: number, duree: number, mode: SimMode, tmi: number, taux: number, chargesAn: number): { mens: number; net: number } {
  const emprunt = Math.max(0, prix - apport)
  const r = (taux / 100) / 12, n = duree * 12
  const mens = r > 0 && emprunt > 0 ? emprunt * r / (1 - Math.pow(1 + r, -n)) : emprunt > 0 ? emprunt / n : 0
  const loyerAn = loyer * 12
  const interets = emprunt * (taux / 100) * 0.9, amort = prix * 0.85 / 25
  const tTotal = tmi / 100 + 0.172
  let impotMois = 0
  if      (mode === 'lmnp_reel')  impotMois = Math.max(0, loyerAn - chargesAn - interets - amort) * tTotal / 12
  else if (mode === 'lmnp_micro') impotMois = loyerAn * 0.5 * tTotal / 12
  else if (mode === 'ir_nu')      impotMois = Math.max(0, loyerAn - chargesAn - interets) * tTotal / 12
  else { const b = Math.max(0, loyerAn - chargesAn - interets - amort); impotMois = (b <= 42500 ? b * 0.15 : 42500 * 0.15 + (b - 42500) * 0.25) / 12 }
  return { mens: Math.round(mens), net: Math.round(loyer - mens - chargesAn / 12 - impotMois) }
}

// ── Editable number cell ──────────────────────────────────────────────────────

function EditableNumCell({ value, display, isBest, onChange }: {
  value: number; display: string; isBest?: boolean; onChange: (v: number) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft]     = useState('')
  if (editing) {
    return (
      <div className="cmp-cell">
        <input className="cmp-edit-input" type="number" value={draft} autoFocus
          onChange={(e) => setDraft(e.target.value)}
          onBlur={() => { const v = parseFloat(draft); if (!isNaN(v) && v > 0) onChange(v); setEditing(false) }}
          onKeyDown={(e) => { if (e.key === 'Enter') e.currentTarget.blur(); if (e.key === 'Escape') setEditing(false) }} />
      </div>
    )
  }
  return (
    <div className={cn('cmp-cell cmp-cell-editable', isBest && 'cmp-best')}
      onClick={() => { setDraft(String(value)); setEditing(true) }}>
      <div className="cmp-val">{display}</div>
      <div className="cmp-edit-hint">✎ modifier</div>
    </div>
  )
}

// ── État select ───────────────────────────────────────────────────────────────

const ETAT_OPTIONS = ['Neuf', 'Très bon', 'Bon état', 'À rafraîchir', 'Travaux légers', 'Rénovation complète']

function EtatSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const color = value === 'Neuf' || value === 'Très bon' ? 'var(--green)'
    : value === 'Bon état' ? 'var(--blue)'
    : value === 'À rafraîchir' ? 'var(--amber)'
    : 'var(--red)'
  return (
    <div className="cmp-cell">
      <select className="cmp-etat-select" value={value} onChange={(e) => onChange(e.target.value)}
        style={{ color }}>
        {ETAT_OPTIONS.map((o) => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  )
}

// ── Affinage panel ────────────────────────────────────────────────────────────

function ChoicePills({ label, options, value, onChange }: {
  label: string; options: string[]; value: number; onChange: (v: number) => void
}) {
  return (
    <div className="afi-group">
      <div className="afi-group-label">{label}</div>
      <div className="afi-pills">
        {options.map((o, i) => (
          <button key={i} className={cn('afi-pill', value === i && 'active')} onClick={() => onChange(i)}>{o}</button>
        ))}
      </div>
    </div>
  )
}

function AfinagePanel({ b, state, onChange }: {
  b: CmpRow; state: AfinageState; onChange: (s: AfinageState) => void
}) {
  const factor  = afinageFactor(state)
  const adjPred = adjustedPred(b, state)
  const adjRatio = adjustedRatio(b, state)
  const factorPct = Math.round((factor - 1) * 100)
  const factorStr = factorPct === 0 ? 'Aucun ajustement' : factorPct > 0 ? `+${factorPct}%` : `${factorPct}%`
  const factorColor = factorPct > 0 ? 'var(--green)' : factorPct < 0 ? 'var(--red)' : 'var(--text-faint)'

  return (
    <div className="afi-panel">
      <div className="afi-panel-title"><SlidersHorizontal size={12} /> Affiner l'AVM</div>
      <ChoicePills label="Travaux" options={['Aucun', 'Légers −6%', 'Moyens −14%', 'Lourds −24%']}
        value={state.travaux} onChange={(v) => onChange({ ...state, travaux: v })} />
      <ChoicePills label="Vue" options={['Standard', 'Belle +5%', 'Exception. +12%']}
        value={state.vue} onChange={(v) => onChange({ ...state, vue: v })} />
      <ChoicePills label="Extérieur" options={['Aucun', 'Balcon +3%', 'Terrasse +7%']}
        value={state.exterieur} onChange={(v) => onChange({ ...state, exterieur: v })} />
      <div className="afi-result">
        <span className="afi-result-adj" style={{ color: factorColor }}>{factorStr}</span>
        {adjPred != null && (
          <span className="afi-result-val">
            AVM ajusté : <strong>{eur(adjPred)}</strong>
            {adjRatio != null && <span style={{ color: adjRatio >= 1.05 ? 'var(--green)' : adjRatio >= 0.95 ? 'var(--blue)' : 'var(--red)' }}> ×{adjRatio.toFixed(2)}</span>}
          </span>
        )}
      </div>
    </div>
  )
}

// ── Investment profile ────────────────────────────────────────────────────────

type InvestType = 'locatif' | 'patrimonial' | 'potentiel' | 'equilibre'
interface InvestProfile { type: InvestType; label: string; color: string; accent: string; points: string[]; desc: string }

function classifyBien(row: CmpRow): InvestProfile {
  const y = row.yield ?? 0, s = row.score ?? 0, r = row.avm_ratio ?? 1
  if (y >= 6) return { type: 'locatif', label: 'Locatif', color: 'var(--green)', accent: 'oklch(0.52 0.155 152 / 0.1)',
    points: [`Rendement brut ${y.toFixed(1)} %`, row.type === 'appart' ? 'Structure LMNP Réel pertinente' : 'Location saisonnière possible', 'Priorité cashflow sur plus-value'],
    desc: 'Ce bien génère des revenus immédiats significatifs. L\'objectif premier est le flux locatif net, la plus-value est secondaire.' }
  if (s >= 65 && y < 5.5) return { type: 'patrimonial', label: 'Patrimonial', color: 'var(--accent)', accent: 'oklch(0.72 0.095 72 / 0.1)',
    points: [`Score ALPESTATE ${s} / 100`, 'Foncier en zone à rareté forte', 'Valorisation sur 10–15 ans'],
    desc: 'Pari sur l\'appréciation du foncier dans une zone contrainte. Le rendement est secondaire — le capital est l\'actif principal.' }
  if (row.needs_renovation || r >= 1.15) return { type: 'potentiel', label: 'Potentiel', color: 'var(--violet)', accent: 'oklch(0.52 0.18 300 / 0.1)',
    points: [row.needs_renovation ? 'Travaux à prévoir — décote intégrée' : `Décote AVM × ${r.toFixed(2)}`, 'Plus-value à la rénovation ou renégociation', 'Profil pour investisseur actif'],
    desc: 'Stratégie value-add. La valeur se crée par l\'action (travaux, renégociation) et non par le marché seul.' }
  return { type: 'equilibre', label: 'Équilibré', color: 'var(--blue)', accent: 'oklch(0.54 0.175 234 / 0.1)',
    points: [y > 0 ? `Rendement ${y.toFixed(1)} % — correct` : 'Rendement non estimé', s > 0 ? `Score ${s} / 100` : 'Emplacement solide', 'Revenus + valorisation à parts égales'],
    desc: 'Profil mixte sans excellence particulière. Convient à une stratégie diversifiée ou à un premier investissement.' }
}

function InvestCards({ biens }: { biens: CmpRow[] }) {
  const profiles = biens.map(classifyBien)
  return (
    <div className="cmp-invest-section">
      <div className="cmp-invest-header">
        <span className="cmp-invest-title">Profil naturel du bien</span>
        <span className="cmp-invest-sub">Classification automatique selon rendement, score et état</span>
      </div>
      <div className="cmp-invest-grid" style={{ gridTemplateColumns: `repeat(${biens.length}, 1fr)` }}>
        {biens.map((b, i) => {
          const p = profiles[i]
          return (
            <div key={b.key} className="cmp-invest-card" style={{ background: p.accent, borderColor: p.color + '44' }}>
              <div className="cmp-invest-type" style={{ color: p.color }}>{p.label}</div>
              <div className="cmp-invest-bien-name">{b.title}</div>
              <ul className="cmp-invest-points">
                {p.points.map((pt, j) => (
                  <li key={j}><Check size={10} strokeWidth={3} style={{ color: p.color, flexShrink: 0 }} />{pt}</li>
                ))}
              </ul>
              <p className="cmp-invest-desc">{p.desc}</p>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Cell components ───────────────────────────────────────────────────────────

function Cell({ value, sub, isBest = false, color }: { value: React.ReactNode; sub?: string; isBest?: boolean; color?: string }) {
  return (
    <div className={cn('cmp-cell', isBest && 'cmp-best')}>
      <div className="cmp-val" style={color ? { color } : undefined}>{value}</div>
      {sub && <div className="cmp-sub">{sub}</div>}
    </div>
  )
}
function RowLabel({ children }: { children: React.ReactNode }) {
  return <div className="cmp-row-label">{children}</div>
}
function SectionRow({ label, cols, collapsed = false, onToggle }: {
  label: string; cols: number; collapsed?: boolean; onToggle?: () => void
}) {
  return (
    <div className="cmp-section" style={{ gridColumn: `1 / span ${cols + 1}` }}>
      {onToggle && (
        <button className="cmp-section-toggle" onClick={onToggle}>
          <ChevronDown size={11} className={cn('cmp-section-chevron', collapsed && 'rotated')} />
        </button>
      )}
      <span>{label}</span>
    </div>
  )
}

// ── Column header ─────────────────────────────────────────────────────────────

function ColHeader({ row, onRemove, afinOpen, afinState, onToggleAfi, onSetAfi }: {
  row: CmpRow; onRemove: () => void
  afinOpen: boolean; afinState: AfinageState
  onToggleAfi: () => void; onSetAfi: (s: AfinageState) => void
}) {
  const priceDrop = row.price_drop && row.price > 0
    ? Math.round(row.price_drop / (row.price + row.price_drop) * 100) : null
  const hasAfi = afinState.travaux > 0 || afinState.vue > 0 || afinState.exterieur > 0

  return (
    <div className="cmp-col-header">
      <button className="cmp-remove-btn" onClick={onRemove}><X size={11} /></button>
      <div className="cmp-col-photo">
        {row.photos[0] ? <img src={row.photos[0]} alt="" /> : <div className="cmp-col-photo-ph">{row.type === 'appart' ? <Building2 size={22} /> : <Home size={22} />}</div>}
      </div>
      <div className="cmp-col-meta">
        <div className="cmp-col-type-chip">{row.type === 'appart' ? <><Building2 size={10} /> Appartement</> : <><Home size={10} /> Maison</>}</div>
        {priceDrop && <div className="cmp-col-drop"><TrendingDown size={10} /> -{priceDrop}%</div>}
      </div>
      <div className="cmp-col-title">
        {row.url ? <a href={row.url} target="_blank" rel="noopener noreferrer" className="cmp-title-link">{row.title}</a> : row.title}
      </div>
      <div className="cmp-col-location">{row.neighbourhood}</div>
      <div className="cmp-col-score-row">
        <ScoreBadge score={row.score} />
        <div className="cmp-col-actions">
          <button
            className={cn('cmp-afi-btn', afinOpen && 'active', hasAfi && 'has-adj')}
            onClick={onToggleAfi}
            title="Affiner l'AVM"
          >
            <SlidersHorizontal size={11} />
            Affiner
            {hasAfi && <span className="cmp-afi-dot" />}
          </button>
          {row.url && <a href={row.url} target="_blank" rel="noopener noreferrer" className="action-btn"><ExternalLink size={11} /></a>}
        </div>
      </div>
      {afinOpen && (
        <AfinagePanel b={row} state={afinState} onChange={onSetAfi} />
      )}
    </div>
  )
}

// ── Empty state ───────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="cmp-empty">
      <div className="cmp-empty-icon"><ArrowLeftRight size={28} strokeWidth={1.2} /></div>
      <div className="cmp-empty-title">Aucun bien sélectionné</div>
      <p className="cmp-empty-sub">
        Depuis l'onglet <strong>Biens</strong>, cliquez sur <ArrowLeftRight size={12} style={{ display: 'inline', verticalAlign: 'middle' }} /> sur les annonces pour les ajouter ici. Jusqu'à 4 biens.
      </p>
    </div>
  )
}

// ── Main ──────────────────────────────────────────────────────────────────────

export function ComparateurTab() {
  const { compareIds, toggleCompare, investProfile, setActiveTab, setSimPreselect, simParams } = useStore()
  const [strategie, setStrategie]   = useState<InvestStrategie>(investProfile.strategie ?? 'mixte')
  const [affinages, setAffinages]   = useState<Record<string, AfinageState>>({})
  const [afinOpen, setAfinOpen]     = useState<string | null>(null)
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set())
  // Overrides & simulation
  const [simMode, setSimMode]       = useState<SimMode>('lmnp_reel')
  const [simTmi, setSimTmi]         = useState(30)
  const [simApport, setSimApport]   = useState(100_000)
  const [simDuree, setSimDuree]     = useState(20)
  const [prixOverrides, setPrixOverrides]   = useState<Record<string, number>>({})
  const [loyerOverrides, setLoyerOverrides] = useState<Record<string, number>>({})
  const [etatOverrides, setEtatOverrides]   = useState<Record<string, string>>({})

  const toggleSection = (s: string) => setCollapsedSections((prev) => {
    const next = new Set(prev)
    if (next.has(s)) next.delete(s); else next.add(s)
    return next
  })
  const isClosed = (s: string) => collapsedSections.has(s)

  const biens = useMemo(
    () => compareIds.map((k) => DATA_MAP.get(k)).filter(Boolean) as CmpRow[],
    [compareIds]
  )

  const getAfi = (key: string): AfinageState => affinages[key] ?? DEFAULT_AFI
  const setAfi = (key: string, s: AfinageState) => setAffinages((prev) => ({ ...prev, [key]: s }))

  const effectivePrice = (b: CmpRow) => prixOverrides[b.key] ?? b.price
  const effectiveLoyer = (b: CmpRow) => {
    const ep = effectivePrice(b)
    return loyerOverrides[b.key] ?? (b.yield != null ? Math.round(ep * b.yield / 100 / 12) : 1500)
  }
  const effectiveYield = (b: CmpRow): number | null => {
    if (loyerOverrides[b.key] != null || prixOverrides[b.key] != null) {
      return (effectiveLoyer(b) * 12 / effectivePrice(b)) * 100
    }
    return b.yield
  }
  const effectiveEtat = (b: CmpRow) => etatOverrides[b.key] ?? (b.needs_renovation ? 'Travaux légers' : 'Bon état')

  const adjRatios = useMemo(
    () => Object.fromEntries(biens.map((b) => {
      const afi = getAfi(b.key)
      const ep = prixOverrides[b.key] ?? b.price
      if (b.avm_pred == null) return [b.key, b.avm_ratio]
      return [b.key, (b.avm_pred * afinageFactor(afi)) / ep]
    })),
    [biens, affinages, prixOverrides]
  )
  const adjPreds = useMemo(
    () => Object.fromEntries(biens.map((b) => [b.key, adjustedPred(b, getAfi(b.key))])),
    [biens, affinages]
  )

  if (biens.length === 0) return <EmptyState />

  const count   = biens.length
  const bPrix   = bestIdx(biens.map((b) => effectivePrice(b)), 'min')
  const bPm2    = bestIdx(biens.map((b) => pm2(effectivePrice(b), b.surface) ?? null), 'min')
  const bSurf   = bestIdx(biens.map((b) => b.surface), 'max')
  const bScore  = bestIdx(biens.map((b) => b.score), 'max')
  const bRatio  = bestIdx(biens.map((b) => adjRatios[b.key] ?? b.avm_ratio), 'max')
  const bYield  = bestIdx(biens.map((b) => effectiveYield(b)), 'max')
  const bAvm    = bestIdx(biens.map((b) => adjRatios[b.key] ?? b.avm_ratio), 'max') // meilleure affaire = ratio le plus haut

  const stratScores = biens.map((b) => strategyScore(b, strategie, adjRatios[b.key] ?? null, effectiveYield(b)))
  const bStrat  = bestIdx(stratScores.map((s) => s), 'max')

  const cashflows = biens.map((b) => quickCashflow(effectivePrice(b), simApport, effectiveLoyer(b), simDuree, simMode, simTmi, simParams.taux, simParams.chargesAn))
  const bCashflow = bestIdx(cashflows.map((c) => c.net), 'max')

  const currentStrat = STRATEGIES.find((s) => s.id === strategie)

  return (
    <div className="cmp-page overflow-auto h-full">
      <div className="cmp-inner">

        {/* Header */}
        <div className="cmp-header">
          <div className="cmp-header-left">
            <h1 className="cmp-title">Comparateur</h1>
            <span className="cmp-subtitle">{count} bien{count > 1 ? 's' : ''} sélectionné{count > 1 ? 's' : ''}</span>
          </div>
          <div className="cmp-header-right">
            <div className="cmp-strat-wrap">
              <span className="cmp-best-dot" />
              <label className="cmp-strat-label">Stratégie</label>
              <div className="cmp-strat-select-wrap">
                <select
                  className="cmp-strat-select"
                  value={strategie}
                  onChange={(e) => setStrategie(e.target.value as InvestStrategie)}
                >
                  {STRATEGIES.map((s) => <option key={s.id} value={s.id}>{s.label} — {s.desc}</option>)}
                </select>
                <ChevronDown size={12} className="cmp-strat-chevron" />
              </div>
            </div>
          </div>
        </div>

        {/* Grid */}
        <div className="cmp-wrap">
          <div className="cmp-grid" style={{ gridTemplateColumns: `148px repeat(${count}, 1fr)` }}>

            {/* Column headers */}
            <div className="cmp-corner" />
            {biens.map((b) => (
              <ColHeader key={b.key} row={b}
                onRemove={() => toggleCompare(b.key)}
                afinOpen={afinOpen === b.key}
                afinState={getAfi(b.key)}
                onToggleAfi={() => setAfinOpen(afinOpen === b.key ? null : b.key)}
                onSetAfi={(s) => setAfi(b.key, s)}
              />
            ))}

            {/* Score stratégie */}
            <SectionRow label={`Score ${currentStrat?.label ?? 'Mixte'}`} cols={count}
              collapsed={isClosed('score')} onToggle={() => toggleSection('score')} />
            {!isClosed('score') && <>
              <RowLabel>Score adapté</RowLabel>
              {biens.map((b, i) => (
                <div key={b.key} className={cn('cmp-cell', bStrat === i && 'cmp-best')} style={{ padding: '12px 16px' }}>
                  <StratScoreBar score={stratScores[i]} isBest={bStrat === i} />
                </div>
              ))}
            </>}

            {/* ── Financier ── */}
            <SectionRow label="Financier" cols={count}
              collapsed={isClosed('financier')} onToggle={() => toggleSection('financier')} />
            {!isClosed('financier') && <>
              <RowLabel>Prix total</RowLabel>
              {biens.map((b, i) => (
                <EditableNumCell key={b.key}
                  value={effectivePrice(b)}
                  display={`${eur(effectivePrice(b))}${b.nb_baisses > 0 ? ` · ${b.nb_baisses}↘` : ''}`}
                  isBest={bPrix === i}
                  onChange={(v) => setPrixOverrides((p) => ({ ...p, [b.key]: v }))}
                />
              ))}

              <RowLabel>Prix / m²</RowLabel>
              {biens.map((b, i) => { const v = pm2(effectivePrice(b), b.surface); return <Cell key={b.key} value={v ? `${num(v)} €/m²` : '—'} isBest={bPm2 === i} /> })}

              <RowLabel>AVM (ajusté)</RowLabel>
              {biens.map((b, i) => (
                <Cell key={b.key}
                  value={<AVMBadge pred={adjPreds[b.key] ?? b.avm_pred} ratio={adjRatios[b.key] ?? b.avm_ratio} />}
                  isBest={bAvm === i}
                />
              ))}

              <RowLabel>Loyer estimé</RowLabel>
              {biens.map((b) => (
                <EditableNumCell key={b.key}
                  value={effectiveLoyer(b)}
                  display={`${eur(effectiveLoyer(b), 0)} /mois`}
                  onChange={(v) => setLoyerOverrides((p) => ({ ...p, [b.key]: v }))}
                />
              ))}

              <RowLabel>Rendement brut</RowLabel>
              {biens.map((b, i) => (
                <div key={b.key} className={cn('cmp-cell cmp-cell-gauge', bYield === i && 'cmp-best')}>
                  <YieldSegGauge value={effectiveYield(b)} />
                </div>
              ))}
            </>}

            {/* ── Logement ── */}
            <SectionRow label="Logement" cols={count}
              collapsed={isClosed('logement')} onToggle={() => toggleSection('logement')} />
            {!isClosed('logement') && <>
              <RowLabel>Surface</RowLabel>
              {biens.map((b, i) => <Cell key={b.key} value={`${b.surface_carrez ?? b.surface} m²`} sub={b.surface_carrez ? `Carrez · scoring ${Math.round(b.surface)} m²` : undefined} isBest={bSurf === i} />)}

              <RowLabel>Pièces</RowLabel>
              {biens.map((b) => <Cell key={b.key} value={b.rooms === 1 ? 'Studio' : `${b.rooms} pièces`} />)}

              <RowLabel>Terrain</RowLabel>
              {biens.map((b) => <Cell key={b.key} value={b.surf_terrain ? `${num(b.surf_terrain)} m²` : '—'} />)}

              <RowLabel>DPE</RowLabel>
              {biens.map((b) => <Cell key={b.key} value={<DpeBadge dpe={b.dpe} />} />)}

              <RowLabel>État</RowLabel>
              {biens.map((b) => (
                <EtatSelect key={b.key}
                  value={effectiveEtat(b)}
                  onChange={(v) => setEtatOverrides((p) => ({ ...p, [b.key]: v }))}
                />
              ))}
            </>}

            {/* ── Évaluation ── */}
            <SectionRow label="Évaluation" cols={count}
              collapsed={isClosed('evaluation')} onToggle={() => toggleSection('evaluation')} />
            {!isClosed('evaluation') && <>
              <RowLabel>Score ALPESTATE</RowLabel>
              {biens.map((b, i) => <Cell key={b.key}
                value={b.score != null ? `${b.score} / 100` : '—'} isBest={bScore === i}
                color={b.score != null ? b.score >= 70 ? 'var(--green)' : b.score >= 50 ? 'var(--blue)' : b.score >= 30 ? 'var(--amber)' : 'var(--red)' : undefined} />)}

              <RowLabel>Ratio AVM</RowLabel>
              {biens.map((b, i) => {
                const r = adjRatios[b.key] ?? b.avm_ratio
                return <Cell key={b.key}
                  value={r != null ? `× ${r.toFixed(2)}` : '—'}
                  sub={r != null ? r >= 1.1 ? 'Sous-évalué' : r >= 0.95 ? 'Au marché' : 'Surévalué' : undefined}
                  isBest={bRatio === i}
                  color={r != null ? r >= 1.1 ? 'var(--green)' : r >= 0.95 ? 'var(--blue)' : 'var(--red)' : undefined} />
              })}
            </>}

            {/* ── Infos ── */}
            <SectionRow label="Infos" cols={count}
              collapsed={isClosed('infos')} onToggle={() => toggleSection('infos')} />
            {!isClosed('infos') && <>
              <RowLabel>Quartier</RowLabel>
              {biens.map((b) => <Cell key={b.key} value={b.neighbourhood} />)}

              <RowLabel>En ligne depuis</RowLabel>
              {biens.map((b) => {
                const d = daysAgo(b.first_seen)
                return <Cell key={b.key}
                  value={d === 0 ? "Aujourd'hui" : d === 1 ? 'Hier' : `${d} jours`}
                  color="var(--accent)"
                />
              })}
            </>}

            {/* ── Simulation rapide ── */}
            <SectionRow label="Simulation rapide" cols={count}
              collapsed={isClosed('simulation')} onToggle={() => toggleSection('simulation')} />
            {!isClosed('simulation') && <>
              {/* Paramètres partagés — s'étendent sur toutes les colonnes bien */}
              <RowLabel>Détention</RowLabel>
              <div style={{ gridColumn: `2 / span ${count}` }} className="cmp-shared-cell">
                <select className="cmp-shared-select" value={simMode} onChange={(e) => setSimMode(e.target.value as SimMode)}>
                  {SIM_MODES.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
                </select>
              </div>

              <RowLabel>TMI</RowLabel>
              <div style={{ gridColumn: `2 / span ${count}` }} className="cmp-shared-cell">
                <select className="cmp-shared-select" value={simTmi} onChange={(e) => setSimTmi(+e.target.value)}>
                  {[0, 11, 30, 41, 45].map((t) => <option key={t} value={t}>{t}%</option>)}
                </select>
              </div>

              <RowLabel>Apport</RowLabel>
              <div style={{ gridColumn: `2 / span ${count}` }} className="cmp-shared-cell">
                <div className="cmp-shared-input-wrap">
                  <input type="number" className="cmp-shared-input" value={simApport} step={5000}
                    onChange={(e) => setSimApport(Math.max(0, +e.target.value || 0))} />
                  <span className="cmp-shared-suffix">€</span>
                </div>
              </div>

              <RowLabel>Durée prêt</RowLabel>
              <div style={{ gridColumn: `2 / span ${count}` }} className="cmp-shared-cell">
                <div className="cmp-shared-input-wrap">
                  <input type="number" className="cmp-shared-input" value={simDuree} min={5} max={30} step={1}
                    onChange={(e) => setSimDuree(Math.max(5, Math.min(30, +e.target.value || 20)))} />
                  <span className="cmp-shared-suffix">ans · {simParams.taux} %</span>
                </div>
              </div>

              {/* Résultats par bien */}
              <RowLabel>Mensualité</RowLabel>
              {biens.map((b, i) => (
                <Cell key={b.key} value={`${eur(cashflows[i].mens, 0)} /mois`} color="var(--text-dim)" />
              ))}

              <RowLabel>Cashflow net</RowLabel>
              {biens.map((b, i) => {
                const cf = cashflows[i].net
                return (
                  <Cell key={b.key} isBest={bCashflow === i}
                    value={`${cf >= 0 ? '+' : ''}${eur(cf, 0)} /mois`}
                    sub={`TMI ${simTmi}%`}
                    color={cf >= 0 ? 'var(--green)' : 'var(--red)'}
                  />
                )
              })}
            </>}

            {/* ── Simulation par bien ── */}
            <RowLabel><Calculator size={12} style={{ opacity: 0.4 }} /></RowLabel>
            {biens.map((b) => (
              <div key={b.key} className="cmp-cell cmp-sim-btn-cell">
                <button className="cmp-sim-col-btn" onClick={() => { setSimPreselect(b.key); setActiveTab('analyse') }}>
                  <Calculator size={11} /> Simuler ce bien →
                </button>
              </div>
            ))}

          </div>
        </div>

        <InvestCards biens={biens} />
      </div>

    </div>
  )
}
