import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import {
  X, ExternalLink, ChevronLeft, ChevronRight,
  Building2, Home, TrendingDown, Calendar, Ruler,
  AlertTriangle, Info, MapPin, Flag, CheckCircle, Clock, ArrowLeft,
  GitCompare, Zap, BarChart2,
} from 'lucide-react'
import type { BienRow } from '@/components/tabs/BiensTab'
import type { PriceHistory, Listing, Maison } from '@/types'
import { ScoreBadge } from '@/components/shared/ScoreBadge'
import { YieldGauge } from '@/components/shared/YieldGauge'
import { AppartActions } from '@/components/shared/ActionButtons'
import { CorrectionModal } from '@/components/shared/CorrectionModal'
import { fetchCorrections, FIELD_LABELS, type Correction } from '@/lib/supabase'
import { eur, num, daysAgo, median } from '@/lib/utils'
import { APPARTS, MAISONS } from '@/lib/data'
import { useStore } from '@/store/useStore'
import { buildProjection, computeTRI, findApportOptimal } from '@/lib/simulator'
import type { FiscalMode } from '@/types'

// ── Comps (comparable sales from DVF) ─────────────────────────────────────────

interface Comp {
  d: string       // date YYYY-MM-DD
  c: string       // commune uppercase
  s: string       // section cadastrale
  a: string       // adresse
  v: number       // valeur €
  sf: number      // surface m²
  pm2: number     // prix/m²
  lat?: number
  lon?: number
}

// Lazy-load comps.json only when drawer opens (389KB, ~70KB gzipped)
let compsCache: Comp[] | null = null

async function loadComps(): Promise<Comp[]> {
  if (compsCache) return compsCache
  const m = await import('@/data/comps.json')
  compsCache = m.default as Comp[]
  return compsCache
}

// location display → commune DVF uppercase
const LOCATION_COMMUNE: Record<string, string> = {
  'Chamonix':       'CHAMONIX MONT BLANC',
  'Argentière':     'CHAMONIX MONT BLANC',
  'Les Houches':    'LES HOUCHES',
  'Saint-Gervais':  'SAINT GERVAIS LES BAINS',
  'Sallanches':     'SALLANCHES',
  'Passy':          'PASSY',
  'Servoz':         'SERVOZ',
  'Domancy':        'DOMANCY',
}

// neighbourhood → section cadastrale Chamonix
const NEIGHBOURHOOD_SECTION: Record<string, string> = {
  'Les Praz':        'B',
  'Les Tines':       'B',
  'Le Lavancher':    'B',
  'Argentière':      'A',
  'Le Tour':         'A',
  'Montroc':         'A',
  'Les Bossons':     'E',
  'Les Pélerins':    'E',
  'Les Gaillands':   'G',
  'Chamonix Centre': 'G',
  'Chamonix (secteur non précisé)': 'G',
  'Les Houches':     'C',
}

function findComps(row: BienRow, all: Comp[]): Comp[] {
  const commune = LOCATION_COMMUNE[row._appart_location ?? ''] ?? ''
  const section = NEIGHBOURHOOD_SECTION[row.neighbourhood ?? '']
  const priceMin = row.price * 0.75
  const priceMax = row.price * 1.25
  const surfMin  = row.surface * 0.55
  const surfMax  = row.surface * 1.60

  return all
    .filter(c => {
      if (c.c !== commune) return false
      if (c.v < priceMin || c.v > priceMax) return false
      if (c.sf < surfMin || c.sf > surfMax) return false
      // For Chamonix: also filter by section if known
      if (commune === 'CHAMONIX MONT BLANC' && section && c.s !== section) return false
      return true
    })
    .sort((a, b) => {
      // Sort by price proximity first, then date desc
      const da = Math.abs(a.v - row.price)
      const db = Math.abs(b.v - row.price)
      return da - db
    })
    .slice(0, 6)
}

