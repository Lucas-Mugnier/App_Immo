# -*- coding: utf-8 -*-
"""
bot_overnight.py — Bot scraping overnight, comportement humain simulé
Sources : SeLoger (Google) · Bien'ici (Google)

SETUP sessions (une seule fois) :
    python bot_overnight.py --setup                    ← login toutes sources
    python bot_overnight.py --setup --source seloger   ← une source
    SeLoger / Bien'ici : browser s'ouvre → clique "Continuer avec Google"
                         → connecte-toi → Entrée pour sauver

RUN (la nuit) :
    python bot_overnight.py               ← toutes sources, toutes communes vallée
    python bot_overnight.py --headless    ← sans fenêtre (prod / cron)
    python bot_overnight.py --source bienici   ← une source seulement

OUTPUT :
    dvf/listings_raw_YYYYMMDD.json        ← brut JSON
    dvf/listings_market.db                ← DB dédupliquée + AVM scorée
    scraper_overnight.log                 ← log détaillé
"""
import sys; sys.stdout.reconfigure(encoding='utf-8')
import argparse, asyncio, json, os, re, sqlite3, time, hashlib, logging, random
from datetime import date, datetime
from typing import Optional
from pathlib import Path
from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, BrowserContext

load_dotenv(Path(__file__).parent / ".env")

# ── Config ─────────────────────────────────────────────────────────────────────
BASE         = Path(__file__).parent
DVF_DIR      = BASE / "dvf"
SESSION_DIR  = BASE / "sessions"          # cookies par compte
DB_PATH      = DVF_DIR / "listings_market.db"
IDX_PATH     = DVF_DIR / "market_index.json"
LOG_PATH     = BASE / "scraper_overnight.log"
RAW_OUT      = DVF_DIR / f"listings_raw_{date.today().strftime('%Y%m%d')}.json"

DVF_DIR.mkdir(exist_ok=True)
SESSION_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_PATH, encoding="utf-8"),
        logging.StreamHandler(),
    ]
)
log = logging.getLogger("bot_overnight")

# ── AVM models ─────────────────────────────────────────────────────────────────
MARKET_INDEX = {}
if IDX_PATH.exists():
    MARKET_INDEX = {int(k): float(v) for k, v in json.loads(IDX_PATH.read_text()).items()}
MARKET_IDX_NOW = MARKET_INDEX.get(date.today().year, MARKET_INDEX.get(2025, 1.12))

def _load_appart_meta_overnight() -> dict:
    p = BASE / "dvf" / "avm_appart_cham_meta.json"
    return json.loads(p.read_text("utf-8")) if p.exists() else {}

def _load_dvf_pm2_overnight() -> dict:
    p = BASE / "dvf" / "dvf_stats.json"
    if not p.exists(): return {}
    stats = json.loads(p.read_text("utf-8"))
    return {k: v.get("median_m2", 0) for k, v in stats.get("communes", {}).items()}

_APPART_META_OVN = _load_appart_meta_overnight()
_DVF_PM2_OVN     = _load_dvf_pm2_overnight()

# ── Normalize commune ──────────────────────────────────────────────────────────
COMMUNE_NORM = {
    "chamonix": "CHAMONIX MONT BLANC", "chamonix mont blanc": "CHAMONIX MONT BLANC",
    "les houches": "LES HOUCHES",
    "servoz": "SERVOZ",
    "saint gervais": "SAINT GERVAIS LES BAINS",
    "saint-gervais-les-bains": "SAINT GERVAIS LES BAINS",
    "sallanches": "SALLANCHES",
    "passy": "PASSY", "domancy": "DOMANCY",
}
def norm_commune(raw: str) -> str:
    r = re.sub(r'[-_]', ' ', (raw or "").lower().strip())
    for k, v in COMMUNE_NORM.items():
        if k in r or r in k:
            return v
    return raw.upper().strip()

def parse_price(s) -> Optional[int]:
    s = re.sub(r"[^\d]", "", str(s or ""))
    return int(s) if s else None

def parse_surface(s) -> Optional[float]:
    m = re.search(r"([\d,\.]+)", str(s or "").replace(",", "."))
    return float(m.group(1)) if m else None

def listing_id(source: str, url: str) -> str:
    return hashlib.md5(f"{source}:{url}".encode()).hexdigest()[:16]

def _ratio_to_score(ratio: float | None) -> int | None:
    """Score continu 0-100 basé sur ratio prix/AVM.
    ratio=0.50 → 100 (deal exceptionnel)
    ratio=0.75 → 72  (bonne affaire)
    ratio=1.00 → 44  (prix marché)
    ratio=1.40 → 0   (très surévalué)
    """
    if ratio is None:
        return None
    return max(0, min(100, round((1.40 - ratio) / 0.90 * 100)))

def avm_score(prix, surface, commune, surf_terrain=0, type_bien="maison", section: str = "G"):
    """Estime valeur marché. Retourne (pred, ratio, score, model_tag).
    section : section cadastrale Chamonix (A-G) — déduite de l'URL SeLoger.
    """
    if not prix or not surface or surface < 10:
        return None, None, None, None

    pred = None
    model_tag = "dvf_stats"

    # 1. Chamonix maisons → XGBoost predict_avm.py (section-aware)
    if commune == "CHAMONIX MONT BLANC" and type_bien == "maison":
        try:
            import sys as _sys
            _sys.path.insert(0, str(BASE))
            from predict_avm import predict as _predict_avm
            res  = _predict_avm(section, surface, surf_terrain or 0, "U",
                                pieces=max(1, round(surface / 20)))
            pred      = res["valeur"]
            model_tag = "chamonix_mai_xgb"
        except Exception:
            pass

    # 2. Chamonix apparts → meta pm2 par section
    if pred is None and commune == "CHAMONIX MONT BLANC":
        if _APPART_META_OVN:
            pm2_ref = (_APPART_META_OVN.get("pm2_section", {}).get(section)
                       or _APPART_META_OVN.get("pm2_global_cham", 10198))
            emp_idx = max(_APPART_META_OVN.get("emp_idx", {}).values(), default=1.0)
            pred      = surface * pm2_ref * emp_idx
            model_tag = "chamonix_apt_meta"

    # 3. Autres communes → DVF stats
    if pred is None:
        pm2_ref = _DVF_PM2_OVN.get(commune, 0)
        if pm2_ref > 0:
            pred = surface * pm2_ref + (surf_terrain or 0) * pm2_ref * 0.05
        else:
            pred = surface * 6000 * MARKET_IDX_NOW

    ratio = prix / pred if pred else None
    pm2   = prix / surface if surface > 0 else 0

    # Outliers manifestes → score=None (données suspectes, non scorées)
    # pm2 hors plage réaliste Alpes ou ratio extrême
    is_outlier = (pm2 > 0 and (pm2 < 3_000 or pm2 > 28_000)) or \
                 (ratio is not None and (ratio < 0.40 or ratio > 2.20))

    score = None if is_outlier else _ratio_to_score(ratio)
    return (round(pred), round(ratio, 3) if ratio else None, score, model_tag)

# ── DB Schema ──────────────────────────────────────────────────────────────────
SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id              TEXT PRIMARY KEY,
    source          TEXT,
    url             TEXT UNIQUE,
    titre           TEXT,
    type_bien       TEXT,
    commune         TEXT,
    code_postal     TEXT,
    adresse_raw     TEXT,
    prix            INTEGER,
    surface         REAL,
    surf_terrain    REAL,
    pieces          INTEGER,
    chambres        INTEGER,
    dpe             TEXT,
    description     TEXT,
    photos_json     TEXT,
    avm_pred        REAL,
    avm_ratio       REAL,
    avm_score       INTEGER,
    avm_model       TEXT,
    first_seen      TEXT,
    last_seen       TEXT,
    jours_marche    INTEGER,
    prix_initial    INTEGER,
    nb_baisses      INTEGER DEFAULT 0,
    active          INTEGER DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_commune   ON listings(commune);
