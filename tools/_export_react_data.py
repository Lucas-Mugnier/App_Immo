"""
_export_react_data.py
=====================
Reads from dvf/listings_market.db and exports the JSON files consumed by the React dashboard.
No longer depends on dashboard.html (email bot architecture removed).

Usage:
    python _export_react_data.py
"""
import json, re, sqlite3, sys, unicodedata
from pathlib import Path
from datetime import datetime

sys.stdout.reconfigure(encoding="utf-8")

BASE  = Path(__file__).parent.parent   # project root (tools/../)
DB    = BASE / "dvf" / "listings_market.db"
REACT = BASE / "dashboard-react" / "src" / "data"
# Annonces scrapées : PRIVÉES — jamais dans src/ (sinon incluses dans le bundle public).
# Publiées vers Supabase Storage par dashboard-react/scripts/publish-data.mjs
PRIVATE = BASE / "dashboard-react" / "private-data"
PRIVATE.mkdir(exist_ok=True)
CFG   = BASE / "config.json"
STRUCTURED_IDS_FILE          = BASE / "tools" / "_structured_ids.json"
NEIGHBOURHOOD_OVERRIDES_FILE = BASE / "tools" / "_neighbourhood_overrides.json"
SURFACE_CARREZ_FILE          = BASE / "tools" / "_surface_carrez_overrides.json"

if not DB.exists():
    print("ERREUR: dvf/listings_market.db introuvable — lancez d'abord scraper_nd.py")
    sys.exit(1)

if not REACT.exists():
    print("ERREUR: dashboard-react/src/data/ introuvable")
    sys.exit(1)

# Rent references for yield computation
RENT_PM2 = {}
if CFG.exists():
    cfg = json.loads(CFG.read_text(encoding="utf-8"))
    RENT_PM2 = cfg.get("criteria", {}).get("rent_per_m2_monthly", {})

# DB commune (uppercase) → (React display name, config.json key)
COMMUNE_MAP = {
    "CHAMONIX MONT BLANC":     ("Chamonix",      "Chamonix"),
    "LES HOUCHES":             ("Les Houches",   "Les Houches"),
    "SAINT GERVAIS LES BAINS": ("Saint-Gervais", "Saint-Gervais"),
    "SALLANCHES":              ("Sallanches",    "Sallanches"),
    "PASSY":                   ("Passy",         "Passy"),
    "SERVOZ":                  ("Servoz",        "Servoz"),
    "DOMANCY":                 ("Domancy",       "Domancy"),
}

# DB avm_model tag → React union literal
def map_avm_model(tag):
    if tag in ("chamonix_apt_meta", "chamonix_mai_xgb", "avm_lookup"):
        return "chamonix_apt"
    if tag in ("dvf_stats", "vallee_apt"):
        return "vallee_apt"
    return None

_LOGO_PATH_PATTERNS = ['/logo', '/agence', '/logotype', '/agency']

def filter_photos(photos: list) -> list:
    """Supprime les logos d'agences SeLoger.
    Pattern logo : ?ci_seal=...&h=50 (h <= 100, pas de w=)
    Pattern photo : ?ci_seal=...&w=626&h=470 (toujours un w=)
    """
    out = []
    for url in photos:
        if not url:
            continue
        # Exclure chemins logo/agence explicites
        low = url.lower()
        if any(p in low for p in _LOGO_PATH_PATTERNS):
            continue
        # Logo SeLoger = h=50 sans w= dans les query params
        has_w = bool(re.search(r'[?&]w=\d+', url))
        h_m = re.search(r'[?&]h=(\d+)', url)
        if not has_w and h_m and int(h_m.group(1)) <= 100:
            continue
        # Garder uniquement si URL vide de params OU a un w= de taille raisonnable
        if has_w:
            w_val = int(re.search(r'[?&]w=(\d+)', url).group(1))
            if w_val < 200:
                continue
        out.append(url)
    return out

_RENO_KEYWORDS = [
    'à rénover', 'a renover', 'à réhabiliter', 'à rehabiliter',
    'travaux', 'rénovation', 'renovation', 'rénover', 'renover',
    'à rafraîchir', 'à rafraichir', 'rafraîchissement', 'rafraichissement',
    'remettre en état', 'remise en état', 'à remettre', 'mettre en valeur',
    'réhabiliter', 'rehabiliter', 'grange', 'ferme', 'ancienne ferme',
    'travaux à prévoir', 'travaux a prevoir', 'nécessite des travaux',
    'plan énergétique', 'plan energetique', 'isolation à prévoir',
    'permis de construire', 'potentiel de construction',
]