function ComparableSales({ row }: { row: BienRow }) {
  const [open, setOpen]     = useState(false)
  const [comps, setComps]   = useState<Comp[] | null>(null)
  const [loading, setLoading] = useState(false)
  const mounted = useRef(true)

  useEffect(() => { mounted.current = true; return () => { mounted.current = false } }, [])

  // Reset when row changes
  useEffect(() => { setComps(null); setLoading(false) }, [row._key])

  // Lazy-load only when opened for the first time
  useEffect(() => {
    if (!open || comps !== null) return
    setLoading(true)
    loadComps().then(all => {
      if (!mounted.current) return
      setComps(findComps(row, all))
      setLoading(false)
    })
  }, [open, row._key])  // eslint-disable-line react-hooks/exhaustive-deps

  const listingPm2   = row.surface > 0 ? row.price / row.surface : 0
  const medianDvfPm2 = comps && comps.length > 0 ? median(comps.map(c => c.pm2)) : null
  // spread < 0 = listing cheaper than DVF = good deal
  const spread = medianDvfPm2 ? (listingPm2 - medianDvfPm2) / medianDvfPm2 * 100 : null

  const verdictColor  = spread == null ? 'var(--text-faint)'
    : spread <= -5  ? 'var(--green)'
    : spread <= 10  ? 'var(--amber)'
    : 'var(--red)'
  const verdictLabel  = spread == null ? null
    : spread <= -10 ? 'Sous le marché'
    : spread <= 5   ? 'Dans le marché'
    : 'Au-dessus du marché'

  return (
    <div className="similar-section">
      <button
        className={`similar-toggle${open ? ' open' : ''}`}
        onClick={() => setOpen(o => !o)}
      >
        <MapPin size={11} />
        <span>Ventes comparables DVF 2022–2025</span>
        {spread != null && (
          <span className="comps-quick-verdict" style={{ color: verdictColor }}>
            {spread > 0 ? '+' : ''}{Math.round(spread)}%
          </span>
        )}
        <ChevronRight size={12} className={`similar-toggle-chevron${open ? ' rotated' : ''}`} />
      </button>

      {open && (
        <div className="comps-panel">
          {loading && <div className="comps-loading">Chargement des ventes comparables…</div>}

          {!loading && comps !== null && (
            <>
              {/* Verdict banner */}
              {spread != null && medianDvfPm2 != null && (
                <div className="comps-verdict" style={{ borderColor: verdictColor }}>
                  <div className="comps-verdict-row">
                    <div className="comps-verdict-col">
                      <div className="comps-verdict-val">{Math.round(listingPm2).toLocaleString('fr-FR')}€/m²</div>
                      <div className="comps-verdict-key">Annonce</div>
                    </div>
                    <div className="comps-verdict-arrow" style={{ color: verdictColor }}>
                      {spread > 0 ? '▲' : '▼'}
                    </div>
                    <div className="comps-verdict-col">
                      <div className="comps-verdict-val">{Math.round(medianDvfPm2).toLocaleString('fr-FR')}€/m²</div>
                      <div className="comps-verdict-key">DVF médian</div>
                    </div>
                    <div className="comps-verdict-badge" style={{ background: verdictColor + '22', color: verdictColor, borderColor: verdictColor + '55' }}>
                      {spread > 0 ? '+' : ''}{Math.round(spread)}% · {verdictLabel}
                    </div>
                  </div>
                </div>
              )}

              {comps.length === 0
                ? <div className="comps-empty">Aucune vente comparable trouvée dans le DVF 2022–2025</div>
                : <div className="comps-list">
                    {comps.map((c, i) => {
                      // pct from listing's perspective: negative = listing cheaper = good
                      const pct = listingPm2 > 0 ? (listingPm2 - c.pm2) / c.pm2 * 100 : 0
                      const isGood = pct <= 0
                      const dateLabel = new Date(c.d).toLocaleDateString('fr-FR', { month: 'short', year: 'numeric' })
                      return (
                        <div key={i} className="comp-row">
                          <span className="comp-icon"><MapPin size={10} /></span>
                          <div className="comp-body">
                            <span className="comp-address">{c.a}</span>
                            <span className="comp-meta">{dateLabel} · {Math.round(c.sf)}m² · sect. {c.s}</span>
                          </div>
                          <div className="comp-prices">
                            <span className="comp-total">{eur(c.v)}</span>
                            <span className="comp-pm2" style={{ color: isGood ? 'var(--red)' : 'var(--green)' }}>
                              {Math.round(c.pm2).toLocaleString('fr-FR')}€/m²
                              <span className="comp-pm2-delta">
                                {pct > 0 ? '+' : ''}{Math.round(pct)}%
                              </span>
                            </span>
                          </div>
                        </div>
                      )
                    })}
                  </div>
              }
            </>
          )}
        </div>
      )}
    </div>
  )
}

// ── BienRow converters ────────────────────────────────────────────────────────

function aptToBienRow(r: Listing): BienRow {
  return {
    _type: 'appart', _key: r.id, title: r.title, url: r.url,
    price: r.price, surface: r.surface, rooms: r.rooms,
    neighbourhood: r.neighbourhood, score: r.score,
    avm_pred: r.avm_pred, avm_ratio: r.avm_ratio,
    is_structured: !!r.is_structured, first_seen: r.first_seen,
    photos: r.photos ?? [], surface_carrez: r.surface_carrez,
    charges: r.charges, dpe: r.dpe, days_on_market: r.days_on_market,
    price_history: r.price_history, price_drop: r.price_drop,
    nb_baisses: r.nb_baisses, is_relisted: r.is_relisted,
    relisted_after_days: r.relisted_after_days, avm_model: r.avm_model,
    description: r.description,
    _appart_id: r.id, _appart_surface: r.surface,
    _appart_rooms: r.rooms, _appart_location: r.location,
  }
}

function maisonToBienRow(m: Maison): BienRow {
  return {
    _type: 'maison', _key: `m_${m.id}`, title: m.titre ?? m.adresse_raw,
    url: m.url, price: m.prix, surface: m.surface, rooms: m.pieces,
    neighbourhood: m.neighbourhood, score: m.avm_score,
    avm_pred: m.avm_pred, avm_ratio: m.avm_ratio,
    is_structured: !!m.is_structured, first_seen: m.first_seen,
    photos: m.photos ?? [], surf_terrain: m.surf_terrain,
    needs_renovation: m.needs_renovation, yield: m.yield,
    price_history: m.historique_prix ?? [], description: m.description,
    nb_baisses: m.nb_baisses, avm_model: m.avm_model,
    _maison_id: m.id, _appart_location: m.neighbourhood,
  }
}

// ── Similar active listings ───────────────────────────────────────────────────

function SimilarCard({ item, onClick }: { item: BienRow; onClick: () => void }) {
  const photo = item.photos?.[0]
  const pm2v  = item.surface > 0 ? Math.round(item.price / item.surface) : null
  return (
    <button className="similar-card" onClick={onClick}>
      <div className="similar-card-photo">
        {photo
          ? <img src={photo} alt="" />
          : <div className="similar-card-photo-placeholder">
              {item._type === 'appart' ? <Building2 size={18} /> : <Home size={18} />}
            </div>
        }
        {item.score != null && (
          <span className="similar-card-score" style={{
            background: item.score >= 60 ? 'var(--green)' : item.score >= 40 ? 'var(--amber)' : 'var(--red)',
          }}>
            {item.score}
          </span>
        )}
      </div>
      <div className="similar-card-body">
        <div className="similar-card-hood">{item.neighbourhood}</div>
        <div className="similar-card-price">{Math.round(item.price / 1000)}k€</div>
        <div className="similar-card-meta">
          {item.surface}m²{pm2v ? ` · ${(pm2v / 1000).toFixed(1)}k€/m²` : ''}
        </div>
      </div>
    </button>
  )
}

