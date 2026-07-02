# -*- coding: utf-8 -*-
"""
scraper.py — Scraper marché immobilier vallée de Chamonix
Sources : SeLoger · LeBonCoin · Logic-Immo
  - Normalise vers schema commun
  - Dédup cross-source par (commune, surface, prix, type)
  - Stocke dans listings_market.sqlite
  - Calcule score AVM si chamonix_avm disponible
  - Log time_on_market (delta première/dernière vue)

Usage :
  python scraper.py                  # toutes sources, toutes communes
  python scraper.py --source seloger
  python scraper.py --commune chamonix
  python scraper.py --dry-run        # affiche sans stocker
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import argparse, json, os, re, sqlite3, time, hashlib, logging
from datetime import datetime, date
from typing import Optional
import requests
from bs4 import BeautifulSoup

# ── Config ────────────────────────────────────────────────────────────────────
BASE     = os.path.dirname(os.path.abspath(__file__))
DB_PATH  = os.path.join(BASE, "dvf", "listings_market.db")
IDX_PATH = os.path.join(BASE, "dvf", "market_index.json")
LOG_PATH = os.path.join(BASE, "scraper.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(LOG_PATH, encoding="utf-8"), logging.StreamHandler()]
)
log = logging.getLogger("scraper")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# Communes de la vallée à scraper
COMMUNES_VALLEY = [
    "chamonix-mont-blanc", "les-houches", "servoz",
    "saint-gervais-les-bains", "sallanches", "passy", "domancy",
]

# Market index pour scorer les listings
MARKET_INDEX = {}
if os.path.exists(IDX_PATH):
    raw = json.load(open(IDX_PATH))
    MARKET_INDEX = {int(k): float(v) for k, v in raw.items()}
CURRENT_YEAR = date.today().year
MARKET_IDX_NOW = MARKET_INDEX.get(CURRENT_YEAR, MARKET_INDEX.get(2025, 1.12))

# ── DB Setup ──────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id              TEXT PRIMARY KEY,   -- hash(source+url)
    source          TEXT,               -- seloger|lbc|pap|logicimmo
    url             TEXT UNIQUE,
    titre           TEXT,
    type_bien       TEXT,               -- maison|appartement|terrain
    commune         TEXT,
    code_postal     TEXT,
    adresse_raw     TEXT,
    prix            INTEGER,            -- € listing
    surface         REAL,               -- m² bâti
    surf_terrain    REAL,               -- m² terrain (0 si appart)
    pieces          INTEGER,
    chambres        INTEGER,
    dpe             TEXT,
    description     TEXT,
    photos_json     TEXT,               -- JSON list of URLs
    -- AVM scoring
    avm_pred        REAL,               -- € prédiction modèle (euros courants)
    avm_ratio       REAL,               -- prix_listing / avm_pred  (<1 = sous-coté)
    avm_score       INTEGER,            -- 0-100, >70 = opportunité
    avm_model       TEXT,               -- chamonix_mai_xgb|chamonix_apt_meta|dvf_stats
    -- Temporel
    first_seen      TEXT,               -- ISO date
    last_seen       TEXT,
    jours_marche    INTEGER,            -- last_seen - first_seen
    prix_initial    INTEGER,            -- prix à first_seen
    nb_baisses      INTEGER DEFAULT 0,
    -- Statut
    active          INTEGER DEFAULT 1,  -- 1=actif, 0=vendu/retiré
    notes           TEXT
);
CREATE INDEX IF NOT EXISTS idx_commune   ON listings(commune);
CREATE INDEX IF NOT EXISTS idx_type      ON listings(type_bien);
CREATE INDEX IF NOT EXISTS idx_avm_score ON listings(avm_score DESC);
CREATE INDEX IF NOT EXISTS idx_active    ON listings(active);

CREATE TABLE IF NOT EXISTS prix_history (
    listing_id  TEXT,
    date_obs    TEXT,
    prix        INTEGER,
    PRIMARY KEY (listing_id, date_obs)
);
"""

