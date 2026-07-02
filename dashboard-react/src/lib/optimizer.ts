import type { FiscalMode } from '@/types'
import {
  buildProjection, computeTRI, computeVAN, findApportOptimal,
  type ProjRow,
} from '@/lib/simulator'

// ── Profils ────────────────────────────────────────────────────────────────────

export type ProfilAcquisition = 'locatif' | 'valeur' | 'rp' | 'mixte' | 'marchand'

export interface ProfileWeights { tri: number; decote: number; confort: number }

export interface ProfileDef {
  id: ProfilAcquisition
  label: string
  emoji: string
  tagline: string
  description: string
  weights: ProfileWeights
  triLabel: string
  decoteLabel: string
  confortLabel: string
}

export const PROFILES: ProfileDef[] = [
  {
    id: 'locatif',
    label: 'Locatif pur',
    emoji: '📈',
    tagline: 'Rendement maximum',
    description: 'Cashflow positif et TRI élevé. Le loyer finance l\'achat.',
    weights: { tri: 0.70, decote: 0.20, confort: 0.10 },
    triLabel: 'TRI', decoteLabel: 'Décote marché', confortLabel: 'Qualité',
  },
  {
    id: 'valeur',
    label: 'Pari valeur',
    emoji: '💎',
    tagline: 'Acheter sous le marché',
    description: 'Identifier les biens décotés pour maximiser la plus-value à la revente.',
    weights: { tri: 0.10, decote: 0.80, confort: 0.10 },
    triLabel: 'Rendement', decoteLabel: 'Décote AVM', confortLabel: 'Qualité',
  },
  {
    id: 'rp',
    label: 'Résidence principale',
    emoji: '🏡',
    tagline: 'Trouver son chez-soi · au bon prix',
    description: 'Tu peux te l\'offrir ? La surface et le quartier correspondent ? C\'est ici que ça se décide.',
    weights: { tri: 0.30, decote: 0.20, confort: 0.50 },
    triLabel: 'Abordabilité', decoteLabel: 'Décote marché', confortLabel: 'Confort & quartier',
  },
  {
    id: 'mixte',
    label: 'Mixte RP + locatif',
    emoji: '⚖️',
    tagline: 'Le modèle alpin idéal',
    description: 'Vivre et rentabiliser — résidence principale avec location saisonnière.',
    weights: { tri: 0.35, decote: 0.30, confort: 0.35 },
    triLabel: 'Rendement locatif', decoteLabel: 'Décote', confortLabel: 'Confort & quartier',
  },
  {
    id: 'marchand',
    label: 'Marchand de bien',
    emoji: '🔨',
    tagline: 'Acheter · Rénover · Revendre',
    description: 'Identifier les biens très décotés avec potentiel travaux. Revente courte (3-5 ans) pour rotation rapide du capital.',
    weights: { tri: 0.45, decote: 0.55, confort: 0.00 },
    triLabel: 'TRI revente', decoteLabel: 'Décote / potentiel', confortLabel: 'Qualité actuelle',
  },
]

// ── Catalog ───────────────────────────────────────────────────────────────────

export interface CatalogBien {
  id: string
  type: 'appart' | 'maison'
  title: string
  price: number
  surface: number
  rooms: number
  neighbourhood: string
  yieldPct: number | null
  avmRatio: number | null
  photo: string | null
  url: string | null
}

// ── Scoring ────────────────────────────────────────────────────────────────────

const NEIGHBOURHOOD_CONFORT: Record<string, number> = {
  'Les Praz':           0.92,
  'Le Lavancher':       0.85,
  'Argentière':         0.85,
  'Montroc':            0.82,
  'Le Tour':            0.80,
  'Chamonix Centre':    0.78,
  'Les Tines':          0.72,
  'Les Bois':           0.70,
  'Les Pélerins':       0.60,
  'Les Gaillands':      0.58,
  'Les Bossons':        0.58,
  'Les Houches':        0.50,
  'Servoz':             0.42,
  'Saint-Gervais':      0.38,
  'Sallanches':         0.30,
  'Passy':              0.28,
  'Domancy':            0.25,
}

export function confortScore(bien: CatalogBien): number {
  const surfScore  = Math.min(1, Math.log(Math.max(1, bien.surface) / 20) / Math.log(250 / 20))
  const roomScore  = Math.min(1, (bien.rooms - 1) / 4)
  const hoodScore  = NEIGHBOURHOOD_CONFORT[bien.neighbourhood] ?? 0.55
  return surfScore * 0.35 + roomScore * 0.25 + hoodScore * 0.40
}

