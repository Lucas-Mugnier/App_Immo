import { useState, useMemo, useCallback, useEffect, useRef } from 'react'
import { eur } from '@/lib/utils'
import { APPARTS, MAISONS } from '@/lib/data'
import { useStore } from '@/store/useStore'
import {
  Zap, ChevronRight, Building2, Home,
  TrendingUp, Gem, Scale, Hammer, Award,
} from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts'
import {
  PROFILES, rankBiens, computeStressTest, computeSensitivity,
  computeEndettement, confortScore, decoteScore, triScore,
  SENS_APPORT_PCTS, SENS_TAUX, FISCAL_LABELS,
  type CatalogBien, type BienOptimResult, type ProfilAcquisition,
  type OptimParams, type DTIResult,
} from '@/lib/optimizer'
import { buildProjection, computeTRI, computeVAN, type ProjRow } from '@/lib/simulator'
import type { FiscalMode } from '@/types'

const FISCAL_IDS: FiscalMode[] = ['lmnp_reel', 'lmnp_micro', 'ir_nu', 'sci_is']

const PROFILE_ICONS: Record<string, React.ReactNode> = {
  locatif:  <TrendingUp size={14} />,
  valeur:   <Gem size={14} />,
  rp:       <Home size={14} />,
  mixte:    <Scale size={14} />,
  marchand: <Hammer size={14} />,
}

// ── Color helpers ─────────────────────────────────────────────────────────────

function scoreColor(s: number) {
  if (s >= 70) return 'var(--green)'
  if (s >= 50) return 'var(--accent)'
  if (s >= 35) return 'var(--amber)'
  return 'var(--red)'
}
function triColor(t: number | null) {
  if (t == null) return 'var(--text-faint)'
  if (t >= 8)  return 'var(--green)'
  if (t >= 5)  return 'var(--accent)'
  if (t >= 3)  return 'var(--amber)'
  return 'var(--red)'
}
function effortColor(t: number | null) {
  if (t == null) return 'var(--text-faint)'
  if (t <= 0.25) return 'var(--green)'
  if (t <= 0.33) return 'var(--accent)'
  if (t <= 0.40) return 'var(--amber)'
  return 'var(--red)'
}
function vanColor(v: number) { return v > 0 ? 'var(--green)' : 'var(--red)' }
function triCellBg(t: number | null) {
  if (t == null) return 'var(--surface-3)'
  if (t >= 9)  return 'oklch(0.52 0.155 152 / 0.35)'
  if (t >= 7)  return 'oklch(0.52 0.155 152 / 0.20)'
  if (t >= 5)  return 'oklch(0.72 0.095 72  / 0.25)'
  if (t >= 3)  return 'oklch(0.72 0.18  72  / 0.18)'
  if (t >= 0)  return 'oklch(0.64 0.17  40  / 0.15)'
  return 'oklch(0.64 0.17 40 / 0.30)'
}

// ── Small components ──────────────────────────────────────────────────────────

function ScoreBar({ value, color = 'var(--accent)' }: { value: number; color?: string }) {
  return (
    <div className="opt-scorebar">
      <div className="opt-scorebar-fill" style={{ width: `${value}%`, background: color }} />
    </div>
  )
}

function ProfileCard({ profil, active, onClick }: {
  profil: typeof PROFILES[0]; active: boolean; onClick: () => void
}) {
  return (
    <button className={`opt-profile-card${active ? ' active' : ''}`} onClick={onClick}>
      <div className="opt-profile-icon">{PROFILE_ICONS[profil.id]}</div>
      <div className="opt-profile-body">
        <div className="opt-profile-label">{profil.label}</div>
        <div className="opt-profile-tagline">{profil.tagline}</div>
      </div>
      {active && <div className="opt-profile-check"><Award size={11} /></div>}
    </button>
  )
}

function DtiBadge({ dti, isRP }: { dti: DTIResult; isRP?: boolean }) {
  const pct = Math.round(dti.tauxEndettement * 100)
  const color = dti.endettable ? (pct <= 28 ? 'var(--green)' : 'var(--accent)') : 'var(--red)'
  return (
    <div className="opt-dti-badge" style={{ borderColor: color, color }}>
      <span className="opt-dti-pct">{pct}%</span>
      <span className="opt-dti-icon">{dti.endettable ? '✓' : '✗'}</span>
      {isRP && <span style={{ fontSize: '0.6rem', marginLeft: 2 }}>effort</span>}
    </div>
  )
}

function KpiChip({ label, value, color, sub }: { label: string; value: string; color?: string; sub?: string }) {
  return (
    <div className="an-kpi-chip">
      <span className="an-kpi-label">{label}</span>
      <span className="an-kpi-value" style={color ? { color } : undefined}>{value}</span>
      {sub && <span className="an-kpi-sub">{sub}</span>}
    </div>
  )
}

// ── Sort header cell ──────────────────────────────────────────────────────────

function SortTh({ col, label, active, dir, onSort }: {
  col: string; label: string; active: boolean; dir: 'asc' | 'desc'; onSort: (c: string) => void
}) {
  return (
    <th className={`an-sort-th${active ? ' active' : ''}`} onClick={() => onSort(col)}>
      {label}
      {active && <span className="an-sort-arrow">{dir === 'desc' ? ' ↓' : ' ↑'}</span>}
    </th>
  )
}

// ── Rank row — RP or locatif ──────────────────────────────────────────────────

function FinancableCell({ dti }: { dti: DTIResult }) {
  if (dti.revenusMensuels <= 0) return <td className="an-rank-num" style={{ color: 'var(--text-faint)' }}>—</td>
  return (
    <td className="an-rank-num" style={{ color: dti.endettable ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>
      {dti.endettable ? 'Oui' : 'Non'}
    </td>
  )
}

function RankRow({ r, rank, selected, isRP, onClick }: {
  r: BienOptimResult; rank: number; selected: boolean; isRP: boolean; onClick: () => void
}) {
  const decotePct = r.bien.avmRatio != null ? ((1 - r.bien.avmRatio) * 100).toFixed(0) : null
  return (
    <tr className={`an-rank-row${selected ? ' selected' : ''}`} onClick={onClick}>
      <td className="an-rank-num">{rank}</td>
      <td className="an-rank-bien">
        {r.bien.photo
          ? <img src={r.bien.photo} alt="" className="an-rank-photo" />
          : <div className="an-rank-photo-ph">{r.bien.type === 'appart' ? <Building2 size={9} /> : <Home size={9} />}</div>
        }
        <div className="an-rank-info">
          <div className="an-rank-title">{r.bien.title}</div>
          <div className="an-rank-meta">{r.bien.neighbourhood} · {r.bien.surface}m² · {Math.round(r.bien.price / 1000)}k€</div>
        </div>
      </td>
      <td className="an-rank-score-cell">
        <span style={{ color: scoreColor(r.score), fontWeight: 700, fontSize: '0.73rem' }}>{r.score}</span>
        <ScoreBar value={r.score} color={scoreColor(r.score)} />
      </td>

      {isRP ? (
        <>
          <td className="an-rank-num" style={{ color: effortColor(r.tauxEffort) }}>
            {r.tauxEffort != null ? `${Math.round(r.tauxEffort * 100)}%` : '—'}
          </td>
          <td className="an-rank-num">{eur(r.mensualite, 0)}/m</td>
          <FinancableCell dti={r.dti} />
        </>
      ) : (
        <>
          <td className="an-rank-num" style={{ color: triColor(r.triOpt) }}>
            {r.triOpt != null ? `${r.triOpt.toFixed(1)}%` : '—'}
          </td>
          <td className="an-rank-num" style={{ color: r.cfMois1 >= 0 ? 'var(--green)' : 'var(--red)' }}>
            {r.cfMois1 >= 0 ? '+' : ''}{eur(r.cfMois1, 0)}
          </td>
          <td className="an-rank-num" style={{ color: r.bien.avmRatio != null ? (r.bien.avmRatio < 1 ? 'var(--green)' : 'var(--red)') : 'var(--text-faint)' }}>
            {decotePct != null ? `${+decotePct > 0 ? '+' : ''}${decotePct}%` : '—'}
          </td>
          <FinancableCell dti={r.dti} />
        </>
      )}
    </tr>
  )
}

// ── Chart tooltips ────────────────────────────────────────────────────────────

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: { name: string; value: number; stroke: string }[]; label?: number }) {
  if (!active || !payload?.length) return null
  return (
    <div className="sim-tooltip">
      <div className="sim-tooltip-year">An {label}</div>
      {payload.map((p) => (
        <div key={p.name} className="sim-tooltip-row">
          <span style={{ color: p.stroke }}>{p.name}</span>
          <span className="sim-tooltip-val" style={{ color: p.stroke }}>{eur(p.value)}</span>
        </div>
      ))}
    </div>
  )
}