# Mots-clés qui annulent une fausse détection (travaux déjà réalisés)
_RENO_NEGATORS = [
    'travaux réalisés', 'travaux realises', 'travaux effectués', 'travaux effectues',
    'après travaux', 'apres travaux', 'rénové', 'renove', 'rénovation terminée',
    'récemment rénové', 'recemment renove', 'entièrement rénové', 'entierement renove',
    'parfaitement entretenu', 'très bon état', 'tres bon etat', 'excellent état',
]

def detect_renovation(titre: str | None, description: str | None) -> bool:
    text = ((titre or '') + ' ' + (description or '')).lower()
    if any(neg in text for neg in _RENO_NEGATORS):
        return False
    return any(k in text for k in _RENO_KEYWORDS)


_VOIR_PLUS_RE = re.compile(r'\s*Voir plus\s*$', re.IGNORECASE)

def strip_ui_artefacts(text: str | None) -> str:
    """Strip 'Voir plus' and similar UI artefacts from stored descriptions."""
    if not text:
        return ""
    return _VOIR_PLUS_RE.sub("", text).strip()


def baisses_bonus(nb_baisses: int | None) -> int:
    """Bonus score pour vendeur sous pression : +5 pts si ≥2 baisses, +10 pts si ≥3."""
    if not nb_baisses:
        return 0
    if nb_baisses >= 3:
        return 10
    if nb_baisses >= 2:
        return 5
    return 0


def drop_pct_bonus(prix_initial, prix) -> int:
    """Piste D: bonus basé sur le % de baisse total depuis prix_initial.
    Plus fiable que nb_baisses (SeLoger remet souvent le compteur à 0)."""
    if not prix_initial or not prix or prix_initial <= prix:
        return 0
    pct = (prix_initial - prix) / prix_initial * 100
    if pct >= 20: return 15
    if pct >= 10: return 10
    if pct >= 5:  return 5
    return 0


def anciennete_penalty(jours_marche) -> int:
    """Pénalité ancienneté : -5pts après 60j, -10pts après 120j sur le marché."""
    if not jours_marche:
        return 0
    if jours_marche > 120:
        return -10
    if jours_marche > 60:
        return -5
    return 0


def _maison_adjusted_score(raw_score: int | None, surface: float | None, needs_renovation: bool, jours_marche=None) -> int | None:
    """Pénalités qualitatives sur le score AVM maisons uniquement.
    - Petite surface : < 80m² = -10pts, 80-100m² = -5pts (atypique pour chalet alpin)
    - Rénovation détectée : -12pts
    - Ancienneté : -5pts >60j, -10pts >120j
    """
    if raw_score is None:
        return None
    score = raw_score
    if surface:
        if surface < 80:
            score -= 10
        elif surface < 100:
            score -= 5
    if needs_renovation:
        score -= 12
    score += anciennete_penalty(jours_marche)
    return max(0, min(100, score))

_SLUG_NEIGHBOURHOOD = {
    'les-bossons-les-moussoux':       'Les Bossons',
    'les-bossons':                    'Les Bossons',
    'les-moussoux':                   'Les Bossons',
    'les-pelerins-le-betty':          'Les Pélerins',
    'les-pelerins':                   'Les Pélerins',
    'le-betty':                       'Les Pélerins',
    'chamonix-sud-bois-du-bouchet':   'Les Gaillands',
    'bois-du-bouchet':                'Les Gaillands',
    'les-gaillands':                  'Les Gaillands',
    'argentiere':                     'Argentière',
    'la-tour-argentiere':             'Argentière',
    'les-chosalets':                  'Argentière',
    'le-tour':                        'Le Tour',
    'les-praz':                       'Les Praz',
    'la-flegere':                     'Les Praz',
    'les-tines':                      'Les Tines',
    'chamonix-centre':                'Chamonix Centre',
    'aiguille-du-midi':               'Chamonix Centre',
    # Multi-zone slug — intentionally unmapped: description must provide the zone.
    # Without a description keyword, falls through to commune → Chamonix Centre.
    # 'la-tour-argentiere-les-praz':  unmapped
}

_DESC_NEIGHBOURHOOD = [
    # Checked against description + title (normalized — handles accents and encoding artifacts)
    (['montroc'],                                                    'Montroc'),
    (['domaine de balme', 'le tour'],                                'Le Tour'),
    (['lavancher'],                                                   'Argentière'),  # Le Lavancher = Argentière zone
    (['argentiere', 'grands montets', 'grand-montets'],              'Argentière'),
    (['tines'],                                                      'Les Tines'),
    (['flegere', 'golf de chamonix', 'les praz'],                    'Les Praz'),
    (['gaillands', 'bois du bouchet'],                               'Les Gaillands'),
    (['pelerins', 'le betty'],                                       'Les Pélerins'),
    (['bossons', 'moussoux', 'chemin napoleon'],                     'Les Bossons'),
    (['chavants', 'les houches', 'houches'],                         'Les Houches'),
]

