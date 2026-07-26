import { useState, useMemo, useEffect, useCallback } from 'react'
import { eur, cn } from '@/lib/utils'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts'
import { APPARTS, MAISONS } from '@/lib/data'
import { useStore } from '@/store/useStore'
import { Building2, Home, Zap, X } from 'lucide-react'
import type { FiscalMode, SimObjectif, SimParams } from '@/types'
import {
  buildProjection, computeTRI, findApportOptimal,
  type ProjRow,
} from '@/lib/simulator'

// ── Fiscal modes ───────────────────────────────────────────────────────────────

const FISCAL_MODES: { id: FiscalMode; label: string; hint: string }[] = [
  { id: 'lmnp_reel',  label: 'LMNP Réel',  hint: 'Amortissement 25 ans · déduction charges + intérêts' },
  { id: 'lmnp_micro', label: 'Micro BIC',   hint: 'Abattement forfaitaire 50 % sur recettes brutes' },
  { id: 'ir_nu',      label: 'IR Nu',       hint: 'Micro-foncier 30 % (< 15 k€) · ou régime réel' },
  { id: 'sci_is',     label: 'SCI IS',      hint: "IS 15 % jusqu'à 42 500 € · 25 % au-delà" },
]
const TMI_OPTIONS = [0, 11, 30, 41, 45]

const OBJECTIFS: { id: SimObjectif; label: string; hint: string }[] = [
  { id: 'tri',        label: 'TRI',        hint: 'Maximiser le rendement global' },
  { id: 'cashflow',   label: 'Cashflow',   hint: 'Cashflow positif au plus vite' },
  { id: 'patrimoine', label: 'Patrimoine', hint: 'Valeur nette maximale long terme' },
]

// ── Bien catalog ───────────────────────────────────────────────────────────────

interface BienItem {
  id: string; type: 'appart' | 'maison'
  title: string; price: number; surface: number
  rooms: number; neighbourhood: string
  yieldPct: number | null; photo: string | null; url: string | null
}

const ALL_BIENS: BienItem[] = [
  ...APPARTS.filter((r) => r.price && r.surface).map((r): BienItem => ({
    id: r.id, type: 'appart', title: r.title,
    price: r.price, surface: r.surface, rooms: r.rooms,
    neighbourhood: r.neighbourhood, yieldPct: r.yield ?? null,
    photo: r.photos?.[0] ?? null, url: r.url ?? null,
  })),
  ...MAISONS.filter((r) => r.prix && r.surface).map((r): BienItem => ({
    id: `m_${r.id}`, type: 'maison', title: r.titre ?? r.adresse_raw,
    price: r.prix, surface: r.surface, rooms: r.pieces,
    neighbourhood: r.neighbourhood, yieldPct: r.yield ?? null,
    photo: r.photos?.[0] ?? null, url: r.url ?? null,
  })),
]

// ── Projection engine ──────────────────────────────────────────────────────────

// ── Optimiser (local, basé sur le bien simulé) ───────────────────────────────

interface OptimInsight { type: 'success' | 'info' | 'warning'; text: string }

interface OptimResult {
  bestReventeYear: number; bestTri: number
  bestMode: FiscalMode; bestModeLabel: string; bestModeCfBonus: number
  breakEvenCfYear: number | null
  apport0: number
  insights: OptimInsight[]
}