export function decoteScore(avmRatio: number | null): number {
  if (avmRatio == null) return 0.50
  if (avmRatio <= 0.80) return 1.00
  if (avmRatio <= 1.00) return 0.50 + (1.00 - avmRatio) * 2.50
  if (avmRatio <= 1.20) return Math.max(0, 0.50 - (avmRatio - 1.00) * 2.50)
  return 0
}

export function triScore(tri: number | null): number {
  if (tri == null || tri < 0) return 0
  if (tri >= 15) return 1
  if (tri >= 10) return 0.80 + (tri - 10) / 25
  if (tri >= 5)  return 0.40 + (tri - 5)  / 12.5
  return tri / 12.5
}

export function abordabiliteScore(tauxEffort: number | null): number {
  if (tauxEffort == null || tauxEffort <= 0) return 0.50
  if (tauxEffort <= 0.20) return 1.00
  if (tauxEffort <= 0.25) return 0.85
  if (tauxEffort <= 0.30) return 0.65
  if (tauxEffort <= 0.33) return 0.40
  if (tauxEffort <= 0.40) return 0.15
  return 0.00
}

export function compositeScore(
  ts: number, ds: number, cs: number,
  w: ProfileWeights,
): number {
  return Math.round(100 * (ts * w.tri + ds * w.decote + cs * w.confort))
}

// ── Taux d'endettement (règle HCSF 35%) ──────────────────────────────────────

export interface DTIResult {
  revenusMensuels: number      // salaire + loyer × 70%
  mensualitesTotales: number   // mensualite nouvelle + dettes existantes
  tauxEndettement: number      // mensualitesTotales / revenusMensuels
  mensualiteMax: number        // revenusMensuels × 35% - dettes existantes
  endettable: boolean          // tauxEndettement ≤ 35%
  marge: number                // mensualiteMax - mensualite (positif = ok)
  capaciteEmprunt: number      // prix max finançable (emprunt max × 12 / r × (1-(1+r)^-n))
}

export function computeEndettement(
  salaireNet: number,
  loyer: number,
  mensualite: number,
  dettesExistantes: number,
  taux: number,
  duree: number,
  loyerPct = 0.70,
): DTIResult {
  const revenusMensuels    = salaireNet + loyer * loyerPct
  const mensualitesTotales = mensualite + dettesExistantes
  const tauxEndettement    = revenusMensuels > 0 ? mensualitesTotales / revenusMensuels : 1
  const mensualiteMax      = Math.max(0, revenusMensuels * 0.35 - dettesExistantes)

  // Capacité d'emprunt depuis mensualiteMax
  const r  = (taux / 100) / 12
  const n  = duree * 12
  const capaciteEmprunt = r > 0
    ? Math.round(mensualiteMax * (1 - Math.pow(1 + r, -n)) / r / 1000) * 1000
    : Math.round(mensualiteMax * n / 1000) * 1000

  return {
    revenusMensuels: Math.round(revenusMensuels),
    mensualitesTotales: Math.round(mensualitesTotales),
    tauxEndettement,
    mensualiteMax: Math.round(mensualiteMax),
    endettable: tauxEndettement <= 0.35,
    marge: Math.round(mensualiteMax - mensualite),
    capaciteEmprunt,
  }
}

// ── Optimizer params ──────────────────────────────────────────────────────────

export interface OptimParams {
  budget: number
  apportEur: number
  taux: number
  duree: number
  tmi: number
  fraisNotaireP: number
  indexLoyer: number
  indexPrix: number
  salaireNet: number       // revenu mensuel net
  dettesExistantes: number // mensualités de crédit existantes
}

const FISCAL_IDS: FiscalMode[] = ['lmnp_reel', 'lmnp_micro', 'ir_nu', 'sci_is']
const FISCAL_LABELS: Record<FiscalMode, string> = {
  lmnp_reel: 'LMNP Réel', lmnp_micro: 'Micro BIC', ir_nu: 'IR Nu', sci_is: 'SCI IS',
}

function loyerFor(bien: CatalogBien): number {
  return bien.yieldPct
    ? Math.round(bien.price * bien.yieldPct / 100 / 12)
    : Math.round(bien.price * 0.045 / 12)
}

function chargesFor(bien: CatalogBien): number {
  // taxe foncière + copro + assurance PNO + provision travaux
  // ~0.5% du prix + 1 000€ fixes → 300k→2500€, 500k→3500€, 800k→5000€
  return Math.round(bien.price * 0.005 + 1000)
}

// ── Per-bien optimisation ─────────────────────────────────────────────────────