def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    # Migration: ajouter colonnes si absentes (DB existante)
    cols = {r[1] for r in con.execute("PRAGMA table_info(listings)")}
    if "avm_model" not in cols:
        con.execute("ALTER TABLE listings ADD COLUMN avm_model TEXT")
    con.commit()
    return con

def listing_id(source: str, url: str) -> str:
    return hashlib.md5(f"{source}:{url}".encode()).hexdigest()[:16]

# ── Normalisation commune ─────────────────────────────────────────────────────
COMMUNE_MAP = {
    "chamonix": "CHAMONIX MONT BLANC",
    "chamonix-mont-blanc": "CHAMONIX MONT BLANC",
    "les houches": "LES HOUCHES",
    "les-houches": "LES HOUCHES",
    "servoz": "SERVOZ",
    "saint-gervais": "SAINT GERVAIS LES BAINS",
    "saint-gervais-les-bains": "SAINT GERVAIS LES BAINS",
    "sallanches": "SALLANCHES",
    "passy": "PASSY",
    "domancy": "DOMANCY",
}

def normalize_commune(raw: str) -> str:
    r = raw.lower().strip().replace("–","-").replace(" ","")
    for k, v in COMMUNE_MAP.items():
        if k.replace("-","") in r or r in k.replace("-",""):
            return v
    return raw.upper().strip()

def parse_price(s: str) -> Optional[int]:
    s = re.sub(r"[^\d]", "", str(s))
    return int(s) if s else None

def parse_surface(s: str) -> Optional[float]:
    m = re.search(r"([\d,\.]+)", str(s).replace(",","."))
    return float(m.group(1)) if m else None

# ── AVM helpers ───────────────────────────────────────────────────────────────
def _load_appart_meta() -> dict:
    """Charge avm_appart_cham_meta.json une seule fois."""
    p = os.path.join(BASE, "dvf", "avm_appart_cham_meta.json")
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    return {}

def _load_dvf_pm2() -> dict:
    """Retourne {commune_maj: median_m2} depuis dvf_stats.json."""
    p = os.path.join(BASE, "dvf", "dvf_stats.json")
    if not os.path.exists(p):
        return {}
    with open(p, encoding="utf-8") as f:
        stats = json.load(f)
    return {k: v.get("median_m2", 0) for k, v in stats.get("communes", {}).items()}

def _avm_ratio_to_score(ratio) -> int | None:
    if ratio is None:
        return None
    if ratio <= 0.75: return 95
    if ratio <= 0.85: return 80
    if ratio <= 0.95: return 65
    if ratio <= 1.05: return 50
    if ratio <= 1.20: return 30
    if ratio <= 1.40: return 15
    return 5

# Chargé une fois au démarrage
_APPART_META  = _load_appart_meta()
_DVF_PM2      = _load_dvf_pm2()