function computeOptim(p: {
  prix: number; fraisNotaireP: number; loyer: number; chargesAn: number
  taux: number; duree: number; tmi: number; mode: FiscalMode
  apportEur: number; objectif: SimObjectif
}): OptimResult {
  const base = { ...p, indexLoyer: 2, indexPrix: 3, dureeRevente: 0 }

  // Meilleure année de revente (TRI max)
  let bestTRI = -Infinity, bestReventeYear = 10
  for (let yr = 1; yr <= 20; yr++) {
    const rows = buildProjection({ ...base, dureeRevente: yr })
    const tri = computeTRI(p.apportEur, p.prix, p.fraisNotaireP, rows, yr)
    if (tri != null && tri > bestTRI) { bestTRI = tri; bestReventeYear = yr }
  }

  // Meilleur régime fiscal (CF an 1 max)
  const currentRows = buildProjection({ ...base, mode: p.mode })
  const currentCF   = currentRows[0].cashflowAn
  let bestMode: FiscalMode = p.mode, bestCF = -Infinity, bestModeLabel = ''
  for (const m of ['lmnp_reel', 'lmnp_micro', 'ir_nu', 'sci_is'] as FiscalMode[]) {
    const rows = buildProjection({ ...base, mode: m })
    if (rows[0].cashflowAn > bestCF) {
      bestCF = rows[0].cashflowAn
      bestMode = m
      bestModeLabel = FISCAL_MODES.find((f) => f.id === m)?.label ?? m
    }
  }
  const bestModeCfBonus = bestCF - currentCF

  // Année cashflow cumulé positif
  const rows20 = buildProjection({ ...base })
  const breakEvenCfYear = rows20.find((r) => r.cashflowCumul >= 0)?.annee ?? null

  // Apport minimum pour CF=0
  const apport0 = findApportOptimal(p.prix, p.fraisNotaireP, p.loyer, p.chargesAn, p.taux, p.duree, p.tmi, p.mode)

  const insights: OptimInsight[] = []

  if (p.objectif === 'tri' || p.objectif === 'patrimoine') {
    insights.push({ type: 'info', text: `Revente optimale : an ${bestReventeYear} → TRI ${bestTRI.toFixed(1)} %` })
  }
  if (p.objectif === 'cashflow') {
    if (currentCF >= 0) {
      insights.push({ type: 'success', text: `Cashflow positif dès l'an 1 : ${eur(currentCF / 12, 0)}/mois` })
    } else {
      insights.push({ type: 'warning', text: `Pour équilibrer : apport minimum ${eur(apport0)}` })
    }
  }
  if (bestMode !== p.mode && bestModeCfBonus > 500) {
    insights.push({ type: 'info', text: `Régime plus avantageux : ${bestModeLabel} (+${eur(bestModeCfBonus, 0)}/an de cashflow)` })
  }
  if (breakEvenCfYear != null) {
    insights.push({
      type: breakEvenCfYear <= 5 ? 'success' : breakEvenCfYear <= 12 ? 'info' : 'warning',
      text: `Cashflow cumulé positif à partir de l'an ${breakEvenCfYear}`,
    })
  } else {
    insights.push({ type: 'warning', text: 'Cashflow cumulé reste négatif sur 20 ans — vérifier les hypothèses' })
  }
  if (apport0 > p.apportEur + 5_000) {
    insights.push({ type: 'warning', text: `Apport actuel insuffisant pour l'équilibre : il faut ${eur(apport0)}` })
  } else if (p.apportEur > apport0 + 20_000) {
    insights.push({ type: 'info', text: `Apport excédentaire · minimum pour équilibrer : ${eur(apport0)}` })
  }

  return { bestReventeYear, bestTri: bestTRI, bestMode, bestModeLabel, bestModeCfBonus, breakEvenCfYear, apport0, insights }
}

// ── Chart tooltip ─────────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }: {
  active?: boolean
  payload?: { name: string; value: number; color: string; dataKey: string }[]
  label?: number
}) {
  if (!active || !payload?.length) return null
  return (
    <div className="sim-tooltip">
      <div className="sim-tooltip-year">Année {label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="sim-tooltip-row">
          <span style={{ color: p.color }}>{p.name}</span>
          <span className="sim-tooltip-val">{eur(p.value)}</span>
        </div>
      ))}
    </div>
  )
}

// ── Top opportunities ─────────────────────────────────────────────────────────

const TOP_BIENS = [...ALL_BIENS]
  .filter((b) => b.yieldPct != null)
  .sort((a, b) => (b.yieldPct ?? 0) - (a.yieldPct ?? 0))
  .slice(0, 10)

// ── Main ───────────────────────────────────────────────────────────────────────

