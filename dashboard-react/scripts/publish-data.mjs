#!/usr/bin/env node
/**
 * publish-data.mjs — publie les annonces exportées vers Supabase (bucket PRIVÉ)
 * et régénère les agrégats publics.
 *
 *   node scripts/publish-data.mjs
 *
 * Entrées  : private-data/listings.json, private-data/maisons.json
 *            (écrits par tools/_export_react_data.py — jamais commités)
 * Sorties  : - upload vers Storage « private-data » (lecture réservée aux
 *              comptes de public.allowed_users) → visible en ligne immédiatement,
 *              sans redéploiement
 *            - src/data/maison_secteurs.json (stats agrégées, publiques) :
 *              à commiter/pusher si le fichier a changé (redéploiement Vercel)
 *
 * Secrets  : dashboard-react/.env.publish (gitignoré)
 *              SUPABASE_URL=https://xxx.supabase.co
 *              SUPABASE_SERVICE_ROLE_KEY=...   (clé service_role — NE JAMAIS l'exposer)
 */
import { readFileSync, writeFileSync, existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { createClient } from '@supabase/supabase-js'

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..')
const BUCKET = 'private-data'

function loadEnv(file) {
  if (!existsSync(file)) return
  for (const line of readFileSync(file, 'utf8').split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/)
    if (m && !process.env[m[1]]) process.env[m[1]] = m[2].replace(/^["']|["']$/g, '')
  }
}
loadEnv(join(ROOT, '.env.publish'))
loadEnv(join(ROOT, '.env.local'))

const url = process.env.SUPABASE_URL || process.env.VITE_SUPABASE_URL
const key = process.env.SUPABASE_SERVICE_ROLE_KEY
if (!url || !key) {
  console.error('ERREUR : SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY requis (fichier dashboard-react/.env.publish).')
  process.exit(1)
}

const looksValid = (key.startsWith('eyJ') && key.split('.').length === 3) || key.startsWith('sb_secret_')
if (!looksValid) {
  console.error(`ERREUR : SUPABASE_SERVICE_ROLE_KEY ne ressemble pas à une clé secrète (${key.length} caractères).`)
  console.error('  → Supabase → Project Settings → API Keys → onglet « Legacy API keys » → service_role → Reveal → copier')
  console.error('    (une longue chaîne qui commence par eyJ…), ou une clé « sb_secret_… ».')
  process.exit(1)
}

const readJson = (p) => JSON.parse(readFileSync(join(ROOT, p), 'utf8'))
const listings = readJson('private-data/listings.json')
const maisons  = readJson('private-data/maisons.json')
if (!Array.isArray(listings) || !Array.isArray(maisons) || listings.length === 0) {
  console.error('ERREUR : private-data/*.json vide ou invalide — lance d\'abord tools/_export_react_data.py')
  process.exit(1)
}

// ── 1. Agrégats publics lissés (« échantillon », aucune annonce individuelle) ──
const median = (a) => { const s = [...a].sort((x, y) => x - y); const m = Math.floor(s.length / 2); return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2 }
const byHood = {}
for (const m of maisons) {
  if (!m.prix || !m.surface) continue
  ;(byHood[m.neighbourhood] ??= []).push(m.prix / m.surface)
}
// Lissage : PM² arrondis à la centaine, et secteurs de moins de MIN_N biens masqués
// (stats à zéro) pour qu'aucun bien individuel ne soit identifiable.
const MIN_N = 3
const r100 = (x) => Math.round(x / 100) * 100
const secteurs = {}
for (const h of Object.keys(byHood).sort()) {
  const v = byHood[h]
  secteurs[h] = v.length >= MIN_N
    ? { secteur: h, n: v.length, medianPm2: r100(median(v)), minPm2: r100(Math.min(...v)), maxPm2: r100(Math.max(...v)) }
    : { secteur: h, n: 0, medianPm2: 0, minPm2: 0, maxPm2: 0 }
}
const secPath = join(ROOT, 'src/data/maison_secteurs.json')
const before = existsSync(secPath) ? readFileSync(secPath, 'utf8') : ''
const after = JSON.stringify(secteurs, null, 2) + '\n'
writeFileSync(secPath, after)
console.log(`✓ maison_secteurs.json — ${Object.keys(secteurs).length} secteurs${before.trim() === after.trim() ? ' (inchangé)' : ' (MODIFIÉ → commit + push pour mettre le site à jour)'}`)

// ── 2. Upload privé ──────────────────────────────────────────────────────────
const supabase = createClient(url, key, { auth: { persistSession: false } })
for (const [name, data] of [['listings.json', listings], ['maisons.json', maisons]]) {
  const { error } = await supabase.storage.from(BUCKET).upload(name, JSON.stringify(data), {
    contentType: 'application/json', upsert: true, cacheControl: '60',
  })
  if (error) { console.error(`ERREUR upload ${name} :`, error.message); process.exit(1) }
  console.log(`✓ ${name} publié (${data.length} biens) → bucket privé « ${BUCKET} »`)
}
console.log('Terminé. Les comptes autorisés voient les nouvelles annonces au prochain chargement.')