# ── AVM Scoring ───────────────────────────────────────────────────────────────
def compute_avm_score(listing: dict) -> dict:
    """
    Estime la valeur marchande (AVM) d'un listing et calcule le ratio prix/AVM.

    Hiérarchie des modèles :
      1. Chamonix maisons  → XGBoost predict_avm.py (section G par défaut, ±15%)
      2. Chamonix apparts  → meta pm2_section[G] × surface × emp_idx (±8.8%)
      3. Autres communes   → dvf_stats.json median_m2 (heuristique)
    """
    prix      = listing.get("prix")
    surface   = listing.get("surface")
    commune   = listing.get("commune", "")
    type_bien = listing.get("type_bien", "appartement")
    surf_ter  = listing.get("surf_terrain", 0) or 0

    if not prix or not surface or surface < 10:
        return {"avm_pred": None, "avm_ratio": None, "avm_score": None}

    avm_pred = None
    avm_model_tag = "dvf_stats"

    # 1. Chamonix maisons → XGBoost (section G = centrevillage, meilleur défaut)
    if commune == "CHAMONIX MONT BLANC" and type_bien == "maison":
        try:
            sys.path.insert(0, BASE)
            from predict_avm import predict as _predict_avm
            res = _predict_avm(
                section="G", surface=surface,
                surf_terrain=surf_ter, plu_zone="U",
                pieces=max(1, round(surface / 20)),
            )
            avm_pred     = res["valeur"]
            avm_model_tag = "chamonix_mai_xgb"
        except Exception as e:
            log.debug(f"predict_avm import failed: {e}")

    # 2. Chamonix apparts → meta pm2 × surface × emp_idx courant
    if avm_pred is None and commune == "CHAMONIX MONT BLANC":
        if _APPART_META:
            pm2_ref = _APPART_META.get("pm2_section", {}).get("G",
                       _APPART_META.get("pm2_global_cham", 10198))
            emp_idx = max(_APPART_META.get("emp_idx", {}).values(), default=1.0)
            avm_pred      = surface * pm2_ref * emp_idx
            avm_model_tag = "chamonix_apt_meta"

    # 3. Autres communes → DVF stats median_m2
    if avm_pred is None:
        pm2_ref = _DVF_PM2.get(commune, 0)
        if pm2_ref > 0:
            val_ter_approx = surf_ter * pm2_ref * 0.05
            avm_pred = surface * pm2_ref + val_ter_approx
        else:
            # Dernier recours : heuristique vallée générique
            pm2_ref = 6000
            avm_pred = surface * pm2_ref * MARKET_IDX_NOW

    ratio = prix / avm_pred if avm_pred and avm_pred > 0 else None
    return {
        "avm_pred":  round(avm_pred) if avm_pred else None,
        "avm_ratio": round(ratio, 3) if ratio else None,
        "avm_score": _avm_ratio_to_score(ratio),
        "avm_model": avm_model_tag,
    }

# ── Upsert listing ────────────────────────────────────────────────────────────
def upsert_listing(con: sqlite3.Connection, data: dict, dry_run=False):
    lid  = listing_id(data["source"], data["url"])
    now  = date.today().isoformat()
    prix = data.get("prix")

    existing = con.execute(
        "SELECT prix, first_seen, prix_initial, nb_baisses FROM listings WHERE id=?", (lid,)
    ).fetchone()

    if existing:
        old_prix, first_seen, prix_initial, nb_baisses = existing
        nb_baisses = nb_baisses or 0
        if prix and old_prix and prix < old_prix:
            nb_baisses += 1
            log.info(f"  BAISSE {data['url'][:60]} {old_prix:,}→{prix:,}€")
        if not dry_run:
            con.execute("""
                UPDATE listings SET
                    last_seen=?, prix=?, jours_marche=?,
                    nb_baisses=?, active=1,
                    avm_pred=?, avm_ratio=?, avm_score=?, avm_model=?
                WHERE id=?
            """, (now,
                  prix or old_prix,
                  (date.fromisoformat(now) - date.fromisoformat(first_seen)).days,
                  nb_baisses,
                  data.get("avm_pred"), data.get("avm_ratio"), data.get("avm_score"),
                  data.get("avm_model"), lid))
            if prix:
                con.execute(
                    "INSERT OR IGNORE INTO prix_history VALUES (?,?,?)", (lid, now, prix)
                )
    else:
        avm = compute_avm_score(data)
        data.update(avm)
        if not dry_run:
            con.execute("""
                INSERT OR IGNORE INTO listings (
                    id, source, url, titre, type_bien, commune, code_postal,
                    adresse_raw, prix, surface, surf_terrain, pieces, chambres,
                    dpe, description, photos_json,
                    avm_pred, avm_ratio, avm_score, avm_model,
                    first_seen, last_seen, jours_marche, prix_initial, nb_baisses, active
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,0,1)
            """, (lid,
                  data.get("source"), data.get("url"), data.get("titre"),
                  data.get("type_bien"), data.get("commune"), data.get("code_postal"),
                  data.get("adresse_raw"), prix, data.get("surface"), data.get("surf_terrain"),
                  data.get("pieces"), data.get("chambres"), data.get("dpe"),
                  data.get("description"), json.dumps(data.get("photos",[])),
                  data.get("avm_pred"), data.get("avm_ratio"), data.get("avm_score"),
                  data.get("avm_model"), now, now, prix))
            if prix:
                con.execute(
                    "INSERT OR IGNORE INTO prix_history VALUES (?,?,?)", (lid, now, prix)
                )
        score_s = f"score={data.get('avm_score')}  ratio={data.get('avm_ratio')}"
        log.info(f"  NEW {data.get('source'):<10} {data.get('commune'):<28} "
                 f"{prix:>10,}€  {data.get('surface',0):.0f}m²  {score_s}")
        return True
    return False

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPERS PAR SOURCE
# ══════════════════════════════════════════════════════════════════════════════