# SeLoger multi-zone adresse_raw labels — contain multiple neighbourhood names so
# _ADDR_SPECIFIC would false-positive; skip directly to description check for these.
_MULTI_ZONE_ADDR = [
    'la tour-argentiere-les praz',   # "La Tour-Argentière-Les Praz" — hyphens survive _norm
]

# Specific neighbourhood keywords from adresse_raw (NOT commune-level)
# These are only checked when adresse_raw is NOT a known multi-zone SeLoger label.
_ADDR_SPECIFIC = [
    (['les bossons', 'moussoux'],                   'Les Bossons'),
    (['les pelerins', 'le betty'],                  'Les Pélerins'),
    (['chamonix sud', 'bois du bouchet'],           'Les Gaillands'),
    (['les tines'],                                 'Les Tines'),
    (['lavancher'],                                 'Argentière'),  # Le Lavancher = Argentière zone
    (['argentiere'],                                'Argentière'),
    (['les praz'],                                  'Les Praz'),
    (['les houches'],                               'Les Houches'),
    (['servoz'],                                    'Servoz'),
    (['domancy'],                                   'Domancy'),
]

# Commune-level fallback — only consulted after all other checks fail
_ADDR_COMMUNE = [
    (['saint-gervais', 'saint gervais'],       'Saint-Gervais'),
    (['passy'],                                'Passy'),
    (['sallanches'],                           'Sallanches'),
    (['chamonix'],                             'Chamonix Centre'),
]


def _norm(s: str) -> str:
    """Normalize text for neighbourhood matching:
    - Replace '?' between letters (encoding artifact for accented chars) with 'e'
    - Strip combining accents (NFD decomposition)
    - Lowercase
    """
    s = re.sub(r'(?<=[a-zA-Z])\?(?=[a-zA-Z])', 'e', s)
    s = ''.join(c for c in unicodedata.normalize('NFKD', s) if unicodedata.category(c) != 'Mn')
    return s.lower()


def detect_neighbourhood(adresse_raw: str | None, url: str | None, description: str = '', listing_id: str = '', titre: str = '') -> str:
    if listing_id and listing_id in _neighbourhood_overrides:
        return _neighbourhood_overrides[listing_id]

    addr = _norm(adresse_raw or '')
    # Combine description + title (appart descriptions empty in DB, but titles carry location words)
    text = _norm((description or '') + ' ' + (titre or '')).strip()

    # 1. adresse_raw specific keywords — but skip for multi-zone SeLoger labels
    #    (e.g. "La Tour-Argentière-Les Praz" contains multiple zone names → unreliable)
    if not any(mz in addr for mz in _MULTI_ZONE_ADDR):
        for kws, name in _ADDR_SPECIFIC:
            if any(k in addr for k in kws):
                return name

    # 2. Description + title keywords — checked before URL slug (content > zone slug)
    if text:
        for kws, name in _DESC_NEIGHBOURHOOD:
            if any(k in text for k in kws):
                return name

    # 3. URL slug — SeLoger zone assignment (can be stale, hence checked after content)
    m = re.search(r'/achat/(?:appartement|maison)/[\w-]+-\d{2,5}/([^/]+)/\d+', url or '')
    if m:
        slug = m.group(1)
        if slug in _SLUG_NEIGHBOURHOOD:
            return _SLUG_NEIGHBOURHOOD[slug]

    # 4. Commune-level fallback from adresse_raw
    for kws, name in _ADDR_COMMUNE:
        if any(k in addr for k in kws):
            return name

    return 'Chamonix Centre'


