import { useState, useMemo, useCallback } from 'react'
import { eur } from '@/lib/utils'
import { APPARTS, MAISONS } from '@/lib/data'
import { useStore } from '@/store/useStore'
import { Zap, ChevronRight, Building2, Home, Info, TrendingUp, Gem, Scale, Hammer, Award } from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceLine,
} from 'recharts'
import {
  PROFILES, rankBiens, computeStressTest,
  computeSensitivity, computeVanCurve, computeEndettement,
  confortScore, decoteScore, triScore,
  SENS_APPORT_PCTS, SENS_TAUX,
  type CatalogBien, type BienOptimResult, type ProfilAcquisition, type OptimParams,
} from '@/lib/optimizer'

// ── Catalog ───────────────────────────────────────────────────────────────────

const CATALOG: CatalogBien[] = [
  ...APPARTS.filter((r) => r.price && r.surface).map((r): CatalogBien => ({
    id: r.id, type: 'appart', title: r.title,
    price: r.price, surface: r.surface, rooms: r.rooms,
    neighbourhood: r.neighbourhood, yieldPct: r.yield ?? null,
    avmRatio: r.avm_ratio ?? null, photo: r.photos?.[0] ?? null, url: r.url,
  })),
  ...MAISONS.filter((r) => r.prix && r.surface).map((r): CatalogBien => ({
    id: `m_${r.id}`, type: 'maison', title: r.titre ?? r.adresse_raw,
    price: r.prix, surface: r.surface, rooms: r.pieces,
    neighbourhood: r.neighbourhood, yieldPct: r.yield ?? null,
    avmRatio: r.avm_ratio ?? null, photo: r.photos?.[0] ?? null, url: r.url ?? null,
  })),
]

// ── Score bar ─────────────────────────────────────────────────────────────────

function ScoreBar({ value, max = 100, color = 'var(--accent)' }: { value: number; max?: number; color?: string }) {
  const pct = Math.round((value / max) * 100)
  return (
    <div className="opt-scorebar">
      <div className="opt-scorebar-fill" style={{ width: `${pct}%`, background: color }} />
    </div>
  )
}

function scoreColor(s: number): string {
  if (s >= 70) return 'var(--green)'
  if (s >= 50) return 'var(--accent)'
  if (s >= 35) return 'var(--amber)'
  return 'var(--red)'
}

function triColor(tri: number | null): string {
  if (tri == null) return 'var(--text-faint)'
  if (tri >= 8) return 'var(--green)'
  if (tri >= 5) return 'var(--accent)'
  if (tri >= 3) return 'var(--amber)'
  return 'var(--red)'
}

function vanColor(van: number): string {
  return van > 0 ? 'var(--green)' : 'var(--red)'
}

function triCellBg(tri: number | null): string {
  if (tri == null) return 'var(--surface-3)'
  if (tri >= 9)  return 'oklch(0.52 0.155 152 / 0.35)'
  if (tri >= 7)  return 'oklch(0.52 0.155 152 / 0.20)'
  if (tri >= 5)  return 'oklch(0.72 0.095 72  / 0.25)'
  if (tri >= 3)  return 'oklch(0.72 0.18  72  / 0.18)'
  if (tri >= 0)  return 'oklch(0.64 0.17  40  / 0.15)'
  return 'oklch(0.64 0.17 40 / 0.30)'
}

// ── VAN chart tooltip ─────────────────────────────────────────────────────────

function VanTooltip({ active, payload, label }: {
  active?: boolean
  payload?: { value: number }[]
  label?: number
}) {
  if (!active || !payload?.length) return null
  const v = payload[0].value
  return (
    <div className="sim-tooltip">
      <div className="sim-tooltip-year">Taux {label} %</div>
      <div className="sim-tooltip-row">
        <span style={{ color: v >= 0 ? 'var(--green)' : 'var(--red)' }}>VAN</span>
        <span className="sim-tooltip-val" style={{ color: v >= 0 ? 'var(--green)' : 'var(--red)' }}>{eur(v)}</span>
      </div>
    </div>
  )
}