export interface BienOptimResult {
  bien: CatalogBien
  loyer: number
  chargesAn: number
  optMode: FiscalMode
  optModeLabel: string
  optRevente: number
  optApport: number
  apport0: number
  triOpt: number | null
  cfMois1: number
  van5: number
  van8: number
  mensualite: number
  ts: number
  ds: number
  cs: number
  score: number
  projOpt: ProjRow[]
  dti: DTIResult
  tauxEffort: number | null   // mensualite / salaireNet (RP mode only)
  isRPMode: boolean
}

export function optimiseBien(
  bien: CatalogBien,
  params: OptimParams,
  profil: ProfilAcquisition,
): BienOptimResult {
  // ── Résidence principale — logique dédiée ──────────────────────────────────
  if (profil === 'rp') {
    const chargesAn = chargesFor(bien)
    const apport    = Math.min(params.apportEur, bien.price)
    const proj = buildProjection({
      prix: bien.price, apportEur: apport, loyer: 0, chargesAn,
      taux: params.taux, duree: params.duree,
      indexLoyer: params.indexLoyer, indexPrix: params.indexPrix,
      tmi: params.tmi, dureeRevente: 0, mode: 'ir_nu',
      fraisNotaireP: params.fraisNotaireP,
    })
    const mensualite  = proj[0].mensualite
    const tauxEffort  = params.salaireNet > 0 ? mensualite / params.salaireNet : null
    const ds          = decoteScore(bien.avmRatio)
    const cs          = confortScore(bien)
    const as_         = abordabiliteScore(tauxEffort)
    const profile     = PROFILES.find((p) => p.id === 'rp')!
    const score       = compositeScore(as_, ds, cs, profile.weights)
    // DTI RP : pas de loyer perçu, on vérifie salaire vs mensualité
    const dti = computeEndettement(params.salaireNet, 0, mensualite, params.dettesExistantes, params.taux, params.duree)
    return {
      bien, loyer: 0, chargesAn,
      optMode: 'ir_nu', optModeLabel: 'RP', optRevente: 0, optApport: apport,
      apport0: apport, triOpt: null, cfMois1: proj[0].cashflowAn / 12,
      van5: 0, van8: 0, mensualite,
      ts: as_, ds, cs, score, projOpt: proj, dti, tauxEffort, isRPMode: true,
    }
  }

  // ── Modes locatif / valeur / mixte / marchand ──────────────────────────────
  const { taux, duree, tmi, fraisNotaireP, indexLoyer, indexPrix } = params
  const loyer     = loyerFor(bien)
  const chargesAn = chargesFor(bien)
  const apport    = Math.min(params.apportEur, bien.price)
  const base      = { prix: bien.price, loyer, chargesAn, taux, duree, indexLoyer, indexPrix, tmi, fraisNotaireP }

  // 1 — meilleur mode fiscal (sur apport ref)
  let optMode: FiscalMode = 'lmnp_reel'
  let bestModeCF = -Infinity
  for (const mode of FISCAL_IDS) {
    const p = buildProjection({ ...base, apportEur: apport, dureeRevente: 0, mode })
    if (p[0].cashflowAn > bestModeCF) { bestModeCF = p[0].cashflowAn; optMode = mode }
  }

  // 2 — meilleure année revente (TRI max)
  let optRevente = 10, bestTRI = -Infinity
  for (let yr = 3; yr <= 20; yr++) {
    const p   = buildProjection({ ...base, apportEur: apport, dureeRevente: yr, mode: optMode })
    const tri = computeTRI(apport, bien.price, fraisNotaireP, p, yr)
    if (tri != null && tri > bestTRI) { bestTRI = tri; optRevente = yr }
  }

  // 3 — apport pour CF = 0
  const apport0 = findApportOptimal(bien.price, fraisNotaireP, loyer, chargesAn, taux, duree, tmi, optMode)

  // 4 — projection finale avec paramètres optimaux
  const optApport = apport
  const projOpt   = buildProjection({ ...base, apportEur: optApport, dureeRevente: optRevente, mode: optMode })
  const triOpt    = computeTRI(optApport, bien.price, fraisNotaireP, projOpt, optRevente)

  // 5 — VAN
  const van5 = computeVAN(optApport, bien.price, fraisNotaireP, projOpt, optRevente, 0.05)
  const van8 = computeVAN(optApport, bien.price, fraisNotaireP, projOpt, optRevente, 0.08)

  // 6 — scores
  const profile = PROFILES.find((p) => p.id === profil)!
  const ts = triScore(triOpt)
  const ds = decoteScore(bien.avmRatio)
  const cs = confortScore(bien)
  const score = compositeScore(ts, ds, cs, profile.weights)

  // 7 — taux d'endettement
  const dti = computeEndettement(
    params.salaireNet, loyer, projOpt[0].mensualite, params.dettesExistantes,
    params.taux, params.duree,
  )

  return {
    bien, loyer, chargesAn,
    optMode, optModeLabel: FISCAL_LABELS[optMode], optRevente, optApport,
    apport0, triOpt, cfMois1: projOpt[0].cashflowAn / 12,
    van5, van8, mensualite: projOpt[0].mensualite,
    ts, ds, cs, score, projOpt, dti, tauxEffort: null, isRPMode: false,
  }
}