_STRUCTURED_PRODUCT_KEYWORDS = [
    # Operators
    'odalys', 'pierre & vacances', 'pierre vacances', 'mgm résidences', 'mgm resorts',
    'belambra', 'lagrange vacances', 'goélia', 'goelia', 'maeva', 'club med',
    'mmv ', 'vacancéole', 'vacanceole', 'terrelia', 'bc vacances',
    'cgh résidences', 'cgh residences', 'village club', 'family village',
    # Structural keywords
    'bail commercial', 'bail en cours', 'bail de location', 'exploitant',
    'loyer garanti', 'loyers garantis', 'revenu garanti', 'revenus garantis',
    'résidence de tourisme', 'residence de tourisme',
    'leaseback', 'occupation personnelle',
    'gestion hôtelière', 'gestion hoteliere',
    'résidence gérée', 'residence geree',
    'gestionnaire de résidence',
    'sécurité des loyers', 'securite des loyers',
    # Leaseback patterns supplémentaires (détectés sur annonces réelles)
    'garanti par un bail', 'garantis par un bail',
    'bail garanti', 'fin de bail',
    'loyer annuel garanti', 'loyer ht/an', 'loyers ht/an',
    'loyer annuel ht', 'loyer annuel net',
    'eur ht/an', '€ ht/an', 'eur/an garanti', '€/an garanti',
    'résidence avec services', 'residence avec services',
    'résidence tourisme', 'residence tourisme',
    'accueil et service toute l', 'acceuil et service',
    # LMNP / occupation propriétaire (keywords précis pour éviter les faux positifs)
    'lmnp', 'loueur meublé non professionnel',
    "semaines d'occupation", "semaine d'occupation",
    "droit d'occupation", "votre occupation personnelle",
    'vous percevrez', 'vous en percevrez',
    'mise en location est prise en charge',
    'prise en charge par un professionnel',
    # Résidences gérées / lots numérotés
    'kaméléon', 'kameléon', 'caméléon',
    'géré par', 'gere par',
    'lot n°', 'lot no ', 'numéro de lot',
    'contrat de bail commercial',
    'résidence montagne gérée',
    'propriétaire de semaines', 'proprietaire de semaines',
    'loyer indexé', 'loyer indexe',
    'revenu locatif garanti',
]

_structured_ids_blacklist: set[str] = set()
if STRUCTURED_IDS_FILE.exists():
    _structured_ids_blacklist = set(json.loads(STRUCTURED_IDS_FILE.read_text(encoding='utf-8')))

_neighbourhood_overrides: dict[str, str] = {}
if NEIGHBOURHOOD_OVERRIDES_FILE.exists():
    _neighbourhood_overrides = json.loads(NEIGHBOURHOOD_OVERRIDES_FILE.read_text(encoding='utf-8'))

# surface_carrez overrides: {listing_id: carrez_m2}
_surface_carrez_overrides: dict[str, float] = {}
if SURFACE_CARREZ_FILE.exists():
    _surface_carrez_overrides = {k: float(v) for k, v in json.loads(SURFACE_CARREZ_FILE.read_text(encoding='utf-8')).items()}

# Coefficient for non-Carrez space (3m² non-Carrez = 2m² effective)
_NON_CARREZ_COEFF = 0.4

def effective_surface(total: float, carrez: float) -> float:
    """Convert (total, carrez) to a single effective surface for AVM/yield."""
    non_carrez = max(0.0, total - carrez)
    return carrez + non_carrez * _NON_CARREZ_COEFF

def _avm_ratio_to_score(ratio) -> int | None:
    if ratio is None:
        return None
    if ratio <= 0.75:
        # Piste B: continu — ratio=0.75→95, ratio=0→100. Différencie les vrais outliers.
        return min(100, round(95 + (0.75 - ratio) / 0.75 * 5))
    if ratio <= 0.85: return 80
    if ratio <= 0.95: return 65
    if ratio <= 1.05: return 50
    if ratio <= 1.20: return 30
    if ratio <= 1.40: return 15
    return 5

def is_structured_product(listing_id: str, titre: str | None, description: str | None, description_full: str | None = None) -> bool:
    if listing_id in _structured_ids_blacklist:
        return True
    text = ((titre or '') + ' ' + (description or '') + ' ' + (description_full or '')).lower()
    return any(k in text for k in _STRUCTURED_PRODUCT_KEYWORDS)


_SL_QUARTIER_SECTION = {
    "chamonix-centre": "G", "chamonix-sud-bois-du-bouchet": "G",
    "aiguille-du-midi": "G", "les-gaillands": "G",
    "les-bois": "D", "les-mouilles": "D",
    "les-bossons-les-moussoux": "E", "les-pelerins-le-betty": "E",
    "les-bossons": "E", "les-moussoux": "E", "les-pelerins": "E",
    "le-betty": "E", "ouest": "E", "ouest-et-nord": "E",
    "les-praz": "B", "la-flegere": "B", "les-tines": "B",
    "la-tour-argentiere-les-praz": "B",
    "argentiere": "A", "la-tour-argentiere": "A", "le-tour": "A",
    "les-chosalets": "A", "est": "A",
}

def _section_from_url(url: str) -> str:
    m = re.search(r'/annonces/[^/]+/[^/]+/[^/]+-\d{2,5}/([^/]+)/\d+\.htm', url or "")
    if m:
        q = m.group(1)
        if q in _SL_QUARTIER_SECTION:
            return _SL_QUARTIER_SECTION[q]
    return "G"

def _quartier_label_from_url(url: str) -> str:
    """Human-readable quartier from SeLoger URL slug."""
    m = re.search(r'/achat/(?:appartement|maison)/[\w-]+-\d{2,5}/([^/]+)/\d+\.htm', url or "")
    if not m:
        return ""
    slug = m.group(1)
    if re.match(r'^\d+$', slug):
        return ""
    return slug.replace('-', ' ').title()