// ── Profile card ──────────────────────────────────────────────────────────────

const PROFILE_ICONS: Record<string, React.ReactNode> = {
  locatif:  <TrendingUp size={14} />,
  valeur:   <Gem size={14} />,
  rp:       <Home size={14} />,
  mixte:    <Scale size={14} />,
  marchand: <Hammer size={14} />,
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

// ── Bien row in ranking table ─────────────────────────────────────────────────

function RankRow({ r, rank, selected, onClick }: {
  r: BienOptimResult; rank: number; selected: boolean; onClick: () => void
}) {
  const decotePct = r.bien.avmRatio != null
    ? ((1 - r.bien.avmRatio) * 100).toFixed(0)
    : null
  return (
    <tr className={`opt-rank-row${selected ? ' selected' : ''}`} onClick={onClick}>
      <td className="opt-rank-num">{rank}</td>
      <td className="opt-rank-bien">
        {r.bien.photo
          ? <img src={r.bien.photo} alt="" className="opt-rank-photo" />
          : <div className="opt-rank-photo-ph">{r.bien.type === 'appart' ? <Building2 size={10} /> : <Home size={10} />}</div>
        }
        <div className="opt-rank-info">
          <div className="opt-rank-title">{r.bien.title}</div>
          <div className="opt-rank-meta">{r.bien.neighbourhood} · {r.bien.surface}m² · {Math.round(r.bien.price / 1000)}k€</div>
        </div>
      </td>
      <td className="opt-rank-score-cell">
        <span className="opt-rank-score-val" style={{ color: scoreColor(r.score) }}>{r.score}</span>
        <ScoreBar value={r.score} color={scoreColor(r.score)} />
      </td>
      <td className="opt-rank-num" style={{ color: triColor(r.triOpt) }}>
        {r.triOpt != null ? `${r.triOpt.toFixed(1)}%` : '—'}
      </td>
      <td className="opt-rank-num" style={{ color: r.bien.avmRatio != null ? (r.bien.avmRatio < 1 ? 'var(--green)' : 'var(--red)') : 'var(--text-faint)' }}>
        {decotePct != null ? `${+decotePct > 0 ? '+' : ''}${decotePct}%` : '—'}
      </td>
      <td className="opt-rank-num" style={{ color: r.cfMois1 >= 0 ? 'var(--green)' : 'var(--red)' }}>
        {r.cfMois1 >= 0 ? '+' : ''}{eur(r.cfMois1, 0)}/m
      </td>
      <td className="opt-rank-mode-cell">
        <span className="opt-rank-mode-badge">{r.optModeLabel}</span>
      </td>
      <td className="opt-rank-dti-cell">
        {r.dti.revenusMensuels > 0
          ? <DtiBadge dti={r.dti} />
          : <span className="opt-dti-na">—</span>
        }
      </td>
    </tr>
  )
}

function DtiBadge({ dti }: { dti: import('@/lib/optimizer').DTIResult }) {
  const pct = Math.round(dti.tauxEndettement * 100)
  const color = dti.endettable
    ? pct <= 28 ? 'var(--green)' : 'var(--accent)'
    : 'var(--red)'
  return (
    <div className="opt-dti-badge" style={{ borderColor: color, color }}>
      <span className="opt-dti-pct">{pct}%</span>
      <span className="opt-dti-icon">{dti.endettable ? '✓' : '✗'}</span>
    </div>
  )
}

// ── Detail tabs ───────────────────────────────────────────────────────────────

type DetailTab = 'params' | 'van' | 'stress' | 'sensib'

function DetailPanel({ result, params, profil }: {
  result: BienOptimResult; params: OptimParams; profil: ProfilAcquisition
}) {
  const [tab, setTab] = useState<DetailTab>('params')
  const profile = PROFILES.find((p) => p.id === profil)!

  const stress  = useMemo(() => computeStressTest(result.bien, result, params), [result, params])
  const sens    = useMemo(() => computeSensitivity(result.bien, result, params), [result, params])
  const vanCurve = useMemo(() => computeVanCurve(result.bien, result, params), [result, params])

  const breakEvenRate = useMemo(() => {
    for (let i = 0; i < vanCurve.length - 1; i++) {
      if (vanCurve[i].van >= 0 && vanCurve[i + 1].van < 0) {
        return +vanCurve[i].discountRate.toFixed(1)
      }
    }
    return null
  }, [vanCurve])

  const fraisNot   = result.bien.price * params.fraisNotaireP / 100
  const investTotal = result.optApport + fraisNot
  const ts = triScore(result.triOpt)
  const ds = decoteScore(result.bien.avmRatio)
  const cs = confortScore(result.bien)

  return (
    <div className="opt-detail">
      {/* Header */}
      <div className="opt-detail-header">
        <div className="opt-detail-bien-info">
          {result.bien.photo && (
            result.bien.url
              ? <a href={result.bien.url} target="_blank" rel="noopener noreferrer">
                  <img src={result.bien.photo} alt="" className="opt-detail-photo" />
                </a>
              : <img src={result.bien.photo} alt="" className="opt-detail-photo" />
          )}
          <div>
            {result.bien.url
              ? <a href={result.bien.url} target="_blank" rel="noopener noreferrer" className="opt-detail-title-link">{result.bien.title}</a>
              : <div className="opt-detail-title">{result.bien.title}</div>
            }
            <div className="opt-detail-meta">
              {result.bien.neighbourhood} · {result.bien.surface}m² · {result.bien.rooms}p · {eur(result.bien.price)}
            </div>
          </div>
        </div>
        <div className="opt-detail-score-block">
          <div className="opt-detail-score-val" style={{ color: scoreColor(result.score) }}>{result.score}</div>
          <div className="opt-detail-score-label">Score {profile.label}</div>
        </div>
      </div>

      {/* Score breakdown */}
      <div className="opt-score-breakdown">
        <div className="opt-score-dim">
          <span className="opt-score-dim-label">{profile.triLabel}</span>
          <div className="opt-score-dim-bar">
            <div className="opt-score-dim-fill" style={{ width: `${ts * 100}%`, background: triColor(result.triOpt) }} />
          </div>
          <span className="opt-score-dim-val" style={{ color: triColor(result.triOpt) }}>
            {result.triOpt != null ? `${result.triOpt.toFixed(1)}%` : '—'}
          </span>
          <span className="opt-score-dim-weight">×{Math.round(profile.weights.tri * 100)}%</span>
        </div>
        <div className="opt-score-dim">
          <span className="opt-score-dim-label">{profile.decoteLabel}</span>
          <div className="opt-score-dim-bar">
            <div className="opt-score-dim-fill" style={{
              width: `${ds * 100}%`,
              background: result.bien.avmRatio != null && result.bien.avmRatio < 1 ? 'var(--green)' : 'var(--amber)',
            }} />
          </div>
          <span className="opt-score-dim-val" style={{ color: result.bien.avmRatio != null && result.bien.avmRatio < 1 ? 'var(--green)' : 'var(--amber)' }}>
            {result.bien.avmRatio != null ? `${((1 - result.bien.avmRatio) * 100).toFixed(0)}%` : '—'}
          </span>
          <span className="opt-score-dim-weight">×{Math.round(profile.weights.decote * 100)}%</span>
        </div>
        <div className="opt-score-dim">
          <span className="opt-score-dim-label">{profile.confortLabel}</span>
          <div className="opt-score-dim-bar">
            <div className="opt-score-dim-fill" style={{ width: `${cs * 100}%`, background: 'oklch(0.65 0.18 275)' }} />
          </div>
          <span className="opt-score-dim-val" style={{ color: 'oklch(0.65 0.18 275)' }}>
            {Math.round(cs * 10)}/10
          </span>
          <span className="opt-score-dim-weight">×{Math.round(profile.weights.confort * 100)}%</span>
        </div>
      </div>

      {/* Tabs */}
      <div className="opt-detail-tabs">
        {(['params', 'van', 'stress', 'sensib'] as DetailTab[]).map((t) => (
          <button key={t} className={`opt-detail-tab${tab === t ? ' active' : ''}`} onClick={() => setTab(t)}>
            {{ params: 'Paramètres', van: 'VAN', stress: 'Stress test', sensib: 'Sensibilité' }[t]}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div className="opt-detail-content">

        {/* Paramètres optimaux */}
        {tab === 'params' && (
          <>
            <div className="opt-params-grid">
              <OptKpi label="Apport optimal" value={eur(result.optApport)} sub={`${Math.round(result.optApport / result.bien.price * 100)}% du prix`} />
              <OptKpi label="Pour CF = 0" value={eur(result.apport0)} sub="apport minimum" color={result.apport0 <= result.optApport ? 'var(--green)' : 'var(--amber)'} />
              <OptKpi label="Régime optimal" value={result.optModeLabel} sub="pour ce profil" />
              <OptKpi label="Revente optimale" value={`An ${result.optRevente}`} sub="TRI maximum" />
              <OptKpi label="TRI estimé" value={result.triOpt != null ? `${result.triOpt.toFixed(1)} %` : '—'} color={triColor(result.triOpt)} big />
              <OptKpi label="Cashflow mois 1" value={`${result.cfMois1 >= 0 ? '+' : ''}${eur(result.cfMois1, 0)}/mois`}
                color={result.cfMois1 >= 0 ? 'var(--green)' : 'var(--red)'} big />
              <OptKpi label="Loyer estimé" value={`${eur(result.loyer)}/mois`} sub={`${(result.loyer * 12 / result.bien.price * 100).toFixed(1)}% brut`} />
              <OptKpi label="Mensualité" value={`${eur(result.mensualite)}/mois`} sub={`${params.taux}% sur ${params.duree}ans`} />
              <OptKpi label="Invest. total" value={eur(investTotal)} sub={`apport + notaire ${params.fraisNotaireP}%`} />
              <OptKpi label="VAN @ 5 %" value={eur(result.van5)} color={vanColor(result.van5)} sub="vs bourse 5%" />
              <OptKpi label="VAN @ 8 %" value={eur(result.van8)} color={vanColor(result.van8)} sub="vs bourse 8%" />
              {breakEvenRate != null
                ? <OptKpi label="TRI équiv. bourse" value={`${breakEvenRate} %`} sub="taux d'indifférence" color="var(--accent)" />
                : <OptKpi label="TRI équiv. bourse" value=">" sub="meilleur que 12%" color="var(--green)" />
              }
            </div>

            {result.dti.revenusMensuels > 0 && (
              <div className="opt-dti-block">
                <div className="opt-dti-block-title">
                  Taux d'endettement
                  <DtiBadge dti={result.dti} />
                </div>
                <div className="opt-dti-rows">
                  <div className="opt-dti-row">
                    <span>Revenus pris en compte</span>
                    <span>{Math.round(result.dti.revenusMensuels)} €/mois</span>
                  </div>
                  <div className="opt-dti-row">
                    <span>Mensualité crédit</span>
                    <span>{Math.round(result.mensualite)} €/mois</span>
                  </div>
                  <div className="opt-dti-row">
                    <span>+ Dettes existantes</span>
                    <span>{Math.round(params.dettesExistantes)} €/mois</span>
                  </div>
                  <div className="opt-dti-row opt-dti-row-total">
                    <span>Total mensualités</span>
                    <span>{result.dti.mensualitesTotales} €/mois</span>
                  </div>
                  <div className="opt-dti-row opt-dti-row-total">
                    <span>Taux d'endettement</span>
                    <span style={{ color: result.dti.endettable ? 'var(--green)' : 'var(--red)' }}>
                      {Math.round(result.dti.tauxEndettement * 100)} % {result.dti.endettable ? '✓ HCSF' : '✗ dépasse 35%'}
                    </span>
                  </div>
                  <div className="opt-dti-row">
                    <span>Mensualité max (35%)</span>
                    <span>{result.dti.mensualiteMax} €/mois</span>
                  </div>
                  <div className="opt-dti-row">
                    <span>Marge disponible</span>
                    <span style={{ color: result.dti.marge >= 0 ? 'var(--green)' : 'var(--red)' }}>
                      {result.dti.marge >= 0 ? '+' : ''}{result.dti.marge} €/mois
                    </span>
                  </div>
                  <div className="opt-dti-row">
                    <span>Capacité d'emprunt</span>
                    <span style={{ color: 'var(--accent)' }}>{Math.round(result.dti.capaciteEmprunt / 1000)}k€</span>
                  </div>
                </div>
              </div>
            )}
          </>
        )}

        {/* VAN curve */}
        {tab === 'van' && (
          <div className="opt-van-section">
            <div className="opt-van-header">
              <span className="opt-van-title">VAN en fonction du taux d'actualisation</span>
              <span className="opt-van-sub">VAN &gt; 0 = l'investissement bat l'alternative financière</span>
            </div>
            {breakEvenRate != null && (
              <div className="opt-van-breakeven">
                Taux d'indifférence : <strong>{breakEvenRate} %</strong>
                {breakEvenRate < 5
                  ? ' — investissement sous-performant vs bourse'
                  : breakEvenRate < 8
                    ? ' — compétitif vs portefeuille 7-8%'
                    : ' — bat une allocation actions standard'
                }
              </div>
            )}
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={vanCurve} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <defs>
                  <linearGradient id="vanGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%"  stopColor="var(--green)" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="var(--green)" stopOpacity={0.02} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
                <XAxis dataKey="discountRate" tick={{ fontSize: 10, fill: 'var(--text-faint)' }} tickLine={false}
                  tickFormatter={(v) => `${v}%`} />
                <YAxis tick={{ fontSize: 10, fill: 'var(--text-faint)' }} tickLine={false} axisLine={false}
                  tickFormatter={(v) => `${Math.round(v / 1000)}k`} />
                <Tooltip content={<VanTooltip />} />
                <ReferenceLine y={0} stroke="var(--border-strong)" strokeDasharray="4 3" />
                {breakEvenRate != null && (
                  <ReferenceLine x={breakEvenRate} stroke="var(--amber)" strokeDasharray="5 3"
                    label={{ value: `${breakEvenRate}%`, fontSize: 9, fill: 'var(--amber)' }} />
                )}
                <Area type="monotone" dataKey="van" name="VAN"
                  stroke="var(--green)" fill="url(#vanGrad)" strokeWidth={2} dot={false} />
              </AreaChart>
            </ResponsiveContainer>
            <div className="opt-van-note">
              <Info size={10} /> VAN calculée avec revente an {result.optRevente}, frais agence 5%,
              frais notaire {params.fraisNotaireP}%.
              Taux d'actualisation = coût d'opportunité de votre capital.
            </div>
          </div>
        )}

        {/* Stress test */}
        {tab === 'stress' && (
          <div className="opt-stress-section">
            <div className="opt-van-header">
              <span className="opt-van-title">Scénarios de marché</span>
              <span className="opt-van-sub">Même bien, mêmes paramètres, hypothèses de marché différentes</span>
            </div>
            {stress.map((s) => (
              <div key={s.id} className="opt-stress-row">
                <div className="opt-stress-label-col">
                  <span className="opt-stress-name" style={{ color: s.color }}>{s.label}</span>
                  <span className="opt-stress-hypo">prix {s.indexPrix > 0 ? '+' : ''}{s.indexPrix}%/an · loyer +{s.indexLoyer}%/an · vacance {Math.round(s.vacanceP * 100)}%</span>
                </div>
                <div className="opt-stress-kpis">
                  <div className="opt-stress-kpi">
                    <span className="opt-stress-kpi-label">TRI</span>
                    <span className="opt-stress-kpi-val" style={{ color: triColor(s.tri) }}>
                      {s.tri != null ? `${s.tri.toFixed(1)}%` : '—'}
                    </span>
                  </div>
                  <div className="opt-stress-kpi">
                    <span className="opt-stress-kpi-label">CF/mois</span>
                    <span className="opt-stress-kpi-val" style={{ color: s.cfMois1 >= 0 ? 'var(--green)' : 'var(--red)' }}>
                      {s.cfMois1 >= 0 ? '+' : ''}{eur(s.cfMois1, 0)}
                    </span>
                  </div>
                  <div className="opt-stress-kpi">
                    <span className="opt-stress-kpi-label">Patrimoine an 10</span>
                    <span className="opt-stress-kpi-val" style={{ color: s.patrimoineAn10 >= 0 ? 'var(--text)' : 'var(--red)' }}>
                      {eur(s.patrimoineAn10)}
                    </span>
                  </div>
                  <div className="opt-stress-kpi">
                    <span className="opt-stress-kpi-label">VAN @ 5%</span>
                    <span className="opt-stress-kpi-val" style={{ color: vanColor(s.van5) }}>
                      {eur(s.van5)}
                    </span>
                  </div>
                </div>
                <div className="opt-stress-bar-wrap">
                  {s.tri != null && (
                    <div className="opt-stress-bar"
                      style={{ width: `${Math.min(100, Math.max(0, s.tri / 15 * 100))}%`, background: s.color }} />
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Sensitivity heatmap */}
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
                    {SENS_TAUX.map((t) => (
                      <th key={t} className="opt-sens-th">{t}%</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sens.map((row, ri) => (
                    <tr key={ri}>
                      <td className="opt-sens-rowh">
                        {SENS_APPORT_PCTS[ri]}%
                        <span className="opt-sens-rowh-sub">{eur(Math.round(result.bien.price * SENS_APPORT_PCTS[ri] / 100 / 1000) * 1000)}</span>
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

function OptKpi({ label, value, sub, color, big }: {
  label: string; value: string; sub?: string; color?: string; big?: boolean
}) {
  return (
    <div className={`opt-kpi${big ? ' big' : ''}`}>
      <div className="opt-kpi-label">{label}</div>
      <div className="opt-kpi-value" style={color ? { color } : undefined}>{value}</div>
      {sub && <div className="opt-kpi-sub">{sub}</div>}
    </div>
  )
}

// ── Main ───────────────────────────────────────────────────────────────────────

export function OptimiseurTab() {
  const {
    profilAcquisition, setProfilAcquisition,
    salaireNet: storeSalaireNet, setSalaireNet,
    dettesExistantes: storeDettes, setDettesExistantes,
  } = useStore()
  const profil = profilAcquisition ?? 'locatif'
  const profile = PROFILES.find((p) => p.id === profil)!

  const [params, setParams] = useState<OptimParams>({
    budget: 2_000_000,
    apportEur: 200_000,
    taux: 3.5,
    duree: 20,
    tmi: 30,
    fraisNotaireP: 7.5,
    indexLoyer: 2,
    indexPrix: 3,
    vacanceP: 0.04,
    salaireNet: storeSalaireNet,
    dettesExistantes: storeDettes,
  })
  const sp = useCallback((p: Partial<OptimParams>) => {
    setParams((prev) => ({ ...prev, ...p }))
    if (p.salaireNet !== undefined) setSalaireNet(p.salaireNet)
    if (p.dettesExistantes !== undefined) setDettesExistantes(p.dettesExistantes)
  }, [setSalaireNet, setDettesExistantes])

  const [ran, setRan]             = useState(false)
  const [running, setRunning]     = useState(false)
  const [results, setResults]     = useState<BienOptimResult[]>([])
  const [selected, setSelected]   = useState<BienOptimResult | null>(null)

  const handleRun = useCallback(() => {
    setRunning(true)
    // use setTimeout to let React render "Calcul en cours..." first
    setTimeout(() => {
      const res = rankBiens(CATALOG, params, profil)
      setResults(res)
      setSelected(res[0] ?? null)
      setRan(true)
      setRunning(false)
    }, 10)
  }, [params, profil])

  // Re-run when profil changes if already ran
  const handleProfileChange = useCallback((p: ProfilAcquisition) => {
    setProfilAcquisition(p)
    if (ran) {
      setRunning(true)
      setTimeout(() => {
        const res = rankBiens(CATALOG, params, p)
        setResults(res)
        setSelected(res[0] ?? null)
        setRunning(false)
      }, 10)
    }
  }, [ran, params, setProfilAcquisition])

  // Count biens within budget
  const inBudget = useMemo(() =>
    CATALOG.filter((b) => b.price <= params.budget && b.price > 0).length,
  [params.budget])

  return (
    <div className="sim-page">
      <div className="opt-layout">

        {/* ── Sidebar ── */}
        <aside className="sim-sidebar opt-sidebar">

          {/* Profile selector */}
          <div className="sim-group">
            <div className="sim-group-title">Profil acquéreur</div>
            <div className="opt-profiles">
              {PROFILES.map((p) => (
                <ProfileCard key={p.id} profil={p} active={profil === p.id}
                  onClick={() => handleProfileChange(p.id)} />
              ))}
            </div>
            <div className="opt-profile-desc">{profile.description}</div>
            <div className="opt-weights-row">
              <WeightChip label={profile.triLabel} pct={Math.round(profile.weights.tri * 100)} color="var(--accent)" />
              <WeightChip label={profile.decoteLabel} pct={Math.round(profile.weights.decote * 100)} color="var(--green)" />
              <WeightChip label={profile.confortLabel} pct={Math.round(profile.weights.confort * 100)} color="oklch(0.65 0.18 275)" />
            </div>
          </div>

          {/* Params */}
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

            <div className="sim-field">
              <div className="sim-field-header">
                <label className="sim-field-label">Taux crédit</label>
                <span className="sim-field-curval">{params.taux.toFixed(1)} %</span>
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

            <div className="sim-field">
              <label className="sim-field-label">TMI</label>
              <div className="sim-tmi-pills">
                {[0, 11, 30, 41, 45].map((t) => (
                  <button key={t} className={`sim-tmi-pill${params.tmi === t ? ' active' : ''}`}
                    onClick={() => sp({ tmi: t })}>{t}%</button>
                ))}
              </div>
            </div>

            <div className="sim-field">
              <div className="sim-field-header">
                <label className="sim-field-label">Frais notaire</label>
                <span className="sim-field-curval">{params.fraisNotaireP.toFixed(1)} %</span>
              </div>
              <input type="range" className="sim-range" min={2} max={9} step={0.5}
                value={params.fraisNotaireP} onChange={(e) => sp({ fraisNotaireP: +e.target.value })}
                style={{ accentColor: 'var(--accent)' }} />
            </div>
          </div>

          {/* Capacité d'emprunt */}
          <div className="sim-group">
            <div className="sim-group-title">Capacité d'emprunt</div>
            <div className="sim-field">
              <label className="sim-field-label">Salaire mensuel net</label>
              <div className="sim-field-wrap">
                <input type="number" className="sim-field-input" value={params.salaireNet || ''} step={100}
                  placeholder="0"
                  onChange={(e) => sp({ salaireNet: Math.max(0, +e.target.value || 0) })} />
                <span className="sim-field-suffix">€/mois</span>
              </div>
            </div>
            <div className="sim-field">
              <label className="sim-field-label">Mensualités existantes</label>
              <div className="sim-field-wrap">
                <input type="number" className="sim-field-input" value={params.dettesExistantes || ''} step={50}
                  placeholder="0"
                  onChange={(e) => sp({ dettesExistantes: Math.max(0, +e.target.value || 0) })} />
                <span className="sim-field-suffix">€/mois</span>
              </div>
            </div>
            {params.salaireNet > 0 && (() => {
              const r = (params.taux / 100) / 12
              const n = params.duree * 12
              const mensMax = Math.max(0, (params.salaireNet) * 0.35 - params.dettesExistantes)
              const capEmp = r > 0
                ? Math.round(mensMax * (1 - Math.pow(1 + r, -n)) / r / 1000) * 1000
                : Math.round(mensMax * n / 1000) * 1000
              return (
                <div className="opt-dti-summary">
                  <span className="opt-dti-summary-label">Mensualité max</span>
                  <span className="opt-dti-summary-val">{Math.round(mensMax)} €/mois</span>
                  <span className="opt-dti-summary-label">Capacité d'emprunt</span>
                  <span className="opt-dti-summary-val">{Math.round(capEmp / 1000)}k€</span>
                </div>
              )
            })()}
          </div>

          {/* CTA */}
          <button className="opt-run-btn" onClick={handleRun} disabled={running}>
            {running ? (
              <span>Calcul en cours…</span>
            ) : (
              <><Zap size={14} /> Analyser {inBudget} biens <ChevronRight size={14} /></>
            )}
          </button>

        </aside>

        {/* ── Main ── */}
        <main className="sim-main opt-main">

          {!ran && (
            <div className="opt-empty">
              <div className="opt-empty-icon">{PROFILE_ICONS[profil]}</div>
              <div className="opt-empty-title">Profil : {profile.label}</div>
              <div className="opt-empty-desc">{profile.description}</div>
              <div className="opt-empty-hint">
                Configure tes paramètres dans la sidebar et clique sur Analyser
              </div>
              <button className="opt-run-btn opt-run-btn-center" onClick={handleRun} disabled={running}>
                <Zap size={14} /> Lancer l'analyse sur {inBudget} biens
              </button>
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
              {/* Ranking table */}
              <div className="opt-ranking-card">
                <div className="sim-chart-header" style={{ marginBottom: '10px' }}>
                  <span className="sim-chart-title">
                    Classement — {results.length} biens · profil {profile.label}
                  </span>
                  <span className="sim-chart-sub">
                    Score = {Math.round(profile.weights.tri * 100)}% TRI + {Math.round(profile.weights.decote * 100)}% décote + {Math.round(profile.weights.confort * 100)}% confort
                  </span>
                </div>
                <div className="opt-table-scroll">
                  <table className="opt-rank-table">
                    <thead>
                      <tr>
                        <th>#</th>
                        <th>Bien</th>
                        <th>Score</th>
                        <th>TRI opt.</th>
                        <th>Décote</th>
                        <th>CF/mois</th>
                        <th>Régime opt.</th>
                        <th>Endettement</th>
                      </tr>
                    </thead>
                    <tbody>
                      {results.map((r, i) => (
                        <RankRow key={r.bien.id} r={r} rank={i + 1}
                          selected={selected?.bien.id === r.bien.id}
                          onClick={() => setSelected(r)} />
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              {/* Detail panel */}
              {selected && (
                <DetailPanel result={selected} params={params} profil={profil} />
              )}
            </>
          )}

        </main>
      </div>
    </div>
  )
}

function WeightChip({ label, pct, color }: { label: string; pct: number; color: string }) {
  return (
    <div className="opt-weight-chip">
      <span className="opt-weight-pct" style={{ color }}>{pct}%</span>
      <span className="opt-weight-label">{label}</span>
    </div>
  )
}
