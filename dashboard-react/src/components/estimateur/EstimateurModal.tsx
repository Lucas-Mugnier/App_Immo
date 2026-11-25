import { useStore } from '@/store/useStore'
import {
  avmInterp, avmAffine,
  avmMaisonDvf, avmMaisonAnnonces, avmAffineMaison,
  getMaisonDvfStats,
  AVM_COMMUNES, ALL_MAISON_SECTEURS, MAISON_SECTEURS,
  AVM_OPTS, terrainLabel, surfaceDiscountLabel, parkingMaisonLabel, vueMaisonLabel,
} from '@/lib/avm'
import avmLookupRaw from '@/data/avm_lookup.json'
import { eur, cn } from '@/lib/utils'
import { X, Calculator, TrendingUp, Building2, Home, Info } from 'lucide-react'

const AVM_LOOKUP_META = avmLookupRaw as Record<string, { mape?: number; model?: string }>

// ── ChipGroup ─────────────────────────────────────────────────────────────────

function ChipGroup<T extends string>({
  value, onChange, opts, label,
}: {
  value: T; onChange: (v: T) => void
  opts: { value: string; label: string }[]; label: string
}) {
  return (
    <div className="flex flex-col gap-1.5">
      <label className="text-[0.65rem] font-display font-600 text-faint uppercase tracking-widest">{label}</label>
      <div className="flex flex-wrap gap-1.5">
        {opts.map((o) => (
          <button key={o.value}
            className={cn('chip cursor-pointer transition-all',
              value === o.value
                ? 'bg-ice-bright/15 border-ice-bright text-ice-bright'
                : 'bg-alpine-surface border-alpine-border text-sub hover:border-alpine-line hover:text-text',
            )}
            onClick={() => onChange(o.value as T)} type="button">
            {o.label}
          </button>
        ))}
      </div>
    </div>
  )
}

// ── Result card (used twice: DVF + annonces) ──────────────────────────────────