def make_appart_title(titre: str, pieces: int, adresse_raw: str, url: str, neighbourhood: str = '') -> str:
    if titre:
        return titre
    # Prefer specific neighbourhood name; fall back to slug label then adresse_raw
    slug_label = _quartier_label_from_url(url)
    # If slug is the broad "La Tour Argentiere Les Praz", use neighbourhood instead
    _AMBIGUOUS_SLUGS = {'La Tour Argentiere Les Praz', 'La Tour-Argentiere-Les Praz'}
    quartier = neighbourhood if (neighbourhood and (not slug_label or slug_label in _AMBIGUOUS_SLUGS)) else (slug_label or neighbourhood or adresse_raw or "")
    if pieces and pieces > 0:
        label = "Studio" if pieces == 1 else f"T{pieces}"
        return f"{label} · {quartier}" if quartier else label
    return quartier

def compute_yield(prix, surface, cfg_key):
    if not prix or not surface or surface <= 0:
        return None
    rent_pm2 = RENT_PM2.get(cfg_key, 0)
    if not rent_pm2:
        return None
    return round((surface * rent_pm2 * 12) / prix * 100, 2)


def _yield_to_score(rendement: float | None) -> int | None:
    """Piste A: composante yield 0-100, calibrée marché Chamonix (médiane ~2.4% → 50)."""
    if rendement is None:
        return None
    if rendement >= 4.5: return 100
    if rendement >= 3.5: return 85
    if rendement >= 3.0: return 75
    if rendement >= 2.5: return 65
    if rendement >= 2.0: return 50
    if rendement >= 1.5: return 25
    return 5


# Piste C: seuils prix/m² minimum par commune (en dessous = surface probablement erronée)
_PM2_SUSPECT_MIN = {
    "Chamonix":      4000,
    "Les Houches":   3500,
    "Saint-Gervais": 2500,
    "Sallanches":    1800,
    "Passy":         2500,
    "Servoz":        1500,
    "Domancy":       1500,
}

def _pm2_suspect_flag(prix, surface, cfg_key: str) -> bool:
    """Détecte un prix/m² anormalement bas indiquant une surface probablement mal renseignée."""
    if not prix or not surface or surface <= 0:
        return False
    return (prix / surface) < _PM2_SUSPECT_MIN.get(cfg_key, 1500)


# Loyers maisons longue durée Chamonix vallée (€/m²/mois) — source marché 2025
# SeLoger / ChacunSonLieu : maisons ~11-17€/m² selon quartier
_MAISON_RENT_PM2: dict[str, float] = {
    'Chamonix Centre': 17.0,
    'Les Praz':        15.5,
    'Les Bossons':     15.0,
    'Les Pélerins':    14.5,
    'Les Gaillands':   14.0,
    'Les Tines':       14.0,
    'Le Lavancher':    13.5,
    'Argentière':      13.0,
    'Le Tour':         12.0,
    'Montroc':         12.0,
    'Saint-Gervais':   12.0,
    'Les Houches':     13.0,
    'Servoz':          11.0,
    'Sallanches':      10.0,
    'Passy':           10.0,
    'Domancy':         10.0,
}
_MAISON_RENT_DEFAULT = 13.0  # quartier inconnu


def _surface_rent_factor(surface: float) -> float:
    """Décote pour grandes surfaces : un chalet 200m² ne loue pas au même €/m² qu'un 80m²."""
    if surface <= 80:   return 1.00
    if surface <= 120:  return 0.92
    if surface <= 180:  return 0.82
    if surface <= 250:  return 0.72
    return 0.62


def compute_maison_yield(prix: float, surface: float, neighbourhood: str) -> float | None:
    if not prix or not surface or surface <= 0:
        return None
    rent_pm2 = _MAISON_RENT_PM2.get(neighbourhood, _MAISON_RENT_DEFAULT)
    factor   = _surface_rent_factor(surface)
    monthly  = surface * rent_pm2 * factor
    return round((monthly * 12) / prix * 100, 2)


def _richness(item: dict, price_key: str = "price", surface_key: str = "surface") -> int:
    """Score de richesse d'un item pour le dedup (description + photos)."""
    desc = item.get("description", "") or ""
    photos = item.get("photos", []) or []
    return len(desc) + len(photos) * 50