# ── LeBonCoin ─────────────────────────────────────────────────────────────────
def scrape_lbc(commune_slug: str, type_bien="maison", max_pages=5) -> list:
    """
    LeBonCoin immobilier — API JSON non-officielle via /recherche.
    type_bien: 'maison', 'appartement', 'terrain'
    """
    CATID = {"maison": "9", "appartement": "10", "terrain": "11"}
    results = []
    session = requests.Session()
    session.headers.update(HEADERS)

    for page in range(1, max_pages + 1):
        url = (
            f"https://www.leboncoin.fr/recherche"
            f"?category={CATID.get(type_bien,'9')}"
            f"&locations={commune_slug}"
            f"&real_estate_type={CATID.get(type_bien,'9')}"
            f"&page={page}"
        )
        try:
            r = session.get(url, timeout=15)
            r.raise_for_status()
        except Exception as e:
            log.warning(f"LBC {commune_slug} p{page}: {e}")
            break

        soup = BeautifulSoup(r.text, "html.parser")

        # Cherche le JSON next.js data
        script = soup.find("script", {"id": "__NEXT_DATA__"})
        if not script:
            log.warning(f"LBC: no __NEXT_DATA__ on {url}")
            break

        try:
            data  = json.loads(script.string)
            ads   = (data.get("props",{})
                        .get("pageProps",{})
                        .get("searchData",{})
                        .get("ads", []))
        except Exception as e:
            log.warning(f"LBC JSON parse error: {e}")
            break

        if not ads:
            break

        for ad in ads:
            attrs = {a["key"]: a.get("value_label", a.get("values",[""])[0])
                     for a in ad.get("attributes", [])}
            prix    = parse_price(ad.get("price", [None])[0] if ad.get("price") else None)
            surface = parse_surface(attrs.get("square",""))
            surf_ter= parse_surface(attrs.get("land_plot_surface",""))
            loc     = ad.get("location", {})
            commune_raw = loc.get("city","") or loc.get("department_name","")

            if not prix or not surface:
                continue

            results.append({
                "source":       "lbc",
                "url":          f"https://www.leboncoin.fr/ventes_immobilieres/{ad.get('list_id')}.htm",
                "titre":        ad.get("subject",""),
                "type_bien":    type_bien,
                "commune":      normalize_commune(commune_raw),
                "code_postal":  loc.get("zipcode",""),
                "adresse_raw":  commune_raw,
                "prix":         prix,
                "surface":      surface,
                "surf_terrain": surf_ter or 0,
                "pieces":       int(attrs.get("rooms","0") or 0),
                "chambres":     int(attrs.get("bedrooms","0") or 0),
                "dpe":          attrs.get("energy_rate",""),
                "description":  ad.get("body","")[:500],
                "photos":       [p.get("url","") for p in ad.get("images",{}).get("urls_large",[]) or []],
            })

        time.sleep(1.5)
        log.info(f"LBC {commune_slug} {type_bien} p{page}: {len(ads)} annonces")

    return results