function VanTooltip({ active, payload, label }: { active?: boolean; payload?: { value: number }[]; label?: number }) {
  if (!active || !payload?.length) return null
  const v = payload[0].value
  return (
    <div className="sim-tooltip">
      <div className="sim-tooltip-year">Taux {label}%</div>
      <div className="sim-tooltip-row">
        <span style={{ color: v >= 0 ? 'var(--green)' : 'var(--red)' }}>VAN</span>
        <span className="sim-tooltip-val" style={{ color: v >= 0 ? 'var(--green)' : 'var(--red)' }}>{eur(v)}</span>
      </div>
    </div>
  )
}

// ── Shared data types ─────────────────────────────────────────────────────────

interface SimData {
  rows: ProjRow[]
  tri: number | null
  van5: number
  van8: number
  cfMois1: number
  mensualite: number
  apport: number
  revente: number
}

interface SimOverrides {
  loyer: number
  chargesAn: number
  mode: FiscalMode
  revente: number
  planRevente: boolean
}

// ══════════════════════════════════════════════════════════════════════════════
// SIMULATION LOCATIF
// ══════════════════════════════════════════════════════════════════════════════

type AnDetailTab = 'annuel' | 'van' | 'stress' | 'sensib'

function SimDetail({ selected, simData, simOverrides, params, profil }: {
  selected: BienOptimResult
  simData: SimData
  simOverrides: SimOverrides
  params: OptimParams
  profil: ProfilAcquisition
}) {
  const [tab, setTab] = useState<AnDetailTab>('annuel')
  const profile = PROFILES.find((p) => p.id === profil)!

  const chartData = simData.rows.map((r) => ({
    annee: r.annee,
    'Patrimoine net': Math.round(r.patrimoineNet),
    'CF cumulé': Math.round(r.cashflowCumul),
  }))

  const vanCurve = useMemo(() =>
    Array.from({ length: 13 }, (_, i) => ({
      discountRate: i,
      van: computeVAN(simData.apport, selected.bien.price, params.fraisNotaireP, simData.rows, simData.revente, i / 100),
    })),
  [simData, selected.bien.price, params.fraisNotaireP])

  const breakEvenRate = useMemo(() => {
    for (let i = 0; i < vanCurve.length - 1; i++) {
      if (vanCurve[i].van >= 0 && vanCurve[i + 1].van < 0) return vanCurve[i].discountRate
    }
    return null
  }, [vanCurve])

  const stress = useMemo(() => computeStressTest(selected.bien, selected, params), [selected, params])
  const sens   = useMemo(() => computeSensitivity(selected.bien, selected, params), [selected, params])

  const decotePct   = selected.bien.avmRatio != null ? ((1 - selected.bien.avmRatio) * 100).toFixed(0) : null
  const fraisNot    = Math.round(selected.bien.price * params.fraisNotaireP / 100)
  const investTotal = simData.apport + fraisNot

  return (
    <div className="an-detail">
      {/* Header */}
      <div className="an-detail-header">
        <div className="an-detail-bien-info">
          {selected.bien.photo && (
            selected.bien.url
              ? <a href={selected.bien.url} target="_blank" rel="noopener noreferrer"><img src={selected.bien.photo} alt="" className="an-detail-photo" /></a>
              : <img src={selected.bien.photo} alt="" className="an-detail-photo" />
          )}
          <div className="an-detail-bien-text">
            {selected.bien.url
              ? <a href={selected.bien.url} target="_blank" rel="noopener noreferrer" className="an-detail-title">{selected.bien.title}</a>
              : <div className="an-detail-title">{selected.bien.title}</div>
            }
            <div className="an-detail-meta">{selected.bien.neighbourhood} · {selected.bien.surface}m² · {selected.bien.rooms}p · {eur(selected.bien.price)}</div>
          </div>
        </div>
        <div className="an-detail-right">
          <div className="an-detail-score" style={{ color: scoreColor(selected.score) }}>
            {selected.score}<span className="an-detail-score-label">/{profile.label}</span>
          </div>
          {selected.dti.revenusMensuels > 0 && <DtiBadge dti={selected.dti} />}
        </div>
      </div>

      {/* KPI strip */}
      <div className="an-kpi-strip">
        <KpiChip label="TRI estimé"    value={simData.tri != null ? `${simData.tri.toFixed(1)}%` : '—'} color={triColor(simData.tri)} />
        <KpiChip label="CF / mois"     value={`${simData.cfMois1 >= 0 ? '+' : ''}${eur(simData.cfMois1, 0)}`} color={simData.cfMois1 >= 0 ? 'var(--green)' : 'var(--red)'} />
        <KpiChip label="VAN @ 5%"      value={eur(simData.van5)} color={vanColor(simData.van5)} />
        <KpiChip label="VAN @ 8%"      value={eur(simData.van8)} color={vanColor(simData.van8)} />
        <KpiChip label="Mensualité"    value={`${eur(simData.mensualite, 0)}/m`} />
        <KpiChip label="Invest. total" value={eur(investTotal)} />
        {decotePct != null && (
          <KpiChip label="Décote AVM" value={`${+decotePct > 0 ? '+' : ''}${decotePct}%`} color={selected.bien.avmRatio! < 1 ? 'var(--green)' : 'var(--red)'} />
        )}
        <KpiChip label="Patr. an 10" value={eur(simData.rows[9]?.patrimoineNet ?? 0)} />
      </div>

      {/* Chart */}
      <div className="an-chart-section">
        <div className="an-chart-header">
          <span className="an-chart-title">Projection sur {simData.rows.length} ans</span>
          <span className="an-chart-sub">
            {FISCAL_LABELS[simOverrides.mode]}
            {simOverrides.planRevente ? ` · revente an ${simOverrides.revente}` : ' · sans revente'}
          </span>
        </div>
        <ResponsiveContainer width="100%" height={150}>
          <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="anPatrimGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="var(--accent)" stopOpacity={0.22} />
                <stop offset="95%" stopColor="var(--accent)" stopOpacity={0.01} />
              </linearGradient>
              <linearGradient id="anCfGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="var(--green)" stopOpacity={0.15} />
                <stop offset="95%" stopColor="var(--green)" stopOpacity={0.01} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="annee" tick={{ fontSize: 9, fill: 'var(--text-faint)' }} tickLine={false} tickFormatter={(v) => `${v}a`} />
            <YAxis tick={{ fontSize: 9, fill: 'var(--text-faint)' }} tickLine={false} axisLine={false} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <Tooltip content={<ChartTooltip />} />
            <ReferenceLine y={0} stroke="var(--border-strong)" strokeDasharray="4 3" />
            <Area type="monotone" dataKey="Patrimoine net" stroke="var(--accent)" fill="url(#anPatrimGrad)" strokeWidth={2} dot={false} />
            <Area type="monotone" dataKey="CF cumulé" stroke="var(--green)" fill="url(#anCfGrad)" strokeWidth={1.5} dot={false} strokeDasharray="5 3" />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Sub-tabs */}
      <div className="an-detail-tabs">
        {(['annuel', 'van', 'stress', 'sensib'] as AnDetailTab[]).map((t) => (
          <button key={t} className={`an-detail-tab${tab === t ? ' active' : ''}`} onClick={() => setTab(t)}>
            {{ annuel: 'Annuel', van: 'VAN', stress: 'Stress test', sensib: 'Sensibilité' }[t]}
          </button>
        ))}
      </div>

      <div className="an-tab-content">
        {tab === 'annuel' && (
          <div className="an-annuel-wrap">
            <table className="an-annuel-table">
              <thead><tr><th>An</th><th>Loyer</th><th>CF/an</th><th>CF cumulé</th><th>Patrimoine</th></tr></thead>
              <tbody>
                {simData.rows.map((r) => (
                  <tr key={r.annee} className={r.annee === simOverrides.revente && simOverrides.planRevente ? 'an-annuel-revente' : ''}>
                    <td>{r.annee}</td>
                    <td>{eur(r.loyerAnnuel, 0)}</td>
                    <td style={{ color: r.cashflowAn >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>
                      {r.cashflowAn >= 0 ? '+' : ''}{eur(r.cashflowAn, 0)}
                    </td>
                    <td style={{ color: r.cashflowCumul >= 0 ? 'var(--green)' : 'var(--red)' }}>
                      {r.cashflowCumul >= 0 ? '+' : ''}{eur(r.cashflowCumul, 0)}
                    </td>
                    <td style={{ fontWeight: 600 }}>{eur(r.patrimoineNet, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {tab === 'van' && (
          <div className="opt-van-section">
            <div className="opt-van-header">
              <span className="opt-van-title">VAN vs taux d'actualisation</span>
              <span className="opt-van-sub">VAN &gt; 0 → l'investissement bat l'alternative financière</span>
            </div>
            {breakEvenRate != null && (
              <div className="opt-van-breakeven">
                Taux d'indifférence : <strong>{breakEvenRate}%</strong>
                {breakEvenRate < 5 ? ' — sous-performant vs bourse'
                  : breakEvenRate < 8 ? ' — compétitif vs portefeuille 7-8%'
                  : ' — bat une allocation actions standard'}
              </div>
            )}
            <ResponsiveContainer width="100%" height={180}>
              <AreaChart data={vanCurve} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="anVanGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="var(--green)" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="var(--green)" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="discountRate" tick={{ fontSize: 10, fill: 'var(--text-faint)' }} tickLine={false} tickFormatter={(v) => `${v}%`} />
                <YAxis tick={{ fontSize: 10, fill: 'var(--text-faint)' }} tickLine={false} axisLine={false} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
                <Tooltip content={<VanTooltip />} />
                <ReferenceLine y={0} stroke="var(--border-strong)" strokeDasharray="4 3" />
                {breakEvenRate != null && (
                  <ReferenceLine x={breakEvenRate} stroke="var(--amber)" strokeDasharray="5 3"
                    label={{ value: `${breakEvenRate}%`, fontSize: 9, fill: 'var(--amber)' }} />
                )}
                <Area type="monotone" dataKey="van" name="VAN" stroke="var(--green)" fill="url(#anVanGrad)" strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}

        {tab === 'stress' && (
          <div className="opt-stress-section">
            <div className="opt-van-header">
              <span className="opt-van-title">Scénarios de marché</span>
              <span className="opt-van-sub">Même bien, mêmes paramètres, hypothèses différentes</span>
            </div>
            {stress.map((s) => (
              <div key={s.id} className="opt-stress-row">
                <div className="opt-stress-label-col">
                  <span className="opt-stress-name" style={{ color: s.color }}>{s.label}</span>
                  <span className="opt-stress-hypo">prix {s.indexPrix > 0 ? '+' : ''}{s.indexPrix}%/an · loyer +{s.indexLoyer}%/an · vacance {Math.round(s.vacanceP * 100)}%</span>
                </div>
                <div className="opt-stress-kpis">
                  <div className="opt-stress-kpi"><span className="opt-stress-kpi-label">TRI</span><span className="opt-stress-kpi-val" style={{ color: triColor(s.tri) }}>{s.tri != null ? `${s.tri.toFixed(1)}%` : '—'}</span></div>
                  <div className="opt-stress-kpi"><span className="opt-stress-kpi-label">CF/mois</span><span className="opt-stress-kpi-val" style={{ color: s.cfMois1 >= 0 ? 'var(--green)' : 'var(--red)' }}>{s.cfMois1 >= 0 ? '+' : ''}{eur(s.cfMois1, 0)}</span></div>
                  <div className="opt-stress-kpi"><span className="opt-stress-kpi-label">Patr. an 10</span><span className="opt-stress-kpi-val">{eur(s.patrimoineAn10)}</span></div>
                  <div className="opt-stress-kpi"><span className="opt-stress-kpi-label">VAN @5%</span><span className="opt-stress-kpi-val" style={{ color: vanColor(s.van5) }}>{eur(s.van5)}</span></div>
                </div>
                <div className="opt-stress-bar-wrap">
                  {s.tri != null && <div className="opt-stress-bar" style={{ width: `${Math.min(100, Math.max(0, s.tri / 15 * 100))}%`, background: s.color }} />}
                </div>
              </div>
            ))}
          </div>
        )}

        {tab === 'sensib' && (
          <div className="opt-sens-section">
            <div className="opt-van-header">
              <span className="opt-van-title">TRI selon apport × taux crédit</span>
              <span className="opt-van-sub">Chaque cellule = TRI estimé avec ces paramètres</span>
            </div>
            <div className="opt-sens-wrap">
              <table className="opt-sens-table">
                <thead>
                  <tr>
                    <th className="opt-sens-corner">Apport \ Taux</th>
                    {SENS_TAUX.map((t) => <th key={t} className="opt-sens-th">{t}%</th>)}
                  </tr>
                </thead>
                <tbody>
                  {sens.map((row, ri) => (
                    <tr key={ri}>
                      <td className="opt-sens-rowh">
                        {SENS_APPORT_PCTS[ri]}%
                        <span className="opt-sens-rowh-sub">{eur(Math.round(selected.bien.price * SENS_APPORT_PCTS[ri] / 100 / 1000) * 1000)}</span>
                      </td>
                      {row.map((cell, ci) => (
                        <td key={ci} className="opt-sens-cell" style={{ background: triCellBg(cell.tri) }}>
                          {cell.tri != null ? `${cell.tri.toFixed(1)}%` : '—'}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="opt-sens-legend">
              <span style={{ color: 'var(--green)' }}>■</span> ≥9%
              <span style={{ color: 'oklch(0.52 0.155 152)' }}>■</span> 7-9%
              <span style={{ color: 'var(--accent)' }}>■</span> 5-7%
              <span style={{ color: 'var(--amber)' }}>■</span> 3-5%
              <span style={{ color: 'var(--red)' }}>■</span> 0-3%
              <span style={{ color: 'var(--text-faint)' }}>■</span> &lt;0%
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// SIMULATION RÉSIDENCE PRINCIPALE
// ══════════════════════════════════════════════════════════════════════════════

type RPTab = 'mensualites' | 'vs-location' | 'marche'

interface CmpRow {
  annee: number
  loyerCumul: number
  coutAchatCumul: number
  delta: number    // positif = achat moins cher que location (cumulé)
  equity: number
  richesseNette: number
}

function SimDetailRP({ selected, simData, params, loyerActuel }: {
  selected: BienOptimResult
  simData: SimData
  params: OptimParams
  loyerActuel: number
}) {
  const [tab, setTab] = useState<RPTab>('mensualites')

  const mensualite  = simData.mensualite
  const tauxEffort  = params.salaireNet > 0 ? mensualite / params.salaireNet : null
  const chargesMois = selected.chargesAn / 12
  const coutTotal   = mensualite + chargesMois
  const deltaVsLoc  = loyerActuel > 0 ? loyerActuel - coutTotal : null  // + = achat moins cher/mois

  const decotePct = selected.bien.avmRatio != null ? ((1 - selected.bien.avmRatio) * 100).toFixed(0) : null

  // Données graphique : équité (patrimoine net = valeur bien - capital dû)
  const chartData = simData.rows.map((r) => ({
    annee: r.annee,
    'Équité accumulée': Math.round(r.patrimoineNet),
  }))

  // Comparaison achat vs location année par année
  const comparison = useMemo((): CmpRow[] => {
    if (!loyerActuel) return []
    let loyerCumul     = 0
    let coutAchatCumul = 0
    return simData.rows.map((r) => {
      // Loyer indexé chaque année (propriétaire peut augmenter)
      loyerCumul     += loyerActuel * 12 * Math.pow(1 + params.indexLoyer / 100, r.annee - 1)
      coutAchatCumul += mensualite * 12 + r.chargesYr
      const delta        = Math.round(loyerCumul - coutAchatCumul)
      const richesseNette = Math.round(r.patrimoineNet + delta)
      return {
        annee:          r.annee,
        loyerCumul:     Math.round(loyerCumul),
        coutAchatCumul: Math.round(coutAchatCumul),
        delta,
        equity:         Math.round(r.patrimoineNet),
        richesseNette,
      }
    })
  }, [simData, loyerActuel, mensualite, params.indexLoyer])

  // Scénarios prix marché
  const prixScenarios = useMemo(() => {
    const scenarios = [
      { label: 'Crise', color: 'var(--red)',    indexPrix: -2 },
      { label: 'Base',  color: 'var(--accent)', indexPrix:  3 },
      { label: 'Boom',  color: 'var(--green)',  indexPrix:  7 },
    ]
    return scenarios.map((s) => {
      const rows = buildProjection({
        prix: selected.bien.price, apportEur: simData.apport, loyer: 0,
        chargesAn: selected.chargesAn, taux: params.taux, duree: params.duree,
        indexLoyer: params.indexLoyer, indexPrix: s.indexPrix,
        tmi: params.tmi, dureeRevente: 0, mode: 'ir_nu', fraisNotaireP: params.fraisNotaireP,
      })
      return { ...s, patrimoineAn10: rows[9].patrimoineNet, patrimoineAn20: rows[19].patrimoineNet }
    })
  }, [selected, simData, params])

  // Verdict achat vs location
  const verdict = useMemo(() => {
    if (!comparison.length || !loyerActuel) return null
    const breakEven = comparison.find((r) => r.richesseNette > 0)
    const an10 = comparison[9]
    return { breakEven: breakEven?.annee ?? null, richesseAn10: an10.richesseNette, deltaAn10: an10.delta }
  }, [comparison, loyerActuel])

  return (
    <div className="an-detail">
      {/* Header */}
      <div className="an-detail-header">
        <div className="an-detail-bien-info">
          {selected.bien.photo && (
            selected.bien.url
              ? <a href={selected.bien.url} target="_blank" rel="noopener noreferrer"><img src={selected.bien.photo} alt="" className="an-detail-photo" /></a>
              : <img src={selected.bien.photo} alt="" className="an-detail-photo" />
          )}
          <div className="an-detail-bien-text">
            {selected.bien.url
              ? <a href={selected.bien.url} target="_blank" rel="noopener noreferrer" className="an-detail-title">{selected.bien.title}</a>
              : <div className="an-detail-title">{selected.bien.title}</div>
            }
            <div className="an-detail-meta">{selected.bien.neighbourhood} · {selected.bien.surface}m² · {selected.bien.rooms}p · {eur(selected.bien.price)}</div>
          </div>
        </div>
        <div className="an-detail-right">
          <div className="an-detail-score" style={{ color: scoreColor(selected.score) }}>
            {selected.score}<span className="an-detail-score-label">/RP</span>
          </div>
          {/* DTI / finançabilité */}
          {selected.dti.revenusMensuels > 0 && (
            <div className={`an-rp-verdict-badge ${selected.dti.endettable ? 'ok' : 'nok'}`}>
              {selected.dti.endettable ? '✓ Finançable' : '✗ Hors capacité'}
            </div>
          )}
        </div>
      </div>

      {/* KPI strip */}
      <div className="an-kpi-strip">
        <KpiChip label="Mensualité"   value={`${eur(mensualite, 0)}/m`} />
        <KpiChip label="+ Charges"    value={`${eur(chargesMois, 0)}/m`} />
        <KpiChip label="Coût total"   value={`${eur(coutTotal, 0)}/m`} />
        {tauxEffort != null && (
          <KpiChip label="Taux d'effort" value={`${Math.round(tauxEffort * 100)}%`}
            color={effortColor(tauxEffort)}
            sub={tauxEffort <= 0.35 ? '✓ HCSF ok' : '✗ > 35%'} />
        )}
        {deltaVsLoc != null && (
          <KpiChip label="vs loyer actuel"
            value={`${deltaVsLoc >= 0 ? '+' : ''}${eur(deltaVsLoc, 0)}/m`}
            color={deltaVsLoc >= 0 ? 'var(--green)' : 'var(--red)'}
            sub={deltaVsLoc >= 0 ? 'achat moins cher' : 'achat plus cher'} />
        )}
        <KpiChip label="Équité an 10" value={eur(simData.rows[9]?.patrimoineNet ?? 0)} />
        <KpiChip label="Équité an 20" value={eur(simData.rows[19]?.patrimoineNet ?? 0)} />
        {decotePct != null && (
          <KpiChip label="Décote AVM" value={`${+decotePct > 0 ? '+' : ''}${decotePct}%`}
            color={selected.bien.avmRatio! < 1 ? 'var(--green)' : 'var(--red)'} />
        )}
      </div>

      {/* Bloc finançabilité visible */}
      {selected.dti.revenusMensuels > 0 && (
        <div className="an-rp-dti-bar">
          <div className="an-rp-dti-label">
            <span>Taux d'effort</span>
            <span style={{ color: selected.dti.endettable ? 'var(--green)' : 'var(--red)', fontWeight: 700 }}>
              {Math.round(selected.dti.tauxEndettement * 100)}% / 35% max HCSF
            </span>
          </div>
          <div className="an-rp-dti-track">
            <div className="an-rp-dti-fill"
              style={{
                width: `${Math.min(100, selected.dti.tauxEndettement * 100 / 0.35 * 100)}%`,
                background: selected.dti.endettable ? 'var(--green)' : 'var(--red)',
              }} />
            <div className="an-rp-dti-limit" />
          </div>
          <div className="an-rp-dti-detail">
            <span>Marge : {selected.dti.marge >= 0 ? '+' : ''}{eur(selected.dti.marge, 0)}/m</span>
            <span>Capacité emprunt : {Math.round(selected.dti.capaciteEmprunt / 1000)}k€</span>
          </div>
        </div>
      )}

      {/* Chart équité */}
      <div className="an-chart-section">
        <div className="an-chart-header">
          <span className="an-chart-title">Constitution du patrimoine</span>
          <span className="an-chart-sub">Valeur bien − capital dû = votre équité</span>
        </div>
        <ResponsiveContainer width="100%" height={130}>
          <AreaChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <defs>
              <linearGradient id="anEquiteGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%"  stopColor="var(--accent)" stopOpacity={0.28} />
                <stop offset="95%" stopColor="var(--accent)" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
            <XAxis dataKey="annee" tick={{ fontSize: 9, fill: 'var(--text-faint)' }} tickLine={false} tickFormatter={(v) => `${v}a`} />
            <YAxis tick={{ fontSize: 9, fill: 'var(--text-faint)' }} tickLine={false} axisLine={false} tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
            <Tooltip content={<ChartTooltip />} />
            <Area type="monotone" dataKey="Équité accumulée" stroke="var(--accent)" fill="url(#anEquiteGrad)" strokeWidth={2} dot={false} />
          </AreaChart>
        </ResponsiveContainer>
      </div>

      {/* Sub-tabs */}
      <div className="an-detail-tabs">
        <button className={`an-detail-tab${tab === 'mensualites' ? ' active' : ''}`} onClick={() => setTab('mensualites')}>Remboursement</button>
        <button className={`an-detail-tab${tab === 'vs-location' ? ' active' : ''}`} onClick={() => setTab('vs-location')}>
          Achat vs Location {!loyerActuel && <span style={{ opacity: 0.5, fontSize: '0.6rem' }}>(renseigne loyer)</span>}
        </button>
        <button className={`an-detail-tab${tab === 'marche' ? ' active' : ''}`} onClick={() => setTab('marche')}>Évolution marché</button>
      </div>

      <div className="an-tab-content">

        {/* Tableau amortissement simplifié */}
        {tab === 'mensualites' && (
          <div className="an-annuel-wrap">
            <table className="an-annuel-table">
              <thead>
                <tr><th>An</th><th>Valeur bien</th><th>Capital dû</th><th>Équité</th><th>Charges/an</th></tr>
              </thead>
              <tbody>
                {simData.rows.map((r) => (
                  <tr key={r.annee}>
                    <td>{r.annee}</td>
                    <td>{eur(r.valeurBien, 0)}</td>
                    <td style={{ color: 'var(--red)' }}>{eur(r.capitalRestant, 0)}</td>
                    <td style={{ fontWeight: 600, color: 'var(--accent)' }}>{eur(r.patrimoineNet, 0)}</td>
                    <td style={{ color: 'var(--text-faint)' }}>{eur(r.chargesYr, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Achat vs Location */}
        {tab === 'vs-location' && (
          <div>
            {!loyerActuel ? (
              <div className="an-rp-empty-loc">
                Renseigne ton <strong>loyer actuel</strong> dans la sidebar pour voir la comparaison achat vs location.
              </div>
            ) : (
              <>
                {/* Verdict */}
                {verdict && (
                  <div className={`an-rp-verdict ${verdict.richesseAn10 > 0 ? 'positive' : 'negative'}`}>
                    {verdict.breakEven != null
                      ? `À partir de l'an ${verdict.breakEven}, acheter vous avantage financièrement. À 10 ans : +${eur(verdict.richesseAn10)} de richesse nette vs rester locataire.`
                      : verdict.richesseAn10 > 0
                        ? `Acheter est financièrement plus intéressant dès maintenant. À 10 ans : +${eur(verdict.richesseAn10)}.`
                        : `Sur 10 ans, rester locataire reste plus avantageux (${eur(verdict.richesseAn10)}). Vérifiez le prix du bien.`
                    }
                  </div>
                )}
                <div className="an-annuel-wrap">
                  <table className="an-annuel-table">
                    <thead>
                      <tr>
                        <th>An</th>
                        <th>Loyers cumulés</th>
                        <th>Coût achat cumulé</th>
                        <th>Delta</th>
                        <th>Équité</th>
                        <th>Richesse nette</th>
                      </tr>
                    </thead>
                    <tbody>
                      {comparison.map((r) => (
                        <tr key={r.annee}>
                          <td>{r.annee}</td>
                          <td style={{ color: 'var(--red)' }}>{eur(r.loyerCumul, 0)}</td>
                          <td style={{ color: 'var(--text-dim)' }}>{eur(r.coutAchatCumul, 0)}</td>
                          <td style={{ color: r.delta >= 0 ? 'var(--green)' : 'var(--red)', fontWeight: 600 }}>
                            {r.delta >= 0 ? '+' : ''}{eur(r.delta, 0)}
                          </td>
                          <td style={{ color: 'var(--accent)' }}>{eur(r.equity, 0)}</td>
                          <td style={{ fontWeight: 700, color: r.richesseNette >= 0 ? 'var(--green)' : 'var(--red)' }}>
                            {r.richesseNette >= 0 ? '+' : ''}{eur(r.richesseNette, 0)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <div className="an-rp-cmp-note">
                  Delta = loyers cumulés − (mensualités + charges) cumulées.
                  Richesse nette = équité (patrimoine) + delta.
                  Loyer indexé à +{params.indexLoyer}%/an.
                </div>
              </>
            )}
          </div>
        )}

        {/* Scénarios marché */}
        {tab === 'marche' && (
          <div className="opt-stress-section">
            <div className="opt-van-header">
              <span className="opt-van-title">Évolution du patrimoine selon le marché</span>
              <span className="opt-van-sub">Ton équité à 10 et 20 ans selon la croissance du prix de l'immobilier</span>
            </div>
            {prixScenarios.map((s) => (
              <div key={s.label} className="opt-stress-row">
                <div className="opt-stress-label-col">
                  <span className="opt-stress-name" style={{ color: s.color }}>{s.label}</span>
                  <span className="opt-stress-hypo">prix {s.indexPrix > 0 ? '+' : ''}{s.indexPrix}%/an</span>
                </div>
                <div className="opt-stress-kpis">
                  <div className="opt-stress-kpi">
                    <span className="opt-stress-kpi-label">Équité an 10</span>
                    <span className="opt-stress-kpi-val" style={{ color: s.color }}>{eur(s.patrimoineAn10)}</span>
                  </div>
                  <div className="opt-stress-kpi">
                    <span className="opt-stress-kpi-label">Équité an 20</span>
                    <span className="opt-stress-kpi-val" style={{ color: s.color }}>{eur(s.patrimoineAn20)}</span>
                  </div>
                </div>
                <div className="opt-stress-bar-wrap">
                  <div className="opt-stress-bar"
                    style={{ width: `${Math.min(100, Math.max(0, s.patrimoineAn10 / (selected.bien.price * 2) * 100))}%`, background: s.color }} />
                </div>
              </div>
            ))}
          </div>
        )}

      </div>
    </div>
  )
}

// ──────────────────────────────────────────────────────────────────────────────
// Drag-to-resize
// ──────────────────────────────────────────────────────────────────────────────

function useDrag(initial: number, min: number, max: number, dir: 'x' | 'y') {
  const [size, setSize] = useState(initial)
  const anchor = useRef<{ pos: number; init: number } | null>(null)

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    anchor.current = { pos: dir === 'x' ? e.clientX : e.clientY, init: size }
    const move = (ev: MouseEvent) => {
      if (!anchor.current) return
      const d = (dir === 'x' ? ev.clientX : ev.clientY) - anchor.current.pos
      setSize(Math.max(min, Math.min(max, anchor.current.init + d)))
    }
    const up = () => {
      anchor.current = null
      window.removeEventListener('mousemove', move)
      window.removeEventListener('mouseup', up)
    }
    window.addEventListener('mousemove', move)
    window.addEventListener('mouseup', up)
  }, [size, min, max, dir])

  return [size, onMouseDown] as const
}

function ResizeHandle({ dir, onMouseDown }: {
  dir: 'x' | 'y'
  onMouseDown: (e: React.MouseEvent) => void
}) {
  return (
    <div className={`an-resize-handle an-resize-handle-${dir}`} onMouseDown={onMouseDown}>
      <div className="an-resize-grip" />
    </div>
  )
}

// ══════════════════════════════════════════════════════════════════════════════
// ONGLET PRINCIPAL
// ══════════════════════════════════════════════════════════════════════════════

export function AnalyseTab() {
  const {
    profilAcquisition, setProfilAcquisition,
    salaireNet: storeSalaireNet, setSalaireNet,
    dettesExistantes: storeDettes, setDettesExistantes,
    simPreselect, setSimPreselect,
    simParams,
    hidden, locationEdits,
  } = useStore()

  // Catalog réactif : exclut structurés, cachés et applique les corrections de quartier
  const catalog = useMemo((): CatalogBien[] => [
    ...APPARTS
      .filter((r) => r.price && r.surface && !r.is_structured && !hidden[r.id])
      .map((r): CatalogBien => ({
        id: r.id, type: 'appart', title: r.title,
        price: r.price, surface: r.surface, rooms: r.rooms,
        neighbourhood: locationEdits[r.id] ?? r.neighbourhood,
        yieldPct: r.yield ?? null,
        avmRatio: r.avm_ratio ?? null, photo: r.photos?.[0] ?? null, url: r.url,
      })),
    ...MAISONS
      .filter((r) => r.prix && r.surface && !hidden[`m_${r.id}`])
      .map((r): CatalogBien => ({
        id: `m_${r.id}`, type: 'maison', title: r.titre ?? r.adresse_raw,
        price: r.prix, surface: r.surface, rooms: r.pieces,
        neighbourhood: locationEdits[`m_${r.id}`] ?? r.neighbourhood,
        yieldPct: r.yield ?? null,
        avmRatio: r.avm_ratio ?? null, photo: r.photos?.[0] ?? null, url: r.url ?? null,
      })),
  ], [hidden, locationEdits])

  const profil  = profilAcquisition ?? 'locatif'
  const profile = PROFILES.find((p) => p.id === profil)!
  const isRP    = profil === 'rp'

  const [params, setParams] = useState<OptimParams>({
    budget: 2_000_000,
    apportEur: simParams.apportEur,
    taux: simParams.taux,
    duree: simParams.duree,
    tmi: simParams.tmi,
    fraisNotaireP: simParams.fraisNotaireP,
    indexLoyer: simParams.indexLoyer,
    indexPrix: simParams.indexPrix,
    salaireNet: storeSalaireNet,
    dettesExistantes: storeDettes,
  })

  const [loyerActuel, setLoyerActuel] = useState(0)

  const sp = useCallback((p: Partial<OptimParams>) => {
    setParams((prev) => ({ ...prev, ...p }))
    if (p.salaireNet        !== undefined) setSalaireNet(p.salaireNet)
    if (p.dettesExistantes  !== undefined) setDettesExistantes(p.dettesExistantes)
  }, [setSalaireNet, setDettesExistantes])

  const [ran, setRan]         = useState(false)
  const [running, setRunning] = useState(false)
  const [results, setResults] = useState<BienOptimResult[]>([])
  const [selected, setSelected] = useState<BienOptimResult | null>(null)
  const [simOverrides, setSimOverrides] = useState<SimOverrides | null>(null)

  const so = useCallback((p: Partial<SimOverrides>) =>
    setSimOverrides((prev) => prev ? { ...prev, ...p } : null), [])

  const inBudget = useMemo(() =>
    catalog.filter((b) => b.price <= params.budget && b.price > 0).length, [catalog, params.budget])

  const [sidebarW, onSidebarDrag] = useDrag(300, 180, 520, 'x')
  const [rankH,    onRankDrag]    = useDrag(280, 80, 540, 'y')

  const [filterType,     setFilterType]     = useState<'all' | 'appart' | 'maison'>('all')
  const [filterSecteurs, setFilterSecteurs] = useState<Set<string>>(new Set())
  const [filterBudget,   setFilterBudget]   = useState(params.budget)

  const toggleSecteur = useCallback((s: string) => {
    setFilterSecteurs((prev) => {
      const next = new Set(prev)
      if (next.has(s)) next.delete(s)
      else next.add(s)
      return next
    })
  }, [])

  const [sortCol, setSortCol] = useState('score')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const handleSort = useCallback((col: string) => {
    setSortCol((prev) => {
      if (prev === col) setSortDir((d) => d === 'desc' ? 'asc' : 'desc')
      else setSortDir('desc')
      return col
    })
  }, [])

  const sortedResults = useMemo(() => {
    const val = (r: BienOptimResult): number => {
      switch (sortCol) {
        case 'score':      return r.score
        case 'tri':        return r.triOpt ?? -Infinity
        case 'cf':         return r.cfMois1
        case 'decote':     return r.bien.avmRatio != null ? 1 - r.bien.avmRatio : -Infinity
        case 'effort':     return r.tauxEffort ?? Infinity
        case 'mensualite': return r.mensualite
        case 'financable': return r.dti.revenusMensuels > 0 ? (r.dti.endettable ? 1 : 0) : -1
        default:           return r.score
      }
    }
    return [...results].sort((a, b) => sortDir === 'desc' ? val(b) - val(a) : val(a) - val(b))
  }, [results, sortCol, sortDir])

  const handleSelect = useCallback((r: BienOptimResult) => {
    setSelected(r)
    setSimOverrides({
      loyer:       r.loyer,           // 0 for RP (set in optimizer)
      chargesAn:   r.chargesAn,
      mode:        r.optMode,
      revente:     r.optRevente || 15,
      planRevente: r.loyer > 0,       // only relevant for locatif
    })
  }, [])

  const runAnalysis = useCallback((overrideProf?: ProfilAcquisition, preselId?: string) => {
    const p = overrideProf ?? profil
    setRunning(true)
    setTimeout(() => {
      const res = rankBiens(catalog, params, p)
      setResults(res)
      setRan(true)
      setRunning(false)
      const toSel = preselId
        ? (res.find((r) => r.bien.id === preselId || r.bien.id === `m_${preselId}`) ?? res[0])
        : res[0]
      if (toSel) handleSelect(toSel)
    }, 10)
  }, [catalog, params, profil, handleSelect])

  const handleProfileChange = useCallback((p: ProfilAcquisition) => {
    setProfilAcquisition(p)
    runAnalysis(p)
  }, [runAnalysis, setProfilAcquisition])

  // Auto-run on mount
  useEffect(() => { runAnalysis() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Handle navigation from ComparateurTab / BiensTab
  useEffect(() => {
    if (simPreselect) {
      const id = simPreselect
      setSimPreselect(null)
      runAnalysis(undefined, id)
    }
  }, [simPreselect]) // eslint-disable-line react-hooks/exhaustive-deps

  // Simulation projection — reactive to overrides + params
  const simData = useMemo((): SimData | null => {
    if (!selected || !simOverrides) return null
    const revente   = simOverrides.planRevente ? simOverrides.revente : 0
    const apportEff = Math.min(params.apportEur, selected.bien.price)
    const rows = buildProjection({
      prix: selected.bien.price, apportEur: apportEff,
      loyer: simOverrides.loyer, chargesAn: simOverrides.chargesAn,
      taux: params.taux, duree: params.duree,
      indexLoyer: params.indexLoyer, indexPrix: params.indexPrix,
      tmi: params.tmi, dureeRevente: revente,
      mode: simOverrides.mode, fraisNotaireP: params.fraisNotaireP,
    })
    const tri  = computeTRI(apportEff, selected.bien.price, params.fraisNotaireP, rows, revente)
    const van5 = computeVAN(apportEff, selected.bien.price, params.fraisNotaireP, rows, revente, 0.05)
    const van8 = computeVAN(apportEff, selected.bien.price, params.fraisNotaireP, rows, revente, 0.08)
    return { rows, tri, van5, van8, cfMois1: rows[0].cashflowAn / 12, mensualite: rows[0].mensualite, apport: apportEff, revente }
  }, [selected, simOverrides, params])

  const availableSecteurs = useMemo(() => {
    const ns = new Set<string>()
    sortedResults.forEach((r) => { if (r.bien.neighbourhood) ns.add(r.bien.neighbourhood) })
    return [...ns].sort()
  }, [sortedResults])

  const filteredResults = useMemo(() => sortedResults.filter((r) => {
    if (filterType !== 'all' && r.bien.type !== filterType) return false
    if (filterSecteurs.size > 0 && !filterSecteurs.has(r.bien.neighbourhood ?? '')) return false
    if (filterBudget > 0 && r.bien.price > filterBudget) return false
    return true
  }), [sortedResults, filterType, filterSecteurs, filterBudget])

  return (
    <div className="sim-page">
      <div className="an-layout" style={{ gridTemplateColumns: `${sidebarW}px 5px 1fr` }}>

        {/* ── Sidebar ── */}
        <aside className="sim-sidebar">

          {/* Profil */}
          <div className="sim-group">
            <div className="sim-group-title">Profil acquéreur</div>
            <div className="opt-profiles">
              {PROFILES.map((p) => (
                <ProfileCard key={p.id} profil={p} active={profil === p.id}
                  onClick={() => handleProfileChange(p.id)} />
              ))}
            </div>
          </div>

          {/* Paramètres */}
          <div className="sim-group">
            <div className="sim-group-title">Paramètres</div>

            <div className="sim-field">
              <div className="sim-field-header">
                <label className="sim-field-label">Budget max</label>
                <span className="sim-field-curval">{Math.round(params.budget / 1000)}k€ · {inBudget} biens</span>
              </div>
              <input type="range" className="sim-range" min={200_000} max={3_000_000} step={50_000}
                value={params.budget} onChange={(e) => sp({ budget: +e.target.value })}
                style={{ accentColor: 'var(--accent)' }} />
            </div>

            <div className="sim-field">
              <label className="sim-field-label">Apport disponible</label>
              <div className="sim-field-wrap">
                <input type="number" className="sim-field-input" value={params.apportEur} step={10000}
                  onChange={(e) => sp({ apportEur: Math.max(0, +e.target.value || 0) })} />
                <span className="sim-field-suffix">€</span>
              </div>
            </div>

            {/* Loyer actuel — RP seulement */}
            {isRP && (
              <div className="sim-field">
                <label className="sim-field-label">Ton loyer actuel</label>
                <div className="sim-field-wrap">
                  <input type="number" className="sim-field-input" value={loyerActuel || ''}
                    placeholder="0" step={50}
                    onChange={(e) => setLoyerActuel(Math.max(0, +e.target.value || 0))} />
                  <span className="sim-field-suffix">€/m</span>
                </div>
                <div className="sim-field-hint">Sert à comparer achat vs location</div>
              </div>
            )}

            <div className="sim-field">
              <div className="sim-field-header">
                <label className="sim-field-label">Taux crédit</label>
                <span className="sim-field-curval">{params.taux.toFixed(1)}%</span>
              </div>
              <input type="range" className="sim-range" min={0.5} max={7} step={0.1}
                value={params.taux} onChange={(e) => sp({ taux: +e.target.value })}
                style={{ accentColor: 'var(--accent)' }} />
            </div>

            <div className="sim-field">
              <div className="sim-field-header">
                <label className="sim-field-label">Durée</label>
                <span className="sim-field-curval">{params.duree} ans</span>
              </div>
              <input type="range" className="sim-range" min={5} max={30} step={1}
                value={params.duree} onChange={(e) => sp({ duree: +e.target.value })}
                style={{ accentColor: 'var(--accent)' }} />
            </div>

            {/* TMI — masqué en RP */}
            {!isRP && (
              <div className="sim-field">
                <label className="sim-field-label">TMI</label>
                <div className="sim-tmi-pills">
                  {[0, 11, 30, 41, 45].map((t) => (
                    <button key={t} className={`sim-tmi-pill${params.tmi === t ? ' active' : ''}`}
                      onClick={() => sp({ tmi: t })}>{t}%</button>
                  ))}
                </div>
              </div>
            )}

            <div className="sim-field">
              <div className="sim-field-header">
                <label className="sim-field-label">Frais notaire</label>
                <span className="sim-field-curval">{params.fraisNotaireP.toFixed(1)}%</span>
              </div>
              <input type="range" className="sim-range" min={2} max={9} step={0.5}
                value={params.fraisNotaireP} onChange={(e) => sp({ fraisNotaireP: +e.target.value })}
                style={{ accentColor: 'var(--accent)' }} />
            </div>
          </div>

          {/* Ajustements — visible après sélection d'un bien */}
          {selected && simOverrides && (
            <div className="sim-group">
              <div className="sim-group-title">Ajustements</div>
              <div className="an-adj-label">{selected.bien.title}</div>

              {/* Loyer — locatif seulement */}
              {!isRP && (
                <div className="sim-field">
                  <label className="sim-field-label">Loyer mensuel estimé</label>
                  <div className="sim-field-wrap">
                    <input type="number" className="sim-field-input" value={simOverrides.loyer} step={50}
                      onChange={(e) => so({ loyer: Math.max(0, +e.target.value || 0) })} />
                    <span className="sim-field-suffix">€/m</span>
                  </div>
                  <div className="sim-field-hint">
                    {(simOverrides.loyer * 12 / selected.bien.price * 100).toFixed(2)}% brut
                  </div>
                </div>
              )}

              <div className="sim-field">
                <label className="sim-field-label">{isRP ? 'Charges annuelles (copro, TF…)' : 'Charges annuelles'}</label>
                <div className="sim-field-wrap">
                  <input type="number" className="sim-field-input" value={simOverrides.chargesAn} step={100}
                    onChange={(e) => so({ chargesAn: Math.max(0, +e.target.value || 0) })} />
                  <span className="sim-field-suffix">€/an</span>
                </div>
              </div>

              {/* Régime fiscal — locatif seulement */}
              {!isRP && (
                <div className="sim-field">
                  <label className="sim-field-label">Régime fiscal</label>
                  <div className="sim-tmi-pills" style={{ flexWrap: 'wrap' }}>
                    {FISCAL_IDS.map((m) => (
                      <button key={m} className={`sim-tmi-pill${simOverrides.mode === m ? ' active' : ''}`}
                        onClick={() => so({ mode: m })}>
                        {FISCAL_LABELS[m]}
                      </button>
                    ))}
                  </div>
                </div>
              )}

              {/* Plan revente — locatif seulement */}
              {!isRP && (
                <>
                  <div className="sim-field">
                    <label className="sim-field-label">Plan de revente</label>
                    <div className="sim-revente-toggle">
                      <button className={`sim-revente-pill${simOverrides.planRevente ? ' active' : ''}`}
                        onClick={() => so({ planRevente: true })}>Oui</button>
                      <button className={`sim-revente-pill${!simOverrides.planRevente ? ' active' : ''}`}
                        onClick={() => so({ planRevente: false })}>Non</button>
                    </div>
                  </div>
                  {simOverrides.planRevente && (
                    <div className="sim-field">
                      <div className="sim-field-header">
                        <label className="sim-field-label">Année de revente</label>
                        <span className="sim-field-curval">An {simOverrides.revente}</span>
                      </div>
                      <input type="range" className="sim-range" min={1} max={20} step={1}
                        value={simOverrides.revente} onChange={(e) => so({ revente: +e.target.value })}
                        style={{ accentColor: 'var(--accent)' }} />
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* Capacité d'emprunt */}
          <div className="sim-group">
            <div className="sim-group-title">{isRP ? 'Finançabilité' : 'Capacité d\'emprunt'}</div>

            <div className="sim-field">
              <label className="sim-field-label">Salaire mensuel net</label>
              <div className="sim-field-wrap">
                <input type="number" className="sim-field-input" value={params.salaireNet || ''}
                  step={100} placeholder="0"
                  onChange={(e) => sp({ salaireNet: Math.max(0, +e.target.value || 0) })} />
                <span className="sim-field-suffix">€/m</span>
              </div>
            </div>

            <div className="sim-field">
              <label className="sim-field-label">Mensualités existantes</label>
              <div className="sim-field-wrap">
                <input type="number" className="sim-field-input" value={params.dettesExistantes || ''}
                  step={50} placeholder="0"
                  onChange={(e) => sp({ dettesExistantes: Math.max(0, +e.target.value || 0) })} />
                <span className="sim-field-suffix">€/m</span>
              </div>
            </div>

            {params.salaireNet > 0 && (() => {
              const r = (params.taux / 100) / 12
              const n = params.duree * 12
              const mensMax = Math.max(0, params.salaireNet * 0.35 - params.dettesExistantes)
              const cap = r > 0
                ? Math.round(mensMax * (1 - Math.pow(1 + r, -n)) / r / 1000) * 1000
                : Math.round(mensMax * n / 1000) * 1000
              return (
                <div className="opt-dti-summary">
                  <span className="opt-dti-summary-label">Mensualité max</span>
                  <span className="opt-dti-summary-val">{Math.round(mensMax)} €/mois</span>
                  <span className="opt-dti-summary-label">Capacité emprunt</span>
                  <span className="opt-dti-summary-val">{Math.round(cap / 1000)}k€</span>
                </div>
              )
            })()}
          </div>

          {/* CTA */}
          <button className="opt-run-btn" onClick={() => runAnalysis()} disabled={running}>
            {running
              ? <span>Calcul en cours…</span>
              : <><Zap size={14} /> {isRP ? 'Rechercher' : 'Analyser'} {inBudget} biens <ChevronRight size={14} /></>
            }
          </button>

        </aside>
        <ResizeHandle dir="x" onMouseDown={onSidebarDrag} />

        {/* ── Main ── */}
        <main className="an-main">

          {!ran && (
            <div className="opt-empty">
              <div className="opt-empty-icon" style={{ opacity: running ? 0.5 : 1 }}>{PROFILE_ICONS[profil]}</div>
              <div className="opt-empty-title">{running ? 'Analyse en cours…' : profile.label}</div>
              {!running && <div className="opt-empty-desc">{profile.description}</div>}
            </div>
          )}

          {ran && results.length === 0 && (
            <div className="opt-empty">
              <div className="opt-empty-title">Aucun bien dans ce budget</div>
              <div className="opt-empty-desc">Augmente le budget maximum dans la sidebar.</div>
            </div>
          )}

          {ran && results.length > 0 && (
            <>
              {/* Filter bar */}
              <div className="an-filter-bar">
                <span className="an-filter-label">Budget</span>
                <div className="an-filter-budget">
                  <input
                    type="number" className="an-filter-budget-input"
                    value={Math.round(filterBudget / 1000)} step={50}
                    onChange={(e) => setFilterBudget(Math.max(0, (+e.target.value || 0) * 1000))}
                  />
                  <span className="an-filter-label">k€</span>
                </div>

                <div className="an-filter-sep" />

                <span className="an-filter-label">Type</span>
                <div className="an-filter-pills">
                  {(['all', 'appart', 'maison'] as const).map((t) => (
                    <button key={t}
                      className={`an-filter-pill${filterType === t ? ' active' : ''}`}
                      onClick={() => setFilterType(t)}>
                      {t === 'all' ? 'Tous' : t === 'appart' ? 'Apparts' : 'Maisons'}
                    </button>
                  ))}
                </div>

                {availableSecteurs.length > 1 && (
                  <>
                    <div className="an-filter-sep" />
                    <span className="an-filter-label">Secteur</span>
                    <div className="an-filter-pills an-filter-pills-wrap">
                      {availableSecteurs.map((s) => (
                        <button key={s}
                          className={`an-filter-pill${filterSecteurs.has(s) ? ' active' : ''}`}
                          onClick={() => toggleSecteur(s)}>
                          {s}
                        </button>
                      ))}
                      {filterSecteurs.size > 0 && (
                        <button className="an-filter-pill an-filter-pill-clear"
                          onClick={() => setFilterSecteurs(new Set())}>
                          ✕
                        </button>
                      )}
                    </div>
                  </>
                )}
              </div>

              {/* Ranking */}
              <div className="an-ranking-wrap" style={{ maxHeight: `${rankH}px` }}>
                <div className="an-ranking-header">
                  <span>
                    {filteredResults.length}
                    {filteredResults.length !== results.length && <span className="an-ranking-sub"> / {results.length}</span>}
                    {' '}biens · {profile.label}
                  </span>
                  <span className="an-ranking-sub">
                    {isRP
                      ? '30% abordabilité · 20% décote · 50% confort'
                      : `${Math.round(profile.weights.tri * 100)}% TRI · ${Math.round(profile.weights.decote * 100)}% décote · ${Math.round(profile.weights.confort * 100)}% confort`
                    }
                  </span>
                </div>
                <table className="an-rank-table">
                  <thead>
                    <tr>
                      <th className="an-sort-th">#</th>
                      <th className="an-sort-th">Bien</th>
                      <SortTh col="score"     label="Score"      active={sortCol === 'score'}     dir={sortDir} onSort={handleSort} />
                      {isRP ? (
                        <>
                          <SortTh col="effort"     label="Effort"     active={sortCol === 'effort'}     dir={sortDir} onSort={handleSort} />
                          <SortTh col="mensualite" label="Mensualité" active={sortCol === 'mensualite'} dir={sortDir} onSort={handleSort} />
                          <SortTh col="financable" label="Finançable" active={sortCol === 'financable'} dir={sortDir} onSort={handleSort} />
                        </>
                      ) : (
                        <>
                          <SortTh col="tri"        label="TRI"        active={sortCol === 'tri'}        dir={sortDir} onSort={handleSort} />
                          <SortTh col="cf"         label="CF/mois"    active={sortCol === 'cf'}         dir={sortDir} onSort={handleSort} />
                          <SortTh col="decote"     label="Décote"     active={sortCol === 'decote'}     dir={sortDir} onSort={handleSort} />
                          <SortTh col="financable" label="Finançable" active={sortCol === 'financable'} dir={sortDir} onSort={handleSort} />
                        </>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {filteredResults.map((r, i) => (
                      <RankRow key={r.bien.id} r={r} rank={i + 1} isRP={isRP}
                        selected={selected?.bien.id === r.bien.id}
                        onClick={() => handleSelect(r)} />
                    ))}
                  </tbody>
                </table>
              </div>
              <ResizeHandle dir="y" onMouseDown={onRankDrag} />

              {/* Simulation detail */}
              {selected && simData && simOverrides && (
                isRP
                  ? <SimDetailRP selected={selected} simData={simData} params={params} loyerActuel={loyerActuel} />
                  : <SimDetail selected={selected} simData={simData} simOverrides={simOverrides} params={params} profil={profil} />
              )}
            </>
          )}

        </main>
      </div>
    </div>
  )
}
