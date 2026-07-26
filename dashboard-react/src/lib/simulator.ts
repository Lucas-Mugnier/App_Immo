import type { FiscalMode } from '@/types'

// Plus-value immobilière — taux effectif après abattements progressifs
// IR: exonéré après 22 ans (6%/an dès an 6)
// PS: exonéré après 30 ans (1.65%/an dès an 6, puis 9%/an dès an 22)
function tauxPlusValue(anneesDetention: number): number {
  if (anneesDetention >= 30) return 0
  const abatIR = anneesDetention >= 6
    ? Math.min(1, (anneesDetention - 5) * 0.06)
    : 0
  const abatCS = anneesDetention >= 22
    ? Math.min(1, (anneesDetention - 5) * 0.0165 + (anneesDetention - 22) * 0.09)
    : anneesDetention >= 6
    ? Math.min(1, (anneesDetention - 5) * 0.0165)
    : 0
  return (1 - abatIR) * 0.19 + (1 - abatCS) * 0.172
}

export interface ProjRow {
  annee: number
  loyerAnnuel: number; chargesYr: number; interets: number; impot: number
  mensualite: number; cashflowAn: number; cashflowCumul: number
  valeurBien: number; capitalRestant: number; patrimoineNet: number
  gainRevente: number | null
}

export function buildProjection(p: {
  prix: number; apportEur: number; loyer: number; chargesAn: number
  taux: number; duree: number; indexLoyer: number; indexPrix: number
  tmi: number; dureeRevente: number; mode: FiscalMode; fraisNotaireP: number
  vacanceP?: number
}): ProjRow[] {
  const {
    prix, apportEur, loyer, chargesAn, taux, duree, indexLoyer, indexPrix,
    tmi, dureeRevente, mode, fraisNotaireP, vacanceP = 0,
  } = p
  const fraisNotaire = prix * fraisNotaireP / 100
  const emprunt      = Math.max(0, prix - apportEur)
  const r            = (taux / 100) / 12
  const n            = duree * 12
  const mensualite   = r > 0 && emprunt > 0
    ? emprunt * r / (1 - Math.pow(1 + r, -n))
    : emprunt > 0 ? emprunt / n : 0
  const amortAn      = prix * 0.85 / 25

  let capitalRestant = emprunt
  let cashflowCumul  = 0

  return Array.from({ length: 20 }, (_, idx) => {
    const yr          = idx + 1
    const loyerBrut   = loyer * 12 * Math.pow(1 + indexLoyer / 100, yr - 1)
    const loyerAnnuel = loyerBrut * (1 - vacanceP)
    const chargesYr   = chargesAn * Math.pow(1.02, yr - 1)
    const valeurBien  = prix * Math.pow(1 + indexPrix / 100, yr)

    let interets = 0
    for (let m = 0; m < 12; m++) {
      const intM = capitalRestant * r
      const capM = Math.min(mensualite - intM, capitalRestant)
      interets      += intM
      capitalRestant = Math.max(0, capitalRestant - capM)
    }

    const tTotal = (tmi + 17.2) / 100
    let impot = 0
    if (mode === 'lmnp_reel') {
      impot = Math.max(0, loyerAnnuel - chargesYr - interets - amortAn) * tTotal
    } else if (mode === 'lmnp_micro') {
      impot = loyerAnnuel * 0.5 * tTotal
    } else if (mode === 'ir_nu') {
      impot = loyerAnnuel <= 15_000
        ? loyerAnnuel * 0.7 * tTotal
        : Math.max(0, loyerAnnuel - chargesYr - interets) * tTotal
    } else {
      const bnc = Math.max(0, loyerAnnuel - chargesYr - interets - amortAn)
      impot = bnc <= 42_500 ? bnc * 0.15 : 42_500 * 0.15 + (bnc - 42_500) * 0.25
    }

    const cashflowAn = loyerAnnuel - chargesYr - mensualite * 12 - impot
    cashflowCumul   += cashflowAn
    const patrimNow  = valeurBien - capitalRestant + cashflowCumul - (apportEur + fraisNotaire)

    let gainRevente: number | null = null
    if (yr === dureeRevente && dureeRevente > 0) {
      const fraisVente   = valeurBien * 0.05
      const gainBrut     = valeurBien - (prix + fraisNotaire)
      const taxPV        = gainBrut > 0 ? gainBrut * tauxPlusValue(yr) : 0
      gainRevente = Math.round(
        valeurBien - capitalRestant - fraisVente - taxPV - (apportEur + fraisNotaire) + cashflowCumul
      )
    }

    return {
      annee: yr,
      loyerAnnuel: Math.round(loyerAnnuel), chargesYr: Math.round(chargesYr),
      interets: Math.round(interets), impot: Math.round(impot),
      mensualite: Math.round(mensualite),
      cashflowAn: Math.round(cashflowAn), cashflowCumul: Math.round(cashflowCumul),
      valeurBien: Math.round(valeurBien), capitalRestant: Math.round(capitalRestant),
      patrimoineNet: Math.round(patrimNow), gainRevente,
    }
  })
}

