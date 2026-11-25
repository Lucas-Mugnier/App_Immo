import avmLookupRaw from '@/data/avm_lookup.json'
import { DVF_STATS } from '@/lib/data'
import maisonSecteursRaw from '@/data/maison_secteurs.json'

const AVM_LOOKUP = avmLookupRaw as Record<string, {
  surf: number[]
  data: Record<string, number[]>
  sections?: Record<string, Record<string, number[]>>
}>

export const EST_COEFFS = {
  etat:    { cata: -0.45, renov: -0.28, moyen: -0.10, bon: 0, tres_bon: 0.10, neuf: 0.18 },
  vue:     { default: 0, vue_deg: 0.04, vue_massif: 0.08, vue_MB: 0.15 },
  etage:   { rdc: -0.06, inter: 0, last: 0.04, last_asc: 0.06 },
  parking: { aucun: 0, ext: 0.015, box: 0.04, dbox: 0.06 },
  ext:     { aucun: 0, balcon: 0.02, loggia: 0.02, terrasse: 0.04, gde_terr: 0.07 },
} as Record<string, Record<string, number>>

function lerp(x: number, x0: number, x1: number, y0: number, y1: number): number {
  if (x1 === x0) return y0
  return y0 + ((x - x0) / (x1 - x0)) * (y1 - y0)
}

export function avmInterp(commune: string, rooms: number, surface: number): number | null {
  const entry = AVM_LOOKUP[commune]
  if (!entry) return null
  const surfs = entry.surf
  const rKey = String(Math.max(1, Math.min(5, rooms)))
  const vals = entry.data[rKey]
  if (!vals || !vals.length) return null

  const s = Math.max(surfs[0], Math.min(surfs[surfs.length - 1], surface))
  let i = 0
  while (i < surfs.length - 1 && surfs[i + 1] < s) i++
  if (i >= surfs.length - 1) return vals[vals.length - 1] ?? null

  const v0 = vals[i], v1 = vals[i + 1]
  if (v0 == null || v1 == null) return null
  return Math.round(lerp(s, surfs[i], surfs[i + 1], v0, v1))
}

export function avmAffine(base: number, etat: string, vue: string, etage: string, parking: string, ext: string): number {
  const c = EST_COEFFS
  const delta = (c.etat[etat] ?? 0) + (c.vue[vue] ?? 0) + (c.etage[etage] ?? 0) + (c.parking[parking] ?? 0) + (c.ext[ext] ?? 0)
  return Math.round(base * (1 + delta))
}

// Toutes les communes du lookup — Chamonix/Argentière ±8.8%, vallée ±15%
export const AVM_COMMUNES = Object.keys(AVM_LOOKUP)

// ── Maison — décote surface ────────────────────────────────────────────────────
// Les grands chalets ont un PM² plus faible que la médiane (calculée sur ~130-180m²).
// Le coefficient est appliqué sur le PM² AVANT multiplication par la surface.

function lerpLocal(x: number, x0: number, x1: number, y0: number, y1: number): number {
  return x1 === x0 ? y0 : y0 + ((x - x0) / (x1 - x0)) * (y1 - y0)
}

export function surfaceDiscount(surface: number): number {
  if (surface <= 100) return 1.12
  if (surface <= 160) return lerpLocal(surface, 100, 160, 1.12, 1.00)
  if (surface <= 250) return lerpLocal(surface, 160, 250, 1.00, 0.93)
  if (surface <= 400) return lerpLocal(surface, 250, 400, 0.93, 0.85)
  return 0.85
}

export function surfaceDiscountLabel(surface: number): string {
  const d = surfaceDiscount(surface)
  const pct = Math.round((d - 1) * 100)
  const sign = pct >= 0 ? '+' : ''
  return `${sign}${pct} % (décote surface)`
}

// ── Maison — terrain coefficient ───────────────────────────────────────────────
// Le PM² issu des annonces/DVF inclut DÉJÀ la valeur du terrain implicitement
// (prix_total / surface_hab). Le coefficient terrain ne corrige que l'écart
// par rapport à un terrain "standard" (~300–700 m²) pour ce type de bien.
// Coefficients volontairement conservateurs pour éviter le double-comptage.

export function terrainCoeff(surfTerrain: number): number {
  if (surfTerrain < 150) return -0.03
  if (surfTerrain < 300) return -0.01
  if (surfTerrain < 700) return 0          // terrain standard
  if (surfTerrain < 1500) return 0.02
  if (surfTerrain < 3000) return 0.03
  return 0.04
}

export function terrainLabel(surfTerrain: number): string {
  if (surfTerrain < 150) return '−3 % (très petit terrain)'
  if (surfTerrain < 300) return '−1 % (petit terrain)'
  if (surfTerrain < 700) return '±0 % (terrain standard)'
  if (surfTerrain < 1500) return '+2 % (grand terrain)'
  if (surfTerrain < 3000) return '+3 % (très grand terrain)'
  return '+4 % (terrain exceptionnel)'
}

// ── Maison — modèle DVF (transactions historiques) ────────────────────────────

// Les sections cadastrales de maisons maps vers la commune DVF
export const HOOD_TO_DVF_COMMUNE: Record<string, string> = {
  'Argentière':      'CHAMONIX MONT BLANC',
  'Chamonix Centre': 'CHAMONIX MONT BLANC',
  'Chamonix (secteur non précisé)': 'CHAMONIX MONT BLANC',
  'Les Bossons':     'CHAMONIX MONT BLANC',
  'Les Gaillands':   'CHAMONIX MONT BLANC',
  'Les Praz':        'CHAMONIX MONT BLANC',
  'Les Tines':       'CHAMONIX MONT BLANC',
  'Les Houches':     'LES HOUCHES',
  'Servoz':          'SERVOZ',
  'Saint-Gervais':   'SAINT GERVAIS LES BAINS',
  'Sallanches':      'SALLANCHES',
  'Passy':           'PASSY',
}

