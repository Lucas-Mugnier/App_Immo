import type { Listing, Maison } from '@/types'
import dvfRaw from '@/data/dvf_stats.json'
import dvfPointsRaw from '@/data/dvf_points.json'

/**
 * Périmètre marché : CHAMONIX UNIQUEMENT (incl. Argentière, même commune).
 * Les annonces vallée (Les Houches, Sallanches, St-Gervais…) restent dans
 * listings.json mais sont exclues du dashboard tant que le périmètre
 * n'est pas élargi. Modèle AVM définitif = chamonix_apt seulement.
 */
export const MARKET_SCOPE = ['Chamonix', 'Argentiere', 'Argentière'] as const

/*
 * Données PRIVÉES (annonces scrapées) : elles ne sont JAMAIS incluses dans le
 * bundle public. Elles sont téléchargées après connexion d'un compte autorisé
 * (voir lib/privateData.ts) puis injectées ici via setPrivateData().
 * Les exports `let` sont des live bindings ES : les modules qui lisent APPARTS
 * au moment du rendu voient les nouvelles valeurs. Les onglets privés sont
 * chargés en lazy APRÈS l'injection, donc leur code module-level aussi.
 */
export let APPARTS: Listing[] = []
export let APPARTS_HORS_SCOPE: Listing[] = []
export let MAISONS: Maison[] = []

export const COUNTS = { apparts: 0, maisons: 0, horsScope: 0 }

export function setPrivateData(listings: Listing[], maisons: Maison[]) {
  APPARTS = listings.filter((r) => (MARKET_SCOPE as readonly string[]).includes(r.location))
  APPARTS_HORS_SCOPE = listings.filter((r) => !(MARKET_SCOPE as readonly string[]).includes(r.location))
  MAISONS = maisons
  COUNTS.apparts = APPARTS.length
  COUNTS.maisons = MAISONS.length
  COUNTS.horsScope = APPARTS_HORS_SCOPE.length
}

export interface DvfCommuneYear {
  median_m2: number
  n: number
  q1?: number
  q3?: number
}

export interface DvfByType {
  median_m2: number
  n: number
  q1_m2: number
  q3_m2: number
}

export interface DvfCommune {
  display: string
  n: number
  median_m2: number
  q1_m2: number
  q3_m2: number
  mean_m2: number
  cagr_pct: number
  trend_pct: number
  parking_pct: number
  by_year: Record<string, DvfCommuneYear>
  by_type?: { appart?: DvfByType; maison?: DvfByType }
}

export interface DvfStats {
  generated_at: string
  total_transactions: number
  annees: number[]
  communes: Record<string, DvfCommune>
}

export const DVF_STATS = dvfRaw as unknown as DvfStats

export interface DvfPoint {
  lat:  number
  lon:  number
  a:    string | null   // adresse
  p:    number          // prix total
  s:    number          // surface m²
  m2:   number | null   // prix/m²
  t:    string          // type: "appart" | "maison"
  y:    string          // annee
  sec:  string          // section cadastrale
  ter?: number          // terrain m² (maisons uniquement)
}

export const DVF_POINTS = dvfPointsRaw as unknown as DvfPoint[]