export function computeTRI(
  apportEur: number, prix: number, fraisNotaireP: number,
  rows: ProjRow[], revente: number,
): number | null {
  const invest = -(apportEur + prix * fraisNotaireP / 100)
  const flows  = [invest, ...rows.map((r, i) =>
    i + 1 === revente && r.gainRevente != null ? r.gainRevente : r.cashflowAn,
  )]
  let rate = 0.07
  for (let iter = 0; iter < 200; iter++) {
    let npv = 0, dnpv = 0
    for (let t = 0; t < flows.length; t++) {
      const d = Math.pow(1 + rate, t)
      npv  += flows[t] / d
      dnpv -= t * flows[t] / (d * (1 + rate))
    }
    if (Math.abs(dnpv) < 1e-10) break
    const next = rate - npv / dnpv
    if (Math.abs(next - rate) < 1e-7) { rate = next; break }
    rate = Math.max(-0.99, Math.min(5, next))
  }
  return isFinite(rate) && rate > -0.99 && rate < 5 ? rate * 100 : null
}

export function computeVAN(
  apportEur: number, prix: number, fraisNotaireP: number,
  rows: ProjRow[], revente: number, discountRate: number,
): number {
  const invest = apportEur + prix * fraisNotaireP / 100
  let van = -invest
  const n = Math.min(rows.length, revente > 0 ? revente : rows.length)
  for (let t = 0; t < n; t++) {
    const row = rows[t]
    let cf = row.cashflowAn
    if (revente > 0 && t + 1 === revente) {
      cf += row.valeurBien - row.capitalRestant - row.valeurBien * 0.05
    }
    van += cf / Math.pow(1 + discountRate, t + 1)
  }
  if (revente <= 0) {
    const last = rows[n - 1]
    van += (last.valeurBien - last.capitalRestant - last.valeurBien * 0.05) /
      Math.pow(1 + discountRate, n)
  }
  return Math.round(van)
}

export function findApportOptimal(
  prix: number, fraisNotaireP: number, loyer: number, chargesAn: number,
  taux: number, duree: number, tmi: number, mode: FiscalMode, vacanceP = 0,
): number {
  let lo = 0, hi = Math.round(prix * (1 + fraisNotaireP / 100))
  for (let i = 0; i < 60; i++) {
    const mid  = Math.round((lo + hi) / 2)
    const proj = buildProjection({
      prix, apportEur: mid, loyer, chargesAn, taux, duree,
      indexLoyer: 2, indexPrix: 3, tmi, dureeRevente: 0, mode, fraisNotaireP, vacanceP,
    })
    if (proj[0].cashflowAn >= 0) hi = mid
    else lo = mid
    if (hi - lo <= 500) break
  }
  return Math.ceil(hi / 5000) * 5000
}