export function rankBiens(
  biens: CatalogBien[],
  params: OptimParams,
  profil: ProfilAcquisition,
): BienOptimResult[] {
  return biens
    .filter((b) => b.price <= params.budget && b.price > 0 && b.surface > 0)
    .map((b) => optimiseBien(b, params, profil))
    .sort((a, b) => b.score - a.score)
}

// ── Stress test ───────────────────────────────────────────────────────────────

export interface StressResult {
  id: string
  label: string
  color: string
  indexPrix: number
  indexLoyer: number
  vacanceP: number
  tri: number | null
  cfMois1: number
  patrimoineAn10: number
  van5: number
}

export function computeStressTest(
  bien: CatalogBien,
  result: BienOptimResult,
  params: OptimParams,
): StressResult[] {
  const { optMode, optApport, optRevente, loyer, chargesAn } = result
  const { taux, duree, tmi, fraisNotaireP } = params
  const base = {
    prix: bien.price, apportEur: optApport, loyer, chargesAn,
    taux, duree, tmi, fraisNotaireP, mode: optMode, dureeRevente: optRevente,
  }

  const scenarios = [
    { id: 'crisis', label: 'Crise',        color: 'var(--red)',    indexPrix: -3,  indexLoyer: 0.5, vacanceP: 0.15 },
    { id: 'base',   label: 'Base marché',  color: 'var(--accent)', indexPrix:  3,  indexLoyer: 2.0, vacanceP: 0.04 },
    { id: 'boom',   label: 'Boom alpin',   color: 'var(--green)',  indexPrix:  6,  indexLoyer: 3.5, vacanceP: 0.01 },
  ]

  return scenarios.map((s) => {
    const proj = buildProjection({ ...base, indexPrix: s.indexPrix, indexLoyer: s.indexLoyer, vacanceP: s.vacanceP })
    const tri  = computeTRI(optApport, bien.price, fraisNotaireP, proj, optRevente)
    const van5 = computeVAN(optApport, bien.price, fraisNotaireP, proj, optRevente, 0.05)
    return {
      ...s,
      tri,
      cfMois1:         proj[0].cashflowAn / 12,
      patrimoineAn10:  proj[9].patrimoineNet,
      van5,
    }
  })
}

// ── Sensitivity heatmap ───────────────────────────────────────────────────────

export interface SensCell {
  apportPct: number
  taux: number
  tri: number | null
  van5: number
}

const SENS_APPORT_PCTS = [5, 10, 15, 20, 30, 40]
const SENS_TAUX        = [1.5, 2.5, 3.5, 4.5, 5.5, 6.5]

export function computeSensitivity(
  bien: CatalogBien,
  result: BienOptimResult,
  params: OptimParams,
): SensCell[][] {
  const { optMode, optRevente, loyer, chargesAn } = result
  const { duree, tmi, fraisNotaireP, indexLoyer, indexPrix } = params

  return SENS_APPORT_PCTS.map((apportPct) => {
    const apportEur = Math.round(bien.price * apportPct / 100 / 5000) * 5000
    return SENS_TAUX.map((taux) => {
      const proj = buildProjection({
        prix: bien.price, apportEur, loyer, chargesAn,
        taux, duree, tmi, fraisNotaireP, mode: optMode,
        indexLoyer, indexPrix, dureeRevente: optRevente,
      })
      const tri  = computeTRI(apportEur, bien.price, fraisNotaireP, proj, optRevente)
      const van5 = computeVAN(apportEur, bien.price, fraisNotaireP, proj, optRevente, 0.05)
      return { apportPct, taux, tri, van5 }
    })
  })
}

// ── VAN curve (VAN vs taux d'actualisation 0→12%) ────────────────────────────

export interface VanPoint { discountRate: number; van: number }

export function computeVanCurve(
  bien: CatalogBien,
  result: BienOptimResult,
  params: OptimParams,
): VanPoint[] {
  const { optApport, optRevente, projOpt } = result
  const { fraisNotaireP } = params
  return Array.from({ length: 13 }, (_, i) => {
    const r = i * 0.01
    return {
      discountRate: r * 100,
      van: computeVAN(optApport, bien.price, fraisNotaireP, projOpt, optRevente, r),
    }
  })
}

export { SENS_APPORT_PCTS, SENS_TAUX, FISCAL_LABELS }