function ModelCard({
  title, subtitle, base, affined, n, price, confidence, color,
}: {
  title: string; subtitle: string
  base: number | null; affined: number | null; n: number
  price: number; confidence: 'high' | 'medium' | 'low'
  color: string
}) {
  const ratio    = affined && price > 0 ? affined / price : null
  const pctDiff  = ratio ? ((ratio - 1) * 100).toFixed(1) : null
  const sign     = ratio && ratio > 1 ? '+' : ''
  const confLabel = confidence === 'high' ? 'Fiable' : confidence === 'medium' ? 'Estimatif' : 'Indicatif'

  return (
    <div className="est-model-card" style={{ borderTopColor: color }}>
      <div className="est-model-header">
        <div className="est-model-title">{title}</div>
        <div className="est-model-sub">{subtitle}</div>
        <span className="est-model-conf" style={{
          color: confidence === 'high' ? 'var(--green)' : confidence === 'medium' ? 'var(--amber)' : 'var(--text-faint)',
        }}>
          {confLabel} · {n} {n > 1 ? 'réf.' : 'réf.'}
        </span>
      </div>
      <div className="est-model-values">
        <div>
          <div className="est-model-label">Base PM²</div>
          <div className="est-model-val">{base ? eur(base) : '—'}</div>
        </div>
        <div>
          <div className="est-model-label">Affiné</div>
          <div className="est-model-val" style={{ color }}>{affined ? eur(affined) : '—'}</div>
        </div>
        <div>
          <div className="est-model-label">vs Prix</div>
          <div className="est-model-val" style={{
            color: ratio == null ? 'var(--text-faint)'
              : ratio >= 1.10 ? 'var(--green)'
              : ratio >= 0.95 ? 'var(--amber)'
              : 'var(--red)',
          }}>
            {pctDiff ? `${sign}${pctDiff}%` : '—'}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Main modal ────────────────────────────────────────────────────────────────

export function EstimateurModal() {
  const { estimateur, closeEstimateur, updateEstimateur } = useStore()

  if (!estimateur.open) return null

  const { propType, surface, rooms, commune, secteur, price, etat, vue, etage, parking, ext, surfTerrain } = estimateur
  const isMaison = propType === 'maison'

  // ── APPARTEMENT ───────────────────────────────────────────────────────────

  const apptBase    = !isMaison ? avmInterp(commune, rooms, surface) : null
  const apptAffined = apptBase ? avmAffine(apptBase, etat, vue, etage, parking, ext) : null
  const apptRatio   = apptAffined && price > 0 ? apptAffined / price : null
  const apptPct     = apptRatio ? ((apptRatio - 1) * 100).toFixed(1) : null

  // ── MAISON — deux modèles ─────────────────────────────────────────────────

  // Modèle 1 : DVF (transactions historiques)
  const dvfBase    = isMaison ? avmMaisonDvf(secteur, surface) : null
  const dvfAffined = dvfBase  ? avmAffineMaison(dvfBase, etat, vue, surfTerrain, parking) : null
  const dvfStats   = getMaisonDvfStats(secteur)

  // Modèle 2 : échantillon de biens sur le marché (stats agrégées et lissées)
  const annBase    = isMaison ? avmMaisonAnnonces(secteur, surface) : null
  const annAffined = annBase  ? avmAffineMaison(annBase, etat, vue, surfTerrain, parking) : null
  const annStats   = MAISON_SECTEURS[secteur]

  // Consensus : moyenne des deux modèles disponibles
  const validModels = [dvfAffined, annAffined].filter((v): v is number => v != null)
  const consensus   = validModels.length > 0 ? Math.round(validModels.reduce((a, b) => a + b, 0) / validModels.length) : null
  const consensusRatio = consensus && price > 0 ? consensus / price : null

  const ratioColor = (r: number | null) => r == null ? 'text-sub'
    : r >= 1.15 ? 'text-glow-green' : r >= 1.05 ? 'text-ice-bright'
    : r >= 0.95 ? 'text-glow-amber' : 'text-glow-red'

  const verdict = (r: number | null) => r == null ? '—'
    : r >= 1.2 ? 'Très bonne affaire' : r >= 1.1 ? 'Sous-évalué'
    : r >= 1.0 ? 'Fair value'         : r >= 0.9 ? 'Légèrement surévalué' : 'Surévalué'

  // Appt adjustments
  const EST_COEFFS_VALUES = {
    etat:    { cata: -0.45, renov: -0.28, moyen: -0.10, bon: 0, tres_bon: 0.10, neuf: 0.18 },
    vue:     { default: 0, vue_deg: 0.04, vue_massif: 0.08, vue_MB: 0.15 },
    etage:   { rdc: -0.06, inter: 0, last: 0.04, last_asc: 0.06 },
    parking: { aucun: 0, ext: 0.015, box: 0.04, dbox: 0.06 },
    ext:     { aucun: 0, balcon: 0.02, loggia: 0.02, terrasse: 0.04, gde_terr: 0.07 },
  } as Record<string, Record<string, number>>
  const adjustments = [
    { label: 'État', key: 'etat', val: etat },
    { label: 'Vue', key: 'vue', val: vue },
    { label: 'Étage', key: 'etage', val: etage },
    { label: 'Parking', key: 'parking', val: parking },
    { label: 'Extérieur', key: 'ext', val: ext },
  ].map((a) => ({ ...a, coeff: EST_COEFFS_VALUES[a.key]?.[a.val] ?? 0 }))
    .filter((a) => a.coeff !== 0)

  return (
    <div className="modal-overlay" onClick={closeEstimateur}>
      <div className="modal-box w-full max-w-2xl mx-4" onClick={(e) => e.stopPropagation()}>

        {/* Header */}
        <div className="flex items-center justify-between p-5 border-b border-alpine-border">
          <div className="flex items-center gap-2">
            <Calculator size={18} className="text-ice" />
            <h2 className="font-display font-700 text-[1rem] text-text">Estimation AVM Affinée</h2>
          </div>
          <button className="action-btn" onClick={closeEstimateur}><X size={14} /></button>
        </div>

        <div className="p-5 space-y-5">

          {/* Type selector */}
          <div className="flex gap-2">
            <button className={cn('est-type-btn', !isMaison && 'active')}
              onClick={() => updateEstimateur({ propType: 'appart' })}>
              <Building2 size={14} /> Appartement
            </button>
            <button className={cn('est-type-btn', isMaison && 'active')}
              onClick={() => updateEstimateur({ propType: 'maison' })}>
              <Home size={14} /> Maison / Chalet
            </button>
          </div>

          {/* ── APPARTEMENT params ── */}
          {!isMaison && (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <div className="flex flex-col gap-1">
                  <label className="text-[0.65rem] font-display font-600 text-faint uppercase tracking-widest">Surface (m²)</label>
                  <input type="number" className="filter-input" value={surface} min={15} max={400}
                    onChange={(e) => updateEstimateur({ surface: +e.target.value })} />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-[0.65rem] font-display font-600 text-faint uppercase tracking-widest">Pièces</label>
                  <input type="number" className="filter-input" value={rooms} min={1} max={8}
                    onChange={(e) => updateEstimateur({ rooms: +e.target.value })} />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-[0.65rem] font-display font-600 text-faint uppercase tracking-widest">Commune</label>
                  <select className="filter-select" value={commune}
                    onChange={(e) => updateEstimateur({ commune: e.target.value })}>
                    {AVM_COMMUNES.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-[0.65rem] font-display font-600 text-faint uppercase tracking-widest">Prix annonce (€)</label>
                  <input type="number" className="filter-input" value={price} step={5000}
                    onChange={(e) => updateEstimateur({ price: +e.target.value })} />
                </div>
              </div>

              <div className="space-y-3 p-4 card-inner rounded-lg">
                <p className="text-[0.72rem] text-sub">Affiner selon les caractéristiques :</p>
                <ChipGroup label="État général" value={etat} onChange={(v) => updateEstimateur({ etat: v })} opts={AVM_OPTS.etat} />
                <ChipGroup label="Vue"          value={vue}  onChange={(v) => updateEstimateur({ vue: v })}  opts={AVM_OPTS.vue} />
                <ChipGroup label="Étage"       value={etage} onChange={(v) => updateEstimateur({ etage: v })} opts={AVM_OPTS.etage} />
                <ChipGroup label="Parking"     value={parking} onChange={(v) => updateEstimateur({ parking: v })} opts={AVM_OPTS.parking} />
                <ChipGroup label="Extérieur"   value={ext}  onChange={(v) => updateEstimateur({ ext: v })}  opts={AVM_OPTS.ext} />
              </div>

              {/* Appt result */}
              <div className="card-inner p-4 rounded-lg">
                <div className="grid grid-cols-3 gap-4 text-center">
                  <div>
                    <div className="kpi-label">Base AVM</div>
                    <div className="kpi-value text-sub">{apptBase ? eur(apptBase) : '—'}</div>
                    <div className="kpi-sub">{commune} · {rooms}p · {surface}m²</div>
                  </div>
                  <div>
                    <div className="kpi-label">AVM Affiné</div>
                    <div className="kpi-value text-ice">{apptAffined ? eur(apptAffined) : '—'}</div>
                    {adjustments.length > 0 && (
                      <div className="kpi-sub">
                        {adjustments.map((a) => `${a.label} ${a.coeff > 0 ? '+' : ''}${(a.coeff * 100).toFixed(0)}%`).join(' · ')}
                      </div>
                    )}
                  </div>
                  <div>
                    <div className="kpi-label">vs Prix annonce</div>
                    <div className={cn('kpi-value', ratioColor(apptRatio))}>
                      {apptPct ? `${apptRatio! > 1 ? '+' : ''}${apptPct}%` : '—'}
                    </div>
                    <div className={cn('kpi-sub', ratioColor(apptRatio))}>{verdict(apptRatio)}</div>
                  </div>
                </div>
                {apptRatio != null && (
                  <div className="mt-4">
                    <div className="bar-track" style={{ height: 6 }}>
                      <div className="bar-fill" style={{
                        width: `${Math.min(100, Math.max(5, apptRatio * 50))}%`,
                        background: apptRatio >= 1.15 ? 'var(--col-green)' : apptRatio >= 1.05 ? 'var(--col-ice)' : apptRatio >= 0.95 ? 'var(--col-amber)' : 'var(--col-red)',
                      }} />
                    </div>
                    <div className="flex justify-between text-[0.6rem] text-faint mt-1">
                      <span>Surévalué</span><span>Fair value ×1.00</span><span>Sous-évalué</span>
                    </div>
                  </div>
                )}
              </div>

              <div className="flex items-center gap-2 text-[0.7rem] text-faint">
                <TrendingUp size={12} />
                <span>
                  {AVM_LOOKUP_META[commune]?.model ?? 'Modèle DVF'} ·
                  MAPE {AVM_LOOKUP_META[commune]?.mape != null ? `±${(AVM_LOOKUP_META[commune].mape! * 100).toFixed(1)}%` : '~±15%'}
                  · Interpolation linéaire sur table PM²
                </span>
              </div>
            </>
          )}

          {/* ── MAISON params ── */}
          {isMaison && (
            <>
              {/* Secteur selector */}
              <div className="est-secteur-wrap">
                <div className="flex flex-col gap-1 flex-1">
                  <label className="text-[0.65rem] font-display font-600 text-faint uppercase tracking-widest">
                    Secteur / Quartier
                  </label>
                  <select className="filter-select" value={secteur}
                    onChange={(e) => updateEstimateur({ secteur: e.target.value })}>
                    {ALL_MAISON_SECTEURS.map((s) => {
                      const stats = MAISON_SECTEURS[s]
                      return (
                        <option key={s} value={s}>
                          {stats.n > 0 ? `${s} — ~${stats.medianPm2.toLocaleString('fr-FR')} €/m²` : s}
                        </option>
                      )
                    })}
                  </select>
                </div>
                {annStats && annStats.n > 0 && (
                  <div className="est-secteur-badge">
                    <span className="est-secteur-pm2">{annStats.medianPm2.toLocaleString('fr-FR')} €/m²</span>
                    <span className="est-secteur-range" title="80 % des biens de l'échantillon sont dans cette fourchette">
                      [{annStats.minPm2.toLocaleString('fr-FR')} – {annStats.maxPm2.toLocaleString('fr-FR')}]
                    </span>
                    <span className="est-secteur-n">échantillon · {annStats.n} biens</span>
                  </div>
                )}
              </div>

              {/* Numeric params */}
              <div className="grid grid-cols-3 gap-3">
                <div className="flex flex-col gap-1">
                  <label className="text-[0.65rem] font-display font-600 text-faint uppercase tracking-widest">Surface hab. (m²)</label>
                  <input type="number" className="filter-input" value={surface} min={20} max={800}
                    onChange={(e) => updateEstimateur({ surface: +e.target.value })} />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-[0.65rem] font-display font-600 text-faint uppercase tracking-widest">Terrain (m²)</label>
                  <input type="number" className="filter-input" value={surfTerrain} min={0} max={20000} step={50}
                    onChange={(e) => updateEstimateur({ surfTerrain: +e.target.value })} />
                </div>
                <div className="flex flex-col gap-1">
                  <label className="text-[0.65rem] font-display font-600 text-faint uppercase tracking-widest">Prix annonce (€)</label>
                  <input type="number" className="filter-input" value={price} step={10000}
                    onChange={(e) => updateEstimateur({ price: +e.target.value })} />
                </div>
              </div>

              {/* Affinage chips */}
              <div className="space-y-3 p-4 card-inner rounded-lg">
                <p className="text-[0.72rem] text-sub">
                  Affinage appliqué aux deux modèles ·{' '}
                  <span className="text-faint">
                    Surface → {surfaceDiscountLabel(surface)} ·
                    Terrain → {terrainLabel(surfTerrain)}
                    {vueMaisonLabel(vue) ? ` · ${vueMaisonLabel(vue)}` : ''}
                    {parkingMaisonLabel(parking) ? ` · ${parkingMaisonLabel(parking)}` : ''}
                  </span>
                </p>
                <ChipGroup label="État général"    value={etat}    onChange={(v) => updateEstimateur({ etat: v })}    opts={AVM_OPTS.etat} />
                <ChipGroup label="Vue"             value={vue}     onChange={(v) => updateEstimateur({ vue: v })}     opts={AVM_OPTS.vue} />
                <ChipGroup label="Garage / parking" value={parking} onChange={(v) => updateEstimateur({ parking: v })} opts={AVM_OPTS.parking} />
              </div>

              {/* Two models + consensus */}
              <div className="est-models-grid">
                <ModelCard
                  title="Modèle DVF"
                  subtitle="Transactions notariales historiques"
                  base={dvfBase}
                  affined={dvfAffined}
                  n={dvfStats?.n ?? 0}
                  price={price}
                  confidence={dvfStats && dvfStats.n >= 50 ? 'high' : dvfStats && dvfStats.n >= 10 ? 'medium' : 'low'}
                  color="oklch(0.65 0.18 275)"
                />
                <ModelCard
                  title="Modèle échantillon"
                  subtitle={`Échantillon de biens sur le marché · ${secteur}`}
                  base={annBase}
                  affined={annAffined}
                  n={annStats?.n ?? 0}
                  price={price}
                  confidence={annStats && annStats.n >= 8 ? 'medium' : 'low'}
                  color="oklch(0.52 0.155 152)"
                />
              </div>

              {/* Consensus */}
              {consensus && (
                <div className="est-consensus">
                  <div className="est-consensus-left">
                    <div className="est-consensus-label">Estimation consensus</div>
                    <div className="est-consensus-sub">Moyenne des {validModels.length} modèles disponibles</div>
                  </div>
                  <div className="est-consensus-right">
                    <div className="est-consensus-val">{eur(consensus)}</div>
                    {consensusRatio && (
                      <div className={cn('est-consensus-pct', ratioColor(consensusRatio))}>
                        {consensusRatio > 1 ? '+' : ''}{((consensusRatio - 1) * 100).toFixed(1)}%
                        <span className="est-consensus-verdict"> · {verdict(consensusRatio)}</span>
                      </div>
                    )}
                  </div>
                </div>
              )}

              {/* Info disclaimer */}
              <div className="flex items-start gap-2 text-[0.68rem] text-faint">
                <Info size={11} className="mt-0.5 flex-shrink-0" />
                <span>
                  <b>DVF :</b> basé sur {dvfStats?.n ?? '—'} ventes notariales (Chamonix Mont-Blanc) ·{' '}
                  <b>Échantillon :</b> médiane PM² lissée d'un échantillon de biens actuellement sur le marché{annStats?.n ? ` (${annStats.n} dans ce secteur)` : ''} ·
                  Modèles indicatifs, précision ±15–25 % · Consulter un expert avant toute décision
                </span>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export function EstimateurFAB() {
  const { openEstimateur, estimateur } = useStore()
  if (estimateur.open) return null
  return (
    <button className="fab has-tooltip" data-tip="Estimer un bien"
      onClick={() => openEstimateur({})} title="Estimer un bien">
      <Calculator size={20} />
    </button>
  )
}