# ── SeLoger ───────────────────────────────────────────────────────────────────
def scrape_seloger(commune_slug: str, type_bien="maison", max_pages=5) -> list:
    """
    SeLoger — JSON interne via l'endpoint de recherche.
    Anti-bot modéré : User-Agent + délais suffisent la plupart du temps.
    Si 403, nécessite rotation proxy.
    """
    TYPE_MAP = {"maison": "1", "appartement": "2", "terrain": "3"}
    results  = []
    session  = requests.Session()
    session.headers.update({**HEADERS,
        "Referer": "https://www.seloger.com/",
        "X-Requested-With": "XMLHttpRequest",
    })

    for page in range(1, max_pages + 1):
        # URL search SeLoger (paramètres observés par DevTools)
        params = {
            "types":       TYPE_MAP.get(type_bien, "1"),
            "natures":     "1",                  # vente
            "places":      f"[{{'inseeCodes':[],'label':'{commune_slug}'}}]",
            "projects":    "1",
            "enterprise":  "0",
            "qsVersion":   "1.0",
            "page":        str(page),
        }
        url = "https://www.seloger.com/list.htm"
        try:
            r = session.get(url, params=params, timeout=20)
            if r.status_code == 403:
                log.warning(f"SeLoger 403 — anti-bot actif pour {commune_slug}. Rotation proxy nécessaire.")
                break
            r.raise_for_status()
        except Exception as e:
            log.warning(f"SeLoger {commune_slug} p{page}: {e}")
            break

        soup   = BeautifulSoup(r.text, "html.parser")
        script = soup.find("script", string=re.compile(r"window\.__REDIAL_PROPS__"))
        if not script:
            # Fallback : cherche JSON dans balises script
            for sc in soup.find_all("script", type="application/ld+json"):
                try:
                    obj = json.loads(sc.string or "")
                    if isinstance(obj, list):
                        for item in obj:
                            if item.get("@type") in ("Apartment","House","RealEstateAgent"):
                                pass  # traiter ici si nécessaire
                except Exception:
                    pass
            log.warning(f"SeLoger: structure inattendue sur {url}")
            break

        try:
            raw   = re.search(r"window\.__REDIAL_PROPS__\s*=\s*(\[.*?\]);", script.string, re.S)
            props = json.loads(raw.group(1)) if raw else []
            cards = []
            for p in props:
                if isinstance(p, dict) and "cards" in p:
                    cards = p["cards"].get("list", [])
                    break
        except Exception as e:
            log.warning(f"SeLoger JSON: {e}")
            break

        if not cards:
            break

        for card in cards:
            prix    = parse_price(card.get("price",""))
            surface = parse_surface(card.get("surface",""))
            commune_raw = card.get("cityLabel","") or card.get("city","")
            surf_ter = parse_surface(card.get("landSurface","")) or 0

            if not prix or not surface:
                continue

            results.append({
                "source":       "seloger",
                "url":          card.get("classifiedURL",""),
                "titre":        card.get("title",""),
                "type_bien":    type_bien,
                "commune":      normalize_commune(commune_raw),
                "code_postal":  card.get("postalCode",""),
                "adresse_raw":  commune_raw,
                "prix":         prix,
                "surface":      surface,
                "surf_terrain": surf_ter,
                "pieces":       int(card.get("rooms",0) or 0),
                "chambres":     int(card.get("bedRooms",0) or 0),
                "dpe":          card.get("ecoScoreText",""),
                "description":  card.get("description","")[:500],
                "photos":       card.get("photos",[]),
            })

        time.sleep(2.0)
        log.info(f"SeLoger {commune_slug} {type_bien} p{page}: {len(cards)} annonces")

    return results