function SimilarListings({ row, onSelect }: { row: BienRow; onSelect: (r: BienRow) => void }) {
  const [open, setOpen] = useState(false)

  const similar = useMemo<BienRow[]>(() => {
    const priceMin = row.price * 0.70
    const priceMax = row.price * 1.30
    const surfMin  = row.surface * 0.65
    const surfMax  = row.surface * 1.35
    if (row._type === 'appart') {
      return APPARTS
        .filter((r) =>
          r.id !== row._key &&
          r.neighbourhood === row.neighbourhood &&
          r.price >= priceMin && r.price <= priceMax &&
          r.surface >= surfMin && r.surface <= surfMax
        )
        .sort((a, b) => Math.abs(a.price - row.price) - Math.abs(b.price - row.price))
        .slice(0, 8)
        .map(aptToBienRow)
    } else {
      return MAISONS
        .filter((m) =>
          m.id !== row._maison_id &&
          m.neighbourhood === row.neighbourhood &&
          m.prix >= priceMin && m.prix <= priceMax &&
          m.surface >= surfMin && m.surface <= surfMax
        )
        .sort((a, b) => Math.abs(a.prix - row.price) - Math.abs(b.prix - row.price))
        .slice(0, 8)
        .map(maisonToBienRow)
    }
  }, [row._key])

  return (
    <div className="similar-section">
      <button
        className={`similar-toggle${open ? ' open' : ''}`}
        onClick={() => setOpen((o) => !o)}
      >
        <Building2 size={11} />
        <span>Annonces similaires</span>
        {similar.length > 0 && (
          <span className="similar-toggle-count">{similar.length}</span>
        )}
        <ChevronRight size={12} className={`similar-toggle-chevron${open ? ' rotated' : ''}`} />
      </button>

      {open && (
        similar.length === 0
          ? <div className="comps-empty" style={{ marginTop: 8 }}>Aucune annonce similaire active dans ce secteur</div>
          : <div className="similar-carousel">
              {similar.map((item) => (
                <SimilarCard key={item._key} item={item} onClick={() => onSelect(item)} />
              ))}
            </div>
      )}
    </div>
  )
}

// ── Sparkline ─────────────────────────────────────────────────────────────────

function Sparkline({ history, currentPrice }: { history: PriceHistory[]; currentPrice: number }) {
  const raw = [
    ...history.map((h) => ({ date: h.date, price: h.price ?? h.prix ?? 0 })),
    { date: 'z_now', price: currentPrice },
  ]
    .filter((p) => p.price > 0)
    .sort((a, b) => a.date.localeCompare(b.date))

  if (raw.length < 2) return null

  const W = 320, H = 60, PAD = 8
  const prices = raw.map((p) => p.price)
  const min = Math.min(...prices)
  const max = Math.max(...prices)
  const range = max - min || 1

  const cx = (i: number) => PAD + (i / (raw.length - 1)) * (W - PAD * 2)
  const cy = (p: number) => H - PAD - ((p - min) / range) * (H - PAD * 2)
  const polyline = raw.map((p, i) => `${cx(i).toFixed(1)},${cy(p.price).toFixed(1)}`).join(' ')
  const lastX = cx(raw.length - 1)
  const lastY = cy(currentPrice)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} style={{ overflow: 'visible' }}>
      <defs>
        <linearGradient id="spark-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.20" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polygon points={`${PAD},${H} ${polyline} ${lastX},${H}`} fill="url(#spark-grad)" />
      <polyline points={polyline} fill="none" stroke="var(--accent)"
        strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
      <circle cx={lastX} cy={lastY} r="4" fill="var(--accent)" />
      <text x={PAD} y={H} fill="var(--text-faint)" fontSize="9"
        fontFamily="var(--font-mono)" dominantBaseline="auto">
        {Math.round(raw[0].price / 1000)}k€
      </text>
      <text x={lastX} y={H} fill="var(--accent)" fontSize="9"
        fontFamily="var(--font-mono)" textAnchor="end" dominantBaseline="auto">
        {Math.round(currentPrice / 1000)}k€
      </text>
    </svg>
  )
}

// ── DPE badge ─────────────────────────────────────────────────────────────────

const DPE_COLORS: Record<string, string> = {
  A: '#009B3A', B: '#4CAF50', C: '#C8D400', D: '#FAC800',
  E: '#F28700', F: '#E84400', G: '#B00000',
}
function DpeBadge({ dpe }: { dpe: string }) {
  const letter = (dpe || '').toUpperCase().charAt(0)
  const color  = DPE_COLORS[letter] ?? 'var(--text-faint)'
  if (!letter || letter === 'N') return null
  return (
    <span className="drawer-chip" style={{ background: color + '22', borderColor: color + '66', color }}>
      DPE {letter}
    </span>
  )
}

// ── AVM ratio bar ─────────────────────────────────────────────────────────────
// Barème : ≤0.75→95  ≤0.85→80  ≤0.95→65  ≤1.05→50  ≤1.20→30  ≤1.40→15  >1.40→5

const AVM_BANDS = [
  { max: 0.75, label: 'Très sous-côté', color: 'var(--green)',  score: 95 },
  { max: 0.85, label: 'Sous-côté',      color: 'var(--green)',  score: 80 },
  { max: 0.95, label: 'Légèrement sous-côté', color: 'oklch(0.60 0.155 140)', score: 65 },
  { max: 1.05, label: 'Dans le marché', color: 'var(--amber)',  score: 50 },
  { max: 1.20, label: 'Légèrement surévalué', color: 'var(--orange)', score: 30 },
  { max: 1.40, label: 'Surévalué',      color: 'var(--red)',    score: 15 },
  { max: Infinity, label: 'Très surévalué', color: 'var(--red)', score: 5 },
]

const AVM_MODEL_INFO: Record<string, { name: string; detail: string }> = {
  chamonix_apt: {
    name: 'Modèle Chamonix',
    detail: 'Entraîné sur les transactions DVF de la commune. Fiabilité élevée sur la vallée de Chamonix.',
  },
  vallee_apt: {
    name: 'Modèle vallée',
    detail: 'Basé sur les statistiques DVF de la vallée Mont-Blanc. Fiabilité modérée — moins précis hors Chamonix centre.',
  },
}