export interface MaisonDvfStats {
  median_m2: number; n: number; q1_m2: number; q3_m2: number
}

export function getMaisonDvfStats(secteur: string): MaisonDvfStats | null {
  const dvfCommune = HOOD_TO_DVF_COMMUNE[secteur] ?? secteur
  const data = DVF_STATS.communes[dvfCommune]?.by_type?.maison
  if (!data?.median_m2 || data.n < 3) return null
  return { median_m2: data.median_m2, n: data.n, q1_m2: data.q1_m2, q3_m2: data.q3_m2 }
}

export function avmMaisonDvf(secteur: string, surface: number): number | null {
  const stats = getMaisonDvfStats(secteur)
  if (!stats) return null
  return Math.round(stats.median_m2 * surfaceDiscount(surface) * surface)
}

// ── Maison — modèle annonces en cours ─────────────────────────────────────────

export interface SecteurStats {
  secteur: string; n: number
  medianPm2: number; minPm2: number; maxPm2: number
}

// Statistiques AGRÉGÉES par secteur (médiane/min/max PM² des annonces maisons),
// générées par scripts/publish-data.mjs. Aucune annonce individuelle n'est publique.
export const MAISON_SECTEURS: Record<string, SecteurStats> =
  maisonSecteursRaw as unknown as Record<string, SecteurStats>

export const ALL_MAISON_SECTEURS = Object.keys(MAISON_SECTEURS).sort()

export function avmMaisonAnnonces(secteur: string, surface: number): number | null {
  const stats = MAISON_SECTEURS[secteur]
  if (!stats || stats.n === 0) return null
  return Math.round(stats.medianPm2 * surfaceDiscount(surface) * surface)
}

// ── Maison — coefficients spécifiques ─────────────────────────────────────────
// Vue : la plupart des maisons à Chamonix ont déjà une bonne vue — le premium
// est plus faible que pour les apparts (où vue_MB est rare).
// Parking : valeur absolue fixe, pas % — un garage vaut ~35k€ qu'il soit sur
// une maison à 800k€ ou 4M€, pas un % du prix total.

export const EST_COEFFS_MAISON = {
  etat:       { cata: -0.45, renov: -0.28, moyen: -0.10, bon: 0, tres_bon: 0.10, neuf: 0.18 } as Record<string, number>,
  vue:        { default: 0, vue_deg: 0.02, vue_massif: 0.04, vue_MB: 0.07 } as Record<string, number>,
  parkingAbs: { aucun: 0, ext: 15_000, box: 35_000, dbox: 60_000 } as Record<string, number>,
}

export function parkingMaisonLabel(parking: string): string {
  const v = EST_COEFFS_MAISON.parkingAbs[parking] ?? 0
  if (v === 0) return ''
  return `+${(v / 1000).toFixed(0)}k€ (garage)`
}

export function vueMaisonLabel(vue: string): string {
  const v = EST_COEFFS_MAISON.vue[vue] ?? 0
  if (v === 0) return ''
  return `+${Math.round(v * 100)}% (vue)`
}

// ── Maison — affinage commun aux deux modèles ──────────────────────────────────

export function avmAffineMaison(base: number, etat: string, vue: string, surfTerrain: number, parking: string): number {
  const pctDelta = (EST_COEFFS_MAISON.etat[etat] ?? 0) + (EST_COEFFS_MAISON.vue[vue] ?? 0) + terrainCoeff(surfTerrain)
  const absAdj   = EST_COEFFS_MAISON.parkingAbs[parking] ?? 0
  return Math.round(base * (1 + pctDelta) + absAdj)
}

// Pour filtrer les communes DVF qui ont des données maison
export const AVM_MAISON_COMMUNES = Object.keys(DVF_STATS.communes).filter(
  (k) => (DVF_STATS.communes[k]?.by_type?.maison?.n ?? 0) >= 3,
)

// ── Options chips ──────────────────────────────────────────────────────────────

export const AVM_OPTS = {
  etat: [
    { value: 'bon',      label: 'Bon état' },
    { value: 'tres_bon', label: 'Très bon' },
    { value: 'neuf',     label: 'Neuf/refait' },
    { value: 'moyen',    label: 'Moyen' },
    { value: 'renov',    label: 'À rénover' },
    { value: 'cata',     label: 'Catastrophique' },
  ],
  vue: [
    { value: 'default',    label: 'Standard' },
    { value: 'vue_deg',    label: 'Dégagée' },
    { value: 'vue_massif', label: 'Vue massif' },
    { value: 'vue_MB',     label: 'Vue Mont-Blanc' },
  ],
  etage: [
    { value: 'inter',    label: 'Étage intermédiaire' },
    { value: 'rdc',      label: 'RDC' },
    { value: 'last',     label: 'Dernier étage' },
    { value: 'last_asc', label: 'Dernier + ascenseur' },
  ],
  parking: [
    { value: 'aucun', label: 'Sans parking' },
    { value: 'ext',   label: 'Parking extérieur' },
    { value: 'box',   label: 'Box / garage fermé' },
    { value: 'dbox',  label: 'Double garage' },
  ],
  ext: [
    { value: 'aucun',    label: 'Aucun extérieur' },
    { value: 'balcon',   label: 'Balcon' },
    { value: 'loggia',   label: 'Loggia' },
    { value: 'terrasse', label: 'Terrasse' },
    { value: 'gde_terr', label: 'Grande terrasse' },
  ],
}