CREATE INDEX IF NOT EXISTS idx_score     ON listings(avm_score DESC);
CREATE INDEX IF NOT EXISTS idx_active    ON listings(active);
CREATE TABLE IF NOT EXISTS prix_history (
    listing_id TEXT, date_obs TEXT, prix INTEGER,
    PRIMARY KEY (listing_id, date_obs)
);
"""

def get_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    # Migration: ajouter colonnes manquantes si DB existante
    cols = {r[1] for r in con.execute("PRAGMA table_info(listings)")}
    if "avm_model" not in cols:
        con.execute("ALTER TABLE listings ADD COLUMN avm_model TEXT")
    con.commit()
    return con

# ══════════════════════════════════════════════════════════════════════════════
# HUMAN BEHAVIOR — simulation réaliste
# ══════════════════════════════════════════════════════════════════════════════

def _gauss_clamp(mu, sigma, lo, hi):
    """Distribution gaussienne clampée — plus réaliste que uniform."""
    return max(lo, min(hi, random.gauss(mu, sigma)))

async def human_delay(min_ms=600, max_ms=2500):
    """
    Délai avec distribution gaussienne + micro-pauses occasionnelles.
    Un humain ne fait pas random.uniform — il a un rythme avec des variations.
    """
    # Délai principal gaussien
    mu    = (min_ms + max_ms) / 2
    sigma = (max_ms - min_ms) / 4
    ms    = _gauss_clamp(mu, sigma, min_ms, max_ms)

    # 8% de chance d'une pause longue (distraction)
    if random.random() < 0.08:
        ms += random.uniform(2000, 6000)

    await asyncio.sleep(ms / 1000)

async def human_scroll(page: Page, n_scrolls=3):
    """
    Scroll progressif avec vitesse variable et pauses de lecture.
    Simule quelqu'un qui lit les annonces, pas un bot qui traverse la page.
    """
    vp_h = (page.viewport_size or {"height": 768})["height"]

    for i in range(n_scrolls):
        # Vitesse variable — début lent, milieu plus rapide, fin lent
        speed_factor = 1.0 - 0.3 * abs(i / max(n_scrolls - 1, 1) - 0.5) * 2
        scroll_px    = int(_gauss_clamp(380, 120, 150, 800) * speed_factor)

        await page.evaluate(f"window.scrollBy({{top: {scroll_px}, behavior: 'smooth'}})")

        # Pause après scroll — plus longue si c'est le premier (on regarde la page)
        if i == 0:
            await asyncio.sleep(random.uniform(1.0, 2.5))
        elif random.random() < 0.25:
            # 25% de chance de s'arrêter pour "lire" une annonce
            await asyncio.sleep(random.uniform(1.5, 4.0))
        else:
            await asyncio.sleep(random.uniform(0.2, 0.8))

async def human_scroll_up(page: Page):
    """Remonte légèrement — comportement naturel en cours de lecture."""
    px = random.randint(100, 300)
    await page.evaluate(f"window.scrollBy({{top: -{px}, behavior: 'smooth'}})")
    await asyncio.sleep(random.uniform(0.3, 0.8))

async def human_move(page: Page, target_x=None, target_y=None):
    """
    Mouvement souris avec trajectoire courbe (bezier approché).
    Pas de téléportation — mouvement en plusieurs étapes.
    """
    vp = page.viewport_size or {"width": 1366, "height": 768}
    tx = target_x or random.randint(80, vp["width"] - 80)
    ty = target_y or random.randint(80, vp["height"] - 80)

    # Position de départ approximative (on ne la connaît pas, on part d'un point plausible)
    sx = random.randint(200, vp["width"] - 200)
    sy = random.randint(200, vp["height"] - 200)

    # Mouvement en 3-6 étapes avec légère déviation (simule bezier)
    steps = random.randint(3, 6)
    for step in range(1, steps + 1):
        t       = step / steps
        # Easing cubique pour accélération/décélération
        ease    = t * t * (3 - 2 * t)
        jitter  = random.gauss(0, 8) if step < steps else 0  # pas de jitter à destination
        ix      = int(sx + (tx - sx) * ease + jitter)
        iy      = int(sy + (ty - sy) * ease + jitter)
        await page.mouse.move(ix, iy)
        await asyncio.sleep(random.uniform(0.01, 0.04))

    await asyncio.sleep(random.uniform(0.05, 0.2))

async def human_hover_random(page: Page):
    """Survole un élément aléatoire sur la page (comportement naturel)."""
    try:
        elements = await page.query_selector_all("a, button, img, h2, h3, p")
        if elements:
            el = random.choice(elements[:20])
            box = await el.bounding_box()
            if box:
                await human_move(page,
                    int(box["x"] + box["width"] / 2),
                    int(box["y"] + box["height"] / 2))
    except Exception:
        pass

async def human_type(page: Page, text: str):
    """
    Frappe au clavier avec vitesse variable + erreurs occasionnelles corrigées.
    WPM moyen humain : 40-60 = 200-300ms par caractère.
    """
    for char in text:
        # Vitesse variable par caractère (touches communes plus rapides)
        base_delay = random.gauss(120, 40)
        base_delay = max(50, min(350, base_delay))

        # 3% de chance d'une faute de frappe corrigée
        if random.random() < 0.03 and char.isalpha():
            wrong_key = random.choice("qwertyuiopasdfghjklzxcvbnm")
            await page.keyboard.type(wrong_key)
            await asyncio.sleep(random.uniform(0.08, 0.18))
            await page.keyboard.press("Backspace")
            await asyncio.sleep(random.uniform(0.05, 0.12))

        await page.keyboard.type(char)
        await asyncio.sleep(base_delay / 1000)

        # Micro-pause naturelle entre mots
        if char == " ":
            await asyncio.sleep(random.uniform(0.0, 0.15))

async def dismiss_cookies(page: Page):
    """
    Accepte ou ferme le bandeau cookies.
    Tente plusieurs sélecteurs courants dans l'ordre.
    """
    selectors = [
        "#didomi-notice-agree-button",
        "#onetrust-accept-btn-handler",
        "button:has-text('Tout accepter')",
        "button:has-text('Accepter tout')",
        "button:has-text('Accepter')",
        "button:has-text('J\\'accepte')",
        "button:has-text('OK')",
        "[data-testid='accept-cookies']",
        ".gdpr-btn-accept",
        ".cookie-accept",
    ]
    for sel in selectors:
        try:
            btn = await page.query_selector(sel)
            if btn and await btn.is_visible():
                await human_move(page)
                await btn.click()
                await asyncio.sleep(random.uniform(0.5, 1.2))
                log.debug(f"Cookies acceptés via: {sel}")
                return True
        except Exception:
            continue
    return False

async def safe_goto(page: Page, url: str, wait="domcontentloaded", retries=3):
    """
    Navigation robuste avec retry + délai aléatoire post-chargement.
    Simule quelqu'un qui attend que la page charge avant d'interagir.
    """
    for attempt in range(retries):
        try:
            await page.goto(url, wait_until=wait, timeout=35000)
            # Délai post-chargement — la page "settle"
            await asyncio.sleep(random.uniform(1.2, 3.0))
            # Gérer cookies dès l'arrivée
            await dismiss_cookies(page)
            return True
        except Exception as e:
            log.warning(f"goto attempt {attempt+1}/{retries}: {str(e)[:80]}")
            if attempt < retries - 1:
                await asyncio.sleep(random.uniform(3, 7))
    return False

async def human_read_page(page: Page):
    """
    Simule un humain qui "lit" la page :
    scroll progressif, quelques survols, parfois remonte.
    """
    await human_scroll(page, random.randint(3, 6))
    if random.random() < 0.4:
        await human_hover_random(page)
    if random.random() < 0.2:
        await human_scroll_up(page)
        await asyncio.sleep(random.uniform(0.5, 1.5))
    if random.random() < 0.3:
        await human_hover_random(page)

# ── Session management ─────────────────────────────────────────────────────────
def session_path(source: str) -> Path:
    return SESSION_DIR / f"{source}_session.json"

def import_firefox_cookies(source: str):
    """
    Lit les cookies du vrai Firefox installé et les sauve comme session Playwright.
    → Connecte-toi sur seloger.com dans TON Firefox, puis lance :
        python bot_overnight.py --import-firefox --source seloger
    Firefox doit être FERMÉ au moment du import (SQLite locked sinon).
    """
    DOMAINS = {
        "seloger": [".seloger.com", "seloger.com", "signin.seloger.com"],
        "bienici": [".bienici.com", "bienici.com"],
    }
    target_domains = DOMAINS.get(source, [])

    try:
        import browser_cookie3
        jar = browser_cookie3.firefox(domain_name=target_domains[0].lstrip("."))
    except Exception as e:
        print(f"Erreur lecture Firefox : {e}")
        print("→ Assure-toi que Firefox est FERMÉ avant l'import.")
        return False

    cookies_pw = []
    for c in jar:
        if not any(d in c.domain for d in [d.lstrip(".") for d in target_domains]):
            continue
        cookies_pw.append({
            "name":     c.name,
            "value":    c.value,
            "domain":   c.domain if c.domain.startswith(".") else f".{c.domain}",
            "path":     c.path or "/",
            "secure":   bool(c.secure),
            "httpOnly": bool(getattr(c, "has_nonstandard_attr", lambda x: False)("HttpOnly")),
            "sameSite": "Lax",
        })

    if not cookies_pw:
        print(f"Aucun cookie {source} trouvé dans Firefox.")
        print(f"→ Connecte-toi d'abord sur {target_domains[0].lstrip('.')} dans Firefox.")
        return False

    session_data = {"cookies": cookies_pw, "origins": []}
    session_path(source).write_text(json.dumps(session_data, ensure_ascii=False, indent=2))
    print(f"✓ {len(cookies_pw)} cookies {source} importés depuis Firefox → {session_path(source)}")
    return True

async def save_session(context: BrowserContext, source: str):
    cookies = await context.cookies()
    storage = await context.storage_state()
    session_path(source).write_text(json.dumps(storage, ensure_ascii=False, indent=2))
    log.info(f"Session {source} sauvée ({len(cookies)} cookies)")

async def load_session(context: BrowserContext, source: str) -> bool:
    p = session_path(source)
    if not p.exists():
        log.warning(f"Pas de session {source} — lance --login d'abord")
        return False
    state = json.loads(p.read_text())
    await context.add_cookies(state.get("cookies", []))
    log.info(f"Session {source} chargée")
    return True

# ══════════════════════════════════════════════════════════════════════════════
# SCRAPERS PAR SOURCE
# ══════════════════════════════════════════════════════════════════════════════

# ── (LeBonCoin retiré — nécessite numéro de téléphone pour compte) ─────────────

# ── SeLoger ───────────────────────────────────────────────────────────────────
# (placeholder ici pour éviter NameError — définition complète plus bas)
LBC_SEARCHES_UNUSED = [
    ("https://www.leboncoin.fr/recherche?category=9&locations=Chamonix-Mont-Blanc_74400&real_estate_type=1",  "maison"),
    ("https://www.leboncoin.fr/recherche?category=9&locations=Chamonix-Mont-Blanc_74400&real_estate_type=2",  "appartement"),
    ("https://www.leboncoin.fr/recherche?category=9&locations=Les_Houches_74310&real_estate_type=1",          "maison"),
    ("https://www.leboncoin.fr/recherche?category=9&locations=Saint-Gervais-les-Bains_74170&real_estate_type=1", "maison"),
    ("https://www.leboncoin.fr/recherche?category=9&locations=Sallanches_74700&real_estate_type=1",           "maison"),
    ("https://www.leboncoin.fr/recherche?category=9&locations=Sallanches_74700&real_estate_type=2",           "appartement"),
    ("https://www.leboncoin.fr/recherche?category=9&locations=Servoz_74310&real_estate_type=1",               "maison"),
    ("https://www.leboncoin.fr/recherche?category=9&locations=Passy_74190&real_estate_type=1",                "maison"),
]

async def scrape_lbc_unused(page: Page) -> list:
    results = []
    for url, type_bien in LBC_SEARCHES:
        log.info(f"LBC: {url[-60:]}")
        ok = await safe_goto(page, url)
        if not ok:
            continue

        try:
            await page.wait_for_selector("[data-test-id='adList'], [data-qa-id='aditem_container']", timeout=20000)
        except Exception:
            log.warning(f"LBC: pas de liste sur {url[-40:]}")
            continue

        await human_scroll(page, 5)
        await human_delay(1000, 2000)

        page_num = 1
        while True:
            # Extraire le JSON __NEXT_DATA__ qui contient toutes les annonces
            data = await page.evaluate("""
                () => {
                    const nd = document.getElementById('__NEXT_DATA__');
                    if (!nd) return null;
                    try { return JSON.parse(nd.textContent); } catch { return null; }
                }
            """)

            ads = []
            if data:
                try:
                    props = data.get("props",{}).get("pageProps",{})
                    ads = (props.get("searchData",{}).get("ads", []) or
                           props.get("ads", []) or [])
                except Exception:
                    pass

            # Fallback: DOM scraping si pas de JSON
            if not ads:
                ads_dom = await page.evaluate("""
                    () => {
                        const items = document.querySelectorAll('[data-qa-id="aditem_container"], li[data-test-id]');
                        return Array.from(items).map(item => {
                            const link  = item.querySelector('a[href*="/ventes_immobilieres/"]');
                            const price = item.querySelector('[aria-label*="Prix"], [data-qa-id="aditem_price"]');
                            const title = item.querySelector('[data-qa-id="aditem_title"], h2, h3');
                            const loc   = item.querySelector('[data-qa-id="aditem_location"]');
                            return {
                                list_id: link ? link.href.match(/(\d+)\.htm/)?.[1] : null,
                                url:     link ? link.href : '',
                                price:   [price ? price.innerText : ''],
                                subject: title ? title.innerText : '',
                                location: { city: loc ? loc.innerText : '' },
                                attributes: [],
                            };
                        }).filter(a => a.url);
                    }
                """)
                ads = ads_dom

            for ad in ads:
                prix = parse_price(
                    (ad.get("price") or [""])[0] if isinstance(ad.get("price"), list)
                    else ad.get("price","")
                )
                attrs = {}
                for a in (ad.get("attributes") or []):
                    if isinstance(a, dict):
                        attrs[a.get("key","")] = a.get("value_label") or (a.get("values",[""])[0] if a.get("values") else "")

                surface   = parse_surface(attrs.get("square","") or attrs.get("surface",""))
                surf_ter  = parse_surface(attrs.get("land_plot_surface","")) or 0
                loc       = ad.get("location",{}) or {}
                commune   = norm_commune(loc.get("city","") or ad.get("location",""))
                ad_url    = ad.get("url","") or f"https://www.leboncoin.fr/ventes_immobilieres/{ad.get('list_id')}.htm"

                if prix and surface:
                    pred, ratio, score, model_tag = avm_score(prix, surface, commune, surf_ter, type_bien)
                    results.append({
                        "source": "lbc", "url": ad_url,
                        "titre": ad.get("subject","").strip(),
                        "type_bien": type_bien, "commune": commune,
                        "code_postal": loc.get("zipcode",""), "adresse_raw": loc.get("city",""),
                        "prix": prix, "surface": surface, "surf_terrain": surf_ter,
                        "pieces": int(attrs.get("rooms",0) or 0),
                        "chambres": int(attrs.get("bedrooms",0) or 0),
                        "dpe": attrs.get("energy_rate",""), "description": ad.get("body","")[:400],
                        "photos": [p.get("url","") for p in (ad.get("images",{}) or {}).get("urls_large",[]) or []],
                        "avm_pred": pred, "avm_ratio": ratio, "avm_score": score, "avm_model": model_tag,
                    })

            log.info(f"  LBC p{page_num}: {len(ads)} annonces")

            # Page suivante
            try:
                next_btn = await page.query_selector("a[aria-label='Page suivante'], button:has-text('Suivant')")
                if not next_btn:
                    break
                await human_move(page)
                await next_btn.click()
                await human_delay(2000, 4000)
                await human_scroll(page, 4)
                page_num += 1
                if page_num > 15:
                    break
            except Exception:
                break

        await human_delay(3000, 6000)

    return results


# ── SeLoger (nodriver — DataDome bypass confirmé) ────────────────────────────
# POCOFR4764 = zone Chamonix-Mont-Blanc (74400) — couvre aussi Les Houches,
# Servoz, Saint-Gervais, Passy (rayon ~30km autour de Chamonix).
# Pour ajouter d'autres communes : trouver leur POCOFR sur seloger.com et
# ajouter une entrée dans SL_ND_SEARCHES.
SL_ND_SEARCHES = [
    ("https://www.seloger.com/classified-search"
     "?distributionTypes=Buy&estateTypes=Apartment&locations=POCOFR4764&priceMax=1500000",
     "appartement"),
    ("https://www.seloger.com/classified-search"
     "?distributionTypes=Buy&estateTypes=House&locations=POCOFR4764",
     "maison"),
]

# Communes cibles (DB uppercase) pour filtre post-extraction
_SL_TARGET_COMMUNES = {
    "CHAMONIX MONT BLANC", "LES HOUCHES", "SAINT GERVAIS LES BAINS",
    "SALLANCHES", "PASSY", "SERVOZ", "DOMANCY",
}

_SL_ARTIFACTS = re.compile(
    r"^\s*(\d+|RDC|tage|de terrain|Programme Neuf|\d{4}|Nouveau|Exclusivit[eé])\s*$",
    re.I,
)

def _clean_sl_commune(raw: str | None) -> str:
    """Nettoie les artefacts de texte SeLoger avant norm_commune()."""
    if not raw:
        return ""
    lines = [l.strip() for l in raw.split("\n") if l.strip() and not _SL_ARTIFACTS.match(l)]
    return lines[-1] if lines else raw.strip()

# Mapping sous-quartier SeLoger → section cadastrale Chamonix.
# Les sections correspondent aux SECTION_DEFAULTS de predict_avm.py :
#   G = centre (0.8km, alt 1062m)  E = Les Bossons/Pélerins (3.2km, alt 1032m)
#   D = Les Bois (1.5km)           B = Les Praz/Flégère (7.2km, alt 1222m)
#   A = Argentière/Le Tour (9.5km, alt 1391m)  C = centre nord (2.8km)
_SL_QUARTIER_SECTION: dict[str, str] = {
    # Centre / très proche centre
    "chamonix-centre":              "G",
    "chamonix-sud-bois-du-bouchet": "G",
    "aiguille-du-midi":             "G",
    "les-gaillands":                "G",
    # Les Bois / centre-est
    "les-bois":                     "D",
    "les-mouilles":                 "D",
    # Les Pélerins / Les Bossons / Les Moussoux → bas de la vallée
    "les-bossons-les-moussoux":     "E",
    "les-pelerins-le-betty":        "E",
    "les-bossons":                  "E",
    "les-moussoux":                 "E",
    "les-pelerins":                 "E",
    "le-betty":                     "E",
    "ouest":                        "E",
    "ouest-et-nord":                "E",
    # Les Praz / La Flégère → mi-vallée
    "les-praz":                     "B",
    "la-flegere":                   "B",
    "les-tines":                    "B",
    "la-tour-argentiere-les-praz":  "B",
    # Argentière / Le Tour → haut de la vallée
    "argentiere":                   "A",
    "la-tour-argentiere":           "A",
    "le-tour":                      "A",
    "les-chosalets":                "A",
    "est":                          "A",
}

def _section_from_sl_url(url: str) -> str:
    """Déduit la section cadastrale Chamonix depuis le sous-quartier de l'URL SeLoger.
    Fallback = G (centre) si quartier inconnu.
    """
    m = re.search(r'/annonces/[^/]+/[^/]+/[^/]+-\d{2,5}/([^/]+)/\d+\.htm', url)
    if m:
        quartier = m.group(1)
        if quartier in _SL_QUARTIER_SECTION:
            return _SL_QUARTIER_SECTION[quartier]
    return "G"  # défaut : centre

def _commune_from_sl_url(url: str) -> Optional[str]:
    """Extrait la commune depuis le chemin de l'URL SeLoger.
    Plus fiable que le texte : l'URL encode toujours la vraie localisation.
    /annonces/achat/appartement/les-houches-74/... → LES HOUCHES
    /annonces/achat/appartement/chamonix-mont-blanc-74/... → CHAMONIX MONT BLANC
    Format SeLoger : /{commune-slug}-{dept_2_digits}/ (code département, pas CP complet)
    """
    m = re.search(r'/annonces/[^/]+/[^/]+/([^/]+)/', url)
    if not m:
        return None
    segment = m.group(1)                          # ex: "chamonix-mont-blanc-74"
    slug = re.sub(r'-\d{2,5}$', '', segment)      # ex: "chamonix-mont-blanc"
    return norm_commune(slug)

# JS d'extraction par card (CSS Emotion obfusqué → on remonte depuis les <a>)
_SL_EXTRACT_JS = """
(type_bien) => {
    const seen = new Set();
    const results = [];
    for (const a of document.querySelectorAll('a[href*="/annonces/"]')) {
        const url = a.href.split('?')[0].split('#')[0];
        if (!url.match(/\\d{6,}\\.htm/) || seen.has(url)) continue;
        seen.add(url);

        // Remonter à la card en cherchant l'ancêtre avec prix et taille < 700 chars
        let card = a;
        for (let i = 0; i < 12; i++) {
            if (!card.parentElement) break;
            const parent = card.parentElement;
            const txt = parent.innerText || '';
            if (txt.includes('€') && txt.length < 700) { card = parent; continue; }
            if (txt.length > 700) break;
            card = parent;
        }
        const text = (card.innerText || '').trim();
        if (!text.includes('€')) continue;

        // Prix : prendre le PREMIER match entre 80k et 2.5M€
        let price = null;
        for (const m of text.matchAll(/(\\d[\\d\\s]{2,9})\\s*€(?!\\s*\\/m)/g)) {
            const v = parseInt(m[1].replace(/\\s/g, ''), 10);
            if (v >= 80000 && v <= 2500000) { price = v; break; }
        }

        const surfM  = text.match(/(\\d+[,\\.]?\\d*)\\s*m²/);
        const surf   = surfM ? parseFloat(surfM[1].replace(',', '.')) : null;
        const roomM  = text.match(/(\\d+)\\s*pi[eè]ce/i);
        const rooms  = roomM ? parseInt(roomM[1], 10) : null;
        const chamM  = text.match(/(\\d+)\\s*chambre/i);
        const chams  = chamM ? parseInt(chamM[1], 10) : null;
        const dpeM   = text.match(/^\\s*([A-G])\\s*$/m);
        const dpe    = dpeM ? dpeM[1] : null;
        // Commune : dernière ligne sans saut de ligne avant la parenthèse
        const cpM    = text.match(/([^\\n\\r]{2,50})\\s*\\((74\\d{3})\\)/);
        const commune_raw = cpM ? cpM[1].trim() : null;
        const cp     = cpM ? cpM[2] : null;

        if (!price || !surf) continue;

        // Photos : déduplication par UUID mms.seloger.com — logos exclus
        const seenUuids = new Set();
        const photos = [];
        for (const img of card.querySelectorAll('img')) {
            const src = img.src || '';
            if (!src.includes('mms.seloger.com')) continue;
            // Logo SeLoger = h=50 sans w= (?ci_seal=...&h=50)
            const hasW = /[?&]w=\d+/.test(src);
            const hM   = src.match(/[?&]h=(\d+)/);
            if (!hasW && hM && parseInt(hM[1]) <= 100) continue;
            if (hasW) {
                const wVal = parseInt(src.match(/[?&]w=(\d+)/)[1]);
                if (wVal < 200) continue;
            }
            if (/\/(logo|agence|logotype|agency)/i.test(src)) continue;
            const uuidM = src.match(/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
            if (uuidM && !seenUuids.has(uuidM[0])) {
                seenUuids.add(uuidM[0]);
                photos.push(src);
            }
        }

        results.push({ url, price, surf, rooms, chams, dpe, commune_raw, cp, type_bien, photos });
    }
    return JSON.stringify(results);
}
"""

_SL_DETAIL_JS = """
() => {
    const text = document.body.innerText || '';

    // Surface terrain : "300 m² de terrain", "Terrain : 300 m²", "Surface du terrain 300 m²"
    const terrainM = text.match(/(\\d[\\d\\s]{0,6})\\s*m[²2]\\s*(de\\s*)?terrain/i)
                  || text.match(/terrain\\s*[:\\-]?\\s*(\\d[\\d\\s]{0,6})\\s*m[²2]/i)
                  || text.match(/surface\\s+d[ue]\\s+terrain\\s*[:\\-]?\\s*(\\d[\\d\\s]{0,6})\\s*m[²2]/i);
    const terrain = terrainM ? parseInt(terrainM[1].replace(/\\s/g,''), 10) : 0;

    // Surface Loi Carrez : "123,75 m² Loi Carrez", "Loi Carrez : 123,75 m²", "Surface habitable 123,75 m²"
    const carrezM = text.match(/(\\d+[,.]\\d+|\\d+)\\s*m[²2]\\s*(loi\\s+)?carrez/i)
                 || text.match(/(?:loi\\s+)?carrez\\s*[:\\-]?\\s*(\\d+[,.]\\d+|\\d+)\\s*m[²2]/i)
                 || text.match(/surface\\s+(?:habitable|loi carrez)\\s*[:\\-]?\\s*(\\d+[,.]\\d+|\\d+)\\s*m[²2]/i);
    const carrez_raw = carrezM ? (carrezM[1] || carrezM[2] || '').replace(',', '.') : '';
    const carrez = carrez_raw ? parseFloat(carrez_raw) : 0;

    // Titre : h1 ou balise title
    const titre = (document.querySelector('h1') || {}).innerText || document.title || '';

    // Description : premier grand paragraphe
    let desc = '';
    for (const p of document.querySelectorAll('p,[class*="description"],[class*="Description"]')) {
        const t = (p.innerText || '').trim();
        if (t.length > 100) { desc = t.slice(0, 800); break; }
    }

    return JSON.stringify({ terrain, carrez, titre: titre.trim().slice(0, 120), desc });
}
"""

async def _sl_fetch_detail(tab, url: str) -> dict:
    """Visite la page détail SeLoger et extrait terrain + titre + description."""
    try:
        await tab.get(url)
        # Attendre le rendu React (innerText > 300 = contenu visible, pas juste le shell HTML)
        for _ in range(15):
            await asyncio.sleep(1)
            body_text_len = await tab.evaluate("document.body.innerText.length")
            if body_text_len > 300:
                break
        # Scroll pour déclencher lazy-load des caractéristiques
        for y in [600, 1400]:
            await tab.evaluate(f"window.scrollTo(0, {y})")
            await asyncio.sleep(0.6)
        await asyncio.sleep(random.uniform(0.5, 1.0))
        raw = await tab.evaluate(f"({_SL_DETAIL_JS})()")
        return json.loads(raw)
    except Exception as e:
        log.debug(f"SeLoger detail {url[-30:]}: {e}")
        return {"terrain": 0, "titre": "", "desc": ""}


async def scrape_seloger_nodriver() -> list:
    """Scrape SeLoger via nodriver (DataDome bypass). Sans Playwright, sans session.
    Phase 1 : SERP — collecte apparts + URLs maisons.
    Phase 2 : détail — visite chaque maison pour récupérer surf_terrain.
               Maisons sans terrain → exclues.
    """
    import nodriver as uc

    results = []
    maison_pending: list[dict] = []   # maisons à enrichir (détail)
    log.info("SeLoger (nodriver): démarrage…")

    browser = await uc.start(
        headless=False,
        browser_args=["--window-size=1366,768", "--lang=fr-FR", "--no-sandbox"],
    )
    try:
        # Warmup homepage : établit cookies + contourne DataDome
        # (headless=True donne body=0 — DataDome bloque Chrome headless)
        log.info("SeLoger: warmup homepage…")
        tab = await browser.get("https://www.seloger.com/")
        await asyncio.sleep(6)
        await tab.evaluate("""
            for (const b of document.querySelectorAll('button,a')) {
                if (b.innerText && b.innerText.includes('Continuer sans')) {
                    b.click(); break;
                }
            }
        """)
        await asyncio.sleep(2)

        seen_urls: set[str] = set()
        rgpd_dismissed = True   # déjà fait sur homepage

        # ── Phase 1 : SERP ────────────────────────────────────────────────────
        for base_url, type_bien in SL_ND_SEARCHES:
            log.info(f"SeLoger SERP: {type_bien} — {base_url[-55:]}")

            for page_num in range(1, 10):
                nav_url = base_url if page_num == 1 else f"{base_url}&page={page_num}"
                try:
                    await tab.get(nav_url)
                except Exception as e:
                    log.warning(f"SeLoger nav: {e}")
                    break

                # Attendre le rendu React (innerText = contenu visible)
                for _ in range(15):
                    await asyncio.sleep(1)
                    body_len = await tab.evaluate("document.body.innerText.length")
                    if body_len > 500:
                        break
                await asyncio.sleep(random.uniform(1.0, 2.0))

                # Détecte le throttling SeLoger ("La recherche est temporairement indisponible")
                page_text = await tab.evaluate("document.body.innerText.slice(0, 400)")
                if "temporairement indisponible" in (page_text or "").lower() or \
                   "trop de requ" in (page_text or "").lower():
                    log.warning(f"SeLoger throttled sur page {page_num} — pause 90s…")
                    await asyncio.sleep(90)
                    # Une seule tentative après la pause
                    await tab.get(nav_url)
                    for _ in range(20):
                        await asyncio.sleep(1)
                        body_len = await tab.evaluate("document.body.innerText.length")
                        if body_len > 500:
                            break

                if not rgpd_dismissed:
                    await tab.evaluate("""
                        for (const b of document.querySelectorAll('button,a')) {
                            if (b.innerText && b.innerText.includes('Continuer sans')) {
                                b.click(); break;
                            }
                        }
                    """)
                    await asyncio.sleep(1.5)
                    rgpd_dismissed = True

                for y in [400, 900, 1500, 2200]:
                    await tab.evaluate(f"window.scrollTo(0, {y})")
                    await asyncio.sleep(random.uniform(0.5, 1.0))

                raw = await tab.evaluate(f"({_SL_EXTRACT_JS})('{type_bien}')")
                try:
                    items = json.loads(raw)
                except Exception:
                    items = []

                new_on_page = 0
                for item in items:
                    url = item.get("url", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)

                    commune_url  = _commune_from_sl_url(url)
                    commune_text = norm_commune(_clean_sl_commune(item.get("commune_raw", "")))
                    commune = commune_url or commune_text
                    if commune not in _SL_TARGET_COMMUNES:
                        continue

                    tb = item.get("type_bien", type_bien)
                    base = {
                        "source": "seloger", "url": url,
                        "type_bien": tb, "commune": commune,
                        "code_postal": item.get("cp", ""),
                        "adresse_raw": item.get("commune_raw", ""),
                        "prix": item["price"], "surface": item["surf"],
                        "pieces": item.get("rooms") or 0,
                        "chambres": item.get("chams") or 0,
                        "dpe": item.get("dpe") or "",
                        "photos": item.get("photos", []),
                        "_section": _section_from_sl_url(url),
                    }

                    if tb == "maison":
                        maison_pending.append(base)
                    else:
                        # Apparts : AVM immédiate, pas besoin de détail
                        section = base.pop("_section")
                        pred, ratio, score, model_tag = avm_score(
                            base["prix"], base["surface"], commune, 0.0, tb,
                            section=section,
                        )
                        results.append({**base, "titre": "", "surf_terrain": 0.0,
                                        "description": "",
                                        "avm_pred": pred, "avm_ratio": ratio,
                                        "avm_score": score, "avm_model": model_tag})
                    new_on_page += 1

                log.info(f"  SeLoger SERP p{page_num}: {len(items)} extraits, {new_on_page} nouveaux")
                if new_on_page == 0:
                    break

                await asyncio.sleep(random.uniform(2, 4))

        # ── Phase 2 : détail maisons ──────────────────────────────────────────
        log.info(f"SeLoger détail: {len(maison_pending)} maisons à enrichir…")
        kept = 0
        for m in maison_pending:
            detail = await _sl_fetch_detail(tab, m["url"])
            terrain = detail.get("terrain") or 0
            if not terrain:
                log.debug(f"  Maison sans terrain → exclue: {m['url'][-50:]}")
                continue
            section = m.pop("_section")
            pred, ratio, score, model_tag = avm_score(
                m["prix"], m["surface"], m["commune"], float(terrain),
                m["type_bien"], section=section,
            )
            results.append({
                **m,
                "titre":        detail.get("titre", "")[:120],
                "surf_terrain": float(terrain),
                "description":  detail.get("desc", "")[:400],
                "avm_pred": pred, "avm_ratio": ratio,
                "avm_score": score, "avm_model": model_tag,
            })
            kept += 1
            log.info(f"  Maison {kept}: terrain={terrain}m² {m['url'][-45:]}")
            await asyncio.sleep(random.uniform(1.5, 3.0))

        log.info(f"SeLoger maisons: {kept}/{len(maison_pending)} avec terrain")

        # ── Phase 2.5 : descriptions appartements ─────────────────────────────
        # Visite la page détail de chaque appartement collecté sans description.
        # La description est la source la plus fiable pour détecter le quartier —
        # les slugs URL SeLoger peuvent être périmés ou génériques.
        apparts_no_desc = [
            r for r in results
            if r.get("type_bien") == "appartement" and not (r.get("description") or "").strip()
        ]

        if apparts_no_desc:
            log.info(f"SeLoger desc apparts: {len(apparts_no_desc)} à enrichir…")
            for ap in apparts_no_desc:
                try:
                    detail = await _sl_fetch_detail(tab, ap["url"])
                    desc = (detail.get("desc") or "").strip()
                    if desc:
                        ap["description"] = desc[:400]
                        log.info(f"  desc OK: {desc[:60]}… [{ap['url'][-35:]}]")
                    else:
                        log.debug(f"  desc vide [{ap['url'][-35:]}]")
                    await asyncio.sleep(random.uniform(1.5, 2.5))
                except Exception as e_d:
                    log.warning(f"  desc error: {e_d}")
            log.info(f"SeLoger desc apparts: enrichissement terminé")

    except Exception as e:
        log.error(f"scrape_seloger_nodriver: {e}", exc_info=True)
    finally:
        browser.stop()

    log.info(f"SeLoger total: {len(results)} listings")
    return results


# ── Bien'ici ──────────────────────────────────────────────────────────────────
# Bien'ici — Utilise l'API interne /realEstateAds.json via fetch() côté navigateur.
# Plus fiable que DOM scraping : le SPA React bloque domcontentloaded en headless.
# Le slug city= correspond à celui de l'URL publique (ex: chamonix-mont-blanc).
BIENICI_API_SEARCHES = [
    # Format slug: {city}-{cp} — correspond à l'URL /recherche/achat/{city}-{cp}
    ("chamonix-mont-blanc-74400",     ["house"],  "maison"),
    ("chamonix-mont-blanc-74400",     ["flat"],   "appartement"),
    ("les-houches-74310",             ["house"],  "maison"),
    ("saint-gervais-les-bains-74170", ["house"],  "maison"),
    ("sallanches-74700",              ["house"],  "maison"),
    ("sallanches-74700",              ["flat"],   "appartement"),
    ("servoz-74310",                  ["house"],  "maison"),
    ("passy-74190",                   ["house"],  "maison"),
]

async def scrape_bienici(page: Page) -> list:
    """
    Scrape Bien'ici via l'API interne /realEstateAds.json.
    On navigue une fois sur le site (wait='commit') pour initialiser les cookies,
    puis on appelle l'API JSON directement via fetch() — même origine, pas de CORS.
    Beaucoup plus fiable que le DOM scraping en headless.
    """
    results = []

    # Init : aller sur Bien'ici juste pour poser les cookies
    log.info("Bien'ici: init cookies...")
    ok = await safe_goto(
        page,
        "https://www.bienici.com/recherche/vente?filterType=buy&propertyType=house&city=chamonix-mont-blanc",
        wait="commit",
    )
    if not ok:
        log.error("Bien'ici: impossible de joindre le site")
        return results
    await asyncio.sleep(5)
    await dismiss_cookies(page)
    await human_delay(800, 1500)

    for city_slug, prop_types, type_bien in BIENICI_API_SEARCHES:
        log.info(f"Bien'ici API: {city_slug} / {prop_types}")

        page_from = 0
        page_num  = 1
        per_page  = 24

        while True:
            filters = {
                "filterType":   "buy",
                "propertyType": prop_types,
                "city":         city_slug,
                "size":         per_page,
                "from":         page_from,
                "sortMethod":   "updatedAt",
            }

            # Appel API via fetch() — same-origin → cookies inclus automatiquement
            resp = await page.evaluate("""
                async (filters) => {
                    try {
                        const qs = encodeURIComponent(JSON.stringify(filters));
                        const r  = await fetch('/realEstateAds.json?filters=' + qs, {
                            headers: {
                                'Accept':           'application/json, text/plain, */*',
                                'X-Requested-With': 'XMLHttpRequest',
                                'Referer':          'https://www.bienici.com/recherche/vente',
                            },
                            credentials: 'include',
                        });
                        if (!r.ok) return { error: r.status, items: [], total: 0 };
                        const d = await r.json();
                        return {
                            items: d.realEstateAds || [],
                            total: d.total || d.realEstateAdsCount || 0,
                        };
                    } catch (e) {
                        return { error: String(e), items: [], total: 0 };
                    }
                }
            """, filters)

            if resp.get("error"):
                log.warning(f"BienIci API {city_slug}: erreur {resp['error']}")
                break

            items = resp.get("items", [])
            total = resp.get("total") or len(items)

            for item in items:
                # Prix — peut être int, float, ou dict {"value": ..., "currency": "EUR"}
                prix_raw = item.get("price")
                if isinstance(prix_raw, dict):
                    prix = prix_raw.get("value") or prix_raw.get("amount")
                elif isinstance(prix_raw, (int, float)):
                    prix = int(prix_raw)
                else:
                    prix = parse_price(str(prix_raw or ""))

                # Surface — API peut retourner une liste [bati, terrain] ou un nombre
                surface = item.get("surfaceArea") or item.get("surface")
                if isinstance(surface, list):
                    surface = surface[0] if surface else None
                if isinstance(surface, str):
                    surface = parse_surface(surface)
                surf_ter = item.get("landSurface") or item.get("landSurfaceArea") or 0
                if isinstance(surf_ter, list):
                    surf_ter = surf_ter[0] if surf_ter else 0
                if isinstance(surf_ter, str):
                    surf_ter = parse_surface(surf_ter) or 0

                commune = norm_commune(
                    item.get("city") or item.get("postalCode") or city_slug
                )

                # URL — peut être chemin relatif
                ad_url = item.get("url", "") or ""
                if ad_url and not ad_url.startswith("http"):
                    ad_url = "https://www.bienici.com" + ad_url
                if not ad_url and item.get("id"):
                    ad_url = f"https://www.bienici.com/annonce/{item['id']}"

                # Filtre: prix=1 = "prix sur demande" sur Bien'ici (placeholder)
                if not prix or prix < 1000 or not surface:
                    continue

                pred, ratio, score, model_tag = avm_score(
                    prix, float(surface), commune, float(surf_ter or 0), type_bien
                )

                # Photos — liste de dicts {"url": ...} ou de strings
                photos_raw = item.get("photos") or item.get("images") or []
                photos = []
                for ph in photos_raw[:5]:
                    if isinstance(ph, dict):
                        photos.append(ph.get("url") or ph.get("large_url") or "")
                    else:
                        photos.append(str(ph))

                results.append({
                    "source":       "bienici",
                    "url":          ad_url,
                    "titre":        str(item.get("title") or item.get("description") or "")[:100],
                    "type_bien":    type_bien,
                    "commune":      commune,
                    "code_postal":  str(item.get("postalCode") or ""),
                    "adresse_raw":  str(item.get("city") or commune),
                    "prix":         prix,
                    "surface":      float(surface),
                    "surf_terrain": float(surf_ter or 0),
                    "pieces":       int((item.get("roomsQuantity")    or 0) if not isinstance(item.get("roomsQuantity"),    list) else (item.get("roomsQuantity",    [0])[0] or 0)),
                    "chambres":     int((item.get("bedroomsQuantity") or 0) if not isinstance(item.get("bedroomsQuantity"), list) else (item.get("bedroomsQuantity", [0])[0] or 0)),
                    "dpe":          str(item.get("energyClassification") or ""),
                    "description":  str(item.get("description") or "")[:400],
                    "photos":       photos,
                    "avm_pred":     pred,
                    "avm_ratio":    ratio,
                    "avm_score":    score,
                    "avm_model":    model_tag,
                })

            log.info(f"  BienIci API {city_slug}/{type_bien} p{page_num}: "
                     f"{len(items)} items / {total} total")

            page_from += per_page
            page_num  += 1
            if page_from >= total or len(items) < per_page or page_num > 15:
                break

            await human_delay(1500, 3500)

        await human_delay(1000, 2500)

    return results


# ══════════════════════════════════════════════════════════════════════════════
# DÉDUP + STORE
# ══════════════════════════════════════════════════════════════════════════════
def dedup_listings(listings: list) -> list:
    """
    Déduplication cross-source.
    Critère : même (commune, surface ±5%, prix ±3%) = doublon.
    Priorité : seloger > bienici (agences > portails).
    """
    priority = {"seloger": 0, "bienici": 1}
    unique   = {}

    for lst in sorted(listings, key=lambda x: priority.get(x.get("source",""), 9)):
        if not lst.get("prix"):
            continue
        # Maisons sans terrain : blacklistées partout
        if lst.get("type_bien") == "maison" and not (lst.get("surf_terrain") or 0):
            continue
        p = lst["prix"]
        s = lst.get("surface") or 0
        c = lst.get("commune","")

        # Clé de dédup: commune + surface bucket + prix bucket
        s_bucket = round(s / 5) * 5 if s else 0   # 0 si surface inconnue
        p_bucket = round(p / 10000)                 # arrondi 10k€
        key = f"{c}|{s_bucket}|{p_bucket}"

        if key not in unique:
            unique[key] = lst
        else:
            # Garde celui avec la source prioritaire (+ infos)
            existing_prio = priority.get(unique[key].get("source",""), 9)
            new_prio      = priority.get(lst.get("source",""), 9)
            if new_prio < existing_prio:
                unique[key] = lst

    result = list(unique.values())
    log.info(f"Dédup: {len(listings)} → {len(result)} listings uniques")
    return result

def store_listings(listings: list) -> dict:
    """Upsert dans DB. Retourne stats."""
    con  = get_db()
    now  = date.today().isoformat()
    new  = 0
    upd  = 0

    for lst in listings:
        # Maisons sans terrain : jamais stockées
        if lst.get("type_bien") == "maison" and not (lst.get("surf_terrain") or 0):
            continue

        lid = listing_id(lst["source"], lst["url"])
        existing = con.execute(
            "SELECT prix, first_seen, nb_baisses FROM listings WHERE id=?", (lid,)
        ).fetchone()

        prix = lst.get("prix")
        if existing:
            old_prix, first_seen, nb_baisses = existing
            nb_baisses = (nb_baisses or 0)
            if prix and old_prix and prix < old_prix:
                nb_baisses += 1
            jours = (date.fromisoformat(now) - date.fromisoformat(first_seen)).days
            new_desc = (lst.get("description") or "").strip()
            con.execute("""
                UPDATE listings SET last_seen=?, prix=?, jours_marche=?,
                    nb_baisses=?, active=1, avm_pred=?, avm_ratio=?, avm_score=?, avm_model=?,
                    description=CASE WHEN (description IS NULL OR description='') AND ? != ''
                                     THEN ? ELSE description END
                WHERE id=?
            """, (now, prix or old_prix, jours, nb_baisses,
                  lst.get("avm_pred"), lst.get("avm_ratio"), lst.get("avm_score"),
                  lst.get("avm_model"), new_desc, new_desc, lid))
            upd += 1
        else:
            con.execute("""
                INSERT OR IGNORE INTO listings (
                    id, source, url, titre, type_bien, commune, code_postal,
                    adresse_raw, prix, surface, surf_terrain, pieces, chambres,
                    dpe, description, photos_json,
                    avm_pred, avm_ratio, avm_score, avm_model,
                    first_seen, last_seen, jours_marche, prix_initial, nb_baisses, active
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,0,1)
            """, (lid, lst["source"], lst["url"], lst.get("titre"),
                  lst.get("type_bien"), lst.get("commune"), lst.get("code_postal"),
                  lst.get("adresse_raw"), prix, lst.get("surface"), lst.get("surf_terrain"),
                  lst.get("pieces"), lst.get("chambres"), lst.get("dpe"),
                  lst.get("description"), json.dumps(lst.get("photos",[])),
                  lst.get("avm_pred"), lst.get("avm_ratio"), lst.get("avm_score"),
                  lst.get("avm_model"), now, now, prix))
            if prix:
                con.execute("INSERT OR IGNORE INTO prix_history VALUES (?,?,?)", (lid, now, prix))
            new += 1

    # Marquer inactifs les vieux non-vus (>45j)
    con.execute("""
        UPDATE listings SET active=0
        WHERE active=1 AND last_seen < date('now', '-45 days')
    """)

    con.commit()
    con.close()
    return {"new": new, "updated": upd, "total": new + upd}

def print_summary(listings: list):
    """Affiche résumé + top opportunités."""
    from collections import defaultdict
    by_source = defaultdict(int)
    by_commune = defaultdict(int)
    opps = []

    for l in listings:
        by_source[l.get("source","?")] += 1
        by_commune[l.get("commune","?")] += 1
        if (l.get("avm_score") or 0) >= 70:
            opps.append(l)

    print(f"\n{'═'*70}")
    print(f"  RÉSULTAT SCRAPING — {date.today()} — {len(listings)} listings uniques")
    print(f"{'═'*70}")
    print("\nPar source :")
    for s, n in sorted(by_source.items()): print(f"  {s:<12} {n:>4}")
    print("\nPar commune :")
    for c, n in sorted(by_commune.items(), key=lambda x:-x[1]):
        print(f"  {c:<30} {n:>4}")

    opps.sort(key=lambda x: (x.get("avm_ratio") or 99))
    if opps:
        print(f"\n{'─'*70}")
        print(f"  TOP OPPORTUNITÉS ({len(opps)} listings score ≥ 70)")
        print(f"{'─'*70}")
        for o in opps[:15]:
            print(f"  [{o.get('avm_score',0):>3}] ratio={o.get('avm_ratio',0):.2f}  "
                  f"{o.get('source'):<10} {o.get('commune',''):<28}  "
                  f"{o.get('prix',0):>10,}€  {o.get('surface',0):.0f}m²")
            print(f"       {o.get('url','')}")

# ══════════════════════════════════════════════════════════════════════════════
# ORCHESTRATION PLAYWRIGHT
# ══════════════════════════════════════════════════════════════════════════════
# SeLoger utilise nodriver (appel direct dans run_scraping) — pas de session Playwright
SCRAPERS_PLAYWRIGHT = {
    "bienici": scrape_bienici,
}

LOGIN_URLS = {
    "bienici": "https://www.bienici.com/connexion",
}

def make_context_opts():
    return dict(
        viewport={"width": 1366, "height": 768},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        locale="fr-FR", timezone_id="Europe/Paris",
        extra_http_headers={
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
            "Sec-CH-UA": '"Google Chrome";v="125", "Chromium";v="125"',
            "Sec-CH-UA-Platform": '"Windows"',
        }
    )

ANTI_BOT_SCRIPT = """
    Object.defineProperty(navigator, 'webdriver', { get: () => false });
    Object.defineProperty(navigator, 'plugins',   { get: () => [1,2,3,4,5] });
    window.chrome = { runtime: {} };
"""

async def run_setup(source: str):
    """Bien'ici : Google OAuth manuel. SeLoger utilise nodriver (pas de session nécessaire)."""
    if source == "seloger":
        print("SeLoger utilise nodriver — aucun setup nécessaire.")
        return
    async with async_playwright() as pw:
        # Firefox pour setup : meilleure compatibilite OAuth / DataDome
        try:
            browser = await pw.firefox.launch(headless=False, slow_mo=60)
        except Exception:
            browser = await pw.chromium.launch(headless=False, slow_mo=60)
        context = await browser.new_context(**make_context_opts())
        await context.add_init_script(ANTI_BOT_SCRIPT)
        page = await context.new_page()

        print(f"\n{'═'*60}")
        print(f"  SETUP {source.upper()} — Connexion avec Google")
        print(f"{'═'*60}")
        print(f"  Browser ouvert → clique 'Continuer avec Google'")
        print(f"  Compte : <ALERT_EMAIL>")
        print(f"  Une fois connecté → Entrée ici\n")
        await page.goto(LOGIN_URLS[source], timeout=30000)
        await human_delay(1500, 3000)
        for sel in ["button:has-text('Google')", "a:has-text('Google')",
                    "[data-provider='google']", "button:has-text('Continuer avec Google')"]:
            btn = await page.query_selector(sel)
            if btn:
                await btn.click(); await human_delay(2000, 3000); break
        input("  [Complète la connexion → Entrée] ")

        await save_session(context, source)
        print(f"\n✓ Session {source} sauvée → {session_path(source)}")
        await browser.close()

async def run_scraping(sources: list, headless=True, dry_run=False):
    """Run principal overnight. SeLoger=nodriver, Bienici=Playwright."""
    all_listings = []

    # ── SeLoger via nodriver (DataDome bypass, pas de session) ───────────────
    if "seloger" in sources:
        log.info(f"\n{'─'*60}\n  SELOGER (nodriver)\n{'─'*60}")
        try:
            sl_listings = await scrape_seloger_nodriver()
            log.info(f"SeLoger: {len(sl_listings)} listings")
            all_listings.extend(sl_listings)
        except Exception as e:
            log.error(f"SeLoger nodriver error: {e}", exc_info=True)
        await asyncio.sleep(random.uniform(5, 12))

    # ── Autres sources via Playwright ─────────────────────────────────────────
    playwright_sources = [s for s in sources if s in SCRAPERS_PLAYWRIGHT]
    if playwright_sources:
        async with async_playwright() as pw:
            for source in playwright_sources:
                scrape_fn = SCRAPERS_PLAYWRIGHT[source]
                log.info(f"\n{'─'*60}\n  {source.upper()}\n{'─'*60}")

                browser = await pw.chromium.launch(
                    headless=headless,
                    slow_mo=random.randint(30, 80),
                    args=["--disable-blink-features=AutomationControlled",
                          "--no-sandbox", "--disable-setuid-sandbox"]
                )
                context = await browser.new_context(**make_context_opts())
                await context.add_init_script(ANTI_BOT_SCRIPT)

                session_ok = await load_session(context, source)
                if not session_ok:
                    log.warning(f"{source}: pas de session — lance --setup d'abord")

                page = await context.new_page()
                try:
                    listings = await scrape_fn(page)
                    log.info(f"{source}: {len(listings)} listings")
                    all_listings.extend(listings)
                except Exception as e:
                    log.error(f"{source} error: {e}", exc_info=True)
                finally:
                    await browser.close()

                await asyncio.sleep(random.uniform(8, 20))

    unique = dedup_listings(all_listings)
    RAW_OUT.parent.mkdir(exist_ok=True)
    RAW_OUT.write_text(json.dumps(unique, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"JSON: {RAW_OUT}  ({len(unique)} listings)")

    if not dry_run:
        stats = store_listings(unique)
        log.info(f"DB: +{stats['new']} nouveaux  ~{stats['updated']} mis à jour")
    else:
        log.info("DRY-RUN: pas de stockage")

    print_summary(unique)
    return unique

# ══════════════════════════════════════════════════════════════════════════════
# MODE TEST — 1 annonce par source pour vérifier que le bot tourne
# ══════════════════════════════════════════════════════════════════════════════
TEST_URLS = {
    # URLs confirmées par l'utilisateur (format exact que SeLoger/Bien'ici/PAP utilisent)
    # SeLoger — classified-search (nouveau format, remplace list.htm)
    # POCOFR4764 = code interne SeLoger pour Chamonix-Mont-Blanc
    "seloger": ("https://www.seloger.com/classified-search?distributionTypes=Buy"
                "&estateTypes=House,Apartment&locations=POCOFR4764",
                "[class*='CardList'] li, [class*='card'], article, "
                "[class*='classified'] article, [class*='Classified'] li", "seloger"),
    # Bien'ici — API mode (wait_sel=None → appel /realEstateAds.json)
    "bienici": ("https://www.bienici.com/recherche/achat/chamonix-mont-blanc-74400",
                None, "bienici"),
}

async def run_test(sources: list):
    """
    Ouvre 1 page par source, récupère les données brutes,
    affiche ce qu'on trouve. But = vérifier que le bot n'est pas bloqué
    et que les sélecteurs fonctionnent.
    """
    print(f"\n{'═'*65}")
    print(f"  TEST MODE — 1 page Chamonix par source")
    print(f"{'═'*65}\n")

    results = {}

    async with async_playwright() as pw:
        for source in sources:
            if source not in TEST_URLS:
                continue

            url, wait_sel, src_name = TEST_URLS[source]
            print(f"  [{source.upper()}] {url[:70]}...")

            # SeLoger : non-headless obligatoire (DataDome détecte headless)
            _headless = (source != "seloger")
            browser = await pw.chromium.launch(
                headless=_headless,
                slow_mo=50,
                args=["--disable-blink-features=AutomationControlled",
                      "--no-sandbox"]
            )
            context = await browser.new_context(**make_context_opts())
            await context.add_init_script(ANTI_BOT_SCRIPT)

            # Charger session si dispo (meilleur taux de succès avec compte)
            await load_session(context, source)

            page = await context.new_page()
            status = "❌ ÉCHEC"
            found  = []

            try:
                # Bien'ici : wait='commit' (domcontentloaded ne fire pas en headless sur ce SPA)
                wait_mode = "commit" if source == "bienici" else "domcontentloaded"
                ok = await safe_goto(page, url, wait=wait_mode)
                if not ok:
                    print(f"  → Navigation échouée\n")
                    results[source] = {"status": "nav_failed", "listings": []}
                    await browser.close()
                    continue

                if source == "bienici":
                    # Bien'ici API mode : pas besoin d'attendre le DOM — on appelle l'API JSON
                    await asyncio.sleep(3)
                    await dismiss_cookies(page)
                else:
                    # Attendre les résultats DOM pour pap/seloger
                    try:
                        await page.wait_for_selector(wait_sel, timeout=15000)
                        status = "✓ PAGE OK"
                    except Exception:
                        title = await page.title()
                        body_text = (await page.evaluate("document.body.innerText"))[:500]
                        print(f"  → Pas de sélecteur trouvé. Titre: {title}")
                        print(f"  → Contenu: {body_text[:200]}")
                        results[source] = {"status": "no_selector", "title": title}
                        await browser.close()
                        continue

                # Scroll humain + lecture (sauf bienici qui n'a pas de DOM à lire)
                if source != "bienici":
                    await human_read_page(page)

                # Extraire selon la source
                if source == "pap":
                    raw = await page.evaluate("""
                        () => {
                            // Sélecteurs confirmés par inspection DOM
                            const cards = document.querySelectorAll(
                                '.search-list-item-alt, .search-list-item'
                            );
                            return Array.from(cards).slice(0,5).map(c => {
                                const link    = c.querySelector("a[href*='/annonces/']");
                                const priceEl = c.querySelector(".item-price, [class*='price']");
                                const imgEl   = c.querySelector("img[alt]");
                                const locEl   = c.querySelector(".item-localisation, [class*='localisa']");
                                const loc     = locEl ? locEl.innerText.trim()
                                                      : (imgEl ? imgEl.alt.trim() : "");
                                const href    = link ? link.getAttribute("href") : "";
                                const cpMatch = href.match(/-(\d{5})-r\d+/) || loc.match(/\((\d{5})\)/);
                                // Surface dans critères
                                const crits = c.querySelectorAll(".item-criteria li, [class*='criteria'] li");
                                const critStr = Array.from(crits).map(e => e.innerText.trim()).join(" | ");
                                return {
                                    url:   href ? "https://www.pap.fr" + href : "",
                                    prix:  priceEl ? priceEl.innerText.trim() : "",
                                    surf:  critStr,
                                    titre: "",
                                    loc:   loc,
                                    cp:    cpMatch ? cpMatch[1] : "",
                                };
                            }).filter(i => i.prix);
                        }
                    """)
                    for r in raw:
                        if r.get("prix"):
                            found.append(r)

                elif source == "seloger":
                    raw_json = await page.evaluate("""
                        () => {
                            // Essai 1 : __NEXT_DATA__ (classified-search)
                            const nd = document.getElementById('__NEXT_DATA__');
                            if (nd) {
                                try {
                                    const data = JSON.parse(nd.textContent);
                                    const pp   = data?.props?.pageProps;
                                    const ads  = pp?.classifieds || pp?.ads || pp?.results
                                              || pp?.initialData?.classifieds || pp?.initialData?.ads || [];
                                    if (ads.length) return ads.slice(0,5).map(a => ({
                                        classifiedURL: a.classifiedURL || a.url || '',
                                        title:   a.publicationTitle || a.title || '',
                                        price:   String(a.price?.publicPrice || a.price || ''),
                                        surface: String(a.surface || a.livingArea || ''),
                                        cityLabel: a.cityLabel || a.city || '',
                                    }));
                                } catch {}
                            }
                            // Essai 2 : __REDIAL_PROPS__ (list.htm)
                            for (const sc of document.querySelectorAll('script')) {
                                const t = sc.textContent || '';
                                if (t.includes('classifiedURL')) {
                                    const m = t.match(/window\.__REDIAL_PROPS__\s*=\s*(\[.*?\]);/s);
                                    if (m) {
                                        try {
                                            const props = JSON.parse(m[1]);
                                            for (const p of props) {
                                                if (p?.cards?.list?.length) return p.cards.list.slice(0,5);
                                            }
                                        } catch {}
                                    }
                                }
                            }
                            // Essai 3 : DOM
                            const items = document.querySelectorAll(
                                '[class*="CardList"] li, article[class*="classified"], article[class*="Classified"]'
                            );
                            return Array.from(items).slice(0,5).map(el => ({
                                title: (el.querySelector('[class*="title"],h2,h3') || {}).innerText || '',
                                price: (el.querySelector('[class*="price"]') || {}).innerText || '',
                                surface: (el.querySelector('[class*="surface"]') || {}).innerText || '',
                                classifiedURL: (el.querySelector('a[href*="seloger"]') || {}).href || '',
                            }));
                        }
                    """)
                    for r in (raw_json or []):
                        if r.get("price") or r.get("prix"):
                            found.append({
                                "url":   r.get("classifiedURL",""),
                                "prix":  r.get("price","") or r.get("prix",""),
                                "surf":  r.get("surface",""),
                                "titre": r.get("title","") or r.get("subject",""),
                                "loc":   r.get("cityLabel",""),
                            })

                elif source == "bienici":
                    # API interne — plus fiable que DOM scraping en headless
                    resp_api = await page.evaluate("""
                        async (filters) => {
                            try {
                                const qs = encodeURIComponent(JSON.stringify(filters));
                                const r  = await fetch('/realEstateAds.json?filters=' + qs, {
                                    headers: {
                                        'Accept':           'application/json, text/plain, */*',
                                        'X-Requested-With': 'XMLHttpRequest',
                                        'Referer':          'https://www.bienici.com/recherche/vente',
                                    },
                                    credentials: 'include',
                                });
                                if (!r.ok) return { error: r.status, items: [] };
                                const d = await r.json();
                                return { items: (d.realEstateAds || []).slice(0, 5), total: d.total || 0 };
                            } catch (e) {
                                return { error: String(e), items: [] };
                            }
                        }
                    """, {
                        "filterType": "buy", "propertyType": ["house"],
                        "city": "chamonix-mont-blanc", "size": 5, "from": 0,
                    })
                    if resp_api.get("error"):
                        log.warning(f"BienIci API test: {resp_api['error']}")
                    for r in (resp_api.get("items") or []):
                        prix_raw = r.get("price")
                        if isinstance(prix_raw, dict):
                            prix_val = prix_raw.get("value") or prix_raw.get("amount") or 0
                        elif isinstance(prix_raw, (int, float)):
                            prix_val = int(prix_raw)
                        else:
                            prix_val = parse_price(str(prix_raw or "")) or 0
                        if prix_val and prix_val >= 1000:  # filter prix sur demande
                            ad_url = r.get("url", "") or ""
                            if ad_url and not ad_url.startswith("http"):
                                ad_url = "https://www.bienici.com" + ad_url
                            # Surface: peut être float, list, ou string
                            surf_raw = r.get("surfaceArea", "?")
                            if isinstance(surf_raw, list):
                                surf_raw = surf_raw[0] if surf_raw else "?"
                            found.append({
                                "url":   ad_url or f"https://www.bienici.com/annonce/{r.get('id','')}",
                                "prix":  f"{prix_val:,} €",
                                "surf":  f"{surf_raw} m²",
                                "titre": str(r.get("title") or r.get("description") or "")[:50],
                                "loc":   str(r.get("city") or ""),
                            })
                    status = "✓ API OK"

                results[source] = {"status": "ok", "listings": found}

                # Prendre screenshot pour debug
                ss_path = BASE / f"test_{source}.png"
                await page.screenshot(path=str(ss_path), full_page=False)
                log.info(f"{source}: screenshot → {ss_path}")

            except Exception as e:
                log.error(f"Test {source}: {e}", exc_info=True)
                results[source] = {"status": f"error: {e}", "listings": []}
            finally:
                await browser.close()

            await asyncio.sleep(random.uniform(3, 6))

    # Rapport
    print(f"\n{'═'*65}")
    print(f"  RÉSULTAT TEST")
    print(f"{'═'*65}")
    all_ok = True
    for source, res in results.items():
        listings = res.get("listings", [])
        ok       = len(listings) > 0
        all_ok   = all_ok and ok
        icon     = "✅" if ok else "❌"
        print(f"\n  {icon} {source.upper():10} — {len(listings)} annonce(s) trouvée(s)  [{res['status']}]")
        for i, lst in enumerate(listings[:3], 1):
            prix  = lst.get("prix","").strip()[:20]
            surf  = lst.get("surf","").strip()[:15]
            titre = (lst.get("titre","") or "").strip()[:50]
            print(f"     #{i}  {prix:<22} {surf:<16} {titre}")
            if lst.get("url"):
                print(f"          {lst['url'][:75]}")

    print(f"\n{'─'*65}")
    if all_ok:
        print(f"  ✅ BOT FONCTIONNEL — toutes les sources répondent")
        print(f"  → Lance --setup pour sauver les sessions, puis --headless pour la nuit")
    else:
        failed = [s for s, r in results.items() if not r.get("listings")]
        print(f"  ⚠️  Sources KO : {', '.join(failed)}")
        print(f"  → Ouvre test_<source>.png pour voir ce que le bot voit")
    print()

    return results

# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bot overnight scraper immobilier")
    parser.add_argument("--test",     action="store_true",
                        help="Test rapide : 1 page Chamonix par source, vérifie que le bot fonctionne")
    parser.add_argument("--setup",    action="store_true",
                        help="Setup sessions (une fois). SeLoger/BienIci=Google OAuth manuel")
    ALL_SOURCES = ["seloger", "bienici"]
    parser.add_argument("--source",   nargs="+", choices=ALL_SOURCES,
                        help="Sources (défaut: seloger bienici)")
    parser.add_argument("--headless", action="store_true", default=False,
                        help="Mode sans fenêtre (prod / cron)")
    parser.add_argument("--dry-run",  action="store_true",
                        help="Scrape sans stocker en DB")
    parser.add_argument("--stats",    action="store_true",
                        help="Affiche stats DB sans scraper")
    parser.add_argument("--import-firefox", action="store_true",
                        help="Importe cookies depuis Firefox installé (Firefox doit être fermé)")
    args    = parser.parse_args()
    sources = args.source or ALL_SOURCES

    if args.test:
        asyncio.run(run_test(sources))

    elif args.stats:
        con  = get_db()
        rows = con.execute("""
            SELECT source, type_bien, COUNT(*) n,
                   ROUND(AVG(prix)) avg_p,
                   SUM(CASE WHEN avm_score>=70 THEN 1 ELSE 0 END) opps,
                   SUM(CASE WHEN nb_baisses>0  THEN 1 ELSE 0 END) baisses
            FROM listings WHERE active=1
            GROUP BY source, type_bien ORDER BY source, n DESC
        """).fetchall()
        print(f"\n{'Source':<12} {'Type':<14} {'N':>5} {'Prix moy':>12} {'Opport':>8} {'Baisses':>8}")
        print("─" * 65)
        for r in rows:
            print(f"{r[0]:<12} {r[1]:<14} {r[2]:>5} {int(r[3] or 0):>11,}€ {r[4]:>8} {r[5]:>8}")
        top = con.execute("""
            SELECT source, commune, type_bien, prix, surface, avm_ratio, avm_score, url
            FROM listings WHERE active=1 AND avm_score>=70
            ORDER BY avm_ratio ASC LIMIT 10
        """).fetchall()
        if top:
            print(f"\n{'─'*65}\nTOP 10 opportunités :\n{'─'*65}")
            for r in top:
                print(f"  [{r[6]:>3}] ratio={r[5]:.2f}  {r[0]:<10} {r[1]:<26} "
                      f"{r[3]:>10,}€  {r[4]:.0f}m²\n       {r[7]}")
        con.close()

    elif getattr(args, "import_firefox", False):
        for source in sources:
            import_firefox_cookies(source)

    elif args.setup:
        for source in sources:
            asyncio.run(run_setup(source))

    else:
        print(f"\n{'═'*60}")
        print(f"  BOT OVERNIGHT — {date.today()}")
        print(f"  Sources : {', '.join(sources)}")
        print(f"  Headless: {args.headless}  |  Dry-run: {args.dry_run}")
        print(f"  Output  : {RAW_OUT}")
        print(f"{'═'*60}\n")
        asyncio.run(run_scraping(sources, headless=args.headless, dry_run=args.dry_run))