export function SimulationTab() {
  const { simPreselect, setSimPreselect, simParams, setSimParams } = useStore()
  const {
    selectedId, mode, tmi, taux, duree, loyer, chargesAn, apportEur,
    fraisNotaireP, indexLoyer, indexPrix, vacanceP, revente, planRevente, objectif,
  } = simParams
  const sp = useCallback((p: Partial<SimParams>) => setSimParams(p), [setSimParams])

  const [showOptim, setShowOptim] = useState(false)
  const [optim, setOptim]         = useState<OptimResult | null>(null)

  const bien = useMemo(() => {
    const id = selectedId || ALL_BIENS[0]?.id
    return ALL_BIENS.find((b) => b.id === id) ?? ALL_BIENS[0]
  }, [selectedId])

  // Init premier chargement + auto-fill quand le bien change
  useEffect(() => {
    const id = selectedId || ALL_BIENS[0]?.id
    if (!id) return
    const b = ALL_BIENS.find((x) => x.id === id)
    if (!b) return
    sp({
      ...(selectedId ? {} : { selectedId: id }),
      loyer: b.yieldPct
        ? Math.round(b.price * b.yieldPct / 100 / 12)
        : Math.round(b.price * 0.045 / 12),
      apportEur: Math.round(b.price * 0.20 / 5000) * 5000,
    })
  }, [selectedId]) // eslint-disable-line react-hooks/exhaustive-deps

  // Préselection depuis le comparateur
  useEffect(() => {
    if (simPreselect) {
      const found = ALL_BIENS.find((b) => b.id === simPreselect)
      if (found) sp({ selectedId: simPreselect })
      setSimPreselect(null)
    }
  }, [simPreselect]) // eslint-disable-line react-hooks/exhaustive-deps

  const proj = useMemo(() => {
    if (!bien) return []
    return buildProjection({
      prix: bien.price, apportEur, loyer, chargesAn,
      taux, duree, indexLoyer, indexPrix, tmi,
      dureeRevente: planRevente ? revente : 0,
      mode, fraisNotaireP, vacanceP: vacanceP / 100,
    })
  }, [bien, apportEur, loyer, chargesAn, taux, duree, indexLoyer, indexPrix, vacanceP, tmi, revente, planRevente, mode, fraisNotaireP])

  const tri = useMemo(() =>
    (bien && planRevente) ? computeTRI(apportEur, bien.price, fraisNotaireP, proj, revente) : null,
  [bien, apportEur, fraisNotaireP, proj, revente, planRevente])

  const handleApportOptimal = useCallback(() => {
    if (!bien) return
    const a = findApportOptimal(bien.price, fraisNotaireP, loyer, chargesAn, taux, duree, tmi, mode, vacanceP / 100)
    sp({ apportEur: a })
  }, [bien, fraisNotaireP, loyer, chargesAn, taux, duree, tmi, mode]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleOptimise = useCallback(() => {
    if (!bien) return
    const result = computeOptim({ prix: bien.price, fraisNotaireP, loyer, chargesAn, taux, duree, tmi, mode, apportEur, objectif })
    setOptim(result)
    setShowOptim(true)
  }, [bien, fraisNotaireP, loyer, chargesAn, taux, duree, tmi, mode, apportEur, objectif])

  if (!bien || proj.length === 0) return null

  const yr1         = proj[0]
  const atRevente   = planRevente ? proj.find((r) => r.annee === revente) : undefined
  const fraisNot    = bien.price * fraisNotaireP / 100
  const investTotal = apportEur + fraisNot
  const apportPct   = bien.price > 0 ? (apportEur / bien.price * 100).toFixed(0) : '0'
  const rdtNet      = investTotal > 0
    ? (yr1.loyerAnnuel - yr1.chargesYr - yr1.impot) / investTotal * 100
    : 0
  const cfMois1     = yr1.cashflowAn / 12

  const currentMode = FISCAL_MODES.find((m) => m.id === mode)!

  return (
    <div className="sim-page">
      <div className="sim-layout">

        {/* ── Sidebar ── */}
        <aside className="sim-sidebar">

          {/* Objectif */}
          <div className="sim-group">
            <div className="sim-group-title">Votre objectif</div>
            <div className="sim-objectif-grid">
              {OBJECTIFS.map((o) => (
                <button key={o.id}
                  className={cn('sim-objectif-pill', objectif === o.id && 'active')}
                  title={o.hint}
                  onClick={() => sp({ objectif: o.id })}>
                  {o.label}
                </button>
              ))}
            </div>
          </div>

          {/* Bien */}
          <div className="sim-group">
            <div className="sim-group-title">Bien simulé</div>
            <select className="sim-bien-select" value={bien?.id ?? ''} onChange={(e) => sp({ selectedId: e.target.value })}>
              <optgroup label="Appartements">
                {ALL_BIENS.filter((b) => b.type === 'appart').map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.neighbourhood} · {b.surface} m² · {Math.round(b.price / 1000)} k€
                  </option>
                ))}
              </optgroup>
              <optgroup label="Maisons">
                {ALL_BIENS.filter((b) => b.type === 'maison').map((b) => (
                  <option key={b.id} value={b.id}>
                    {b.neighbourhood} · {b.surface} m² · {Math.round(b.price / 1000)} k€
                  </option>
                ))}
              </optgroup>
            </select>
            <div className="sim-bien-card">
              {bien.photo ? (
                bien.url
                  ? <a href={bien.url} target="_blank" rel="noopener noreferrer" className="sim-bien-photo-link">
                      <img src={bien.photo} alt="" className="sim-bien-photo" />
                    </a>
                  : <img src={bien.photo} alt="" className="sim-bien-photo" />
              ) : (
                <div className="sim-bien-photo-ph">
                  {bien.type === 'appart' ? <Building2 size={24} /> : <Home size={24} />}
                </div>
              )}
              <div className="sim-bien-info">
                {bien.url
                  ? <a href={bien.url} target="_blank" rel="noopener noreferrer" className="sim-bien-name sim-bien-link">{bien.title}</a>
                  : <div className="sim-bien-name">{bien.title}</div>
                }
                <div className="sim-bien-meta">{bien.neighbourhood} · {bien.surface} m² · {bien.rooms} p.</div>
                <div className="sim-bien-price">{eur(bien.price)}</div>
                {bien.yieldPct && (
                  <div className="sim-bien-yield">{bien.yieldPct.toFixed(1)} % rdt brut</div>
                )}
              </div>
            </div>
          </div>

          {/* Financement */}
          <div className="sim-group">
            <div className="sim-group-title">Financement</div>
            <div className="sim-field">
              <label className="sim-field-label">Apport</label>
              <div className="sim-apport-input-row">
                <div className="sim-field-wrap">
                  <input type="number" className="sim-field-input" value={apportEur} step={5000} min={0}
                    onChange={(e) => sp({ apportEur: Math.max(0, +e.target.value || 0) })} />
                  <span className="sim-field-suffix">€</span>
                </div>
                <button className="sim-apport-opt-btn" onClick={handleApportOptimal}
                  title="Apport minimum pour cashflow = 0 à l'année 1">
                  ⚡ CF = 0
                </button>
              </div>
              <div className="sim-field-hint">{apportPct} % du prix · notaire ≈ {eur(fraisNot)}</div>
            </div>
            <SimSlider label="Frais de notaire" value={fraisNotaireP} min={2} max={9} step={0.5}
              format={(v) => `${v.toFixed(1)} % = ${eur(bien.price * v / 100)}`}
              onChange={(v) => sp({ fraisNotaireP: v })} />
            <SimSlider label="Taux crédit" value={taux} min={0.5} max={7} step={0.1}
              format={(v) => `${v.toFixed(1)} %`} onChange={(v) => sp({ taux: v })} />
            <SimSlider label="Durée" value={duree} min={5} max={30} step={1}
              format={(v) => `${v} ans`} onChange={(v) => sp({ duree: v })} />
          </div>

          {/* Revenus */}
          <div className="sim-group">
            <div className="sim-group-title">Revenus & charges</div>
            <SimNumField label="Loyer mensuel" value={loyer} suffix="€/mois" step={50}
              hint={`${(loyer * 12 / bien.price * 100).toFixed(1)} % rendement brut calculé`}
              onChange={(v) => sp({ loyer: v })} />
            <SimNumField label="Charges annuelles" value={chargesAn} suffix="€/an" step={200}
              hint="Copro, assurance, gestion, taxe foncière"
              onChange={(v) => sp({ chargesAn: v })} />
          </div>

          {/* Régime fiscal */}
          <div className="sim-group">
            <div className="sim-group-title">Régime fiscal</div>
            <div className="sim-fiscal-grid">
              {FISCAL_MODES.map((m) => (
                <button key={m.id} className={cn('sim-fiscal-pill', mode === m.id && 'active')}
                  onClick={() => sp({ mode: m.id })}>
                  {m.label}
                </button>
              ))}
            </div>
            <div className="sim-fiscal-hint">{currentMode.hint}</div>
            <div className="sim-sublabel">Tranche marginale d'imposition</div>
            <div className="sim-tmi-pills">
              {TMI_OPTIONS.map((t) => (
                <button key={t} className={cn('sim-tmi-pill', tmi === t && 'active')} onClick={() => sp({ tmi: t })}>
                  {t} %
                </button>
              ))}
            </div>
          </div>

          {/* Hypothèses */}
          <div className="sim-group">
            <div className="sim-group-title">Hypothèses projection</div>
            <SimSlider label="Revalorisation loyer" value={indexLoyer} min={0} max={5} step={0.5}
              format={(v) => `+${v} %/an`} onChange={(v) => sp({ indexLoyer: v })} />
            <SimSlider label="Revalorisation prix" value={indexPrix} min={0} max={8} step={0.5}
              format={(v) => `+${v} %/an`} onChange={(v) => sp({ indexPrix: v })} />
            <SimSlider label="Vacance locative" value={vacanceP} min={0} max={20} step={1}
              format={(v) => v === 0 ? 'Aucune' : `${v} %/an`} onChange={(v) => sp({ vacanceP: v })} />
            <div className="sim-revente-header">
              <span className="sim-field-label">Scénario de revente</span>
              <div className="sim-revente-toggle">
                <button className={cn('sim-revente-pill', planRevente && 'active-yes')}
                  onClick={() => sp({ planRevente: true })}>Oui</button>
                <button className={cn('sim-revente-pill', !planRevente && 'active-no')}
                  onClick={() => sp({ planRevente: false })}>Non</button>
              </div>
            </div>
            {planRevente && (
              <SimSlider label="" value={revente} min={1} max={20} step={1}
                format={(v) => `Revente an ${v}`} onChange={(v) => sp({ revente: v })} />
            )}
          </div>

          {/* Optimiser CTA */}
          <div className="sim-optim-sidebar">
            <div className="sim-group-title">Optimisation IA</div>
            <div className="sim-optim-sidebar-hint">
              Calcule le meilleur scénario selon votre objectif&nbsp;:
              meilleure année de revente, régime fiscal optimal, apport idéal.
            </div>
            <button className="sim-optim-sidebar-btn" onClick={handleOptimise}>
              <Zap size={14} /> Optimiser — {OBJECTIFS.find((o) => o.id === objectif)?.label}
            </button>
          </div>

        </aside>

        {/* ── Main ── */}
        <main className="sim-main">

          {/* Top opportunités */}
          {TOP_BIENS.length > 0 && (
            <div className="sim-topops">
              <div className="sim-topops-label">Top opportunités rendement</div>
              <div className="sim-topops-scroll">
                {TOP_BIENS.map((b) => {
                  const isActive = b.id === (bien?.id ?? '')
                  const yColor = (b.yieldPct ?? 0) >= 6 ? 'var(--green)' : (b.yieldPct ?? 0) >= 4 ? 'var(--amber)' : 'var(--text-dim)'
                  return (
                    <button key={b.id} className={cn('sim-topop-card', isActive && 'active')}
                      onClick={() => sp({ selectedId: b.id })}>
                      {b.photo
                        ? <img src={b.photo} alt="" className="sim-topop-img" />
                        : <div className="sim-topop-img-ph">{b.type === 'appart' ? <Building2 size={16} /> : <Home size={16} />}</div>
                      }
                      <div className="sim-topop-body">
                        <div className="sim-topop-hood">{b.neighbourhood}</div>
                        <div className="sim-topop-meta">{b.surface} m² · {Math.round(b.price / 1000)} k€</div>
                        <div className="sim-topop-yield" style={{ color: yColor }}>
                          {b.yieldPct?.toFixed(1)} % brut
                        </div>
                      </div>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* KPIs */}
          <div className="sim-kpis">
            <SimKPI label="Mensualité" value={eur(yr1.mensualite)} sub="/mois" />
            <SimKPI label="Cashflow net / mois" value={`${cfMois1 >= 0 ? '+' : ''}${eur(cfMois1, 0)}`}
              sub="année 1"
              color={cfMois1 >= 0 ? 'var(--green)' : 'var(--red)'} big />
            <SimKPI label="Rendement net" value={`${rdtNet.toFixed(2)} %`} sub="année 1"
              color={rdtNet >= 4 ? 'var(--green)' : rdtNet >= 2 ? 'var(--amber)' : 'var(--red)'} />
            {planRevente ? (
              <SimKPI label={`Gain revente an ${revente}`}
                value={atRevente?.gainRevente != null ? eur(atRevente.gainRevente) : '—'}
                color={atRevente?.gainRevente != null
                  ? atRevente.gainRevente > 0 ? 'var(--green)' : 'var(--red)'
                  : undefined} />
            ) : (
              <SimKPI label="Patrimoine an 10"
                value={proj[9] ? eur(proj[9].patrimoineNet) : '—'}
                color={proj[9] && proj[9].patrimoineNet > 0 ? 'var(--green)' : 'var(--red)'} />
            )}
            {planRevente ? (
              <SimKPI label="TRI estimé"
                value={tri != null ? `${tri.toFixed(1)} %` : '—'}
                color={tri != null ? tri > 7 ? 'var(--green)' : tri > 4 ? 'var(--amber)' : 'var(--red)' : undefined} />
            ) : (
              <SimKPI label="CF cumulé an 20"
                value={eur(proj[19]?.cashflowCumul ?? 0)}
                color={(proj[19]?.cashflowCumul ?? 0) >= 0 ? 'var(--green)' : 'var(--red)'} />
            )}
          </div>

          {/* Barre Optimiser */}
          <div className="sim-optim-bar">
            <span className="sim-optim-bar-label">
              Objectif : <strong>{OBJECTIFS.find((o) => o.id === objectif)?.label}</strong>
              <span className="sim-optim-bar-hint"> · {OBJECTIFS.find((o) => o.id === objectif)?.hint}</span>
            </span>
            <button className="sim-optim-btn" onClick={handleOptimise}>
              <Zap size={13} /> Optimiser
            </button>
          </div>

          {/* Panel recommandations */}
          {showOptim && optim && (
            <div className="sim-optim-panel">
              <div className="sim-optim-panel-header">
                <span className="sim-optim-title">
                  Recommandations — {OBJECTIFS.find((o) => o.id === objectif)?.label}
                </span>
                <button className="action-btn" onClick={() => setShowOptim(false)}><X size={12} /></button>
              </div>
              <div className="sim-optim-insights">
                {optim.insights.map((ins, i) => (
                  <div key={i} className={`sim-optim-insight ${ins.type}`}>{ins.text}</div>
                ))}
              </div>
              <div className="sim-optim-actions">
                {planRevente && optim.bestReventeYear !== revente && (
                  <button className="sim-optim-action-btn"
                    onClick={() => { sp({ revente: optim.bestReventeYear }); setShowOptim(false) }}>
                    → Revente an {optim.bestReventeYear} (TRI {optim.bestTri.toFixed(1)} %)
                  </button>
                )}
                {optim.bestMode !== mode && optim.bestModeCfBonus > 500 && (
                  <button className="sim-optim-action-btn"
                    onClick={() => { sp({ mode: optim.bestMode }); setShowOptim(false) }}>
                    → Passer en {optim.bestModeLabel}
                  </button>
                )}
                {Math.abs(optim.apport0 - apportEur) > 5_000 && (
                  <button className="sim-optim-action-btn"
                    onClick={() => { sp({ apportEur: optim.apport0 }); setShowOptim(false) }}>
                    → Apport CF=0 : {eur(optim.apport0)}
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Détail an 1 + revente */}
          <div className="sim-mid">

            <div className="sim-yr1">
              <div className="sim-yr1-title">Flux mensuels — Année 1</div>
              <div className="sim-yr1-body">
                <Yr1Row label="Loyer perçu"       value={yr1.loyerAnnuel / 12}  color="var(--green)" />
                <Yr1Row label="Mensualité crédit"  value={-yr1.mensualite}        color="var(--red)" />
                <Yr1Row label="Charges & TF"       value={-yr1.chargesYr / 12}   color="var(--text-dim)" />
                <div className="sim-yr1-sep" />
                <Yr1Row label="Cashflow brut"
                  value={(yr1.loyerAnnuel - yr1.chargesYr) / 12 - yr1.mensualite}
                  bold />
                <Yr1Row label="Impôt estimé"       value={-yr1.impot / 12}        color="var(--amber)" />
                <div className="sim-yr1-sep" />
                <Yr1Row label="Cashflow net"        value={cfMois1}
                  color={cfMois1 >= 0 ? 'var(--green)' : 'var(--red)'} bold big />
              </div>
              <div className="sim-invest-summary">
                <span className="sim-invest-label">Investissement total</span>
                <span className="sim-invest-val">{eur(investTotal)}</span>
                <span className="sim-invest-detail">
                  apport {eur(apportEur)} + notaire {eur(fraisNot)} ({fraisNotaireP.toFixed(1)} %)
                </span>
              </div>
            </div>

            {planRevente && atRevente && (
              <div className="sim-revente-card">
                <div className="sim-yr1-title">À la revente — an {revente}</div>
                <div className="sim-yr1-body">
                  <Yr1Row label="Valeur estimée"     value={atRevente.valeurBien}          color="var(--text)" noSign />
                  <Yr1Row label="Capital restant dû"  value={-atRevente.capitalRestant}      color="var(--red)" />
                  <Yr1Row label="Frais de vente 5 %"  value={-atRevente.valeurBien * 0.05}  color="var(--amber)" />
                  <Yr1Row label="Cashflow cumulé"     value={atRevente.cashflowCumul}
                    color={atRevente.cashflowCumul >= 0 ? 'var(--green)' : 'var(--red)'} />
                  <div className="sim-yr1-sep" />
                  <Yr1Row label="Gain net revente"
                    value={atRevente.gainRevente ?? 0}
                    color={(atRevente.gainRevente ?? 0) >= 0 ? 'var(--green)' : 'var(--red)'}
                    bold big />
                </div>
                {tri != null && (
                  <div className="sim-tri">
                    <span className="sim-tri-label">TRI sur {revente} ans</span>
                    <span className="sim-tri-val" style={{ color: tri > 7 ? 'var(--green)' : tri > 4 ? 'var(--amber)' : 'var(--red)' }}>
                      {tri.toFixed(1)} %
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Graphique 20 ans */}
          <div className="sim-chart-card">
            <div className="sim-chart-header">
              <span className="sim-chart-title">Projection 20 ans</span>
              <span className="sim-chart-sub">Patrimoine net · Cashflow cumulé · Valeur du bien</span>
            </div>
            <ResponsiveContainer width="100%" height={260}>
              <AreaChart data={proj} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="sgPn" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="var(--accent)"          stopOpacity={0.4} />
                    <stop offset="95%" stopColor="var(--accent)"          stopOpacity={0.02} />
                  </linearGradient>
                  <linearGradient id="sgCf" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="oklch(0.52 0.155 152)" stopOpacity={0.4} />
                    <stop offset="95%" stopColor="oklch(0.52 0.155 152)" stopOpacity={0.02} />
                  </linearGradient>
                  <linearGradient id="sgVb" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="oklch(0.65 0.18 275)"  stopOpacity={0.2} />
                    <stop offset="95%" stopColor="oklch(0.65 0.18 275)"  stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="annee"
                  tick={{ fontSize: 10, fill: 'var(--text-faint)', fontFamily: 'var(--font-mono)' }}
                  tickLine={false} />
                <YAxis
                  tick={{ fontSize: 10, fill: 'var(--text-faint)', fontFamily: 'var(--font-mono)' }}
                  tickFormatter={(v) => `${Math.round(v / 1000)}k`}
                  tickLine={false} axisLine={false} />
                <Tooltip content={<ChartTooltip />} />
                {planRevente && (
                  <ReferenceLine x={revente} stroke="var(--accent)"
                    strokeDasharray="5 3" strokeWidth={1.5}
                    label={{ value: `an ${revente}`, fontSize: 9, fill: 'var(--accent)', fontFamily: 'var(--font-display)' }} />
                )}
                <Area type="monotone" dataKey="patrimoineNet"  name="Patrimoine net"
                  stroke="var(--accent)"          fill="url(#sgPn)" strokeWidth={2} dot={false} />
                <Area type="monotone" dataKey="cashflowCumul" name="Cashflow cumulé"
                  stroke="oklch(0.52 0.155 152)"  fill="url(#sgCf)" strokeWidth={2} dot={false} />
                <Area type="monotone" dataKey="valeurBien"    name="Valeur bien"
                  stroke="oklch(0.65 0.18 275)"   fill="url(#sgVb)" strokeWidth={1.5} dot={false}
                  strokeDasharray="5 4" />
              </AreaChart>
            </ResponsiveContainer>
          </div>

          {/* Tableau annuel */}
          <div className="sim-table-card">
            <div className="sim-chart-header">
              <span className="sim-chart-title">Tableau annuel</span>
              <span className="sim-chart-sub">Évolution année par année</span>
            </div>
            <div className="sim-table-scroll">
              <table className="sim-tbl">
                <thead>
                  <tr>
                    <th>An</th>
                    <th>CF annuel</th>
                    <th>CF cumulé</th>
                    <th>Valeur bien</th>
                    <th>Dette</th>
                    <th>Patrimoine net</th>
                    {planRevente && <th>Gain revente</th>}
                  </tr>
                </thead>
                <tbody>
                  {proj.map((r) => (
                    <tr key={r.annee} className={planRevente && r.annee === revente ? 'sim-tbl-revente' : ''}>
                      <td className="sim-tbl-an">
                        {r.annee}
                        {planRevente && r.annee === revente && <span className="sim-revente-badge">revente</span>}
                      </td>
                      <td className={cn('sim-tbl-num', r.cashflowAn >= 0 ? 'sim-tbl-green' : 'sim-tbl-red')}>
                        {eur(r.cashflowAn)}
                      </td>
                      <td className={cn('sim-tbl-num', r.cashflowCumul >= 0 ? 'sim-tbl-green' : 'sim-tbl-amber')}>
                        {eur(r.cashflowCumul)}
                      </td>
                      <td className="sim-tbl-num sim-tbl-dim">{eur(r.valeurBien)}</td>
                      <td className="sim-tbl-num sim-tbl-red">{eur(r.capitalRestant)}</td>
                      <td className={cn('sim-tbl-num sim-tbl-bold', r.patrimoineNet >= 0 ? 'sim-tbl-ice' : 'sim-tbl-red')}>
                        {eur(r.patrimoineNet)}
                      </td>
                      {planRevente && (
                        <td className="sim-tbl-num">
                          {r.gainRevente != null
                            ? <span className={r.gainRevente >= 0 ? 'sim-tbl-green' : 'sim-tbl-red'}>{eur(r.gainRevente)}</span>
                            : <span className="sim-tbl-dim">—</span>}
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          <div className="sim-disclaimer">
            Simulation indicative · {currentMode.label} · TMI {tmi} % + PS 17.2 % ·
            Intérêts recalculés mois par mois · Amortissement 25 ans (LMNP Réel) ·
            Frais notaire {fraisNotaireP.toFixed(1)} % · Frais vente 5 % · Consulter un expert avant toute décision
          </div>

        </main>
      </div>
    </div>
  )
}

// ── Sub-components ─────────────────────────────────────────────────────────────

function SimNumField({ label, value, suffix, step, hint, onChange }: {
  label: string; value: number; suffix: string; step: number; hint?: string; onChange: (v: number) => void
}) {
  return (
    <div className="sim-field">
      <label className="sim-field-label">{label}</label>
      <div className="sim-field-wrap">
        <input type="number" className="sim-field-input" value={value} step={step} min={0}
          onChange={(e) => onChange(Math.max(0, +e.target.value || 0))} />
        <span className="sim-field-suffix">{suffix}</span>
      </div>
      {hint && <div className="sim-field-hint">{hint}</div>}
    </div>
  )
}

function SimSlider({ label, value, min, max, step, format, onChange }: {
  label: string; value: number; min: number; max: number; step: number
  format: (v: number) => string; onChange: (v: number) => void
}) {
  return (
    <div className="sim-field">
      <div className="sim-field-header">
        {label && <label className="sim-field-label">{label}</label>}
        <span className="sim-field-curval">{format(value)}</span>
      </div>
      <input type="range" className="sim-range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(+e.target.value)}
        style={{ accentColor: 'var(--accent)' }} />
    </div>
  )
}

function SimKPI({ label, value, sub, color, big }: {
  label: string; value: string; sub?: string; color?: string; big?: boolean
}) {
  return (
    <div className={cn('sim-kpi', big && 'sim-kpi-hero')}>
      <div className="sim-kpi-label">{label}</div>
      <div className="sim-kpi-value" style={color ? { color } : undefined}>{value}</div>
      {sub && <div className="sim-kpi-sub">{sub}</div>}
    </div>
  )
}

function Yr1Row({ label, value, color, bold, big, noSign }: {
  label: string; value: number; color?: string; bold?: boolean; big?: boolean; noSign?: boolean
}) {
  const sign = noSign ? '' : (value >= 0 ? '+' : '')
  return (
    <div className={cn('sim-yr1-row', big && 'sim-yr1-row-hero')}>
      <span className="sim-yr1-label">{label}</span>
      <span className="sim-yr1-val" style={{ color: color ?? 'var(--text)', fontWeight: bold ? 700 : 500 }}>
        {sign}{eur(value, 0)}{!noSign && <span className="sim-yr1-sub">/mois</span>}
      </span>
    </div>
  )
}