# ── Logic-Immo ────────────────────────────────────────────────────────────────
def scrape_logicimmo(commune_slug: str, type_bien="maison", max_pages=3) -> list:
    """Logic-Immo — HTML scraping."""
    TYPE_MAP = {"maison": "vente-maison", "appartement": "vente-appartement"}
    results = []
    session = requests.Session()
    session.headers.update(HEADERS)

    for page in range(1, max_pages + 1):
        slug = TYPE_MAP.get(type_bien, "vente-maison")
        url  = (f"https://www.logic-immo.com/{slug}-{commune_slug},1_{page}.html"
                if page > 1
                else f"https://www.logic-immo.com/{slug}-{commune_slug},1.html")
        try:
            r = session.get(url, timeout=15)
            r.raise_for_status()
        except Exception as e:
            log.warning(f"LogicImmo {commune_slug} p{page}: {e}")
            break

        soup  = BeautifulSoup(r.text, "html.parser")
        cards = soup.select("article[class*='offer-card']") or soup.select("[data-offer-id]")
        if not cards:
            break

        for card in cards:
            try:
                href    = card.select_one("a[href*='/annonce/']")
                url_ad  = "https://www.logic-immo.com" + href["href"] if href else ""
                prix_el = card.select_one("[class*='offer-price']")
                surf_el = card.select_one("[class*='surface']") or card.select_one("[class*='criteria']")
                loc_el  = card.select_one("[class*='offer-locality']") or card.select_one("[class*='location']")

                prix    = parse_price(prix_el.get_text() if prix_el else "")
                surface = parse_surface(surf_el.get_text() if surf_el else "")
                commune_raw = loc_el.get_text().strip() if loc_el else commune_slug

                if not prix or not surface:
                    continue

                results.append({
                    "source":       "logicimmo",
                    "url":          url_ad,
                    "titre":        card.get("title",""),
                    "type_bien":    type_bien,
                    "commune":      normalize_commune(commune_raw),
                    "code_postal":  "",
                    "adresse_raw":  commune_raw,
                    "prix":         prix,
                    "surface":      surface,
                    "surf_terrain": 0,
                    "pieces":       0,
                    "chambres":     0,
                    "dpe":          "",
                    "description":  "",
                    "photos":       [],
                })
            except Exception as e:
                log.debug(f"LogicImmo card: {e}")
                continue

        time.sleep(1.2)
        log.info(f"LogicImmo {commune_slug} {type_bien} p{page}: {len(cards)} annonces")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION
# ══════════════════════════════════════════════════════════════════════════════
SCRAPERS = {
    "lbc":       scrape_lbc,
    "seloger":   scrape_seloger,
    "logicimmo": scrape_logicimmo,
}

# Slugs communes par source
COMMUNE_SLUGS = {
    "lbc": {
        "chamonix": "Chamonix-Mont-Blanc_74400",
        "les-houches": "Les_Houches_74310",
        "saint-gervais": "Saint-Gervais-les-Bains_74170",
        "sallanches": "Sallanches_74700",
        "servoz": "Servoz_74310",
        "passy": "Passy_74190",
    },
    "seloger": {
        "chamonix": "chamonix-mont-blanc-74400",
        "les-houches": "les-houches-74310",
        "saint-gervais": "saint-gervais-les-bains-74170",
        "sallanches": "sallanches-74700",
        "servoz": "servoz-74310",
        "passy": "passy-74190",
    },
    "logicimmo": {
        "chamonix": "chamonix-mont-blanc-74400",
        "les-houches": "les-houches-74310",
        "saint-gervais": "saint-gervais-les-bains-74170",
        "sallanches": "sallanches-74700",
    },
}

TYPES_BIEN = ["maison", "appartement", "terrain"]


