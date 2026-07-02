export interface PriceHistory {
  date: string
  price?: number
  prix?: number
}

export interface Listing {
  id: string
  url: string
  title: string
  price: number
  surface: number
  rooms: number
  location: string
  neighbourhood: string
  surface_carrez?: number | null
  charges: number | null
  dpe: string
  ges: string
  score: number | null
  reasons: string[]
  yield: number | null
  vs_market: number | null
  enriched: number
  first_seen: string
  urls: string[]
  _location_original: string
  _loc_corrected: boolean
  days_on_market: number
  price_history: PriceHistory[]
  price_drop: number | null
  is_relisted: boolean
  relisted_after_days: number | null
  avm_pred: number | null
  avm_ratio: number | null
  avm_model: 'chamonix_apt' | 'vallee_apt' | null
  nb_baisses?: number
  photos?: string[]
  is_structured?: boolean
  // runtime state
  _seen?: boolean
  _rejected?: boolean
  _hidden?: boolean
  _note?: string
}

export interface Maison {
  id: number
  url: string | null
  titre: string | null
  adresse_raw: string
  section: string
  neighbourhood: string
  surface: number
  surf_terrain: number | null
  pieces: number
  prix: number
  prix_initial: number
  nb_baisses: number
  historique_prix: PriceHistory[]
  avm_pred: number | null
  avm_ratio: number | null
  avm_score: number | null
  first_seen: string
  notes: string | null
  lat: number | null
  lon: number | null
  photos?: string[]
  description?: string
  needs_renovation?: boolean
  is_structured?: boolean
  yield?: number | null
  avm_model?: 'chamonix_apt' | 'vallee_apt' | null
  // runtime state
  _seen?: boolean
  _rejected?: boolean
  _hidden?: boolean
}

export type TabId = 'biens' | 'insights' | 'comparateur' | 'simulation' | 'optimiseur' | 'analyse' | 'apprendre' | 'profil' | 'admin'

export type WatchlistStatus = 'a_visiter' | 'visite' | 'offre' | 'refuse'

export interface WatchlistEntry {
  status: WatchlistStatus
  addedAt: string
  title: string
  price: number
  surface: number
  neighbourhood: string
  type: 'appart' | 'maison'
  score: number | null
  url: string | null
}

export type InvestStrategie = 'mixte' | 'locatif' | 'patrimonial' | 'rp' | 'potentiel'

export interface InvestProfile {
  budgetMax: number
  surfaceMin: number
  rendementMin: number
  scoreMin: number
  types: ('appart' | 'maison')[]
  secteurs: string[]
  strategie: InvestStrategie
}

export type BienType = 'apparts' | 'maisons'

export interface OverrideState {
  seen: Set<string>
  rejected: Set<string>
  hidden: Set<string>
  notes: Record<string, string>
  locationEdits: Record<string, string>
}

export type SortDir = 'asc' | 'desc'

export interface SortState {
  key: string
  dir: SortDir
}

export interface AppartFilters {
  search: string
  minScore: number
  minPrice: number
  maxPrice: number
  minSurface: number
  minRooms: number
  minYield: number
  maxDpe: string        // '' = tous, 'C' = garder A/B/C, etc.
  location: string[]
  priceDropOnly: boolean
  freshOnly: boolean
  showHidden: boolean
  showRejected: boolean
  hideStructured: boolean
}

export interface MaisonFilters {
  search: string
  minScore: number
  minPrice: number
  maxPrice: number
  minSurface: number
  minTerrain: number
  minRooms: number
  section: string[]
  renovationFilter: 'all' | 'only' | 'exclude'
  showRejected: boolean
  hideStructured: boolean
}

export type InsightType = 'all' | 'apparts' | 'maisons'
export type MapMetric = 'pm2' | 'ratio' | 'score'

export type FiscalMode = 'lmnp_reel' | 'lmnp_micro' | 'ir_nu' | 'sci_is'
export type SimObjectif = 'tri' | 'cashflow' | 'patrimoine'

export interface SimParams {
  selectedId: string
  mode: FiscalMode
  tmi: number
  taux: number
  duree: number
  loyer: number
  chargesAn: number
  apportEur: number
  fraisNotaireP: number
  indexLoyer: number
  indexPrix: number
  revente: number
  planRevente: boolean
  objectif: SimObjectif
}

export interface EstimateurState {
  open: boolean
  propType: 'appart' | 'maison'
  surface: number
  rooms: number
  commune: string
  price: number
  etat: string
  vue: string
  etage: string
  parking: string
  ext: string
  surfTerrain: number
  secteur: string
  listingId?: string
}
