import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function eur(n: number | null | undefined, digits = 0): string {
  if (n == null) return '—'
  return new Intl.NumberFormat('fr-FR', {
    style: 'currency',
    currency: 'EUR',
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n)
}

export function eurCompact(n: number | null | undefined): string {
  if (n == null) return '—'
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M€`
  if (Math.abs(n) >= 1_000) return `${Math.round(n / 1_000)}k€`
  return `${n}€`
}

export function pct(n: number | null | undefined, digits = 1): string {
  if (n == null) return '—'
  return `${n > 0 ? '+' : ''}${n.toFixed(digits)}%`
}

export function num(n: number | null | undefined, digits = 0): string {
  if (n == null) return '—'
  return new Intl.NumberFormat('fr-FR', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(n)
}

export function pm2(price: number | null, surface: number | null): number | null {
  if (!price || !surface || surface === 0) return null
  return Math.round(price / surface)
}

export function daysAgo(dateStr: string | null | undefined): number {
  if (!dateStr) return 999
  const d = new Date(dateStr)
  const now = new Date()
  return Math.floor((now.getTime() - d.getTime()) / (1000 * 60 * 60 * 24))
}

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '—'
  const d = new Date(dateStr)
  return new Intl.DateTimeFormat('fr-FR', { day: '2-digit', month: '2-digit' }).format(d)
}

export function scoreColor(score: number): string {
  if (score >= 80) return 'text-glow-green'
  if (score >= 60) return 'text-ice-bright'
  if (score >= 40) return 'text-glow-amber'
  return 'text-glow-red'
}

export function scoreBgColor(score: number): string {
  if (score >= 80) return 'bg-glow-green/10 border-glow-green/30 text-glow-green'
  if (score >= 60) return 'bg-ice-bright/10 border-ice-bright/30 text-ice-bright'
  if (score >= 40) return 'bg-glow-amber/10 border-glow-amber/30 text-glow-amber'
  return 'bg-glow-red/10 border-glow-red/30 text-glow-red'
}

export function ratioColor(ratio: number | null): string {
  if (ratio == null) return 'text-alpine-muted'
  if (ratio >= 1.15) return 'text-glow-green'
  if (ratio >= 1.05) return 'text-ice-bright'
  if (ratio >= 0.95) return 'text-glow-amber'
  return 'text-glow-red'
}

export function ratioBg(ratio: number | null): string {
  if (ratio == null) return ''
  if (ratio >= 1.15) return 'bg-glow-green/10 border-glow-green/30 text-glow-green'
  if (ratio >= 1.05) return 'bg-ice-bright/10 border-ice-bright/30 text-ice-bright'
  if (ratio >= 0.95) return 'bg-glow-amber/10 border-glow-amber/30 text-glow-amber'
  return 'bg-glow-red/10 border-glow-red/30 text-glow-red'
}

export function median(arr: number[]): number {
  if (!arr.length) return 0
  const sorted = [...arr].sort((a, b) => a - b)
  const mid = Math.floor(sorted.length / 2)
  return sorted.length % 2 !== 0
    ? sorted[mid]
    : (sorted[mid - 1] + sorted[mid]) / 2
}

export const SECTION_LABELS: Record<string, string> = {
  A: 'Argentière / Le Tour',
  B: 'Les Praz / La Flégère',
  C: 'Centre Nord',
  D: 'Les Bois',
  E: 'Les Bossons / Les Pélerins',
  G: 'Centre-Ville',
}

export const COMMUNE_ORDER = [
  'Chamonix', 'Argentière', 'Les Houches', 'Saint-Gervais',
  'Sallanches', 'Passy', 'Servoz', 'Domancy',
]

// Valley west → east, then outlying communes
export const NEIGHBOURHOOD_ORDER = [
  'Les Houches',
  'Les Bossons',
  'Les Pélerins',
  'Les Gaillands',
  'Chamonix Centre',
  'Les Praz',
  'Les Tines',
  'Le Lavancher',
  'Argentière',
  'Montroc',
  'Le Tour',
  'Servoz',
  'Saint-Gervais',
  'Sallanches',
  'Passy',
  'Domancy',
]