function AvmExplanation({ ratio, model }: { ratio: number; model?: string | null }) {
  const SCALE_MIN = 0.65, SCALE_MAX = 1.55
  const pct = Math.max(0, Math.min(100, (ratio - SCALE_MIN) / (SCALE_MAX - SCALE_MIN) * 100))

  const band = AVM_BANDS.find((b) => ratio <= b.max) ?? AVM_BANDS[AVM_BANDS.length - 1]
  const modelInfo = model ? AVM_MODEL_INFO[model] : null

  return (
    <div className="avm-explain">
      {/* Gauge bar */}
      <div className="avm-scale">
        <div className="avm-scale-track">
          {/* Zones colorées */}
          <div className="avm-zone" style={{ width: `${(0.75 - SCALE_MIN) / (SCALE_MAX - SCALE_MIN) * 100}%`, background: 'var(--green)', opacity: 0.18 }} />
          <div className="avm-zone" style={{ width: `${(0.10) / (SCALE_MAX - SCALE_MIN) * 100}%`, background: 'var(--green)', opacity: 0.12 }} />
          <div className="avm-zone" style={{ width: `${(0.10) / (SCALE_MAX - SCALE_MIN) * 100}%`, background: 'oklch(0.60 0.155 140)', opacity: 0.15 }} />
          <div className="avm-zone" style={{ width: `${(0.10) / (SCALE_MAX - SCALE_MIN) * 100}%`, background: 'var(--amber)', opacity: 0.18 }} />
          <div className="avm-zone" style={{ width: `${(0.15) / (SCALE_MAX - SCALE_MIN) * 100}%`, background: 'var(--orange)', opacity: 0.18 }} />
          <div className="avm-zone" style={{ flex: 1, background: 'var(--red)', opacity: 0.18 }} />
          {/* Cursor */}
          <div className="avm-cursor" style={{ left: `${pct}%` }}>
            <div className="avm-cursor-line" style={{ background: band.color }} />
            <div className="avm-cursor-dot" style={{ background: band.color }} />
          </div>
        </div>
        <div className="avm-scale-labels">
          <span>Sous-côté</span>
          <span>Marché</span>
          <span>Surévalué</span>
        </div>
      </div>

      {/* Résultat */}
      <div className="avm-result">
        <span className="avm-result-label" style={{ color: band.color }}>{band.label}</span>
        <span className="avm-result-ratio" style={{ color: 'var(--text-dim)' }}>
          ratio {ratio.toFixed(2)} → score {band.score}/100
        </span>
      </div>

      {/* Explication barème */}
      <details className="avm-details">
        <summary>
          <Info size={10} /> Comment est calculé ce score ?
        </summary>
        <div className="avm-details-body">
          <p>Le score AVM compare le prix demandé à la valeur estimée par le modèle :</p>
          <table className="avm-scale-table">
            <tbody>
              {AVM_BANDS.map((b, i) => (
                <tr key={i} className={ratio <= b.max && (i === 0 || ratio > AVM_BANDS[i-1].max) ? 'active' : ''}>
                  <td style={{ color: b.color, fontWeight: 600 }}>
                    {i === 0 ? '≤ 0.75' : i === AVM_BANDS.length - 1 ? '> 1.40' : `≤ ${b.max.toFixed(2)}`}
                  </td>
                  <td>{b.label}</td>
                  <td style={{ color: b.color, fontFamily: 'var(--font-mono)' }}>{b.score} pts</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>

      {/* Modèle utilisé */}
      {modelInfo && (
        <div className="avm-model-info">
          <span className="avm-model-name">{modelInfo.name}</span>
          <span className="avm-model-detail">{modelInfo.detail}</span>
        </div>
      )}
    </div>
  )
}

// ── Score breakdown ───────────────────────────────────────────────────────────

// Reconstitue les facteurs qui ont produit le score côté client
function avmBaseScore(ratio: number): number {
  if (ratio <= 0.75) return 95
  if (ratio <= 0.85) return 80
  if (ratio <= 0.95) return 65
  if (ratio <= 1.05) return 50
  if (ratio <= 1.20) return 30
  if (ratio <= 1.40) return 15
  return 5
}

type FactorKind = 'positive' | 'negative' | 'neutral' | 'signal-pos' | 'signal-neg' | 'signal-neutral'

interface Factor {
  label: string
  value: string
  detail?: string
  kind: FactorKind
  isScore: boolean   // true = fait partie du calcul du score, false = signal investisseur
}

function buildFactors(row: BienRow): Factor[] {
  const factors: Factor[] = []

  // ── Calcul du score ──
  if (row.avm_ratio != null) {
    const base = avmBaseScore(row.avm_ratio)
    const band = AVM_BANDS.find((b) => row.avm_ratio! <= b.max) ?? AVM_BANDS[AVM_BANDS.length - 1]
    factors.push({
      label: 'Prix vs estimation marché',
      value: `${base} pts`,
      detail: `${band.label} — ratio ${row.avm_ratio.toFixed(2)}`,
      kind: row.avm_ratio <= 1.05 ? 'positive' : 'negative',
      isScore: true,
    })
  }

  if (row._type === 'maison') {
    if (row.surface < 80) {
      factors.push({ label: 'Surface < 80m²', value: '−10 pts', detail: 'Atypique pour un chalet alpin', kind: 'negative', isScore: true })
    } else if (row.surface < 100) {
      factors.push({ label: 'Surface < 100m²', value: '−5 pts', detail: 'Légèrement sous la norme chalet', kind: 'negative', isScore: true })
    }
    if (row.needs_renovation) {
      factors.push({ label: 'Travaux détectés', value: '−12 pts', detail: 'Mots-clés rénovation dans l\'annonce', kind: 'negative', isScore: true })
    }
  }

  if (row.surface_carrez != null && row.surface > 0) {
    const ratio = row.surface_carrez / row.surface
    factors.push({
      label: 'Loi Carrez appliquée',
      value: `${Math.round(ratio * 100)}% habitable`,
      detail: `Score calculé sur ${Math.round(row.surface)}m² effectifs (${row.surface_carrez}m² Carrez + non-Carrez × 0.4)`,
      kind: ratio < 0.65 ? 'negative' : 'neutral',
      isScore: true,
    })
  }

  // ── Signaux investisseur (n'affectent pas le score) ──
  if (row.dpe) {
    const letter = row.dpe.toUpperCase().charAt(0)
    if (['A', 'B', 'C'].includes(letter)) {
      factors.push({ label: `DPE ${letter}`, value: 'Bon DPE', detail: 'Charges réduites, pas de contrainte de rénovation énergétique', kind: 'signal-pos', isScore: false })
    } else if (['F', 'G'].includes(letter)) {
      factors.push({ label: `DPE ${letter}`, value: 'Passoire énergétique', detail: 'Réglementation 2025+ : obligation de travaux pour louer', kind: 'signal-neg', isScore: false })
    }
  }

  if (row.yield != null) {
    const kind: FactorKind = row.yield >= 4.5 ? 'signal-pos' : row.yield < 3 ? 'signal-neg' : 'signal-neutral'
    factors.push({
      label: `Rendement ${row.yield.toFixed(1)}%`,
      value: row.yield >= 4.5 ? 'Bon rendement' : row.yield < 3 ? 'Faible rendement' : 'Rendement moyen',
      detail: `Moyenne Chamonix : 4–5% — ${row._type === 'maison' ? 'estimé' : 'calculé'}`,
      kind,
      isScore: false,
    })
  }

  if ((row.nb_baisses ?? 0) > 0) {
    factors.push({
      label: `${row.nb_baisses} baisse${(row.nb_baisses ?? 0) > 1 ? 's' : ''} de prix`,
      value: 'Vendeur motivé',
      detail: row.price_drop ? `−${num(row.price_drop)}€ depuis le départ` : undefined,
      kind: 'signal-pos',
      isScore: false,
    })
  }

  if (row.is_relisted) {
    factors.push({
      label: 'Bien relisté',
      value: 'Signal d\'attention',
      detail: row.relisted_after_days ? `Retiré ${row.relisted_after_days}j puis remis en vente` : 'Retiré puis remis en vente',
      kind: 'signal-neg',
      isScore: false,
    })
  }

  return factors
}

const KIND_STYLE: Record<FactorKind, { color: string; dot: string }> = {
  positive:       { color: 'var(--green)',   dot: 'var(--green)' },
  negative:       { color: 'var(--red)',     dot: 'var(--red)' },
  neutral:        { color: 'var(--text-dim)',dot: 'var(--border-strong)' },
  'signal-pos':   { color: 'var(--green)',   dot: 'var(--green)' },
  'signal-neg':   { color: 'var(--orange)',  dot: 'var(--orange)' },
  'signal-neutral':{ color: 'var(--amber)', dot: 'var(--amber)' },
}

function CollapseSection({ label, note, children }: { label: string; note?: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(false)
  return (
    <div className="score-breakdown-group">
      <button className="score-breakdown-group-label score-breakdown-toggle" onClick={() => setOpen(o => !o)}>
        <span>{label}</span>
        {note && <span className="score-breakdown-group-note">{note}</span>}
        <ChevronRight size={11} style={{ marginLeft: 'auto', flexShrink: 0, transform: open ? 'rotate(90deg)' : 'none', transition: 'transform 0.18s' }} />
      </button>
      {open && children}
    </div>
  )
}

function ScoreBreakdown({ row }: { row: BienRow }) {
  const factors = buildFactors(row)
  const scoreFactors  = factors.filter((f) => f.isScore)
  const signalFactors = factors.filter((f) => !f.isScore)

  return (
    <div className="score-breakdown">
      {scoreFactors.length > 0 && (
        <CollapseSection label="Calcul du score">
          {scoreFactors.map((f, i) => <FactorRow key={i} factor={f} />)}
        </CollapseSection>
      )}
      {signalFactors.length > 0 && (
        <CollapseSection label="Signaux investisseur" note="n'affectent pas le score">
          {signalFactors.map((f, i) => <FactorRow key={i} factor={f} />)}
        </CollapseSection>
      )}
    </div>
  )
}

function FactorRow({ factor: f }: { factor: Factor }) {
  const { color, dot } = KIND_STYLE[f.kind]
  return (
    <div className="score-breakdown-row">
      <span className="score-breakdown-dot" style={{ background: dot }} />
      <div className="score-breakdown-content">
        <span className="score-breakdown-label">{f.label}</span>
        {f.detail && <span className="score-breakdown-detail">{f.detail}</span>}
      </div>
      <span className="score-breakdown-value" style={{ color }}>{f.value}</span>
    </div>
  )
}

// ── Drawer simulation panel ───────────────────────────────────────────────────

const FISCAL_MODES_SIM = [
  { id: 'lmnp_reel'  as FiscalMode, label: 'LMNP Réel' },
  { id: 'lmnp_micro' as FiscalMode, label: 'Micro BIC' },
  { id: 'ir_nu'      as FiscalMode, label: 'IR Nu' },
  { id: 'sci_is'     as FiscalMode, label: 'SCI IS' },
]


function DrawerSim({ row, onOpenFull }: { row: BienRow; onOpenFull: () => void }) {
  const { simParams, setSimParams: sp } = useStore()
  const { taux, duree, apportEur, fraisNotaireP, chargesAn, mode, tmi,
          vacanceP, planRevente, revente, indexLoyer, indexPrix } = simParams

  const derivedLoyer = row.yield
    ? Math.round(row.price * (row.yield / 100) / 12)
    : simParams.loyer
  const [loyer, setLoyer] = useState(derivedLoyer)
  useEffect(() => {
    setLoyer(row.yield ? Math.round(row.price * (row.yield / 100) / 12) : simParams.loyer)
  }, [row.price, row.yield]) // eslint-disable-line react-hooks/exhaustive-deps

  const proj = useMemo(() => buildProjection({
    prix: row.price, apportEur, loyer, chargesAn,
    taux, duree, indexLoyer, indexPrix, tmi,
    dureeRevente: planRevente ? revente : 0,
    mode, fraisNotaireP, vacanceP: vacanceP / 100,
  }), [row.price, apportEur, loyer, chargesAn, taux, duree, indexLoyer, indexPrix,
       tmi, revente, planRevente, mode, fraisNotaireP, vacanceP])

  if (!proj.length) return null
  const yr1        = proj[0]
  const fraisNot   = row.price * fraisNotaireP / 100
  const invest     = apportEur + fraisNot
  const rdtNet     = invest > 0 ? (yr1.loyerAnnuel - yr1.chargesYr - yr1.impot) / invest * 100 : 0
  const cfMois     = yr1.cashflowAn / 12
  const apportPct  = row.price > 0 ? Math.round(apportEur / row.price * 100) : 0
  const cfColor    = cfMois >= 0 ? 'var(--green)' : 'var(--red)'
  const modeLabel  = FISCAL_MODES_SIM.find((m) => m.id === mode)?.label ?? mode

  return (
    <div className="drawer-sim">

      {/* ── Résultat principal ── */}
      <div className="ds-result">
        <div className="ds-result-label">Cashflow net / mois · an 1</div>
        <div className="ds-result-val" style={{ color: cfColor }}>
          {cfMois >= 0 ? '+' : ''}{eur(cfMois, 0)}
        </div>
        <div className="ds-result-breakdown">
          <span>{eur(loyer)} loyer</span>
          <span>− {eur(yr1.mensualite)} mensualité</span>
          <span>− {eur(yr1.chargesYr / 12, 0)} charges</span>
          {yr1.impot > 0 && <span>− {eur(yr1.impot / 12, 0)} impôt ({modeLabel})</span>}
        </div>
        <div className="ds-result-sub">
          Rendement net {rdtNet.toFixed(1)} % · Patrimoine an 10 {proj[9] ? eur(proj[9].patrimoineNet, 0) : '—'}
        </div>
      </div>

      {/* ── Apport (levier principal) ── */}
      <div className="ds-apport-block">
        <div className="ds-apport-header">
          <span className="ds-label">Apport — {apportPct} %</span>
          <span className="ds-apport-eur">{eur(apportEur)}</span>
        </div>
        <input type="range" className="sim-range" min={0} max={Math.round(row.price * 0.5 / 5000) * 5000}
          step={5000} value={apportEur} style={{ accentColor: 'var(--accent)' }}
          onChange={(e) => sp({ apportEur: +e.target.value })} />
        <button className="ds-cf0-btn" onClick={() => {
          const a = findApportOptimal(row.price, fraisNotaireP, loyer, chargesAn, taux, duree, tmi, mode, vacanceP / 100)
          sp({ apportEur: a })
        }}>
          <Zap size={11} /> Apport CF = 0
        </button>
      </div>

      {/* ── Params secondaires en grille compacte ── */}
      <div className="ds-params-grid">
        <div className="ds-param">
          <span className="ds-label">Loyer</span>
          <div className="ds-param-ctrl">
            <input type="number" className="ds-mini-input" value={loyer} step={50} min={0}
              onChange={(e) => setLoyer(Math.max(0, +e.target.value || 0))} />
            <span className="ds-unit">€/mois</span>
          </div>
        </div>
        <div className="ds-param">
          <span className="ds-label">Taux</span>
          <div className="ds-param-ctrl">
            <input type="number" className="ds-mini-input" value={taux} step={0.1} min={0.5} max={7}
              onChange={(e) => sp({ taux: Math.max(0.5, +e.target.value || 0) })} />
            <span className="ds-unit">%</span>
          </div>
        </div>
        <div className="ds-param">
          <span className="ds-label">Durée</span>
          <div className="ds-param-ctrl">
            <input type="number" className="ds-mini-input" value={duree} step={1} min={5} max={30}
              onChange={(e) => sp({ duree: Math.max(5, +e.target.value || 20) })} />
            <span className="ds-unit">ans</span>
          </div>
        </div>
        <div className="ds-param">
          <span className="ds-label">Fiscal</span>
          <select className="ds-select" value={mode} onChange={(e) => sp({ mode: e.target.value as FiscalMode })}>
            {FISCAL_MODES_SIM.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
        </div>
      </div>

      <button className="ds-full-btn" onClick={onOpenFull}>
        <BarChart2 size={13} /> Analyse complète →
      </button>
    </div>
  )
}

// ── Main drawer ───────────────────────────────────────────────────────────────

interface Props {
  row: BienRow | null
  onClose: () => void
}

export function DetailDrawer({ row: baseRow, onClose }: Props) {
  const { setActiveTab, setSimPreselect, toggleCompare, compareIds } = useStore()
  const [photoIdx, setPhotoIdx]             = useState(0)
  const [corrections, setCorrections]       = useState<Correction[]>([])
  const [correctionOpen, setCorrectionOpen] = useState(false)
  const [subRow, setSubRow]                 = useState<BienRow | null>(null)
  const [drawerTab, setDrawerTab]           = useState<'detail' | 'sim'>('detail')

  // Reset sub-navigation + sim tab when outer row changes
  useEffect(() => { setSubRow(null); setDrawerTab('detail') }, [baseRow?._key])

  // The row actually displayed (sub-navigation overrides base)
  const row = subRow ?? baseRow

  useEffect(() => { setPhotoIdx(0) }, [row?._key])

  // Fetch community corrections whenever the drawer opens for a new listing
  useEffect(() => {
    if (!row) { setCorrections([]); return }
    fetchCorrections(row._key).then(setCorrections)
  }, [row?._key])

  const handleKey = useCallback((e: KeyboardEvent) => {
    if (e.key === 'Escape') {
      if (subRow) setSubRow(null)
      else onClose()
    }
  }, [onClose, subRow])
  useEffect(() => {
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [handleKey])

  useEffect(() => {
    document.body.style.overflow = row ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [row])

  const open    = baseRow != null
  const photos  = row?.photos ?? []
  const hasPrev = photoIdx > 0
  const hasNext = photoIdx < photos.length - 1

  const totalDrop = row && row.price_history.length > 0
    ? Math.max(0, (row.price_history[0].price ?? row.price_history[0].prix ?? row.price) - row.price)
    : 0
  const firstSeenAgo = row ? daysAgo(row.first_seen) : 0

  return (
    <>
      <div className={`detail-overlay${open ? ' open' : ''}`} onClick={onClose} aria-hidden="true" />

      <aside className={`detail-drawer${open ? ' open' : ''}`} aria-label="Détail du bien">
        {!row ? null : (
          <>
            {/* ── Header ── */}
            <div className="drawer-header">
              {subRow && (
                <button className="drawer-back-btn" onClick={() => setSubRow(null)} title="Retour">
                  <ArrowLeft size={14} />
                </button>
              )}
              <div className="drawer-header-title">
                <span className="drawer-type-badge" style={{
                  background: 'var(--accent-soft)',
                  borderColor: 'oklch(0.72 0.095 72 / 0.4)',
                  color: 'var(--accent)',
                }}>
                  {row._type === 'appart' ? <Building2 size={10} /> : <Home size={10} />}
                  {row._type === 'appart' ? 'Appartement' : 'Maison'}
                </span>
                <span className="drawer-neighbourhood">{row.neighbourhood}</span>
                {row.is_relisted && (
                  <span className="drawer-relisted-badge" title={
                    row.relisted_after_days
                      ? `Retiré puis remis en vente après ${row.relisted_after_days}j`
                      : 'Bien retiré puis remis en vente'
                  }>
                    <AlertTriangle size={9} /> Relisté
                  </span>
                )}
              </div>
              <button className="drawer-close" onClick={onClose} aria-label="Fermer">
                <X size={16} />
              </button>
            </div>

            {/* ── Tab bar ── */}
            <div className="drawer-tabs">
              <button className={`drawer-tab-btn${drawerTab === 'detail' ? ' active' : ''}`}
                onClick={() => setDrawerTab('detail')}>Détail</button>
              <button className={`drawer-tab-btn${drawerTab === 'sim' ? ' active' : ''}`}
                onClick={() => setDrawerTab('sim')}>Simulation</button>
            </div>

            {drawerTab === 'sim' ? (
              <DrawerSim row={row} onOpenFull={() => {
                setSimPreselect(row._key); setActiveTab('analyse'); onClose()
              }} />
            ) : (<>

            {/* ── Gallery ── */}
            <div className="drawer-gallery">
              {photos.length > 0 ? (
                <>
                  <img key={photoIdx} src={photos[photoIdx]} alt="" className="drawer-gallery-img" />
                  {photos.length > 1 && (
                    <>
                      <button
                        className={`drawer-gallery-btn left${hasPrev ? '' : ' disabled'}`}
                        onClick={() => hasPrev && setPhotoIdx(i => i - 1)}
                        aria-label="Photo précédente"
                      ><ChevronLeft size={18} /></button>
                      <button
                        className={`drawer-gallery-btn right${hasNext ? '' : ' disabled'}`}
                        onClick={() => hasNext && setPhotoIdx(i => i + 1)}
                        aria-label="Photo suivante"
                      ><ChevronRight size={18} /></button>
                      <span className="drawer-gallery-counter">{photoIdx + 1} / {photos.length}</span>
                    </>
                  )}
                </>
              ) : (
                <div className="drawer-gallery-placeholder">
                  {row._type === 'appart' ? <Building2 size={40} /> : <Home size={40} />}
                </div>
              )}
            </div>

            {/* ── Body ── */}
            <div className="drawer-body">

              {/* Title + price */}
              <h2 className="drawer-title">{row.title}</h2>
              <div className="drawer-price-row">
                <span className="drawer-price">{eur(row.price)}</span>
                {row.price_drop != null && row.price_drop > 0 && (
                  <span className="drawer-price-drop">
                    <TrendingDown size={11} />
                    -{eur(row.price_drop)} vs départ
                  </span>
                )}
              </div>

              {/* Chips */}
              <div className="drawer-chips">
                {(row.surface_carrez ?? row.surface) > 0 && (
                  <span className="drawer-chip" title={row.surface_carrez
                    ? `Loi Carrez — surface effective scoring : ${Math.round(row.surface)}m²` : undefined}>
                    <Ruler size={10} />
                    {row.surface_carrez ?? row.surface}m²
                    {row.surface_carrez && <sup style={{ fontSize: '0.55rem', opacity: 0.7 }}>C</sup>}
                  </span>
                )}
                {row.rooms > 0 && (
                  <span className="drawer-chip">
                    {row.rooms === 1 ? 'Studio' : `${row.rooms} pièces`}
                  </span>
                )}
                {(row.surf_terrain ?? 0) > 0 && (
                  <span className="drawer-chip">{num(row.surf_terrain!)}m² terrain</span>
                )}
                {row.dpe && <DpeBadge dpe={row.dpe} />}
                {row.charges != null && row.charges > 0 && (
                  <span className="drawer-chip">{num(row.charges)}€/mois charges</span>
                )}
                {row.needs_renovation && (
                  <span className="drawer-chip" style={{
                    background: 'oklch(0.64 0.17 40 / 0.12)',
                    borderColor: 'oklch(0.64 0.17 40 / 0.35)',
                    color: 'var(--orange)',
                  }}>À rénover</span>
                )}
              </div>

              {/* Description de l'annonce */}
              {row.description && row.description.trim().length > 20 && (
                <div className="drawer-section">
                  <div className="drawer-section-label">Description de l'annonce</div>
                  <p className="drawer-description">{row.description.trim()}</p>
                </div>
              )}

              {/* Community corrections */}
              {corrections.length > 0 && (
                <div className="drawer-section corrections-drawer-section">
                  <div className="drawer-section-label">
                    <Flag size={11} /> Corrections communautaires
                  </div>
                  {corrections.map(c => (
                    <div key={c.id} className={`correction-inline correction-inline--${c.status}`}>
                      <span className="correction-inline-icon">
                        {c.status === 'approved'
                          ? <CheckCircle size={11} />
                          : <Clock size={11} />}
                      </span>
                      <span className="correction-inline-field">{FIELD_LABELS[c.field] ?? c.field}</span>
                      <span className="correction-inline-change">
                        {c.current_value && (
                          <><span className="correction-inline-old">{c.current_value}</span> → </>
                        )}
                        <span className="correction-inline-new">{c.suggested_value}</span>
                      </span>
                      {c.reporter_name && (
                        <span className="correction-inline-by">par {c.reporter_name}</span>
                      )}
                      <span className="correction-inline-status">
                        {c.status === 'approved' ? 'Approuvé' : 'En attente'}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              {/* Score */}
              <div className="drawer-section">
                <div className="drawer-section-label">Score d'opportunité</div>
                <div className="drawer-score-row">
                  <ScoreBadge score={row.score} size="lg" />
                  <div className="drawer-score-meta">
                    <span className="drawer-score-label">
                      {row.score == null ? 'Non calculé' :
                        row.score >= 80 ? 'Excellent deal' :
                        row.score >= 60 ? 'Bon deal' :
                        row.score >= 40 ? 'Deal passable' : 'Deal faible'}
                    </span>
                    <span className="drawer-score-sub">
                      Basé sur le rapport prix / valeur marché estimée
                    </span>
                  </div>
                </div>
                <ScoreBreakdown row={row} />
              </div>

              {/* AVM suspect warning */}
              {row.avm_suspect && (
                <div className="drawer-suspect-banner">
                  <AlertTriangle size={12} />
                  <span>Ratio AVM très bas ({row.avm_ratio != null ? `${Math.round(row.avm_ratio * 100)}%` : 'N/A'}) — vérifier la surface ou le bien avant de conclure</span>
                </div>
              )}

              {/* AVM + explication */}
              {row.avm_pred != null && row.avm_ratio != null && (
                <div className="drawer-section">
                  <div className="drawer-section-label"><Info size={11} /> Estimation AVM</div>
                  <div className="drawer-avm-header">
                    <div className="drawer-avm-values">
                      <div>
                        <div className="drawer-kpi-label">Valeur estimée</div>
                        <div className="drawer-kpi-val">{eur(row.avm_pred)}</div>
                      </div>
                      <div>
                        <div className="drawer-kpi-label">Prix demandé</div>
                        <div className="drawer-kpi-val">{eur(row.price)}</div>
                      </div>
                      <div>
                        <div className="drawer-kpi-label">Écart</div>
                        <div className="drawer-kpi-val" style={{
                          color: row.avm_ratio <= 0.95 ? 'var(--green)' : row.avm_ratio <= 1.10 ? 'var(--amber)' : 'var(--red)',
                        }}>
                          {row.avm_ratio <= 1
                            ? `-${Math.round((1 - row.avm_ratio) * 100)}%`
                            : `+${Math.round((row.avm_ratio - 1) * 100)}%`}
                        </div>
                      </div>
                    </div>
                  </div>
                  <AvmExplanation ratio={row.avm_ratio} model={row.avm_model} />
                </div>
              )}

              {/* Rendement */}
              {row.yield != null && (
                <div className="drawer-section">
                  <div className="drawer-section-label">Rendement locatif brut</div>
                  <div className="drawer-yield-row">
                    <YieldGauge value={row.yield} isEstimate={row._type === 'maison'} />
                    <span className="drawer-yield-label">
                      {row._type === 'maison'
                        ? `Estimé sur base loyer ~${Math.round(row.price * row.yield / 100 / 12)}€/mois`
                        : `Calculé — loyer de marché`}
                    </span>
                  </div>
                </div>
              )}

              {/* Historique des prix */}
              {row.price_history.length >= 2 && (
                <div className="drawer-section">
                  <div className="drawer-section-label">
                    <TrendingDown size={11} /> Historique des prix
                  </div>
                  <Sparkline history={row.price_history} currentPrice={row.price} />
                  {(row.nb_baisses ?? 0) > 0 && (
                    <div className="drawer-price-drop-info">
                      <TrendingDown size={10} />
                      {row.nb_baisses} baisse{(row.nb_baisses ?? 0) > 1 ? 's' : ''} de prix
                      {totalDrop > 0 && ` · -${num(totalDrop)}€ au total`}
                    </div>
                  )}
                </div>
              )}

              {/* Ventes comparables DVF */}
              <div className="drawer-section">
                <ComparableSales row={row} />
              </div>

              {/* Annonces similaires actives */}
              <div className="drawer-section">
                <SimilarListings row={row} onSelect={setSubRow} />
              </div>

              {/* Méta */}
              <div className="drawer-meta">
                <Calendar size={10} />
                <span>En ligne depuis {firstSeenAgo} jour{firstSeenAgo > 1 ? 's' : ''}</span>
                {row.days_on_market != null && row.days_on_market > 0 && (
                  <span>· {row.days_on_market}j sur le marché</span>
                )}
                {row.is_relisted && row.relisted_after_days && (
                  <span style={{ color: 'var(--orange)' }}>
                    · Retiré {row.relisted_after_days}j puis relisté
                  </span>
                )}
              </div>
            </div>

            </>)}

            {/* ── Footer ── */}
            <div className="drawer-footer" onClick={(e) => e.stopPropagation()}>
              <AppartActions
                id={row._key}
                surface={row._appart_surface ?? row.surface}
                rooms={row._appart_rooms ?? row.rooms}
                location={row._appart_location}
                price={row.price}
              />
              <div className="drawer-footer-right">
                <button
                  className={`drawer-action-btn${compareIds.includes(row._key) ? ' active' : ''}`}
                  onClick={() => toggleCompare(row._key)}
                  title={compareIds.includes(row._key) ? 'Retirer du comparateur' : 'Ajouter au comparateur'}
                >
                  <GitCompare size={12} />
                  {compareIds.includes(row._key) ? 'Comparé' : 'Comparer'}
                </button>
                <button
                  className="drawer-correction-btn"
                  onClick={() => setCorrectionOpen(true)}
                  title="Signaler une erreur ou proposer une correction"
                >
                  <Flag size={12} />
                  Une erreur ?
                </button>
                {row.url && (
                  <a href={row.url} target="_blank" rel="noopener noreferrer" className="drawer-link-btn">
                    <ExternalLink size={13} />
                    Voir l'annonce
                  </a>
                )}
              </div>
            </div>
          </>
        )}
      </aside>

      {/* Correction modal — rendered outside the drawer to avoid z-index issues */}
      {correctionOpen && row && (
        <CorrectionModal
          row={row}
          onClose={() => {
            setCorrectionOpen(false)
            // Refresh corrections after submission
            fetchCorrections(row._key).then(setCorrections)
          }}
        />
      )}
    </>
  )
}