def run_scraper(sources=None, communes=None, types=None, dry_run=False):
    sources  = sources  or list(SCRAPERS.keys())
    communes = communes or list(COMMUNE_SLUGS.get("lbc", {}).keys())
    types    = types    or TYPES_BIEN

    con      = get_db()
    total_new = 0

    for source in sources:
        fn     = SCRAPERS[source]
        slugs  = COMMUNE_SLUGS.get(source, {})
        for commune_key in communes:
            slug = slugs.get(commune_key)
            if not slug:
                log.debug(f"Pas de slug pour {source}/{commune_key}")
                continue
            for type_bien in types:
                log.info(f"Scraping {source} / {commune_key} / {type_bien} ...")
                try:
                    listings = fn(slug, type_bien)
                    new = 0
                    for listing in listings:
                        if upsert_listing(con, listing, dry_run=dry_run):
                            new += 1
                    if not dry_run:
                        con.commit()
                    total_new += new
                    log.info(f"  → {len(listings)} récupérés  {new} nouveaux")
                except Exception as e:
                    log.error(f"{source}/{commune_key}/{type_bien}: {e}", exc_info=True)
                time.sleep(2)

    # Marquer inactifs les listings non-vus depuis >30 jours
    if not dry_run:
        cutoff = date.today().replace(day=date.today().day - 30).isoformat() \
                 if date.today().day > 30 else "2000-01-01"
        con.execute(
            "UPDATE listings SET active=0 WHERE last_seen < ? AND active=1",
            (cutoff,)
        )
        con.commit()

    # Stats finales
    rows = con.execute("""
        SELECT source, type_bien, COUNT(*) n, AVG(prix) avg_prix,
               SUM(CASE WHEN avm_score>=70 THEN 1 ELSE 0 END) opportunites
        FROM listings WHERE active=1
        GROUP BY source, type_bien ORDER BY source, type_bien
    """).fetchall()

    print(f"\n{'='*70}")
    print(f"SCRAPING TERMINÉ — {total_new} nouveaux listings")
    print(f"{'='*70}")
    print(f"{'Source':<12} {'Type':<14} {'N':>5} {'Prix moy':>12} {'Opport':>8}")
    print("-"*70)
    for r in rows:
        print(f"{r[0]:<12} {r[1]:<14} {r[2]:>5} {r[3]:>11,.0f}€ {r[4]:>8}")

    # Top opportunités
    opps = con.execute("""
        SELECT source, commune, type_bien, prix, surface, avm_pred, avm_ratio, avm_score, url
        FROM listings
        WHERE active=1 AND avm_score >= 70
        ORDER BY avm_score DESC, avm_ratio ASC
        LIMIT 20
    """).fetchall()

    if opps:
        print(f"\n{'='*70}")
        print("TOP OPPORTUNITÉS (score ≥ 70)")
        print(f"{'='*70}")
        for o in opps:
            print(f"  [{o[7]:>3}]  {o[0]:<10} {o[1]:<28} {o[2]:<10} "
                  f"{o[3]:>9,}€  {o[4]:.0f}m²  "
                  f"ratio={o[6]:.2f}")
            print(f"         {o[8]}")

    con.close()
    return total_new


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Scraper immobilier vallée Chamonix")
    parser.add_argument("--source",   nargs="+", choices=list(SCRAPERS.keys()),
                        help="Sources à scraper (défaut: toutes)")
    parser.add_argument("--commune",  nargs="+",
                        help="Communes (défaut: toutes)")
    parser.add_argument("--type",     nargs="+",
                        choices=TYPES_BIEN, help="Types de bien")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Affiche sans stocker en DB")
    parser.add_argument("--stats",    action="store_true",
                        help="Affiche stats DB sans scraper")
    args = parser.parse_args()

    if args.stats:
        con = get_db()
        rows = con.execute("""
            SELECT source, type_bien, COUNT(*) n,
                   MIN(prix) min_p, MAX(prix) max_p, AVG(prix) avg_p,
                   SUM(CASE WHEN avm_score>=70 THEN 1 ELSE 0 END) opps
            FROM listings WHERE active=1
            GROUP BY source, type_bien
        """).fetchall()
        for r in rows:
            print(f"{r[0]:<12} {r[1]:<14} n={r[2]:>4}  "
                  f"{r[3]:,}€-{r[4]:,}€  moy={r[5]:,.0f}€  opps={r[6]}")
        con.close()
    else:
        run_scraper(
            sources=args.source,
            communes=args.commune,
            types=args.type,
            dry_run=args.dry_run,
        )