def deduplicate(items: list[dict], price_key: str = "price", surface_key: str = "surface",
                price_tol: int = 2000, surface_tol: float = 2.0) -> tuple[list[dict], int]:
    """Déduplique les annonces : même prix (±tol€) ET même surface (±tol m²).
    Garde l'annonce la plus riche (description longue + photos)."""
    kept: list[dict] = []
    for item in items:
        p = item.get(price_key, 0) or 0
        s = item.get(surface_key, 0) or 0
        match_idx = None
        for i, k in enumerate(kept):
            kp = k.get(price_key, 0) or 0
            ks = k.get(surface_key, 0) or 0
            if abs(kp - p) <= price_tol and abs(ks - s) <= surface_tol:
                match_idx = i
                break
        if match_idx is None:
            kept.append(item)
        else:
            if _richness(item, price_key, surface_key) > _richness(kept[match_idx], price_key, surface_key):
                kept[match_idx] = item
    removed = len(items) - len(kept)
    return kept, removed


con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row

# Ensure avm_model column exists (added by scrapers, but export runs first in some setups)
existing_cols = {r[1] for r in con.execute("PRAGMA table_info(listings)").fetchall()}
if "avm_model" not in existing_cols:
    con.execute("ALTER TABLE listings ADD COLUMN avm_model TEXT")
    con.commit()
    print("  ↳ colonne avm_model ajoutée (migration)")

# Pre-load price history keyed by listing_id
ph_by_id = {}
for row in con.execute("SELECT listing_id, date_obs, prix FROM prix_history ORDER BY date_obs"):
    ph_by_id.setdefault(row["listing_id"], []).append({
        "date": row["date_obs"],
        "prix": row["prix"],
    })

today = datetime.today().isoformat()[:10]

# ── Appartements ──────────────────────────────────────────────────────────────
listings = []
for row in con.execute(
    "SELECT * FROM listings WHERE type_bien='appartement' AND active=1 AND commune != 'LES HOUCHES' ORDER BY first_seen DESC"
):
    commune_db = (row["commune"] or "").upper().strip()
    display_name, cfg_key = COMMUNE_MAP.get(commune_db, (commune_db.title(), commune_db.title()))

    prix = row["prix"]
    prix_initial = row["prix_initial"] or prix
    price_drop = (prix_initial - prix) if (prix_initial and prix and prix < prix_initial) else None

    neighbourhood = detect_neighbourhood(row["adresse_raw"], row["url"], row["description"] or '', row["id"], row["titre"] or '')
    if neighbourhood == 'Les Houches':
        continue

    # Carrez surface correction
    surface_total  = row["surface"] or 0
    carrez         = _surface_carrez_overrides.get(row["id"])
    surf_eff       = effective_surface(surface_total, carrez) if carrez and surface_total else surface_total

    # Recompute AVM with effective surface when carrez override is known
    avm_pred_raw   = row["avm_pred"]
    avm_ratio_raw  = row["avm_ratio"]
    if carrez and surface_total and avm_pred_raw:
        avm_pred_eff  = avm_pred_raw * (surf_eff / surface_total)
        avm_ratio_eff = round(prix / avm_pred_eff, 3) if prix and avm_pred_eff else avm_ratio_raw
    else:
        avm_pred_eff, avm_ratio_eff = avm_pred_raw, avm_ratio_raw
    # Piste B: toujours recomputer depuis le ratio pour appliquer la formule continue
    avm_score_eff = _avm_ratio_to_score(avm_ratio_eff)

    pm2_suspect    = _pm2_suspect_flag(prix, surf_eff, cfg_key)
    # Fix 1: yield non calculable si surface suspecte (évite un yield trompeur style 11%)
    rendement      = None if pm2_suspect else compute_yield(prix, surf_eff, cfg_key)
    yield_score    = _yield_to_score(rendement)
    penalty        = anciennete_penalty(row["jours_marche"])
    prix_drop_bon  = drop_pct_bonus(prix_initial, prix)
    is_struct      = is_structured_product(row["id"], row["titre"], row["description"], row["description_full"])
    malus_struct   = -20 if is_struct else 0

    if avm_score_eff is not None:
        # Piste A: composite 70% AVM + 30% yield (quand yield dispo, sinon 100% AVM)
        base_score  = round(avm_score_eff * 0.70 + yield_score * 0.30) if yield_score is not None else avm_score_eff
        raw_final   = base_score + penalty + prix_drop_bon + malus_struct
        # Piste C: cap à 50 si prix/m² suspect (surface probablement erronée → AVM biaisé)
        if pm2_suspect:
            raw_final = min(raw_final, 50)
        final_score = max(5, min(100, raw_final))
    else:
        base_score = final_score = None
    desc_clean = strip_ui_artefacts(row["description_full"] or row["description"] or "")

    listings.append({
        "id":                   row["id"],
        "url":                  row["url"] or "",
        "title":                make_appart_title(row["titre"] or "", row["pieces"] or 0, row["adresse_raw"] or "", row["url"] or "", neighbourhood),
        "price":                prix or 0,
        "surface":              surf_eff,
        "surface_carrez":       carrez,
        "rooms":                row["pieces"] or 0,
        "location":             display_name,
        "neighbourhood":        neighbourhood,
        "charges":              None,
        "dpe":                  row["dpe"] or "N/C",
        "ges":                  None,
        "score":                final_score,
        "score_detail":         {"avm": avm_score_eff, "yield_score": yield_score, "base": base_score, "anciennete": penalty, "drop_pct": prix_drop_bon, "structured": malus_struct, "pm2_suspect": pm2_suspect},
        "reasons":              [],
        "yield":                rendement,
        "vs_market":            None,
        "enriched":             0,
        "first_seen":           row["first_seen"] or today,
        "urls":                 [row["url"]] if row["url"] else [],
        "_location_original":   commune_db,
        "_loc_corrected":       False,
        "days_on_market":       row["jours_marche"] or 0,
        "price_history":        ph_by_id.get(row["id"], []),
        "price_drop":           price_drop,
        "is_relisted":          False,
        "relisted_after_days":  None,
        "avm_pred":             avm_pred_eff,
        "avm_ratio":            avm_ratio_eff,
        "avm_model":            map_avm_model(row["avm_model"]),
        "avm_suspect":          bool((avm_ratio_eff is not None and avm_ratio_eff < 0.3) or pm2_suspect),
        "nb_baisses":           row["nb_baisses"] or 0,
        "photos":               filter_photos(json.loads(row["photos_json"]) if row["photos_json"] else []),
        "is_structured":        is_struct,
        "description":          desc_clean,
    })

listings, dedup_removed = deduplicate(listings, price_key="price", surface_key="surface")
out_listings = PRIVATE / "listings.json"
out_listings.write_text(json.dumps(listings, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"✓ listings.json — {len(listings)} appartements ({dedup_removed} doublons supprimés)")

# ── Maisons ───────────────────────────────────────────────────────────────────
maisons = []
for row in con.execute(
    "SELECT * FROM listings WHERE type_bien='maison' AND active=1 AND commune != 'LES HOUCHES' ORDER BY first_seen DESC"
):
    ph = ph_by_id.get(row["id"], [])
    m_neighbourhood = detect_neighbourhood(row["adresse_raw"], row["url"], row["description"] or '', row["id"], row["titre"] or '')
    if m_neighbourhood == 'Les Houches':
        continue
    m_reno           = detect_renovation(row["titre"], row["description"])
    m_struct         = is_structured_product(row["id"], row["titre"], row["description"], row["description_full"] if "description_full" in row.keys() else None)
    # Fix 2: score continu pour maisons — recomputer depuis ratio (Piste B)
    m_avm_score_cont = _avm_ratio_to_score(row["avm_ratio"])
    m_raw_score      = _maison_adjusted_score(m_avm_score_cont, row["surface"], m_reno, row["jours_marche"])
    m_prix_initial   = row["prix_initial"] if "prix_initial" in row.keys() and row["prix_initial"] else row["prix"]
    m_bonus          = drop_pct_bonus(m_prix_initial, row["prix"])
    m_malus          = -20 if m_struct else 0
    m_pm2_suspect    = bool(row["prix"] and row["surface"] and row["surface"] > 0 and (row["prix"] / row["surface"]) < 1500)
    raw_m_final      = None if m_raw_score is None else m_raw_score + m_bonus + m_malus
    if raw_m_final is not None and m_pm2_suspect:
        raw_m_final  = min(raw_m_final, 50)
    m_score          = None if raw_m_final is None else max(5, min(100, raw_m_final))
    m_desc           = strip_ui_artefacts(row["description_full"] or row["description"] or "")

    maisons.append({
        "id":             abs(hash(row["id"])) % 1_000_000,
        "url":            row["url"],
        "titre":          (row["titre"] or "").split("\n")[0].strip() or None,
        "adresse_raw":    row["adresse_raw"] or row["commune"] or "",
        "section":        _section_from_url(row["url"] or ""),
        "neighbourhood":  m_neighbourhood,
        "surface":        row["surface"] or 0,
        "surf_terrain":   row["surf_terrain"] or None,
        "pieces":         row["pieces"] or 0,
        "prix":           row["prix"] or 0,
        "prix_initial":   row["prix_initial"] or row["prix"] or 0,
        "nb_baisses":     row["nb_baisses"] or 0,
        "historique_prix": ph,
        "avm_pred":       row["avm_pred"],
        "avm_ratio":      row["avm_ratio"],
        "avm_score":      m_score,
        "first_seen":     row["first_seen"] or today,
        "notes":          row["notes"],
        "lat":            None,
        "lon":            None,
        "photos":         filter_photos(json.loads(row["photos_json"]) if row["photos_json"] else []),
        "description":    m_desc,
        "needs_renovation": m_reno,
        "is_structured":  m_struct,
        "avm_suspect":    bool((row["avm_ratio"] is not None and row["avm_ratio"] < 0.3) or m_pm2_suspect),
        "yield":          compute_maison_yield(row["prix"] or 0, row["surface"] or 0, m_neighbourhood),
        "avm_model":      map_avm_model(row["avm_model"]) if "avm_model" in row.keys() else None,
    })

maisons, dedup_removed_m = deduplicate(maisons, price_key="prix", surface_key="surface", price_tol=3000, surface_tol=4.0)
out_maisons = PRIVATE / "maisons.json"
out_maisons.write_text(json.dumps(maisons, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"✓ maisons.json — {len(maisons)} maisons ({dedup_removed_m} doublons supprimés)")

con.close()

# ── AVM Lookup (pre-generated, ne change que si les modèles changent) ─────────
# Built by _build_avm_lookup.py; copy from dvf/ if fresher, otherwise keep existing
avm_src = BASE / "dvf" / "avm_lookup.json"
if avm_src.exists():
    avm_data = json.loads(avm_src.read_bytes())
    (REACT / "avm_lookup.json").write_bytes(avm_src.read_bytes())
    print(f"✓ avm_lookup.json — {len(avm_data)} communes (depuis dvf/)")
else:
    # Keep the existing React file — it was already there from previous run
    existing = REACT / "avm_lookup.json"
    if existing.exists():
        n = len(json.loads(existing.read_bytes()))
        print(f"ℹ  avm_lookup.json — conservé tel quel ({n} communes)")
    else:
        print("⚠  avm_lookup.json absent — estimateur non fonctionnel")

# ── DVF Stats (tendances marché) ──────────────────────────────────────────────
dvf_src = BASE / "dvf" / "dvf_stats.json"
if dvf_src.exists():
    dvf_data = json.loads(dvf_src.read_text(encoding="utf-8"))
    (REACT / "dvf_stats.json").write_text(
        json.dumps(dvf_data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"✓ dvf_stats.json — {len(dvf_data.get('communes', {}))} communes")
else:
    print("⚠  dvf/dvf_stats.json absent — dvf_stats.json inchangé")

# ── DVF Points (transactions individuelles géocodées — Chamonix uniquement) ──
import csv as _csv
dvf_clean_src = BASE / "dvf" / "dvf_clean.csv"
if dvf_clean_src.exists():
    dvf_points = []
    with open(dvf_clean_src, newline="", encoding="utf-8") as _f:
        for _r in _csv.DictReader(_f):
            if _r["commune"] != "CHAMONIX MONT BLANC": continue
            if not _r["lat"] or not _r["lon"]: continue
            try:
                _lat    = round(float(_r["lat"]), 5)
                _lon    = round(float(_r["lon"]), 5)
                _prix   = int(float(_r["valeur"]))
                _surf    = round(float(_r["surface"]), 1) if _r["surface"] else None
                _pm2     = round(float(_r["prix_m2"])) if _r["prix_m2"] else None
                _terr    = round(float(_r["surf_terrain"])) if _r.get("surf_terrain") and float(_r["surf_terrain"]) > 0 else None
                _nb_lots = int(float(_r.get("nb_lots", 0) or 0))
            except (ValueError, TypeError):
                continue
            if not _surf or _surf <= 0: continue
            if _pm2 and (_pm2 < 5000 or _pm2 > 40000): continue  # outliers (heritage/SCI < 5k€/m²)
            if _nb_lots >= 4: continue  # lots multiples = SCI/indivision
            _addr_parts = [p for p in [_r["no_voie"], _r["type_voie"], _r["voie"]] if p.strip()]
            _addr = " ".join(_addr_parts).strip() or None
            _pt: dict = {
                "lat":  _lat,
                "lon":  _lon,
                "a":    _addr,
                "p":    _prix,
                "s":    _surf,
                "m2":   _pm2,
                "t":    _r["type_local"],   # "appart" | "maison"
                "y":    _r["annee"],
                "sec":  _r["section"],
            }
            if _terr and _r["type_local"] == "maison":
                _pt["ter"] = _terr
            dvf_points.append(_pt)
    (REACT / "dvf_points.json").write_text(
        json.dumps(dvf_points, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"✓ dvf_points.json — {len(dvf_points)} points Chamonix géocodés")
else:
    print("⚠  dvf/dvf_clean.csv absent — dvf_points.json inchangé")

print("\nDone. `npm run build` dans dashboard-react/ pour publier.")
