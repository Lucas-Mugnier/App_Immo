#!/usr/bin/env python3
"""
Appart Alert - Edition 2 semaines / Investissement locatif Alpes.
Email-first + fetch ONE-SHOT optionnel des candidates pour micro-opportunités.

Corrections v6:
- Résolution base64 des liens de tracking SeLoger (click.by/pro.seloger.com)
- Élimination des doublons URL directe + URL tracking
- Parsing LOCAL par URL (window 1000 chars)
- Filtre URLs strict
"""
import argparse
import base64  # ← AJOUTÉ
import email
import hashlib
import html
import imaplib
import json
import logging
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from email import policy
from email.message import EmailMessage
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable, Optional
from urllib.parse import parse_qs, unquote, urlparse

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ── Regex ───────────────────────────────────────────────────────────
URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.IGNORECASE)

# Prix : accepte espace/nbsp/ /point comme séparateur milliers
# ex: "150 000 €", "150.000€", "1 200 000 €"
PRICE_RE = re.compile(
    r"(?P<price>\d[\d   .]{2,12})\s*(?:€|eur(?:os?)?)",
    re.IGNORECASE
)

# Surface — multi-patterns (avec ou sans contexte)
SURFACE_RE = re.compile(
    r"(?:(?:superficie|surface\s+(?:habitable|loi\s+carrez|carrez|utile)|loi\s+carrez|carrez)\s*(?:[:,de\s]+)?)?"
    r"(?P<surface>\d{1,4}(?:[,\.]\d{1,2})?)"
    r"\s*(?:m\s*[²2]|m(?:etres?|ètres?)\s*carres?)",
    re.IGNORECASE
)
# Fallback : "surface habitable : 45" ou "superficie : 45" sans unité m²
SURFACE_CONTEXT_RE = re.compile(
    r"(?:surface\s+(?:habitable\s*)?|superficie)\s*[:=]?\s*(?P<surface>\d{1,4}(?:[,\.]\d{1,2})?)\s*(?!\d)",
    re.IGNORECASE
)

# Pièces — T2/T3/F2/F3/studio + "3 pièces" + "2P"
ROOMS_RE = re.compile(
    r"(?:"
    r"(?<![A-Za-z])(?:[TtFf])(?P<rooms_tf>[1-9])\b"  # T2, T3, F2…
    r"|(?P<studio>studio|studette)"                    # studio = 1 pièce
    r"|(?P<rooms>\d{1,2})\s*(?:pieces?|pièces?|p\.)(?!\w)"  # "3 pièces"
    r")",
    re.IGNORECASE
)
CHARGES_RE = re.compile(r"(?:quote-part|charges|budget\s+previsionnel)[^.\n]{0,80}?(?P<amount>\d[\d   .]{2,})\s*(?:€|eur|euros)\s*(?:/\s*(?:an|annuel))?", re.IGNORECASE)

# DPE / GES — formats SeLoger ("DPE : B"), LBC ("Classe A"), email standard
DPE_RE = re.compile(
    r"(?:classe\s+(?:energ[i\xe9]+\s+)?|dpe\s*:?\s*|etiquette\s+(?:dpe|energ\xe9tique)\s*:?\s*)"
    r"(?P<dpe>[A-G])(?![A-Za-z0-9])",
    re.IGNORECASE
)
GES_RE = re.compile(
    r"(?:classe\s+(?:climat\s+)?|ges\s*:?\s*|emission\s+ges?\s*:?\s*)"
    r"(?P<ges>[A-G])(?![A-Za-z0-9])",
    re.IGNORECASE
)
REFERENCE_RE = re.compile(r"r[ée]f[ée]rence\s*:?\s*(?P<ref>[A-Za-z0-9][A-Za-z0-9\- ]{1,40})", re.IGNORECASE)

# Bornes de validité
PRICE_MIN, PRICE_MAX = 10_000, 3_000_000
SURFACE_MIN, SURFACE_MAX = 9.0, 600.0

# ── Text utils ────────────────────────────────────────────────────────
class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        if data.strip():
            self.parts.append(data.strip())
    def handle_starttag(self, tag, attrs):
        if tag in {"br", "p", "div", "tr", "li"}:
            self.parts.append("\n")
        # Extraire les URLs des attributs href (emails HTML avec liens d'annonces en image)
        if tag == "a":
            for attr_name, attr_val in attrs:
                if attr_name == "href" and attr_val and attr_val.startswith("http"):
                    self.parts.append(f" {attr_val} ")
    def text(self):
        return _norm_space("\n".join(self.parts))

def _norm_space(value: str) -> str:
    value = html.unescape(value or "")
    value = value.replace("\u00a0", " ").replace("\u202f", " ")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()

def _strip_accents(value: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", value or "") if not unicodedata.combining(c))

def _searchable(value: str) -> str:
    v = _strip_accents(value).lower().replace("'", " ")
    v = re.sub(r"[^a-z0-9]+", " ", v)
    return re.sub(r"\s+", " ", v).strip()

def _extract_text(msg: EmailMessage) -> str:
    plain, html_parts = [], []
    for part in msg.walk():
        if part.is_multipart():
            continue
        ct = part.get_content_type()
        try:
            payload = part.get_content()
        except Exception:
            raw = part.get_payload(decode=True) or b""
            payload = raw.decode(part.get_content_charset() or "utf-8", errors="replace")
        if ct == "text/plain":
            plain.append(str(payload))
        elif ct == "text/html":
            parser = TextExtractor()
            parser.feed(str(payload))
            html_parts.append(parser.text())
    return _norm_space("\n\n".join(plain or html_parts))

# ── Parsing ───────────────────────────────────────────────────────────
def _parse_money(text: str) -> Optional[int]:
    digits = re.sub(r"\D", "", text or "")
    return int(digits) if digits else None

def parse_price(text: str) -> Optional[int]:
    for m in PRICE_RE.finditer(text):
        # Ignorer les montants précédés de "de " (ex: "baissé de 15 000 €" = variation)
        prefix = text[max(0, m.start() - 15):m.start()].lower()
        if re.search(r'\bde\s+$', prefix):
            continue
        val = _parse_money(m.group("price"))
        if val and PRICE_MIN <= val <= PRICE_MAX:
            return val
    return None

def parse_surface(text: str) -> Optional[float]:
    # Passe 1 : SURFACE_RE principal (nombre + unité m²/m2)
    for m in SURFACE_RE.finditer(text):
        try:
            val = float(m.group("surface").replace(",", "."))
            if SURFACE_MIN <= val <= SURFACE_MAX:
                return val
        except (ValueError, IndexError):
            continue
    # Passe 2 : contexte "surface habitable : 45" sans unité explicite
    m = SURFACE_CONTEXT_RE.search(text)
    if m:
        try:
            val = float(m.group("surface").replace(",", "."))
            if SURFACE_MIN <= val <= SURFACE_MAX:
                return val
        except (ValueError, IndexError):
            pass
    return None

def parse_rooms(text: str) -> Optional[int]:
    # Chercher tous les matches, retourner le plus cohérent (1-6)
    for m in ROOMS_RE.finditer(text):
        try:
            if m.group("studio"):
                return 1
            if m.group("rooms_tf") is not None:
                n = int(m.group("rooms_tf"))
                if 1 <= n <= 6:
                    return n
            if m.group("rooms") is not None:
                n = int(m.group("rooms"))
                if 1 <= n <= 8:
                    return n
        except (ValueError, IndexError):
            continue
    return None

def parse_charges(text: str) -> Optional[int]:
    m = CHARGES_RE.search(_strip_accents(text))
    if not m:
        return None
    amount = _parse_money(m.group("amount"))
    return amount if amount and 100 <= amount <= 30000 else None

def parse_dpe(text: str) -> str:
    m = DPE_RE.search(_strip_accents(text))
    return m.group("dpe").upper() if m else ""

def parse_ges(text: str) -> str:
    m = GES_RE.search(_strip_accents(text))
    return m.group("ges").upper() if m else ""

def extract_urls(text: str) -> list[str]:
    return URL_RE.findall(text)

# ── NOUVEAU : Résolution des liens de tracking ──────────────────────
def resolve_tracking_url(url: str) -> str:
    """
    Résout les liens de tracking encodés en base64url (SeLoger, Logic-Immo, etc.)
    Le paramètre 'qs' contient l'URL réelle encodée en base64url.
    """
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        
        # SeLoger / Logic-Immo : paramètre 'qs' en base64url (URL-safe avec - et _)
        if 'qs' in params and params['qs']:
            qs_data = params['qs'][0]
            # Padding base64 si nécessaire
            padding = 4 - len(qs_data) % 4
            if padding != 4:
                qs_data += '=' * padding
            
            try:
                decoded = base64.urlsafe_b64decode(qs_data).decode('utf-8', errors='replace')
                # Chercher une URL d'annonce dans le decoded
                candidates = URL_RE.findall(decoded)
                for cand in candidates:
                    # Vérifier que c'est un domaine immobilier connu
                    if any(d in cand.lower() for d in [
                        "seloger.com", "bienici.com", "leboncoin.fr", 
                        "logic-immo.com", "pap.fr", "fnaim.fr",
                        "green-acres.fr", "avendrealouer.fr", "paruvendu.fr",
                        "orpi.com", "laforet.com", "century21.fr",
                        "mountain-base.com", "immobilier.nestenn.com",
                        "coldwellbanker.fr", "engelvoelkers.com",
                        "sothebysrealty.com", "bellesdemeures.com"
                    ]):
                        # Nettoyer et retourner
                        return cand.rstrip(".,;]'")
            except Exception:
                pass  # Fallback ci-dessous
        
        # Fallback : paramètres classiques de redirect
        for key in ("url", "u", "redirect", "redirect_url", "target", "link"):
            if key in params and params[key]:
                cand = unquote(params[key][0])
                if cand.startswith("http"):
                    return cand.rstrip(".,;]'")
                    
    except Exception as e:
        logger.debug(f"Erreur résolution tracking {url[:60]}: {e}")
    
    return url


def clean_url(url: str) -> str:
    url = url.rstrip(".,;]'")
    
    # ← NOUVEAU : Si c'est un lien de tracking, le résoudre d'abord
    domain = urlparse(url).netloc.lower()
    if any(track in domain for track in ["click.by.seloger.com", "click.pro.seloger.com",
                                          "click.by.logic-immo.com", "redirection.bienici.com",
                                          "c.gle"]):
        resolved = resolve_tracking_url(url)
        if resolved != url:
            logger.debug(f"Tracking résolu (base64): {url[:60]}... -> {resolved[:60]}...")
            return clean_url(resolved)
        # Fallback : suivre la redirection HTTP réelle
        resolved = resolve_url_final(url)
        if resolved != url:
            logger.debug(f"Tracking résolu (HTTP): {url[:60]}... -> {resolved[:60]}...")
            return clean_url(resolved)
    
    # Ancienne logique pour les redirects classiques
    parsed = urlparse(url)
    params = parse_qs(parsed.query)
    for key in ("url", "u", "redirect", "redirect_url", "target", "link"):
        if key in params and params[key]:
            cand = unquote(params[key][0])
            if cand.startswith("http"):
                return clean_url(cand)
    
    # Nettoyer : garder uniquement scheme + netloc + path (pas les params de tracking)
    if "/annonce" in parsed.path.lower() or "/annonces/" in parsed.path.lower():
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    
    # Pour les URLs SeLoger directes (pas les trackers click.by/click.pro), nettoyer aussi
    if "seloger.com" in parsed.netloc.lower() and not any(t in parsed.netloc.lower() for t in ["click.by", "click.pro"]):
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    # Pour Logic-Immo detail-vente
    if "logic-immo.com" in parsed.netloc.lower() and "detail-vente" in parsed.path.lower():
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    # Pour ap.immo (BARNES et agences premium) : garder uniquement scheme+netloc+path
    if "ap.immo" in parsed.netloc.lower() and "/p/" in parsed.path.lower():
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

    return url


def resolve_url_final(url: str, timeout: int = 5) -> str:
    """Fait un HEAD request pour suivre les redirects et retourne l'URL finale nettoyée."""
    try:
        import requests
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9",
        }
        r = requests.head(url, headers=headers, timeout=timeout, allow_redirects=True)
        final = r.url
        parsed = urlparse(final)
        return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    except Exception as e:
        logger.debug(f"HEAD échoué pour {url[:60]}: {e}")
        return url


def is_listing_url(url: str, cfg: dict) -> bool:
    """Retourne True uniquement si l'URL ressemble à une fiche d'annonce immobilière."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parsed.query.lower()

    # 1. Domaines autorisés
    allowed = cfg["criteria"].get("allowed_url_domains", [
        "seloger.com", "bienici.com", "leboncoin.fr", "logic-immo.com",
        "fnaim.fr", "green-acres.fr", "pap.fr", "paruvendu.fr",
        "avendrealouer.fr", "mountain-base.com", "immobilier.nestenn.com",
        "orpi.com", "laforet.com", "century21.fr", "coldwellbanker.fr",
        "engelvoelkers.com", "sothebysrealty.com", "bellesdemeures.com",
        "ap.immo",  # Tracking/listing links BARNES et agences premium (apimo.pro)
        "barnes-montblanc.com", "barnes-alpes.com",
    ])
    if allowed and not any(d in domain for d in allowed):
        return False

    # 2. Exclusions de fichiers statiques / pages de service / tracking
    excluded_patterns = [
        ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".svg", ".woff", ".ico",
        "/assets/", "/static/", "/js/", "/css/", "/img/", "/images/",
        "remoteentry", "client/", "home_main", "ssal_savedsearchmanagement",
        "desinscription", "politique-de-confidentialite", "informations-legales",
        "cgu", "cgv", "mentions-legales", "aide/", "contact", "api/",
    ]
    if any(p in path or p in query or p in domain for p in excluded_patterns):
        return False

    # 3. Patterns positifs (doit ressembler à une annonce)
    listing_patterns = [
        "/annonce", "/achat/", "/location/", "/appartement", "/maison",
        "/studio", "/duplex", "/triplex", "/descriptif", "/detail", "/bien/",
        "/property", "/listing", "/vente-", "/a-vendre", "/immobilier-",
        "/ad/", "/annonces/", "/flat/", "/house/", "/rent/", "/buy/"
    ]
    if any(p in path for p in listing_patterns):
        return True

    # 4. Règles spécifiques par site
    if "seloger.com" in domain and ("/achat/" in path or "/location/" in path or "/annonce" in path):
        return True
    if "bienici.com" in domain and ("/annonce/" in path):
        return True
    if "leboncoin.fr" in domain and "/ad/" in path:
        return True
    if "pap.fr" in domain and "/annonce/" in path:
        return True
    if "mountain-base.com" in domain and (".htm" in path or ".html" in path):
        return True
    if "ap.immo" in domain and "/p/" in path:
        return True  # ap.immo/p/<id> = lien d'annonce BARNES/agences premium (apimo.pro)
    if "barnes-montblanc.com" in domain and len(path) > 10:
        return True
    if "barnes-alpes.com" in domain and len(path) > 10:
        return True

    # Par défaut : rejeter si aucun pattern positif
    return False


def get_context_around_url(text: str, url: str, window: int = 1000) -> str:
    """Extrait un bloc de texte de `window` caractères autour de l'URL."""
    # Essayer l'URL exacte
    idx = text.find(url)
    if idx == -1:
        # Essayer sans query string
        bare = url.split("?")[0]
        idx = text.find(bare)
    if idx == -1:
        # Essayer juste le domaine+path
        parsed = urlparse(url)
        short = f"{parsed.netloc}{parsed.path}"
        idx = text.find(short)
    if idx == -1:
        # Fallback : chercher le domaine seul
        parsed = urlparse(url)
        idx = text.find(parsed.netloc)
    if idx == -1:
        return text  # dernier recours
    start = max(0, idx - window)
    end = min(len(text), idx + window)
    return text[start:end]


def find_location(text: str, aliases: dict, potential_scores: dict = None) -> str:
    """Retourne la commune du bien.
    Priorité 1 — phrases locatives explicites ("à / sur / dans / village de / au cœur de X") :
      le signal le plus fiable, qui empêche la signature d'agence (ex: "DOUGLAS ELLIMAN
      CHAMONIX - LES HOUCHES") de polluer la détection.
    Priorité 2 (aucune phrase locative) — commune la moins dominante parmi celles citées,
      car Chamonix est souvent mentionnée comme référence régionale."""
    hay = _searchable(text)
    found = []
    for main, variants in aliases.items():
        norm = {_searchable(v) for v in variants}
        if any(v and v in hay for v in norm):
            found.append(main)
    if not found:
        return ""
    if len(found) == 1:
        return found[0]

    # Priorité 1 : "<préposition de lieu> <commune>"
    PREF = (r'(?:\bsur |\bdans |\bvillage d |\bau coeur d |\bcoeur d |'
            r'\bsitue a |\bsituee a |\bsitues a |\bsituees a |\bquartier d |\bsecteur d |\ba )')
    loc_hits = {}
    for main in found:
        norm = {_searchable(v) for v in aliases[main]}
        hits = sum(len(re.findall(PREF + re.escape(v) + r'\b', hay)) for v in norm if v)
        if hits:
            loc_hits[main] = hits
    if loc_hits:
        best = max(loc_hits.values())
        top = [m for m, c in loc_hits.items() if c == best]
        if len(top) > 1 and potential_scores:
            top.sort(key=lambda loc: potential_scores.get(loc, 50))
        return top[0]

    # Priorité 2 : heuristique historique (commune la moins dominante)
    if potential_scores:
        found.sort(key=lambda loc: potential_scores.get(loc, 50))
    return found[0]


def listing_id(url: str) -> str:
    """ID stable basé uniquement sur l'URL normalisée (pas sur prix/surface)."""
    stable = clean_url(url).lower().rstrip("/")
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]


def location_from_url(url: str, aliases: dict) -> str:
    """Extrait la commune depuis le chemin de l'URL (signal très fiable).

    Les plateformes immo incluent la commune dans l'URL :
      seloger.com/annonces/achat/appartement/les-houches-74/ou-...
      logic-immo.com/detail-vente-les-houches-74-...

    Cela évite les erreurs liées aux titres marketing ("Chamonix / Les Houches")
    où l'agent cite Chamonix pour attirer mais le bien est en réalité aux Houches.

    Returns: commune détectée ou "" si aucune.
    """
    try:
        path = urlparse(url).path.lower()
        # Normaliser le chemin (remplacer - et / par des espaces) pour la recherche
        path_hay = re.sub(r'[-/]', ' ', path)
        path_hay = _searchable(path_hay)
        for main, variants in aliases.items():
            for v in variants:
                sv = _searchable(v)
                if sv and sv in path_hay:
                    return main
    except Exception:
        pass
    return ""


# ── Enrichissement ONE-SHOT ──────────────────────────────────────────
def fetch_page_text(url: str, timeout: int = 8) -> Optional[str]:
    """Fetch avec headers réalistes pour contourner le blocage anti-bot."""
    try:
        import requests
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Referer": "https://www.google.fr/",
        })
        r = session.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return r.text[:80000]
        logger.debug(f"Fetch status {r.status_code} pour {url[:60]}")
    except Exception as e:
        logger.debug(f"Fetch échoué pour {url[:60]}... : {e}")
    return None


def html_to_text(value: str) -> str:
    parser = TextExtractor()
    parser.feed(value)
    return parser.text()


# ── Scoring ─────────────────────────────────────────────────────────
def estimate_rent(surface: Optional[float], location: str, cfg: dict, text: str) -> Optional[float]:
    if not surface or not location:
        return None
    base = cfg["criteria"]["rent_per_m2_monthly"].get(location)
    if not base:
        return None
    # La grande majorité des biens sont meublés → c'est la référence (mult 1.0).
    # On applique un petit malus uniquement si l'annonce précise "loué nu / non meublé".
    unfurnished_kw = cfg["criteria"].get("unfurnished_keywords", [])
    malus = cfg["criteria"].get("rent_unfurnished_malus", 0.9)
    mult = malus if any(_searchable(k) in _searchable(text) for k in unfurnished_kw) else 1.0
    return round(surface * base * mult, 2)


def score_yield(price: Optional[int], rent_monthly: Optional[float], thresholds: dict) -> tuple[int, list[str]]:
    if not price or not rent_monthly or price <= 0:
        return 0, []
    gross = (rent_monthly * 12 / price) * 100
    t = thresholds
    if gross >= t["yield_excellent"]:
        return 100, [f"rendement {gross:.1f}% (excellent)"]
    if gross >= t["yield_good"]:
        return 80, [f"rendement {gross:.1f}% (bon)"]
    if gross >= t["yield_fair"]:
        return 60, [f"rendement {gross:.1f}% (correct)"]
    if gross >= t["yield_poor"]:
        return 30, [f"rendement {gross:.1f}% (faible)"]
    return 10, [f"rendement {gross:.1f}% (mauvais)"]


def score_value(price: Optional[int], surface: Optional[float], location: str, market: dict, thresholds: dict) -> tuple[int, list[str]]:
    if not price or not surface or not location:
        return 0, []
    ref = market.get(location)
    if not ref:
        return 50, ["prix marché inconnu"]
    ppm = price / surface
    delta = ((ppm - ref) / ref) * 100
    t = thresholds
    if delta <= t["value_bargain"]:
        return 100, [f"{ppm:.0f}€/m² vs {ref:.0f}€/m² (très bon prix)"]
    if delta <= t["value_good"]:
        return 80, [f"{ppm:.0f}€/m² vs {ref:.0f}€/m² (bon prix)"]
    if delta <= t["value_fair"]:
        return 60, [f"{ppm:.0f}€/m² vs {ref:.0f}€/m² (prix marché)"]
    if delta <= t["value_expensive"]:
        return 30, [f"{ppm:.0f}€/m² vs {ref:.0f}€/m² (cher)"]
    return 10, [f"{ppm:.0f}€/m² vs {ref:.0f}€/m² (très cher)"]


def score_cashflow(price: Optional[int], rent_monthly: Optional[float], charges: Optional[int], dpe: str, ges: str, surface: Optional[float], text: str, cfg: dict) -> tuple[int, list[str]]:
    reasons = []
    score = 100
    if dpe in ("F", "G") or ges in ("F", "G"):
        score -= 25
        reasons.append("DPE/GES F-G (interdiction location proche)")
    if any(_searchable(k) in _searchable(text) for k in cfg["criteria"]["heavy_work_keywords"]):
        score -= 25
        reasons.append("gros travaux (cashflow bloqué)")
    if surface and surface < cfg["criteria"].get("min_surface_m2", 20):
        score -= 15
        reasons.append(f"surface < {cfg['criteria']['min_surface_m2']}m²")
    if charges and rent_monthly and rent_monthly > 0:
        ratio = (charges / 12) / rent_monthly
        max_ratio = cfg["criteria"].get("max_charges_vs_rent_ratio", 0.35)
        if ratio > max_ratio:
            score -= 20
            reasons.append(f"charges élevées ({ratio:.0%} du loyer)")
    return max(0, score), reasons


def score_structured(text: str, cfg: dict) -> tuple[int, list[str]]:
    """Détecte les produits structurés: résidences de tourisme, baux commerciaux, nue-propriété, SCPI, etc.

    IMPORTANT: Recherche limitée aux 2000 premiers caractères (contexte local autour de l'annonce),
    pour éviter les faux positifs liés au boilerplate marketing des emails d'agences.
    """
    # Limiter au contexte local — le boilerplate des emails d'agences (marketing patrimonial, etc.)
    # ne doit pas déclencher une détection de produit structuré.
    hay = _searchable(text[:2000])
    for kw in cfg["criteria"].get("structured_product_keywords", []):
        if _searchable(kw) in hay:
            logger.info(f"  → Produit structuré détecté: '{kw}' (dans les 2000 premiers chars)")
            return 0, [f"⚠️ PRODUIT STRUCTURÉ: {kw}"]
    return 100, []


def compute_score(listing: dict, cfg: dict) -> tuple[int, list[str], dict]:
    strat = cfg.get("strategy", "balanced")
    w = cfg["scoring_weights"][strat]
    th = cfg["scoring_thresholds"]
    market = cfg["criteria"]["market_price_per_m2"]
    loc_potential = cfg["criteria"]["location_potential_score"]

    text = listing.get("text", "")
    rent = estimate_rent(listing.get("surface"), listing.get("location"), cfg, text)
    listing["estimated_rent"] = rent
    listing["gross_yield"] = round((rent * 12 / listing["price"]) * 100, 2) if rent and listing.get("price") else None

    # Zone exclue (ex: Plateau d'Assy) → score plancher 0
    excluded_locs = cfg["criteria"].get("excluded_locations", [])
    if listing.get("location") in excluded_locs:
        return 0, [f"🚫 ZONE EXCLUE: {listing['location']}"], {
            "yield": 0, "value": 0, "location": 0,
            "cashflow": 0, "structured": 0,
            "_score_cashflow": 0, "_score_structured": 0,
        }

    # Détection produit structuré en PRIORITÉ
    s_structured, r_structured = score_structured(text, cfg)
    if s_structured == 0:
        return 0, r_structured, {
            "yield": 0, "value": 0, "location": 0,
            "cashflow": 0, "structured": 0,
            "_score_cashflow": 0, "_score_structured": 0,
        }

    s_yield, r_yield = score_yield(listing.get("price"), rent, th)
    s_value, r_value = score_value(listing.get("price"), listing.get("surface"), listing.get("location", ""), market, th)
    s_loc = loc_potential.get(listing.get("location", ""), 50)
    s_cash, r_cash = score_cashflow(listing.get("price"), rent, listing.get("charges"), listing.get("dpe", ""), listing.get("ges", ""), listing.get("surface"), text, cfg)

    total = round(
        s_yield * w["yield"] +
        s_value * w["value"] +
        s_loc * w["location"] +
        s_cash * w["cashflow_risk"] +
        s_structured * w.get("structured", 0.10)
    )

    reasons = r_yield + r_value + r_cash + r_structured
    breakdown = {
        "yield": s_yield,
        "value": s_value,
        "location": s_loc,
        "cashflow": s_cash,
        "structured": s_structured,
        "_score_cashflow": s_cash,
        "_score_structured": s_structured,
    }
    return max(0, min(100, total)), reasons, breakdown


# ── DB ──────────────────────────────────────────────────────────────
def init_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS listings (
            id TEXT PRIMARY KEY,
            url TEXT,
            title TEXT,
            price INTEGER,
            surface REAL,
            rooms INTEGER,
            location TEXT,
            charges INTEGER,
            dpe TEXT,
            ges TEXT,
            score INTEGER,
            reasons TEXT,
            yield REAL,
            vs_market REAL,
            enriched INTEGER DEFAULT 0,
            first_seen TEXT
        )
    """)
    conn.commit()
    return conn


def save_listing(conn: sqlite3.Connection, item: dict):
    # Preserve first_seen if row already exists
    row = conn.execute("SELECT first_seen FROM listings WHERE id = ?", (item["id"],)).fetchone()
    first_seen = row[0] if row else item["first_seen"]

    conn.execute("""
        INSERT OR REPLACE INTO listings
        (id, url, title, price, surface, rooms, location, charges, dpe, ges, score, reasons, yield, vs_market, enriched, first_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        item["id"], item["url"], item["title"], item.get("price"), item.get("surface"),
        item.get("rooms"), item.get("location"), item.get("charges"), item.get("dpe"), item.get("ges"),
        item["score"], json.dumps(item["reasons"], ensure_ascii=False),
        item.get("gross_yield"), item.get("vs_market"), item.get("enriched", 0), first_seen
    ))
    conn.commit()


# ── Historique des prix ──────────────────────────────────────────────
HISTORY_FILE = "listing_history.json"

def load_history(path: Path) -> dict:
    """Charge l'historique persistant entre les runs."""
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Historique illisible ({e}), reset.")
    return {"listings": {}, "_schema": 1}


def save_history(path: Path, history: dict):
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def update_history(history: dict, listing_id: str, price: int, today_iso: str) -> dict:
    """Met à jour l'historique pour un listing et retourne l'entrée courante."""
    h = history["listings"]
    today = datetime.fromisoformat(today_iso).replace(tzinfo=None)

    if listing_id not in h:
        # Nouveau listing
        h[listing_id] = {
            "first_seen":          today_iso,
            "last_seen":           today_iso,
            "price_history":       [{"date": today_iso[:10], "price": price}] if price else [],
            "was_absent":          False,
            "absent_since":        None,
            "relisted":            False,
            "relisted_after_days": None,
        }
    else:
        entry = h[listing_id]

        # Prix changé depuis la dernière fois ?
        ph = entry.get("price_history", [])
        last_price = ph[-1]["price"] if ph else None
        if price and last_price and price != last_price:
            ph.append({"date": today_iso[:10], "price": price})
            entry["price_history"] = ph
        elif price and not ph:
            entry["price_history"] = [{"date": today_iso[:10], "price": price}]

        # Bien relisté (était absent au run précédent) ?
        if entry.get("was_absent"):
            absent_since = entry.get("absent_since")
            if absent_since:
                try:
                    d0 = datetime.fromisoformat(absent_since).replace(tzinfo=None)
                    entry["relisted_after_days"] = (today - d0).days
                except Exception:
                    pass
            entry["relisted"] = True
            entry["was_absent"] = False
            entry["absent_since"] = None

        entry["last_seen"] = today_iso

    return h[listing_id]


def mark_absent_listings(history: dict, current_ids: set, today_iso: str):
    """Marque comme absents les listings non vus ce run."""
    for lid, entry in history["listings"].items():
        if lid not in current_ids and not entry.get("was_absent"):
            entry["was_absent"] = True
            entry["absent_since"] = today_iso


def enrich_from_history(listing: dict, history: dict, today_iso: str) -> dict:
    """Enrichit un listing avec les données historiques."""
    lid  = listing["id"]
    h    = history["listings"].get(lid, {})
    today = datetime.fromisoformat(today_iso).replace(tzinfo=None)

    # Préserver first_seen d'origine
    listing["first_seen"] = h.get("first_seen", listing.get("first_seen", today_iso))

    # Jours sur le marché
    try:
        d0 = datetime.fromisoformat(listing["first_seen"]).replace(tzinfo=None)
        listing["days_on_market"] = max(0, (today - d0).days)
    except Exception:
        listing["days_on_market"] = None

    # Historique de prix
    listing["price_history"] = h.get("price_history", [])

    # Baisse de prix
    ph = listing["price_history"]
    current_price = listing.get("price")
    if len(ph) >= 2 and current_price:
        original_price = ph[0]["price"]
        if original_price and current_price < original_price:
            drop_amount = original_price - current_price
            drop_pct    = round(drop_amount / original_price * 100, 1)
            listing["price_drop"] = {
                "amount":         drop_amount,
                "pct":            drop_pct,
                "original_price": original_price,
                "date":           ph[-1]["date"],
            }
        else:
            listing["price_drop"] = None
    else:
        listing["price_drop"] = None

    # Bien relisté
    listing["is_relisted"]         = h.get("relisted", False)
    listing["relisted_after_days"] = h.get("relisted_after_days")

    return listing


# ── DVF stats loader ─────────────────────────────────────────────────
def load_dvf_stats(base: Path) -> dict | None:
    """Charge dvf/dvf_stats.json si disponible. Retourne None sinon."""
    stats_path = base / "dvf" / "dvf_stats.json"
    if not stats_path.exists():
        return None
    try:
        with open(stats_path, encoding="utf-8") as f:
            stats = json.load(f)
        logger.info(f"DVF stats chargées : {len(stats.get('communes', {}))} communes")
        return stats
    except Exception as e:
        logger.warning(f"Impossible de charger dvf_stats.json: {e}")
        return None


def enhance_config_with_dvf(cfg: dict, dvf_stats: dict | None) -> None:
    """
    Met à jour market_price_per_m2 dans cfg avec les médianes DVF réelles.
    DVF commune key (MAJUSCULES) → config location key.
    """
    if not dvf_stats:
        return

    # Mapping DVF commune → config location
    DVF_TO_CONFIG = {
        "CHAMONIX MONT BLANC":     ["Chamonix", "Argentiere"],
        "SAINT GERVAIS LES BAINS": ["Saint-Gervais", "Le Fayet"],
        "LES HOUCHES":             ["Les Houches"],
        "SALLANCHES":              ["Sallanches"],
        "PASSY":                   ["Passy"],
        "DOMANCY":                 ["Domancy"],
        "SERVOZ":                  ["Servoz"],
    }

    market = cfg["criteria"]["market_price_per_m2"]
    for dvf_key, config_locs in DVF_TO_CONFIG.items():
        commune_data = dvf_stats.get("communes", {}).get(dvf_key)
        if not commune_data:
            continue
        dvf_median = commune_data.get("median_m2")
        if not dvf_median:
            continue
        for loc in config_locs:
            if loc in market:
                old = market[loc]
                market[loc] = int(dvf_median)
                logger.info(f"  Prix marché {loc}: {old} -> {int(dvf_median)} €/m² (DVF)")


# ── Export JSON pour dashboard React ────────────────────────────────
def generate_json(rows: list, config: dict, path: Path, dvf_stats: dict | None = None):
    """Génère data.json compatible avec le dashboard React."""
    # Champs à exclure (trop volumineux / inutiles pour le front)
    EXCLUDE = {"text", "estimated_rent"}

    clean_rows = []
    for r in rows:
        cr = {k: v for k, v in r.items() if k not in EXCLUDE}
        clean_rows.append(cr)

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": {
            "strategy":                config.get("strategy", "balanced"),
            "market_price_per_m2":     config["criteria"]["market_price_per_m2"],
            "rent_per_m2":             config["criteria"]["rent_per_m2_monthly"],
            "location_potential_score":config["criteria"]["location_potential_score"],
            "scoring_weights":         config["scoring_weights"],
            "scoring_thresholds":      config["scoring_thresholds"],
            "excluded_locations":      config["criteria"].get("excluded_locations", []),
            "location_aliases":        config["criteria"]["location_aliases"],
        },
        "listings": clean_rows,
    }

    # Inclure les stats DVF si disponibles
    if dvf_stats:
        output["dvf_stats"] = dvf_stats

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info(f"data.json écrit : {path} ({len(clean_rows)} annonces)"
                + (f" + DVF {len(dvf_stats.get('communes', {}))} communes" if dvf_stats else ""))


# ── IMAP ────────────────────────────────────────────────────────────
def load_env(path: Path):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip().strip('"')


def fetch_messages(cfg: dict):
    host, port = cfg["imap"]["host"], cfg["imap"]["port"]
    email_addr = os.environ.get("IMAP_EMAIL")
    password = os.environ.get("IMAP_PASSWORD")
    if not email_addr or not password:
        logger.error("IMAP_EMAIL / IMAP_PASSWORD manquants")
        return
    for attempt in range(3):
        try:
            with imaplib.IMAP4_SSL(host, port) as imap:
                imap.login(email_addr, password)
                imap.select(cfg["imap"]["mailbox"])
                status, data = imap.search(None, cfg["imap"]["search"])
                if status != "OK":
                    return
                ids = data[0].split()
                logger.info(f"{len(ids)} message(s)")
                for msg_id in ids:
                    status, msg_data = imap.fetch(msg_id, "(RFC822)")
                    if status == "OK" and msg_data and msg_data[0]:
                        yield email.message_from_bytes(msg_data[0][1], policy=policy.default)
            return
        except Exception as e:
            wait = 2 ** attempt
            logger.warning(f"IMAP tentative {attempt+1}/3: {e}, retry dans {wait}s")
            import time
            time.sleep(wait)


# ── HTML Dashboard ──────────────────────────────────────────────────
def generate_html(rows: list, config: dict, path: Path):
    strat = config.get("strategy", "balanced")
    locations = sorted(set(r["location"] for r in rows if r["location"]))
    all_locations = sorted(config["criteria"]["location_aliases"].keys())
    rows_json = json.dumps(rows, ensure_ascii=False)
    all_locations_json = json.dumps(all_locations, ensure_ascii=False)
    scoring_config_json = json.dumps({
        "market_price_per_m2": config["criteria"]["market_price_per_m2"],
        "rent_per_m2_monthly": config["criteria"]["rent_per_m2_monthly"],
        "location_potential_score": config["criteria"]["location_potential_score"],
        "scoring_weights": config["scoring_weights"],
        "scoring_thresholds": config["scoring_thresholds"],
        "strategy": config.get("strategy", "balanced"),
        "excluded_locations": config["criteria"].get("excluded_locations", []),
        "rent_unfurnished_malus": config["criteria"].get("rent_unfurnished_malus", 0.9),
    }, ensure_ascii=False)
    html_content = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Appart Alert - Stratégie: {strat}</title>
<style>
  :root {{
    --bg: #fbeeee; --card: #fff; --text: #1a1212; --muted: #7a6b6b;
    --primary: #a49174; --secondary: #93aaa8; --accent: #2b453e;
    --border: #e8d8d8;
    --good: #2b8c70; --good-bg: #e6f5f0;
    --mid: #b07a20; --mid-bg: #fdf3e0;
    --bad: #b84040; --bad-bg: #fde8e8;
    --structured: #7c3aed; --structured-bg: #f3f0ff;
  }}
  body {{ font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); margin: 0; padding: 20px; }}
  h1 {{ margin: 0 0 6px; font-size: 1.35rem; color: var(--accent); }}
  .meta {{ color: var(--muted); font-size: 0.88rem; margin-bottom: 16px; }}
  .filters {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin-bottom: 14px; }}
  .filters input, .filters select {{ padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; font-size: 0.88rem; width: 100%; box-sizing: border-box; background: var(--card); color: var(--text); }}
  .summary-bar {{ display: flex; gap: 8px; margin-bottom: 14px; flex-wrap: wrap; align-items: center; }}
  .stat-chip {{ background: var(--card); border: 1px solid var(--border); border-radius: 16px; padding: 4px 12px; font-size: 0.8rem; color: var(--text); white-space: nowrap; }}
  .stat-chip strong {{ color: var(--accent); }}
  table {{ width: 100%; border-collapse: collapse; background: var(--card); border-radius: 10px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,0.07); font-size: 0.88rem; }}
  th {{ background: var(--accent); color: rgba(255,255,255,.9); text-align: left; padding: 10px 12px; cursor: pointer; user-select: none; position: sticky; top: 0; font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.05em; }}
  td {{ padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }}
  tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover td {{ background: #fdf5f5; }}
  .sbadge {{ width: 36px; height: 36px; border-radius: 50%; display: inline-flex; align-items: center; justify-content: center; font-weight: 700; font-size: 0.78rem; flex-shrink: 0; }}
  .s-high {{ background: var(--good-bg); color: var(--good); }}
  .s-mid  {{ background: var(--mid-bg);  color: var(--mid);  }}
  .s-low  {{ background: var(--bad-bg);  color: var(--bad);  }}
  .s-struct {{ background: var(--structured-bg); color: var(--structured); }}
  .badge {{ display: inline-block; padding: 2px 7px; border-radius: 10px; font-size: 0.71rem; background: #f0e8e8; margin: 1px 2px 1px 0; }}
  .badge-pos {{ background: var(--good-bg); color: var(--good); }}
  .badge-neg {{ background: var(--bad-bg); color: var(--bad); }}
  .badge-structured {{ background: var(--structured-bg); color: var(--structured); border: 1px solid var(--structured); }}
  a {{ color: var(--accent); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .hidden {{ display: none; }}
  .actions {{ display: flex; gap: 6px; }}
  .btn {{ border: 1px solid var(--border); background: var(--card); padding: 4px 10px; border-radius: 6px; cursor: pointer; font-size: 0.8rem; color: var(--text); }}
  .btn.active {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
  .row-seen td {{ opacity: .5; }}
  .row-rejected td {{ opacity: .28; text-decoration: line-through; }}
  .row-structured td {{ background: #faf5ff; }}
  .enrich-icon {{ color: #8b5cf6; font-size: 0.8rem; margin-left: 4px; }}
  .links-cell a {{ display: inline-block; margin: 2px 4px 2px 0; white-space: nowrap; }}
  .loc-cell {{ cursor: pointer; border-bottom: 1px dashed #b0a0a0; }}
  .loc-cell:hover {{ background: #f5f0eb; }}
  .loc-edited {{ color: var(--accent); font-weight: 600; }}
  .loc-select {{ font-size: 0.85rem; padding: 2px 4px; border-radius: 4px; border: 1px solid var(--accent); }}
  .note-cell {{ font-size: 0.8rem; color: var(--muted); font-style: italic; cursor: pointer; }}
  .note-input {{ font-size: 0.8rem; width: 120px; padding: 2px 4px; border: 1px solid var(--border); border-radius: 4px; }}
  /* ── Onglets ── */
  .tabs {{ display: flex; gap: 2px; margin-bottom: 20px; border-bottom: 2px solid var(--border); }}
  .tab {{ padding: 10px 20px; cursor: pointer; font-size: 0.92rem; font-weight: 600; color: var(--muted); border: none; background: none; border-bottom: 3px solid transparent; margin-bottom: -2px; transition: color .15s; }}
  .tab:hover {{ color: var(--text); }}
  .tab.active {{ color: var(--accent); border-bottom-color: var(--accent); }}
  .content {{ padding: 18px 22px; max-width: 1440px; margin: 0 auto; }}
  /* ── Insights ── */
  .ins-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; margin-bottom: 28px; }}
  .kpi {{ background: var(--card); border-radius: 10px; padding: 16px 18px; border: 1px solid var(--border); box-shadow: 0 1px 3px rgba(0,0,0,0.06); }}
  .kpi-label {{ font-size: 0.76rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }}
  .kpi-val {{ font-size: 1.6rem; font-weight: 700; line-height: 1.1; color: var(--accent); }}
  .kpi-sub {{ font-size: 0.78rem; color: var(--muted); margin-top: 4px; }}
  .ins-card {{ background: var(--card); border-radius: 10px; padding: 20px 22px; border: 1px solid var(--border); box-shadow: 0 1px 3px rgba(0,0,0,0.06); margin-bottom: 18px; }}
  .ins-card h2 {{ font-size: 1rem; margin: 0 0 4px; color: var(--accent); }}
  .ins-card .hint, .hint {{ font-size: 0.8rem; color: var(--muted); margin: 0 0 14px; }}
  .ins-cols {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap: 18px; }}
  .bar-row {{ display: grid; grid-template-columns: 110px 1fr auto; align-items: center; gap: 10px; margin-bottom: 11px; }}
  .bar-label {{ font-size: 0.84rem; font-weight: 600; text-align: right; white-space: nowrap; }}
  .bar-track {{ background: #f0e8e8; border-radius: 6px; height: 22px; position: relative; overflow: hidden; }}
  .bar-fill {{ height: 100%; border-radius: 6px; background: var(--accent); transition: width .3s; }}
  .bar-ref {{ position: absolute; top: -3px; bottom: -3px; width: 2px; background: var(--bad); }}
  .bar-val {{ font-size: 0.83rem; font-variant-numeric: tabular-nums; white-space: nowrap; min-width: 86px; text-align: right; }}
  .pill {{ display: inline-block; padding: 1px 7px; border-radius: 10px; font-size: 0.72rem; font-weight: 600; }}
  .pill-good {{ background: var(--good-bg); color: var(--good); }}
  .pill-bad {{ background: var(--bad-bg); color: var(--bad); }}
  .pill-mid {{ background: var(--mid-bg); color: var(--mid); }}
  .ins-table {{ width: 100%; border-collapse: collapse; font-size: 0.86rem; }}
  .ins-table th {{ position: static; background: #f8f3ef; color: var(--muted); font-weight: 600; text-transform: uppercase; font-size: 0.7rem; letter-spacing: 0.04em; cursor: default; padding: 8px 10px; }}
  .ins-table td {{ padding: 9px 10px; border-bottom: 1px solid var(--border); }}
  .ins-table tr:last-child td {{ border-bottom: none; }}
  .pos {{ color: var(--good); }} .neg {{ color: var(--bad); }}
  .legend {{ font-size: 0.78rem; color: var(--muted); margin-top: 10px; }}
  .legend .dot {{ display: inline-block; width: 9px; height: 2px; background: var(--bad); vertical-align: middle; margin: 0 4px; }}
</style>
</head>
<body>
<h1>🏔️ Appart Alert <span style="font-weight:400;color:#6b7280">| Stratégie: {strat}</span></h1>
<div class="meta">{len(rows)} annonces • Clique sur les en-têtes pour trier • Filtres ci-dessous</div>

<div class="tabs">
  <button class="tab active" id="tab-listings" onclick="showTab('listings')">📋 Annonces</button>
  <button class="tab" id="tab-insights" onclick="showTab('insights')">📊 Insights</button>
  <button class="tab" id="tab-comparateur" onclick="showTab('comparateur')">⚖️ Comparateur</button>
  <button class="tab" id="tab-simulation" onclick="showTab('simulation')">🧮 Simulation</button>
</div>

<div id="view-listings">
<div id="summary-bar" class="summary-bar"></div>
<div class="filters">
  <input id="f-search" placeholder="Rechercher..." oninput="filter()">
  <select id="f-loc" onchange="filter()"><option value="">Toutes communes</option>{"".join(f'<option value="{loc}">{loc}</option>' for loc in locations)}</select>
  <input id="f-minscore" type="number" placeholder="Score min" oninput="filter()">
  <input id="f-maxprice" type="number" placeholder="Prix max €" oninput="filter()">
  <input id="f-minsurf" type="number" placeholder="Surface min m²" oninput="filter()">
  <input id="f-minyield" type="number" step="0.1" placeholder="Rendement min %" oninput="filter()">
  <select id="f-structured" onchange="filter()">
    <option value="">Tous types</option>
    <option value="hide">Cacher produits structurés</option>
    <option value="only">Voir uniquement produits structurés</option>
  </select>
</div>

<table id="table">
<thead>
<tr>
  <th onclick="sort('score')">Score ↕</th>
  <th onclick="sort('location')">Commune ↕</th>
  <th onclick="sort('price')">Prix ↕</th>
  <th onclick="sort('surface')">Surface ↕</th>
  <th onclick="sort('rooms')">Pièces ↕</th>
  <th onclick="sort('vs_market')">vs Marché ↕</th>
  <th>Loyer/mois</th>
  <th onclick="sort('yield')">Rendement ↕</th>
  <th>Raisons</th>
  <th>Lien</th>
  <th>Note</th>
  <th>Action</th>
</tr>
</thead>
<tbody id="tbody"></tbody>
</table>
</div>

<div id="view-insights" class="hidden"></div>

<div id="view-comparateur" class="hidden"></div>

<div id="view-simulation" class="hidden"></div>

<script>
const rows = {rows_json};
const ALL_LOCATIONS = {all_locations_json};
const CFG = {scoring_config_json};
let sortCol = 'score';
let sortAsc = false;

// ── Scoring JS (miroir du Python) ──────────────────────────────────
function estimateRent(surface, location, furnished) {{
  const base = CFG.rent_per_m2_monthly[location];
  if (!base || !surface) return null;
  // Meublé = référence (1.0) ; petit malus seulement si explicitement nu.
  const mult = (furnished === false) ? (CFG.rent_unfurnished_malus || 0.9) : 1.0;
  return surface * base * mult;
}}
// Loyer effectif : priorité au loyer saisi à la main (override), sinon estimation.
function effectiveRent(r, location) {{
  const ov = (JSON.parse(localStorage.getItem('listingOverrides') || '{{}}')[r.id]) || {{}};
  if (ov.loyer != null) return ov.loyer;
  if (r.manual_loyer != null) return r.manual_loyer;
  return estimateRent(r.surface, location, r.furnished);
}}
function scoreYield(price, rentMonthly) {{
  if (!price || !rentMonthly) return [0, []];
  const gross = (rentMonthly * 12 / price) * 100;
  const t = CFG.scoring_thresholds;
  if (gross >= t.yield_excellent) return [100, [`rendement ${{gross.toFixed(1)}}% (excellent)`]];
  if (gross >= t.yield_good)      return [80,  [`rendement ${{gross.toFixed(1)}}% (bon)`]];
  if (gross >= t.yield_fair)      return [60,  [`rendement ${{gross.toFixed(1)}}% (correct)`]];
  if (gross >= t.yield_poor)      return [30,  [`rendement ${{gross.toFixed(1)}}% (faible)`]];
  return [10, [`rendement ${{gross.toFixed(1)}}% (mauvais)`]];
}}
function scoreValue(price, surface, location) {{
  if (!price || !surface || !location) return [0, []];
  const ref = CFG.market_price_per_m2[location];
  if (!ref) return [50, ['prix marché inconnu']];
  const ppm = price / surface;
  const delta = ((ppm - ref) / ref) * 100;
  const t = CFG.scoring_thresholds;
  if (delta <= t.value_bargain)   return [100, [`${{Math.round(ppm)}}€/m² vs ${{ref}}€/m² (très bon prix)`]];
  if (delta <= t.value_good)      return [80,  [`${{Math.round(ppm)}}€/m² vs ${{ref}}€/m² (bon prix)`]];
  if (delta <= t.value_fair)      return [60,  [`${{Math.round(ppm)}}€/m² vs ${{ref}}€/m² (prix marché)`]];
  if (delta <= t.value_expensive) return [30,  [`${{Math.round(ppm)}}€/m² vs ${{ref}}€/m² (cher)`]];
  return [10, [`${{Math.round(ppm)}}€/m² vs ${{ref}}€/m² (très cher)`]];
}}
function isExcludedLoc(loc) {{
  return (CFG.excluded_locations || []).includes(loc);
}}
function computeScore(r, location) {{
  const w = CFG.scoring_weights[CFG.strategy];
  // Zone exclue (ex: Plateau d'Assy) → score plancher 0
  if (isExcludedLoc(location)) {{
    const ref0 = CFG.market_price_per_m2[location];
    const vs0 = (ref0 && r.surface) ? Math.round(((r.price/r.surface - ref0)/ref0)*100) : null;
    const rent0 = effectiveRent(r, location);
    return {{
      score: 0,
      reasons: [`🚫 ZONE EXCLUE: ${{location}}`],
      gross_yield: rent0 ? (rent0 * 12 / r.price * 100) : null,
      vs_market: vs0,
    }};
  }}
  const rent = effectiveRent(r, location);
  const [sYield, rYield] = scoreYield(r.price, rent);
  const [sValue, rValue] = scoreValue(r.price, r.surface, location);
  const sLoc = CFG.location_potential_score[location] || 50;
  // cashflow & structured: on garde ceux du Python (pas de recalcul JS)
  const sCash = r._score_cashflow !== undefined ? r._score_cashflow : 100;
  const sStr  = r._score_structured !== undefined ? r._score_structured : 100;
  const total = Math.round(
    sYield * w.yield +
    sValue * w.value +
    sLoc   * w.location +
    sCash  * w.cashflow_risk +
    sStr   * (w.structured || 0.1)
  );
  const gross = rent ? (rent * 12 / r.price * 100) : null;
  const vsMarket = (() => {{
    const ref = CFG.market_price_per_m2[location];
    return (ref && r.surface) ? Math.round(((r.price/r.surface - ref)/ref)*100) : null;
  }})();
  return {{
    score: Math.max(0, Math.min(100, total)),
    reasons: [...rYield, ...rValue],
    gross_yield: gross,
    vs_market: vsMarket,
  }};
}}

function isStructured(r) {{
  return r.reasons.some(reason => reason.includes('PRODUIT STRUCTURÉ'));
}}

function render() {{
  const tbody = document.getElementById('tbody');
  tbody.innerHTML = '';
  const states = JSON.parse(localStorage.getItem('listingStates') || '{{}}');

  for (const r of rows) {{
    const st = states[r.id] || 'new';
    const structured = isStructured(r);
    const tr = document.createElement('tr');
    tr.dataset.id = r.id;
    if (st === 'seen') tr.classList.add('row-seen');
    if (st === 'rejected') tr.classList.add('row-rejected');
    if (structured) tr.classList.add('row-structured');

    const overrides = JSON.parse(localStorage.getItem('listingOverrides') || '{{}}');
    const ov = overrides[r.id] || {{}};
    const displayLoc = ov.location || r.location || '?';
    // loc-edited = override manuel OU correction automatique depuis l'URL (commune différente du titre email)
    const locClass = (ov.location || r._loc_corrected) ? 'loc-edited' : '';
    const noteText = ov.note || '';

    // Si la commune a été corrigée automatiquement depuis l'URL (r._loc_corrected),
    // recalculer le score JS avec la vraie commune (sinon le score Python est biaisé).
    // Pareil si l'utilisateur a overridé la commune manuellement.
    let autoRecomp = null;
    if (!isStructured(r) && (r._loc_corrected || ov.location)) {{
      autoRecomp = computeScore(r, displayLoc);
    }}
    const displayScore = ov.score !== undefined ? ov.score : (autoRecomp ? autoRecomp.score : r.score);
    const displayYield = ov.gross_yield !== undefined ? ov.gross_yield : (autoRecomp ? autoRecomp.gross_yield : r.yield);
    const displayVsMarket = ov.vs_market !== undefined ? ov.vs_market : (autoRecomp ? autoRecomp.vs_market : r.vs_market);
    const displayReasons = ov.reasons || (autoRecomp ? autoRecomp.reasons : r.reasons);

    const excluded = isExcludedLoc(displayLoc);
    if (excluded) tr.classList.add('row-rejected');

    // Recalculer scoreClass avec le score affiché
    let scoreClass;
    if (excluded) {{ scoreClass = 's-low'; }}
    else if (isStructured(r)) {{ scoreClass = 's-struct'; }}
    else if (displayScore >= 80) {{ scoreClass = 's-high'; }}
    else if (displayScore >= 60) {{ scoreClass = 's-mid'; }}
    else {{ scoreClass = 's-low'; }}

    const vs = displayVsMarket != null ? (displayVsMarket > 0 ? '+' : '') + Math.round(displayVsMarket) + '%' : 'N/A';
    const y = displayYield != null ? displayYield.toFixed(1) + '%' : 'N/A';
    const loyerVal = effectiveRent(r, displayLoc);
    const loyerEdited = ov.loyer != null;
    const enrichBadge = r.enriched ? '<span class="enrich-icon" title="Données enrichies depuis la fiche">🔍</span>' : '';

    let reasonsHtml = '';
    for (const reason of displayReasons) {{
      let cls;
      if (reason.includes('PRODUIT STRUCTURÉ') || reason.includes('ZONE EXCLUE')) {{
        cls = 'badge-structured';
      }} else if (reason.startsWith('-') || reason.includes('❌') || reason.includes('gros') || reason.includes('DPE') || reason.includes('charges')) {{
        cls = 'badge-neg';
      }} else {{
        cls = 'badge-pos';
      }}
      reasonsHtml += `<span class="badge ${{cls}}">${{reason}}</span>`;
    }}

    tr.innerHTML = `
      <td><span class="sbadge ${{scoreClass}}">${{displayScore}}</span>${{enrichBadge}}${{r.manual ? '<span class="enrich-icon" title="Saisi à la main">✍️</span>' : ''}}</td>
      <td class="loc-cell ${{locClass}}" onclick="editLocation('${{r.id}}', this)" title="${{r._loc_corrected && !ov.location ? '⚙️ Corrigé auto depuis URL (était : ' + (r._location_original||'?') + '). Clic pour modifier.' : 'Clic pour modifier'}}">${{displayLoc}}${{r._loc_corrected && !ov.location ? ' <span style="font-size:0.65em;opacity:0.6" title="Commune corrigée automatiquement depuis le chemin de l&#39;URL">⚙️</span>' : ''}}</td>
      <td>${{r.price ? r.price.toLocaleString() + ' €' : '?'}}</td>
      <td>${{r.surface ? r.surface + ' m²' : '?'}}</td>
      <td>${{r.rooms || '?'}}</td>
      <td>${{vs}}</td>
      <td class="loc-cell ${{loyerEdited ? 'loc-edited' : ''}}" onclick="editLoyer('${{r.id}}', this)" title="Clic pour saisir le loyer réel de l'annonce">${{loyerVal != null ? Math.round(loyerVal) + ' €' : '?'}}</td>
      <td>${{y}}</td>
      <td>${{reasonsHtml}}</td>
      <td class="links-cell">${{
        (r.urls && r.urls.length > 1)
          ? r.urls.map((u, i) => {{
              let label = "Lien " + (i+1);
              if (u.includes("seloger.com")) label = "SeLoger";
              else if (u.includes("bienici.com")) label = "BienIci";
              else if (u.includes("leboncoin.fr")) label = "LBC";
              else if (u.includes("pap.fr")) label = "PAP";
              return `<a href="${{u}}" target="_blank">${{label}} →</a>`;
            }}).join(" ")
          : `<a href="${{r.url}}" target="_blank">Voir →</a>`
      }}</td>
      <td class="note-cell" onclick="editNote('${{r.id}}', this)" title="Clic pour ajouter une note">${{noteText || '+ note'}}</td>
      <td class="actions">
        <button class="btn ${{st==='seen'?'active':''}}" onclick="setState('${{r.id}}','seen')">Vu</button>
        <button class="btn ${{st==='rejected'?'active':''}}" onclick="setState('${{r.id}}','rejected')">✕</button>
        ${{r.manual ? `<button class="btn" onclick="deleteManualListing('${{r.id}}')" title="Supprimer ce bien saisi">🗑</button>` : ''}}
      </td>
    `;
    tbody.appendChild(tr);
  }}
}}

function setState(id, state) {{
  const states = JSON.parse(localStorage.getItem('listingStates') || '{{}}');
  states[id] = states[id] === state ? 'new' : state;
  localStorage.setItem('listingStates', JSON.stringify(states));
  render();
}}

function editLocation(id, cell) {{
  if (cell.querySelector('select')) return;
  const overrides = JSON.parse(localStorage.getItem('listingOverrides') || '{{}}');
  const current = (overrides[id] || {{}}).location || cell.innerText.trim();
  const sel = document.createElement('select');
  sel.className = 'loc-select';
  ALL_LOCATIONS.forEach(loc => {{
    const opt = document.createElement('option');
    opt.value = loc; opt.text = loc;
    if (loc === current) opt.selected = true;
    sel.appendChild(opt);
  }});
  const optNone = document.createElement('option');
  optNone.value = ''; optNone.text = '— original —';
  sel.insertBefore(optNone, sel.firstChild);
  cell.innerHTML = '';
  cell.appendChild(sel);
  sel.focus();
  sel.onchange = () => {{
    const val = sel.value;
    const ov = overrides[id] || {{}};
    if (val) {{
      ov.location = val;
      // Recalculer le score avec la nouvelle commune
      const r = rows.find(x => x.id === id);
      if (r) {{
        const recomp = computeScore(r, val);
        ov.score = recomp.score;
        ov.reasons = recomp.reasons;
        ov.gross_yield = recomp.gross_yield;
        ov.vs_market = recomp.vs_market;
      }}
    }} else {{
      delete ov.location; delete ov.score; delete ov.reasons;
      delete ov.gross_yield; delete ov.vs_market;
    }}
    overrides[id] = ov;
    localStorage.setItem('listingOverrides', JSON.stringify(overrides));
    render();
  }};
  sel.onblur = () => render();
}}

function editNote(id, cell) {{
  if (cell.querySelector('input')) return;
  const overrides = JSON.parse(localStorage.getItem('listingOverrides') || '{{}}');
  const current = (overrides[id] || {{}}).note || '';
  const inp = document.createElement('input');
  inp.className = 'note-input';
  inp.value = current;
  inp.placeholder = 'Note...';
  cell.innerHTML = '';
  cell.appendChild(inp);
  inp.focus();
  inp.onblur = () => {{
    const ov = overrides[id] || {{}};
    if (inp.value.trim()) {{ ov.note = inp.value.trim(); }} else {{ delete ov.note; }}
    overrides[id] = ov;
    localStorage.setItem('listingOverrides', JSON.stringify(overrides));
    render();
  }};
  inp.onkeydown = e => {{ if (e.key === 'Enter') inp.blur(); }};
}}

function getDisplayVal(r, col) {{
  const overrides = JSON.parse(localStorage.getItem('listingOverrides') || '{{}}');
  const ov = overrides[r.id] || {{}};
  if (col === 'score') return ov.score !== undefined ? ov.score : r.score;
  if (col === 'yield') return ov.gross_yield !== undefined ? ov.gross_yield : r.yield;
  if (col === 'vs_market') return ov.vs_market !== undefined ? ov.vs_market : r.vs_market;
  if (col === 'location') return ov.location || r.location;
  return r[col];
}}

function sort(col) {{
  if (sortCol === col) sortAsc = !sortAsc; else {{ sortCol = col; sortAsc = true; }}
  const dir = sortAsc ? 1 : -1;
  rows.sort((a,b) => {{
    const va = getDisplayVal(a, col) != null ? getDisplayVal(a, col) : -Infinity;
    const vb = getDisplayVal(b, col) != null ? getDisplayVal(b, col) : -Infinity;
    return (va > vb ? 1 : va < vb ? -1 : 0) * dir;
  }});
  render();
}}

function filter() {{
  const s = document.getElementById('f-search').value.toLowerCase();
  const loc = document.getElementById('f-loc').value;
  const minScore = parseFloat(document.getElementById('f-minscore').value) || 0;
  const maxPrice = parseFloat(document.getElementById('f-maxprice').value) || Infinity;
  const minSurf = parseFloat(document.getElementById('f-minsurf').value) || 0;
  const minYield = parseFloat(document.getElementById('f-minyield').value) || 0;
  const structuredFilter = document.getElementById('f-structured').value;

  for (const tr of document.querySelectorAll('#tbody tr')) {{
    const r = rows.find(x => x.id === tr.dataset.id);
    if (!r) continue;
    const text = tr.innerText.toLowerCase();
    const isStr = isStructured(r);

    let matchStructured = true;
    if (structuredFilter === 'hide' && isStr) matchStructured = false;
    if (structuredFilter === 'only' && !isStr) matchStructured = false;

    const match = text.includes(s) &&
      (!loc || getDisplayVal(r, 'location') === loc) &&
      getDisplayVal(r, 'score') >= minScore &&
      (r.price || 0) <= maxPrice &&
      (r.surface || 0) >= minSurf &&
      (getDisplayVal(r, 'yield') || 0) >= minYield &&
      matchStructured;
    tr.classList.toggle('hidden', !match);
  }}
}}

sort('score');
render();
</script>
</body>
</html>"""
    # ── Onglet Insights (script injecté en clair, pas d'échappement d'accolades) ──
    insights_block = r"""<script>
// ── Helpers ──────────────────────────────────────────────────────────
function _median(a) {
  const v = a.filter(x => x != null && !isNaN(x)).sort((x, y) => x - y);
  if (!v.length) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}
function _avg(a) {
  const v = a.filter(x => x != null && !isNaN(x));
  return v.length ? v.reduce((s, x) => s + x, 0) / v.length : null;
}
function _eur(n) {
  if (n == null || isNaN(n)) return 'N/A';
  return Math.round(n).toLocaleString('fr-FR') + ' €';
}
function _pctPill(delta) {
  if (delta == null || isNaN(delta)) return '<span class="pill">N/A</span>';
  const cls = delta <= -10 ? 'pill-good' : (delta >= 10 ? 'pill-bad' : 'pill-mid');
  const sign = delta > 0 ? '+' : '';
  return `<span class="pill ${cls}">${sign}${Math.round(delta)}%</span>`;
}

// ── Loyer éditable (override → recalcule rendement & score) ───────────
function editLoyer(id, cell) {
  if (cell.querySelector('input')) return;
  const overrides = JSON.parse(localStorage.getItem('listingOverrides') || '{}');
  const r = rows.find(x => x.id === id);
  if (!r) return;
  const ov = overrides[id] || {};
  const loc = ov.location || r.location;
  const current = effectiveRent(r, loc);
  const inp = document.createElement('input');
  inp.className = 'note-input'; inp.type = 'number'; inp.step = '10';
  inp.value = current != null ? Math.round(current) : '';
  inp.placeholder = '€/mois';
  cell.innerHTML = ''; cell.appendChild(inp); inp.focus();
  inp.onblur = () => {
    const ov2 = overrides[id] || {};
    const val = parseFloat(inp.value);
    if (val && val > 0) ov2.loyer = val; else delete ov2.loyer;
    overrides[id] = ov2;
    localStorage.setItem('listingOverrides', JSON.stringify(overrides));
    // recalcule score/rendement avec le loyer effectif ; sinon revient à l'origine
    if (ov2.loyer != null || ov2.location) {
      const recomp = computeScore(r, loc);
      ov2.score = recomp.score; ov2.reasons = recomp.reasons;
      ov2.gross_yield = recomp.gross_yield; ov2.vs_market = recomp.vs_market;
    } else {
      delete ov2.score; delete ov2.reasons; delete ov2.gross_yield; delete ov2.vs_market;
    }
    overrides[id] = ov2;
    localStorage.setItem('listingOverrides', JSON.stringify(overrides));
    render();
  };
  inp.onkeydown = e => { if (e.key === 'Enter') inp.blur(); };
}

// ── Onglets ──────────────────────────────────────────────────────────
function showTab(name) {
  const views = { listings: 'view-listings', insights: 'view-insights', comparateur: 'view-comparateur', simulation: 'view-simulation' };
  for (const [k, vid] of Object.entries(views)) {
    document.getElementById(vid).classList.toggle('hidden', k !== name);
    document.getElementById('tab-' + k).classList.toggle('active', k === name);
  }
  if (name === 'insights') buildInsights();
  if (name === 'comparateur') buildComparateur();
  if (name === 'simulation') buildSimulationFiscale();
}
function isExcludedLocG(loc) { return (CFG.excluded_locations || []).includes(loc); }

// ── Construction des insights ────────────────────────────────────────
function buildInsights() {
  const c = document.getElementById('view-insights');

  // Données enrichies, en respectant les overrides utilisateur (commune, score…)
  const data = rows.map(r => {
    const loc = getDisplayVal(r, 'location');
    const ppm = (r.price && r.surface) ? r.price / r.surface : null;
    return {
      loc, price: r.price, surface: r.surface, rooms: r.rooms,
      score: getDisplayVal(r, 'score'),
      yld: getDisplayVal(r, 'yield'),
      vs: getDisplayVal(r, 'vs_market'),
      ppm, structured: isStructured(r),
      url: (r.urls && r.urls[0]) || r.url
    };
  });
  // Stats de marché : on exclut produits structurés et zones exclues (€/m² trompeur)
  const valid = data.filter(d => !d.structured && !isExcludedLocG(d.loc) && d.ppm != null);

  // ── KPIs globaux ──
  const nbCommunes = new Set(valid.map(d => d.loc)).size;
  const medPrice = _median(valid.map(d => d.price));
  const medPpm = _median(valid.map(d => d.ppm));
  const medYield = _median(valid.map(d => d.yld));
  const medVs = _median(valid.map(d => d.vs));
  const nbDeals = valid.filter(d => d.vs != null && d.vs <= -20).length;
  const best = valid.slice().filter(d => d.vs != null).sort((a, b) => a.vs - b.vs)[0];

  let kpis = '<div class="ins-grid">';
  kpis += kpiCard('Annonces analysées', data.length, `${nbCommunes} communes • ${data.length - valid.length} produits structurés exclus`);
  kpis += kpiCard('Prix médian', _eur(medPrice), 'hors produits structurés');
  kpis += kpiCard('Prix médian / m²', medPpm != null ? _eur(medPpm) + '/m²' : 'N/A', 'toutes communes');
  kpis += kpiCard('Rendement brut médian', medYield != null ? medYield.toFixed(1) + '%' : 'N/A', 'loyer estimé / prix');
  kpis += kpiCard('Décote médiane vs marché', medVs != null ? (medVs > 0 ? '+' : '') + Math.round(medVs) + '%' : 'N/A', `${nbDeals} biens à -20% ou +`);
  kpis += kpiCard('Meilleure opportunité', best ? Math.round(best.vs) + '%' : 'N/A', best ? `${best.loc} • ${_eur(best.price)}` : '');
  kpis += '</div>';

  // ── Agrégation par commune ──
  const byLoc = {};
  for (const d of valid) {
    if (!d.loc) continue;
    (byLoc[d.loc] ||= []).push(d);
  }
  const communes = Object.keys(byLoc).map(loc => {
    const g = byLoc[loc];
    const ref = (CFG.market_price_per_m2 || {})[loc] || null;
    const avgPpm = _avg(g.map(d => d.ppm));
    return {
      loc, n: g.length, avgPpm, ref,
      decote: (ref && avgPpm) ? ((avgPpm - ref) / ref) * 100 : null,
      avgYield: _avg(g.map(d => d.yld)),
      avgScore: _avg(g.map(d => d.score)),
    };
  }).sort((a, b) => b.n - a.n);

  // ── Carte : Prix au m² par commune vs marché ──
  const maxScale = Math.max(...communes.map(x => Math.max(x.avgPpm || 0, x.ref || 0)), 1);
  let ppmRows = '';
  for (const x of communes.slice().sort((a, b) => (b.avgPpm || 0) - (a.avgPpm || 0))) {
    const w = ((x.avgPpm || 0) / maxScale) * 100;
    const refPos = x.ref ? (x.ref / maxScale) * 100 : null;
    ppmRows += `
      <div class="bar-row">
        <div class="bar-label">${x.loc}</div>
        <div class="bar-track">
          <div class="bar-fill" style="width:${w}%"></div>
          ${refPos != null ? `<div class="bar-ref" style="left:${refPos}%" title="Prix marché ${_eur(x.ref)}/m²"></div>` : ''}
        </div>
        <div class="bar-val">${_eur(x.avgPpm)}/m² ${_pctPill(x.decote)}</div>
      </div>`;
  }

  // ── Carte : Rendement moyen par commune ──
  const maxY = Math.max(...communes.map(x => x.avgYield || 0), 1);
  let yRows = '';
  for (const x of communes.slice().sort((a, b) => (b.avgYield || 0) - (a.avgYield || 0))) {
    const w = ((x.avgYield || 0) / maxY) * 100;
    const col = x.avgYield >= 6 ? '#10b981' : (x.avgYield >= 4 ? '#f59e0b' : '#ef4444');
    yRows += `
      <div class="bar-row">
        <div class="bar-label">${x.loc}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${w}%;background:${col}"></div></div>
        <div class="bar-val">${x.avgYield != null ? x.avgYield.toFixed(1) + '%' : 'N/A'}</div>
      </div>`;
  }

  // ── Carte : Répartition des annonces par commune ──
  const maxN = Math.max(...communes.map(x => x.n), 1);
  let nRows = '';
  for (const x of communes) {
    const w = (x.n / maxN) * 100;
    nRows += `
      <div class="bar-row">
        <div class="bar-label">${x.loc}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${w}%;background:#6366f1"></div></div>
        <div class="bar-val">${x.n} annonce${x.n > 1 ? 's' : ''}</div>
      </div>`;
  }

  // ── Carte : Distribution des scores ──
  const buckets = [
    { label: '80–100 (top)', col: '#10b981', test: s => s >= 80 },
    { label: '60–79 (bon)', col: '#f59e0b', test: s => s >= 60 && s < 80 },
    { label: '40–59 (moyen)', col: '#fb923c', test: s => s >= 40 && s < 60 },
    { label: '0–39 (faible)', col: '#ef4444', test: s => s < 40 },
  ];
  const maxB = Math.max(...buckets.map(b => data.filter(d => b.test(d.score)).length), 1);
  let bRows = '';
  for (const b of buckets) {
    const n = data.filter(d => b.test(d.score)).length;
    const w = (n / maxB) * 100;
    bRows += `
      <div class="bar-row">
        <div class="bar-label">${b.label}</div>
        <div class="bar-track"><div class="bar-fill" style="width:${w}%;background:${b.col}"></div></div>
        <div class="bar-val">${n}</div>
      </div>`;
  }

  // ── Carte : Top opportunités (plus forte décote) ──
  const top = valid.filter(d => d.vs != null).sort((a, b) => a.vs - b.vs).slice(0, 6);
  let topRows = '';
  for (const d of top) {
    topRows += `
      <tr>
        <td><strong>${d.loc || '?'}</strong></td>
        <td>${_eur(d.price)}</td>
        <td>${d.surface ? d.surface + ' m²' : '?'}</td>
        <td>${_eur(d.ppm)}/m²</td>
        <td>${_pctPill(d.vs)}</td>
        <td>${d.yld != null ? d.yld.toFixed(1) + '%' : 'N/A'}</td>
        <td><a href="${d.url}" target="_blank">Voir →</a></td>
      </tr>`;
  }

  c.innerHTML = `
    ${kpis}
    <div class="ins-card">
      <h2>Prix au m² par commune</h2>
      <p class="hint">Moyenne des annonces (barre) comparée au prix de marché de référence<span class="legend"><span class="dot"></span>repère rouge</span>. La pastille indique la décote/surcote moyenne.</p>
      ${ppmRows || '<p class="hint">Pas de données.</p>'}
    </div>
    <div class="ins-cols">
      <div class="ins-card">
        <h2>Rendement brut moyen par commune</h2>
        <p class="hint">Loyer annuel estimé ÷ prix d'achat.</p>
        ${yRows}
      </div>
      <div class="ins-card">
        <h2>Répartition des annonces</h2>
        <p class="hint">Nombre de biens détectés par commune.</p>
        ${nRows}
      </div>
    </div>
    <div class="ins-cols">
      <div class="ins-card">
        <h2>Distribution des scores</h2>
        <p class="hint">Qualité globale du flux d'annonces (produits structurés inclus).</p>
        ${bRows}
      </div>
      <div class="ins-card">
        <h2>Top opportunités</h2>
        <p class="hint">Biens les plus décotés vs prix de marché.</p>
        <table class="ins-table">
          <thead><tr><th>Commune</th><th>Prix</th><th>Surface</th><th>€/m²</th><th>vs marché</th><th>Rdt</th><th></th></tr></thead>
          <tbody>${topRows || '<tr><td colspan="7">Pas de données.</td></tr>'}</tbody>
        </table>
      </div>
    </div>`;
}

function kpiCard(label, val, sub) {
  return `<div class="kpi"><div class="kpi-label">${label}</div><div class="kpi-val">${val}</div>${sub ? `<div class="kpi-sub">${sub}</div>` : ''}</div>`;
}

// ═══════════════════════════════════════════════════════════════════════
//  ONGLET SIMULATION — plan de financement, cashflow, score affiné
// ═══════════════════════════════════════════════════════════════════════
const SIM_GLOBAL_DEFAULTS = {
  fraisNotairePct: 7.5, apportPct: 10, taux: 3.5, duree: 20,
  gestionPct: 7, vacancePct: 5, assurancePNO: 150
};
function getSimGlobal() {
  return Object.assign({}, SIM_GLOBAL_DEFAULTS, JSON.parse(localStorage.getItem('simGlobal') || '{}'));
}
function saveSimGlobal(g) { localStorage.setItem('simGlobal', JSON.stringify(g)); }
function getSimSelected() { return JSON.parse(localStorage.getItem('simSelected') || '[]'); }
function saveSimSelected(a) { localStorage.setItem('simSelected', JSON.stringify(a)); }
function getSimBienRaw() { return JSON.parse(localStorage.getItem('simBiens') || '{}'); }
function saveSimBien(id, b) {
  const all = getSimBienRaw(); all[id] = b; localStorage.setItem('simBiens', JSON.stringify(all));
}
// Valeurs par défaut d'un bien (dérivées de l'annonce)
function getSimBien(r) {
  const loc = getDisplayVal(r, 'location');
  const rent = effectiveRent(r, loc) || Math.round((r.surface || 0) * 17);
  const def = {
    prix: r.price || 0, travaux: 0, meubles: 0,
    loyer: Math.round(rent || 0), charges: 0,
    taxe: Math.round(rent || 0), dpe: r.dpe || ''
  };
  return Object.assign(def, (getSimBienRaw()[r.id] || {}));
}

function pmt(principal, annualRatePct, years) {
  const r = annualRatePct / 100 / 12, n = years * 12;
  if (n <= 0) return 0;
  if (r === 0) return principal / n;
  return principal * r / (1 - Math.pow(1 + r, -n));
}

function simScore(coutTotal, surface, loyerAn, loc) {
  if (isExcludedLocG(loc)) return 0;
  const t = CFG.scoring_thresholds, w = CFG.scoring_weights[CFG.strategy];
  const ref = CFG.market_price_per_m2[loc];
  const ppm = surface ? coutTotal / surface : null;
  let sValue = 50;
  if (ref && ppm) {
    const d = ((ppm - ref) / ref) * 100;
    sValue = d <= t.value_bargain ? 100 : d <= t.value_good ? 80 : d <= t.value_fair ? 60 : d <= t.value_expensive ? 30 : 10;
  }
  const gy = coutTotal ? loyerAn / coutTotal * 100 : 0;
  const sYield = gy >= t.yield_excellent ? 100 : gy >= t.yield_good ? 80 : gy >= t.yield_fair ? 60 : gy >= t.yield_poor ? 30 : 10;
  const sLoc = CFG.location_potential_score[loc] || 50;
  const total = Math.round(sYield * w.yield + sValue * w.value + sLoc * w.location + 100 * w.cashflow_risk + 100 * (w.structured || 0.1));
  return Math.max(0, Math.min(100, total));
}

function computeSim(r, g, b) {
  const loc = getDisplayVal(r, 'location');
  const surface = r.surface || 0;
  const prix = +b.prix || 0;
  const notaire = prix * (+g.fraisNotairePct) / 100;
  const coutTotal = prix + notaire + (+b.travaux || 0) + (+b.meubles || 0);
  const apport = coutTotal * (+g.apportPct) / 100;
  const emprunt = Math.max(0, coutTotal - apport);
  const mensualite = pmt(emprunt, +g.taux, +g.duree);
  const loyerAn = (+b.loyer || 0) * 12;
  const gestionAn = loyerAn * (+g.gestionPct) / 100;
  const vacanceAn = loyerAn * (+g.vacancePct) / 100;
  const revenuNet = loyerAn - gestionAn - vacanceAn - (+b.charges || 0) - (+b.taxe || 0) - (+g.assurancePNO || 0);
  const cashflowMois = revenuNet / 12 - mensualite;
  const coc = apport > 0 ? (cashflowMois * 12) / apport * 100 : null;
  return {
    loc, surface, prix, notaire, coutTotal, apport, emprunt, mensualite,
    loyerAn, revenuNet,
    rdtBrut: coutTotal ? loyerAn / coutTotal * 100 : null,
    rdtNet: coutTotal ? revenuNet / coutTotal * 100 : null,
    cashflowMois, cashflowAn: cashflowMois * 12, coc,
    coutCredit: mensualite * (+g.duree) * 12 - emprunt,
    prixRevientM2: surface ? coutTotal / surface : null,
    scoreAffine: simScore(coutTotal, surface, loyerAn, loc),
    scoreInitial: getDisplayVal(r, 'score')
  };
}

function injectSimStyles() {
  if (document.getElementById('sim-styles')) return;
  const css = `
  .sim-intro{color:var(--muted);font-size:.86rem;margin-bottom:16px;}
  .prop-chips{display:flex;gap:8px;flex-wrap:wrap;}
  .prop-chip{background:var(--bg);border:1px solid var(--border);border-radius:20px;padding:7px 12px;cursor:pointer;font-size:.82rem;color:var(--text);transition:all .15s;display:inline-flex;align-items:center;gap:8px;text-align:left;}
  .prop-chip:hover{border-color:var(--primary);}
  .prop-chip--active{background:var(--accent);color:#fff;border-color:var(--accent);}
  .pc-score{display:inline-block;width:28px;height:28px;border-radius:50%;background:rgba(0,0,0,.08);font-size:.76rem;font-weight:700;line-height:28px;text-align:center;flex-shrink:0;}
  .prop-chip--active .pc-score{background:rgba(255,255,255,.2);}
  .pc-info{display:flex;flex-direction:column;line-height:1.2;}
  .pc-loc{font-weight:600;font-size:.82rem;} .pc-meta{font-size:.72rem;opacity:.7;}
  .sim-params-panel{background:var(--card);border:1px solid var(--border);border-radius:12px;}
  .sim-params-summary{cursor:pointer;padding:14px 20px;font-weight:700;font-size:.92rem;list-style:none;color:var(--accent);display:flex;align-items:center;gap:8px;}
  .sim-params-summary::-webkit-details-marker{display:none;}
  .sim-params-hint{font-weight:400;color:var(--muted);font-size:.8rem;margin-left:4px;}
  .sim-params-summary::after{content:'▸';margin-left:auto;color:var(--muted);font-size:.8rem;}
  details[open] .sim-params-summary::after{content:'▾';}
  .sim-params-panel[open] .sim-params-summary{border-bottom:1px solid var(--border);}
  .sim-params-body{padding:16px 20px 18px;}
  .spa-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;}
  .spa-field{min-width:0;}
  .spa-field label{display:block;font-size:.67rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:4px;}
  .spa-field input,.spa-field select{width:100%;box-sizing:border-box;padding:7px 9px;border-radius:7px;border:1px solid var(--border);background:var(--bg);color:var(--text);font-size:.87rem;}
  .spa-sliders{margin-top:14px;display:grid;grid-template-columns:1fr 1fr;gap:14px;}
  @media(max-width:600px){.spa-sliders{grid-template-columns:1fr;}}
  .spa-slider-wrap label{display:block;font-size:.76rem;color:var(--muted);margin-bottom:6px;}
  .spa-sl-val{font-weight:400;color:var(--primary);}
  .spa-slider-wrap input[type=range]{width:100%;accent-color:var(--accent);}
  .spa-check{display:block;font-size:.84rem;margin-top:12px;cursor:pointer;}
  .spa-actions{margin-top:14px;border-top:1px solid var(--border);padding-top:12px;}
  .sim-page{display:flex;flex-direction:column;gap:18px;}
  .sim-block{background:var(--card);border-radius:12px;padding:18px 20px;border:1px solid var(--border);box-shadow:0 1px 4px rgba(0,0,0,.05);}
  .sim-block-title{font-size:.68rem;font-weight:700;text-transform:uppercase;letter-spacing:.08em;color:var(--secondary);margin-bottom:12px;}
  .sim-cols{display:grid;grid-template-columns:1fr 1fr;gap:18px;}
  @media(max-width:680px){.sim-cols{grid-template-columns:1fr;}}
  .dk-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}
  @media(max-width:900px){.dk-grid{grid-template-columns:repeat(2,1fr);}}
  @media(max-width:500px){.dk-grid{grid-template-columns:1fr 1fr;}}
  .dk{border-radius:10px;padding:16px;border:1px solid var(--border);position:relative;overflow:hidden;transition:transform .1s;}
  .dk:hover{transform:translateY(-1px);}
  .dk::before{content:'';position:absolute;left:0;top:0;bottom:0;width:4px;border-radius:10px 0 0 10px;}
  .dk--good{background:var(--good-bg);border-color:var(--good);} .dk--good::before{background:var(--good);}
  .dk--mid{background:var(--mid-bg);border-color:var(--mid);} .dk--mid::before{background:var(--mid);}
  .dk--bad{background:var(--bad-bg);border-color:var(--bad);} .dk--bad::before{background:var(--bad);}
  .dk-label{font-size:.65rem;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin-bottom:6px;}
  .dk-value{font-size:1.45rem;font-weight:700;line-height:1.15;font-variant-numeric:tabular-nums;}
  .dk--good .dk-value{color:var(--good);} .dk--mid .dk-value{color:var(--mid);} .dk--bad .dk-value{color:var(--bad);}
  .dk-sub{font-size:.72rem;color:var(--muted);margin-top:4px;}
  .rg-wrap{overflow-x:auto;}
  .rg-table{width:100%;border-collapse:collapse;font-size:.86rem;font-variant-numeric:tabular-nums;}
  .rg-table thead th{background:var(--accent);color:rgba(255,255,255,.9);padding:9px 13px;font-size:.67rem;text-transform:uppercase;letter-spacing:.05em;font-weight:700;text-align:right;white-space:nowrap;}
  .rg-table thead th:first-child{text-align:left;}
  .rg-table tbody tr{transition:background .1s;}
  .rg-table tbody tr:hover td{background:rgba(43,69,62,.04)!important;}
  .rg-table td{padding:10px 13px;border-bottom:1px solid var(--border);text-align:right;white-space:nowrap;}
  .rg-table td:first-child{text-align:left;}
  .rg-name{font-weight:600;font-size:.84rem;color:var(--text);}
  .rg-active td{background:rgba(43,69,62,.06)!important;} .rg-active .rg-name{color:var(--accent);}
  .rg-best{background:var(--good-bg)!important;color:var(--good);font-weight:700;}
  .rg-neg{color:var(--bad);}
  .sim-assumptions{background:var(--accent);color:#fff;border-radius:12px;padding:16px 20px;margin-bottom:20px;}
  .sim-assumptions h2{margin:0 0 12px;font-size:.97rem;}
  .sim-ass-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:12px;align-items:start;}
  .sim-ass-grid>div{min-width:0;}
  .sim-ass-grid label{display:block;font-size:.68rem;text-transform:uppercase;letter-spacing:.05em;color:rgba(255,255,255,.7);margin-bottom:4px;}
  .sim-ass-grid input,.sim-ass-grid select{width:100%;box-sizing:border-box;padding:7px 9px;border-radius:7px;border:1px solid rgba(255,255,255,.2);background:rgba(0,0,0,.2);color:#fff;font-size:.87rem;}
  .sim-sliders{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px;}
  .sim-sliders label{display:block;font-size:.75rem;color:rgba(255,255,255,.7);margin-bottom:5px;}
  .sim-sliders input[type=range]{width:100%;accent-color:var(--primary);}
  .res-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:1px;background:var(--border);border-radius:10px;overflow:hidden;margin-top:14px;}
  .res{background:var(--card);padding:12px 14px;}
  .res-lbl{font-size:.68rem;color:var(--muted);text-transform:uppercase;letter-spacing:.04em;margin-bottom:4px;}
  .res-val{font-size:1.08rem;font-weight:700;font-variant-numeric:tabular-nums;} .res-sub{font-size:.71rem;color:var(--muted);margin-top:2px;}
  .dpe-warn{margin-top:12px;background:var(--bad-bg);border:1px solid #f5b8b8;color:var(--bad);padding:10px 14px;border-radius:8px;font-size:.82rem;}
  .finplan{margin-top:14px;border-top:1px dashed var(--border);padding-top:12px;}
  .finplan h4{margin:0 0 8px;font-size:.76rem;text-transform:uppercase;letter-spacing:.04em;color:var(--muted);}
  .finplan-row{display:flex;justify-content:space-between;font-size:.84rem;padding:3px 0;border-bottom:1px solid #f8f0f0;}
  .finplan-row.total{font-weight:700;border-bottom:none;border-top:2px solid var(--accent);margin-top:4px;padding-top:8px;}
  .cmp-wrap{overflow-x:auto;}
  .cmp-table{width:100%;border-collapse:collapse;font-size:.85rem;}
  .cmp-table th,.cmp-table td{padding:8px 12px;text-align:right;border-bottom:1px solid #f0e8e8;white-space:nowrap;}
  .cmp-table th:first-child,.cmp-table td:first-child{text-align:left;font-weight:600;color:var(--muted);position:sticky;left:0;background:var(--card);}
  .cmp-table thead th{background:#f8f3ef;font-size:.75rem;color:var(--muted);}
  .cmp-table td.best{background:var(--good-bg);font-weight:700;color:var(--good);}
  .scorechip{display:inline-block;min-width:30px;padding:2px 8px;border-radius:8px;font-weight:700;font-size:.84rem;}
  .sc-high{background:var(--good-bg);color:var(--good);} .sc-mid{background:var(--mid-bg);color:var(--mid);} .sc-low{background:var(--bad-bg);color:var(--bad);}
  .sim-details{background:var(--card);border-radius:12px;border:1px solid var(--border);box-shadow:0 1px 4px rgba(0,0,0,.04);margin-bottom:14px;}
  .sim-details>summary{cursor:pointer;padding:14px 18px;font-weight:700;font-size:.92rem;list-style:none;color:var(--accent);}
  .sim-details>summary::-webkit-details-marker{display:none;}
  .sim-details>summary::before{content:'▸  ';color:var(--primary);}
  .sim-details[open]>summary::before{content:'▾  ';} .sim-details[open]>summary{border-bottom:1px solid var(--border);}
  .sim-details>div{padding:10px 18px 18px;}
  .sim-empty{color:var(--muted);font-size:.9rem;padding:40px;text-align:center;background:var(--card);border-radius:12px;border:1px solid var(--border);}
  .sim-fields{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:12px;margin:14px 0 4px;}
  .sim-fields label{display:block;font-size:.68rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:4px;}
  .sim-fields input,.sim-fields select{width:100%;box-sizing:border-box;padding:7px 9px;border:1px solid var(--border);border-radius:7px;font-size:.87rem;background:var(--card);color:var(--text);}
  .btn-primary{background:var(--accent);color:#fff;border:1px solid var(--accent);padding:9px 18px;border-radius:8px;cursor:pointer;font-weight:600;font-size:.88rem;}
  .btn-primary:hover{background:#3a5a52;}
  .btn-ghost{background:var(--card);border:1px solid var(--border);padding:7px 16px;border-radius:8px;cursor:pointer;font-size:.86rem;color:var(--text);}
  .btn-ghost:hover{border-color:var(--primary);}
  `;
  const s = document.createElement('style');
  s.id = 'sim-styles'; s.textContent = css;
  document.head.appendChild(s);
}

function fmtPct(n, dec) { return n == null || isNaN(n) ? 'N/A' : n.toFixed(dec == null ? 1 : dec) + '%'; }
function scoreChip(s) {
  const cls = s >= 80 ? 'sc-high' : s >= 60 ? 'sc-mid' : 'sc-low';
  return `<span class="scorechip ${cls}">${s}</span>`;
}

function buildComparateur() {
  injectSimStyles();
  const c = document.getElementById('view-comparateur');
  const g = getSimGlobal();

  // Biens candidats : on écarte produits structurés et zones exclues
  const candidates = rows.filter(r => !isStructured(r) && !isExcludedLocG(getDisplayVal(r, 'location')) && r.surface && r.price)
    .sort((a, b) => getDisplayVal(b, 'score') - getDisplayVal(a, 'score'));
  const selected = getSimSelected().filter(id => candidates.some(r => r.id === id));

  // — Hypothèses globales —
  const assum = (key, label, step, suffix) =>
    `<div><label>${label}</label><input type="number" step="${step || 'any'}" value="${g[key]}" oninput="updateSimGlobal('${key}', this.value)">${suffix || ''}</div>`;
  let assumptions = `
    <div class="sim-assumptions">
      <h2>💰 Hypothèses de financement <span style="font-weight:400;color:#9ca3af;font-size:.82rem">— appliquées à tous les biens</span></h2>
      <div class="sim-ass-grid">
        ${assum('apportPct', 'Apport (%)', '1')}
        ${assum('taux', "Taux crédit (%)", '0.1')}
        ${assum('duree', 'Durée (ans)', '1')}
        ${assum('fraisNotairePct', 'Frais notaire (%)', '0.5')}
        ${assum('gestionPct', 'Gestion locative (%)', '1')}
        ${assum('vacancePct', 'Vacance locative (%)', '1')}
        ${assum('assurancePNO', 'Assurance PNO (€/an)', '10')}
      </div>
    </div>`;

  // — Sélecteur de biens —
  let picker = '<div class="sim-picker"><h3>Biens à simuler</h3>';
  for (const r of candidates) {
    const loc = getDisplayVal(r, 'location');
    const checked = selected.includes(r.id) ? 'checked' : '';
    picker += `
      <label class="sim-item">
        <input type="checkbox" ${checked} onchange="toggleSimBien('${r.id}')">
        <span>
          <span class="si-loc">${loc || '?'}</span> ${scoreChip(getDisplayVal(r, 'score'))}<br>
          <span class="si-meta">${_eur(r.price)} · ${r.surface} m²</span>
        </span>
      </label>`;
  }
  picker += '</div>';

  // — Cartes par bien —
  let cards = '';
  if (!selected.length) {
    cards = '<div class="sim-empty">👈 Sélectionne un ou plusieurs biens à gauche pour lancer la simulation.</div>';
  } else {
    for (const id of selected) {
      const r = candidates.find(x => x.id === id);
      if (r) cards += simCard(r, g);
    }
    if (selected.length >= 2) cards += simCompare(selected.map(id => candidates.find(x => x.id === id)).filter(Boolean), g);
  }

  c.innerHTML = `
    <p class="sim-intro">Affine le scoring avec tes hypothèses réelles : prix négocié, travaux, meubles, financement. Les calculs sont sauvegardés automatiquement.</p>
    ${assumptions}
    <div class="sim-layout">
      ${picker}
      <div>${cards}</div>
    </div>`;
}

function simCard(r, g) {
  const b = getSimBien(r);
  const s = computeSim(r, g, b);
  const id = r.id;
  const loc = s.loc;
  const url = (r.urls && r.urls[0]) || r.url;
  const cfClass = s.cashflowMois >= 0 ? 'pos' : 'neg';
  const cocClass = (s.coc || 0) >= 0 ? 'pos' : 'neg';

  const fld = (key, label, val, step, type) =>
    `<div><label>${label}</label><input type="${type || 'number'}" step="${step || 'any'}" value="${val}" oninput="updateSimBien('${id}','${key}', this.value)"></div>`;
  const dpeOpts = ['', 'A', 'B', 'C', 'D', 'E', 'F', 'G'].map(d => `<option value="${d}" ${b.dpe === d ? 'selected' : ''}>${d || '—'}</option>`).join('');

  let dpeWarn = '';
  if (b.dpe === 'F' || b.dpe === 'G') {
    dpeWarn = `<div class="dpe-warn">⚠️ DPE ${b.dpe} (passoire thermique). Location interdite progressivement (G dès 2025, F en 2028). Prévois un budget travaux énergétiques et une décote à la revente.</div>`;
  }

  const decoteVsMarche = CFG.market_price_per_m2[loc]
    ? ((s.prixRevientM2 - CFG.market_price_per_m2[loc]) / CFG.market_price_per_m2[loc]) * 100 : null;

  return `
  <div class="sim-card">
    <div class="sim-card-head">
      <h2>${loc || '?'} · ${r.rooms ? r.rooms + ' pièces · ' : ''}${r.surface} m²</h2>
      <span class="sub">Score initial ${scoreChip(s.scoreInitial)} → affiné ${scoreChip(s.scoreAffine)} · <a href="${url}" target="_blank">voir l'annonce →</a></span>
    </div>
    <div class="sim-fields">
      ${fld('prix', 'Prix négocié (€)', b.prix, '1000')}
      ${fld('travaux', 'Travaux (€)', b.travaux, '1000')}
      ${fld('meubles', 'Meubles (€)', b.meubles, '500')}
      ${fld('loyer', 'Loyer (€/mois)', b.loyer, '10')}
      ${fld('charges', 'Charges non récup. (€/an)', b.charges, '50')}
      ${fld('taxe', 'Taxe foncière (€/an)', b.taxe, '50')}
      <div><label>DPE</label><select oninput="updateSimBien('${id}','dpe', this.value)">${dpeOpts}</select></div>
    </div>
    ${dpeWarn}
    <div class="res-grid">
      <div class="res"><div class="res-lbl">Coût de revient</div><div class="res-val">${_eur(s.coutTotal)}</div><div class="res-sub">${_eur(s.prixRevientM2)}/m² ${decoteVsMarche != null ? _pctPill(decoteVsMarche) : ''}</div></div>
      <div class="res"><div class="res-lbl">Mensualité crédit</div><div class="res-val">${_eur(s.mensualite)}</div><div class="res-sub">emprunt ${_eur(s.emprunt)}</div></div>
      <div class="res"><div class="res-lbl">Cashflow / mois</div><div class="res-val ${cfClass}">${s.cashflowMois >= 0 ? '+' : ''}${_eur(s.cashflowMois)}</div><div class="res-sub">${s.cashflowAn >= 0 ? '+' : ''}${_eur(s.cashflowAn)}/an</div></div>
      <div class="res"><div class="res-lbl">Rendement net</div><div class="res-val">${fmtPct(s.rdtNet)}</div><div class="res-sub">brut ${fmtPct(s.rdtBrut)}</div></div>
      <div class="res"><div class="res-lbl">Cash-on-cash</div><div class="res-val ${cocClass}">${fmtPct(s.coc)}</div><div class="res-sub">/ apport ${_eur(s.apport)}</div></div>
      <div class="res"><div class="res-lbl">Score affiné</div><div class="res-val">${scoreChip(s.scoreAffine)}</div><div class="res-sub">initial ${s.scoreInitial}</div></div>
    </div>
    <div class="finplan">
      <h4>Plan de financement</h4>
      <div class="finplan-row"><span>Prix d'achat négocié</span><span>${_eur(s.prix)}</span></div>
      <div class="finplan-row"><span>Frais de notaire (${g.fraisNotairePct}%)</span><span>${_eur(s.notaire)}</span></div>
      <div class="finplan-row"><span>Travaux</span><span>${_eur(+b.travaux || 0)}</span></div>
      <div class="finplan-row"><span>Meubles</span><span>${_eur(+b.meubles || 0)}</span></div>
      <div class="finplan-row total"><span>Coût total de l'opération</span><span>${_eur(s.coutTotal)}</span></div>
      <div class="finplan-row"><span>Apport (${g.apportPct}%)</span><span>${_eur(s.apport)}</span></div>
      <div class="finplan-row"><span>Montant emprunté · ${g.duree} ans @ ${g.taux}%</span><span>${_eur(s.emprunt)}</span></div>
      <div class="finplan-row"><span>Coût total du crédit (intérêts)</span><span>${_eur(s.coutCredit)}</span></div>
    </div>
  </div>`;
}

function simCompare(list, g) {
  const sims = list.map(r => ({ r, s: computeSim(r, getSimGlobal(), getSimBien(r)) }));
  // Définition des lignes : label, accesseur, formateur, sens (1 = plus grand = mieux, -1 = plus petit = mieux)
  const lines = [
    ['Coût de revient', x => x.coutTotal, v => _eur(v), -1],
    ['Prix de revient /m²', x => x.prixRevientM2, v => _eur(v) + '/m²', -1],
    ['Loyer annuel', x => x.loyerAn, v => _eur(v), 1],
    ['Mensualité crédit', x => x.mensualite, v => _eur(v), -1],
    ['Cashflow /mois', x => x.cashflowMois, v => (v >= 0 ? '+' : '') + _eur(v), 1],
    ['Rendement brut', x => x.rdtBrut, v => fmtPct(v), 1],
    ['Rendement net', x => x.rdtNet, v => fmtPct(v), 1],
    ['Cash-on-cash', x => x.coc, v => fmtPct(v), 1],
    ['Apport nécessaire', x => x.apport, v => _eur(v), -1],
    ['Score affiné', x => x.scoreAffine, v => String(v), 1],
  ];
  let head = '<tr><th>Critère</th>' + sims.map(o => `<th>${o.s.loc}<br><span style="font-weight:400;color:#9ca3af">${o.r.surface} m²</span></th>`).join('') + '</tr>';
  let body = '';
  for (const [label, acc, fmt, dir] of lines) {
    const vals = sims.map(o => acc(o.s));
    const valid = vals.filter(v => v != null && !isNaN(v));
    const best = valid.length ? (dir > 0 ? Math.max(...valid) : Math.min(...valid)) : null;
    body += `<tr><td>${label}</td>` + sims.map((o, i) => {
      const v = vals[i];
      const isBest = best != null && v != null && Math.abs(v - best) < 1e-9;
      return `<td class="${isBest ? 'best' : ''}">${v == null || isNaN(v) ? 'N/A' : fmt(v)}</td>`;
    }).join('') + '</tr>';
  }
  return `<div class="sim-card"><div class="sim-card-head"><h2>📊 Comparateur</h2><span class="sub">meilleure valeur par ligne en vert</span></div><div class="cmp-wrap"><table class="cmp-table"><thead>${head}</thead><tbody>${body}</tbody></table></div></div>`;
}

// — Handlers (re-render léger) —
function updateSimGlobal(key, val) {
  const g = getSimGlobal(); g[key] = parseFloat(val) || 0; saveSimGlobal(g);
  clearTimeout(window._simT); window._simT = setTimeout(buildComparateur, 250);
}
function updateSimBien(id, key, val) {
  const all = getSimBienRaw();
  const r = rows.find(x => x.id === id);
  const b = all[id] || getSimBien(r);
  b[key] = (key === 'dpe') ? val : (parseFloat(val) || 0);
  all[id] = b; localStorage.setItem('simBiens', JSON.stringify(all));
  clearTimeout(window._simT); window._simT = setTimeout(buildComparateur, 250);
}
function toggleSimBien(id) {
  const sel = getSimSelected();
  const i = sel.indexOf(id);
  if (i >= 0) sel.splice(i, 1); else sel.push(id);
  saveSimSelected(sel); buildComparateur();
}

// ═══════════════════════════════════════════════════════════════════════
//  ONGLET SIMULATION FISCALE — régime, compte de résultat, cashflow réel, graphiques
// ═══════════════════════════════════════════════════════════════════════
const REGIMES = [
  { id: 'lmnp_reel',  label: 'LMNP meublé — réel (amortissements)' },
  { id: 'lmnp_micro', label: 'LMNP meublé — micro-BIC (-50%)' },
  { id: 'nu_reel',    label: 'Nom propre nu — réel (foncier)' },
  { id: 'nu_micro',   label: 'Nom propre nu — micro-foncier (-30%)' },
  { id: 'sci_ir',     label: 'SCI à l&#39;IR (translucide)' },
  { id: 'sci_is',     label: 'SCI à l&#39;IS (amortissements)' },
];
const TMI_OPTIONS = [0, 11, 30, 41, 45];
const PREL_SOCIAUX = 17.2;

function getSimf() {
  return Object.assign({ regime: 'lmnp_reel', tmi: 30, reventeAnnee: null, bienId: null, apportPct: null, prix: null,
    loyerIndexPct: 1.6, revaloPrixPct: 2.0, fraisVentePct: 0, sciSortieCash: true, fairValueOverride: null },
    JSON.parse(localStorage.getItem('simFiscal') || '{}'));
}
function saveSimf(s) { localStorage.setItem('simFiscal', JSON.stringify(s)); }

function buildAmort(principal, ratePct, years) {
  const r = ratePct / 100 / 12, m = pmt(principal, ratePct, years);
  const out = []; let bal = principal;
  for (let y = 1; y <= years; y++) {
    let interest = 0, capital = 0;
    for (let k = 0; k < 12; k++) { const i = bal * r, c = m - i; interest += i; capital += c; bal -= c; }
    out.push({ year: y, interest, capital, balance: Math.max(0, bal) });
  }
  return out;
}

function taxYear(regime, loyerAn, chargesDeduc, interest, amortBien, amortMob, tmi, carry) {
  let tax = 0, base = 0, newCarry = carry, amortShown = 0;
  if (regime === 'nu_micro') { base = loyerAn * 0.7; tax = base * (tmi + PREL_SOCIAUX) / 100; }
  else if (regime === 'nu_reel' || regime === 'sci_ir') {
    base = loyerAn - chargesDeduc - interest;
    if (base >= 0) tax = base * (tmi + PREL_SOCIAUX) / 100;
    else tax = -(Math.min(-base, 10700) * tmi / 100); // déficit foncier : économie d'impôt (simplifié)
  }
  else if (regime === 'lmnp_micro') { base = loyerAn * 0.5; tax = base * (tmi + PREL_SOCIAUX) / 100; }
  else if (regime === 'lmnp_reel') {
    const before = loyerAn - chargesDeduc - interest, avail = amortBien + amortMob + carry;
    if (before <= 0) { tax = 0; newCarry = carry + amortBien + amortMob; base = before; }
    else { amortShown = Math.min(before, avail); base = before - amortShown; tax = Math.max(0, base) * (tmi + PREL_SOCIAUX) / 100; newCarry = avail - amortShown; }
  }
  else if (regime === 'sci_is') {
    base = loyerAn - chargesDeduc - interest - amortBien - amortMob; amortShown = amortBien + amortMob;
    if (base > 0) tax = Math.min(base, 42500) * 0.15 + Math.max(0, base - 42500) * 0.25;
  }
  return { tax, base, newCarry, amortShown };
}

// Plus-value des particuliers (nu, LMNP, SCI IR) avec abattements pour durée de détention.
function plusValueParticulier(prixVente, baseAcq, annee, amortReintegre) {
  let pvBrute = prixVente - baseAcq + (amortReintegre || 0);
  if (pvBrute <= 0) return { pvBrute, ir: 0, ps: 0, impot: 0 };
  let abIR = annee <= 5 ? 0 : annee < 22 ? (annee - 5) * 0.06 : 1; abIR = Math.min(1, abIR);
  let abPS;
  if (annee <= 5) abPS = 0;
  else if (annee <= 21) abPS = (annee - 5) * 0.0165;
  else if (annee === 22) abPS = 16 * 0.0165 + 0.016;
  else if (annee < 30) abPS = 16 * 0.0165 + 0.016 + (annee - 22) * 0.09;
  else abPS = 1;
  abPS = Math.min(1, abPS);
  const ir = pvBrute * (1 - abIR) * 0.19, ps = pvBrute * (1 - abPS) * 0.172;
  return { pvBrute, ir, ps, impot: ir + ps };
}

// VAN et TRI (IRR par bissection) d'un flux de trésorerie annuel.
function npv(cfs, rate) { return cfs.reduce((s, c, i) => s + c / Math.pow(1 + rate, i), 0); }
function irr(cfs) {
  let lo = -0.9, hi = 1.0, fLo = npv(cfs, lo), fHi = npv(cfs, hi);
  if (fLo * fHi > 0) return null;
  for (let k = 0; k < 200 && (hi - lo) > 1e-6; k++) {
    const mid = (lo + hi) / 2, f = npv(cfs, mid);
    if (fLo * f <= 0) { hi = mid; } else { lo = mid; fLo = f; }
  }
  return (lo + hi) / 2;
}

function computeFiscal(r, g, b, opts) {
  const prix = opts.prix != null ? opts.prix : (+b.prix || 0);
  const notaire = prix * (+g.fraisNotairePct) / 100;
  const travaux = +b.travaux || 0, meubles = +b.meubles || 0;
  const coutTotal = prix + notaire + travaux + meubles;
  const apportPct = opts.apportPct != null ? opts.apportPct : +g.apportPct;
  const apport = coutTotal * apportPct / 100;
  const emprunt = Math.max(0, coutTotal - apport);
  const dureePret = +g.duree;
  const sched = buildAmort(emprunt, +g.taux, dureePret);
  const reventeAnnee = opts.reventeAnnee || opts.dureeAnalyse || dureePret;
  const years = Math.max(1, Math.min(reventeAnnee, 40));
  const idx = (opts.loyerIndexPct || 0) / 100, revalo = (opts.revaloPrixPct || 0) / 100;
  const loyerBaseAn = (+b.loyer || 0) * 12 * (1 - (+g.vacancePct || 0) / 100);
  const amortBien = prix * 0.85 / 30;
  const usesAmort = (opts.regime === 'lmnp_reel' || opts.regime === 'sci_is');
  let carry = 0, cum = 0, amortBooked = 0, amortDeduc = 0; const rowsY = [];
  for (let y = 1; y <= years; y++) {
    const sc = sched[y - 1] || { interest: 0, capital: 0, balance: 0 };
    const interest = y <= dureePret ? sc.interest : 0;
    const capital = y <= dureePret ? sc.capital : 0;
    const loyerY = loyerBaseAn * Math.pow(1 + idx, y - 1);
    const gestionY = (+b.loyer || 0) * 12 * Math.pow(1 + idx, y - 1) * (+g.gestionPct || 0) / 100;
    const chargesY = gestionY + (+g.assurancePNO || 0) + (+b.taxe || 0) + (+b.charges || 0);
    const aB = y <= 30 ? amortBien : 0, aM = (meubles > 0 && y <= 7) ? meubles / 7 : 0;
    const f = taxYear(opts.regime, loyerY, chargesY, interest, aB, aM, +opts.tmi, carry);
    carry = f.newCarry;
    amortBooked += aB + aM; amortDeduc += f.amortShown;
    const cashNet = loyerY - chargesY - (interest + capital) - f.tax;
    cum += cashNet;
    rowsY.push({ y, loyerAn: loyerY, charges: chargesY, interest, capital, amort: usesAmort ? f.amortShown : 0, resultat: f.base, impot: f.tax, cashNet, cum });
  }
  const cashAvg = rowsY.reduce((s, x) => s + x.cashNet, 0) / years;
  const impotAvg = rowsY.reduce((s, x) => s + x.impot, 0) / years;
  // ── Revente à l'année 'years' ──
  const saleYear = years;
  // Base de revente = fair value estimée (valeur de marché), pas le prix négocié → la décote à l'achat est captée.
  const baseRevente = (opts.fairValueBase != null && opts.fairValueBase > 0) ? opts.fairValueBase : prix;
  const prixVente = (opts.prixVenteCible != null && opts.prixVenteCible > 0) ? opts.prixVenteCible : baseRevente * Math.pow(1 + revalo, saleYear);
  const crd = (saleYear <= dureePret && sched[saleYear - 1]) ? sched[saleYear - 1].balance : 0;
  const fraisVente = prixVente * (opts.fraisVentePct || 0) / 100;
  let revente;
  if (opts.regime === 'sci_is') {
    const vnc = coutTotal - amortBooked;
    const pvC = Math.max(0, prixVente - vnc);
    const isPV = Math.min(pvC, 42500) * 0.15 + Math.max(0, pvC - 42500) * 0.25;
    const cashSCI = prixVente - fraisVente - crd - isPV;
    const netVendeur = opts.sciSortieCash ? (apport + Math.max(0, cashSCI - apport) * 0.70) : cashSCI;
    revente = { prixVente, crd, fraisVente, pvBase: pvC, impotPV: isPV, netVendeur, cashSCI, vnc, modeIS: true };
  } else {
    const reint = opts.regime === 'lmnp_reel' ? amortDeduc : 0;
    const p = plusValueParticulier(prixVente - fraisVente, prix + notaire + travaux, saleYear, reint);
    revente = { prixVente, crd, fraisVente, pvBase: p.pvBrute, impotPV: p.impot, ir: p.ir, ps: p.ps, netVendeur: prixVente - fraisVente - crd - p.impot, modeIS: false };
  }
  const bilan = cum + revente.netVendeur;
  const gainNet = bilan - apport;
  // Flux pour TRI / VAN : -apport en t0, cashflows annuels, + net vendeur l'année de revente.
  const cf = [-apport];
  for (const rr of rowsY) cf.push(rr.cashNet);
  cf[cf.length - 1] += revente.netVendeur;
  const tri = irr(cf);
  const rendAlt = (opts.rendAltPct != null ? opts.rendAltPct : 5) / 100;
  const van = npv(cf, rendAlt);
  return { prix, coutTotal, notaire, apport, emprunt, apportPct, dureePret, years, saleYear, rowsY, cashAvg, cum, impotAvg, revente, bilan, gainNet, tri, van, multiple: apport > 0 ? bilan / apport : null };
}

// ── Graphiques SVG (sans dépendance externe) ──
function _sc(v, dmin, dmax, rmin, rmax) { return dmax === dmin ? (rmin + rmax) / 2 : rmin + (v - dmin) / (dmax - dmin) * (rmax - rmin); }
function chartYears(rowsY) {
  const w = 560, h = 220, pl = 52, pr = 50, pt = 14, pb = 24;
  const cn = rowsY.map(r => r.cashNet), cum = rowsY.map(r => r.cum);
  let ymin = Math.min(0, ...cn), ymax = Math.max(0, ...cn); if (ymin === ymax) ymax = ymin + 1;
  let cmin = Math.min(0, ...cum), cmax = Math.max(0, ...cum); if (cmin === cmax) cmax = cmin + 1;
  const n = rowsY.length, step = (w - pl - pr) / n, bw = step * 0.6;
  const X = i => pl + (i + 0.5) * step, Y = v => _sc(v, ymin, ymax, h - pb, pt), Yc = v => _sc(v, cmin, cmax, h - pb, pt);
  const y0 = Y(0);
  let bars = ''; rowsY.forEach((r, i) => { const y = Y(r.cashNet), top = Math.min(y0, y); bars += `<rect x="${(X(i) - bw / 2).toFixed(1)}" y="${top.toFixed(1)}" width="${bw.toFixed(1)}" height="${Math.max(1, Math.abs(y - y0)).toFixed(1)}" fill="${r.cashNet >= 0 ? '#10b981' : '#ef4444'}" opacity="0.85"/>`; });
  const cumPath = rowsY.map((r, i) => (i ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Yc(r.cum).toFixed(1)).join(' ');
  let xl = ''; rowsY.forEach((r, i) => { if (i % Math.ceil(n / 10) === 0 || i === n - 1) xl += `<text x="${X(i).toFixed(1)}" y="${h - pb + 14}" text-anchor="middle" font-size="9" fill="#9ca3af">${r.y}</text>`; });
  return `<svg viewBox="0 0 ${w} ${h}" width="100%">${bars}<path d="${cumPath}" fill="none" stroke="#6366f1" stroke-width="2"/><line x1="${pl}" y1="${y0.toFixed(1)}" x2="${w - pr}" y2="${y0.toFixed(1)}" stroke="#cbd5e1"/><text x="${pl - 6}" y="${(Y(ymax) + 3).toFixed(1)}" text-anchor="end" font-size="9" fill="#9ca3af">${_eur(ymax)}</text><text x="${pl - 6}" y="${(Y(ymin) + 3).toFixed(1)}" text-anchor="end" font-size="9" fill="#9ca3af">${_eur(ymin)}</text><text x="${w - pr + 4}" y="${(Yc(cmax) + 3).toFixed(1)}" font-size="9" fill="#6366f1">${_eur(cmax)} cum.</text>${xl}</svg>`;
}
function chartLine(points, o) {
  o = o || {}; const w = 340, h = 190, pl = 50, pr = 12, pt = 14, pb = 28;
  const xs = points.map(p => p.x), ys = points.map(p => p.y);
  let ymin = Math.min(0, ...ys), ymax = Math.max(0, ...ys); if (ymin === ymax) ymax = ymin + 1;
  const xmin = Math.min(...xs), xmax = Math.max(...xs);
  const X = v => _sc(v, xmin, xmax, pl, w - pr), Y = v => _sc(v, ymin, ymax, h - pb, pt);
  const path = points.map((p, i) => (i ? 'L' : 'M') + X(p.x).toFixed(1) + ' ' + Y(p.y).toFixed(1)).join(' ');
  const y0 = Y(0);
  let xl = ''; points.forEach((p, i) => { if (i % Math.ceil(points.length / 5) === 0 || i === points.length - 1) xl += `<text x="${X(p.x).toFixed(1)}" y="${h - pb + 14}" text-anchor="middle" font-size="9" fill="#9ca3af">${o.xfmt ? o.xfmt(p.x) : p.x}</text>`; });
  let mk = ''; if (o.markerX != null) { const mx = X(o.markerX); mk = `<line x1="${mx.toFixed(1)}" y1="${pt}" x2="${mx.toFixed(1)}" y2="${h - pb}" stroke="#2563eb" stroke-dasharray="3 3"/>`; }
  return `<svg viewBox="0 0 ${w} ${h}" width="100%">${mk}<line x1="${pl}" y1="${y0.toFixed(1)}" x2="${w - pr}" y2="${y0.toFixed(1)}" stroke="#cbd5e1"/><text x="${pl - 6}" y="${(Y(ymax) + 3).toFixed(1)}" text-anchor="end" font-size="9" fill="#9ca3af">${_eur(ymax)}</text><text x="${pl - 6}" y="${(Y(ymin) + 3).toFixed(1)}" text-anchor="end" font-size="9" fill="#9ca3af">${_eur(ymin)}</text><path d="${path}" fill="none" stroke="${o.color || '#2563eb'}" stroke-width="2"/>${xl}</svg>`;
}
function chartHeatmap(xs, ys, matrix, o) {
  o = o || {}; const w = 560, h = 250, pl = 72, pr = 12, pt = 12, pb = 36;
  const flat = matrix.flat(); let vmin = Math.min(...flat), vmax = Math.max(...flat);
  const cw = (w - pl - pr) / xs.length, ch = (h - pt - pb) / ys.length;
  const color = v => v >= 0
    ? `rgb(${Math.round(209 - 120 * (vmax > 0 ? v / vmax : 0))},${Math.round(250 - 30 * (vmax > 0 ? v / vmax : 0))},${Math.round(229 - 130 * (vmax > 0 ? v / vmax : 0))})`
    : `rgb(254,${Math.round(226 - 110 * (vmin < 0 ? v / vmin : 0))},${Math.round(226 - 110 * (vmin < 0 ? v / vmin : 0))})`;
  let cells = '';
  for (let iy = 0; iy < ys.length; iy++) for (let ix = 0; ix < xs.length; ix++) {
    const v = matrix[iy][ix], x = pl + ix * cw, y = pt + iy * ch;
    cells += `<rect x="${x.toFixed(1)}" y="${y.toFixed(1)}" width="${cw.toFixed(1)}" height="${ch.toFixed(1)}" fill="${color(v)}" stroke="#fff"/><text x="${(x + cw / 2).toFixed(1)}" y="${(y + ch / 2 + 3).toFixed(1)}" text-anchor="middle" font-size="8" fill="#374151">${(Math.round(v / 100) / 10)}k</text>`;
  }
  let xl = ''; xs.forEach((xv, ix) => xl += `<text x="${(pl + (ix + 0.5) * cw).toFixed(1)}" y="${h - pb + 16}" text-anchor="middle" font-size="9" fill="#6b7280">${o.xfmt ? o.xfmt(xv) : xv}</text>`);
  let yl = ''; ys.forEach((yv, iy) => yl += `<text x="${pl - 6}" y="${(pt + (iy + 0.5) * ch + 3).toFixed(1)}" text-anchor="end" font-size="9" fill="#6b7280">${o.yfmt ? o.yfmt(yv) : yv}</text>`);
  return `<svg viewBox="0 0 ${w} ${h}" width="100%">${cells}${xl}${yl}<text x="${(pl + (w - pl - pr) / 2).toFixed(1)}" y="${h - 4}" text-anchor="middle" font-size="9" fill="#9ca3af">${o.xtitle || ''}</text></svg>`;
}

// Fair value par commune : teste plusieurs modèles sur les biens de la commune et garde le meilleur (R²).
function fairValueModel(loc) {
  const pts = rows.filter(r => !isStructured(r) && getDisplayVal(r, 'location') === loc && r.surface > 0 && r.price > 0)
    .map(r => ({ s: r.surface, p: r.price }));
  const n = pts.length;
  if (n < 3) {
    const ref = (CFG.market_price_per_m2 || {})[loc];
    return ref ? { predict: s => s * ref, label: 'prix marché (config)', r2: null, n, ppm: ref } : null;
  }
  const ybar = pts.reduce((a, x) => a + x.p, 0) / n;
  const r2of = predict => { let ssRes = 0, ssTot = 0; for (const x of pts) { const e = x.p - predict(x.s); ssRes += e * e; ssTot += (x.p - ybar) ** 2; } return ssTot > 0 ? 1 - ssRes / ssTot : 0; };
  // A : médiane €/m² (robuste)
  const ppms = pts.map(x => x.p / x.s).sort((a, b) => a - b);
  const med = ppms.length % 2 ? ppms[(ppms.length - 1) / 2] : (ppms[ppms.length / 2 - 1] + ppms[ppms.length / 2]) / 2;
  const A = { predict: s => s * med, label: 'médiane €/m²', r2: r2of(s => s * med), n };
  // B : régression proportionnelle (prix = a·surface)
  const sxx = pts.reduce((a, x) => a + x.s * x.s, 0), sxy = pts.reduce((a, x) => a + x.s * x.p, 0);
  const aProp = sxx ? sxy / sxx : med;
  const B = { predict: s => s * aProp, label: 'régression €/m²', r2: r2of(s => s * aProp), n };
  // C : régression linéaire (prix = a·surface + b)
  const mx = pts.reduce((a, x) => a + x.s, 0) / n, my = ybar;
  let num = 0, den = 0; for (const x of pts) { num += (x.s - mx) * (x.p - my); den += (x.s - mx) ** 2; }
  const aLin = den ? num / den : 0, bLin = my - aLin * mx;
  const C = { predict: s => aLin * s + bLin, label: 'régression linéaire', r2: r2of(s => aLin * s + bLin), n };
  // meilleur modèle par R² (linéaire seulement si pente positive et intercept raisonnable)
  const cands = [A, B];
  if (aLin > 0 && bLin > -ybar) cands.push(C);
  cands.sort((x, y) => y.r2 - x.r2);
  return cands[0];
}

function updateSimGlobalSim(key, val) {
  const g = getSimGlobal(); g[key] = parseFloat(val) || 0; saveSimGlobal(g);
  clearTimeout(window._simfT); window._simfT = setTimeout(buildSimulationFiscale, 250);
}

function buildSimulationFiscale() {
  injectSimStyles();
  const c = document.getElementById('view-simulation');
  const g = getSimGlobal();
  const simf = getSimf();
  const candidates = rows.filter(r => !isStructured(r) && !isExcludedLocG(getDisplayVal(r, 'location')) && r.surface && r.price)
    .sort((a, b) => getDisplayVal(b, 'score') - getDisplayVal(a, 'score'));
  if (!candidates.length) { c.innerHTML = '<div class="sim-empty">Aucun bien à simuler.</div>'; return; }
  const bien = candidates.find(r => r.id === simf.bienId) || candidates[0];
  const b = getSimBien(bien);
  const basePrix = +b.prix || 0;
  const fvModel = fairValueModel(getDisplayVal(bien, 'location'));
  const fairVal = fvModel ? fvModel.predict(bien.surface) : null;
  const curApport = simf.apportPct != null ? simf.apportPct : +g.apportPct;
  const curPrix = simf.prix != null ? simf.prix : basePrix;
  const reventeAnnee = simf.reventeAnnee || +g.duree;
  const sv = getSolver();
  const rendAlt = sv.rendAltPct;
  const fairBase = (simf.fairValueOverride != null && simf.fairValueOverride > 0) ? simf.fairValueOverride : fairVal;
  const opts = { regime: simf.regime, tmi: simf.tmi, reventeAnnee, apportPct: curApport, prix: curPrix,
    loyerIndexPct: simf.loyerIndexPct, revaloPrixPct: simf.revaloPrixPct, fraisVentePct: simf.fraisVentePct, sciSortieCash: simf.sciSortieCash,
    rendAltPct: sv.rendAltPct, fairValueBase: fairBase };
  const F = computeFiscal(bien, g, b, opts);
  const objOpts = [['tri', 'TRI (rendement annualisé)'], ['van', 'VAN (vs placement alternatif)'], ['gain', 'Gain net total (€)']].map(([v, l]) => `<option value="${v}" ${sv.objective === v ? 'selected' : ''}>${l}</option>`).join('');
  const solverPrixMin = sv.prixMin || Math.round(basePrix * 0.85);
  const regOpts = REGIMES.map(x => `<option value="${x.id}" ${x.id === simf.regime ? 'selected' : ''}>${x.label}</option>`).join('');
  const tmiOpts = TMI_OPTIONS.map(t => `<option value="${t}" ${t === +simf.tmi ? 'selected' : ''}>${t}%</option>`).join('');
  const fvOverridden = (simf.fairValueOverride != null && simf.fairValueOverride > 0);
  const fvSub = fvOverridden ? 'valeur saisie manuellement' : (fvModel ? `modèle « ${fvModel.label} »${fvModel.r2 != null ? ` · R² ${(fvModel.r2 * 100).toFixed(0)}%` : ''} · ${fvModel.n} bien${fvModel.n > 1 ? 's' : ''}` : 'données insuffisantes');
  const decoteAchat = fairBase ? Math.round((curPrix - fairBase) / fairBase * 100) : null;

  // ── Property chips ──
  const chipsHtml = candidates.slice(0, 8).map(r => {
    const sc = getDisplayVal(r, 'score');
    const active = r.id === bien.id;
    const cls = active ? 'prop-chip prop-chip--active' : 'prop-chip';
    return `<button class="${cls}" onclick="setSimf('bienId','${r.id}')">
      <span class="pc-score">${Math.round(sc)}</span>
      <span class="pc-info"><span class="pc-loc">${getDisplayVal(r,'location')}</span><span class="pc-meta">${r.surface}m² · ${_eur(r.price)}</span></span>
    </button>`;
  }).join('');

  // ── All-regimes comparison table ──
  const regCols = ['cashAvg', 'tri', 'van', 'gainNet', 'multiple'];
  const regResults = REGIMES.map(rx => {
    const Fx = computeFiscal(bien, g, b, Object.assign({}, opts, { regime: rx.id }));
    return { id: rx.id, label: rx.label, cashAvg: Fx.cashAvg, tri: Fx.tri, van: Fx.van, gainNet: Fx.gainNet, multiple: Fx.multiple };
  });
  const bestPerCol = {};
  for (const col of regCols) {
    const vals = regResults.map(r => col === 'tri' ? (r[col] != null ? r[col] : -Infinity) : (r[col] ?? -Infinity));
    bestPerCol[col] = Math.max(...vals);
  }
  const regTableRows = regResults.map(r => {
    const active = r.id === simf.regime;
    const cells = regCols.map(col => {
      let val, fmt;
      if (col === 'tri') { val = r.tri; fmt = val != null ? (val * 100).toFixed(1) + '%' : '—'; }
      else if (col === 'multiple') { val = r.multiple; fmt = val != null ? '×' + val.toFixed(2) : '—'; }
      else { val = r[col]; fmt = val != null ? ((val >= 0 ? '+' : '') + _eur(val)) : '—'; }
      const isBest = val != null && val !== -Infinity && Math.abs(val - bestPerCol[col]) < 0.001;
      const cls = isBest ? 'rg-best' : (val != null && val < 0 ? 'rg-neg' : '');
      return `<td class="${cls}">${fmt}</td>`;
    }).join('');
    return `<tr class="${active ? 'rg-active' : ''}" onclick="setSimf('regime','${r.id}')" style="cursor:pointer" title="Sélectionner ${r.label}">
      <td class="rg-name">${active ? '▶ ' : ''}${r.label}</td>${cells}
    </tr>`;
  }).join('');

  // ── Per-year rows ──
  let trs = '';
  for (const r of F.rowsY) {
    trs += `<tr><td>${r.y}</td><td>${_eur(r.loyerAn)}</td><td>${_eur(r.charges)}</td><td>${_eur(r.interest)}</td><td>${r.amort ? _eur(r.amort) : '—'}</td><td>${_eur(r.resultat)}</td><td>${_eur(r.impot)}</td><td class="${r.cashNet >= 0 ? 'pos' : 'neg'}">${r.cashNet >= 0 ? '+' : ''}${_eur(r.cashNet)}</td><td>${_eur(r.cum)}</td></tr>`;
  }

  // ── Charts ──
  const apportRange = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50];
  const apportPts = apportRange.map(a => ({ x: a, y: computeFiscal(bien, g, b, Object.assign({}, opts, { apportPct: a })).cashAvg }));
  const prixRange = []; for (let f = 0.8; f <= 1.2001; f += 0.05) prixRange.push(Math.round(basePrix * f));
  const prixPts = prixRange.map(px => ({ x: px, y: computeFiscal(bien, g, b, Object.assign({}, opts, { prix: px })).cashAvg }));
  const hmApport = [0, 10, 20, 30, 40, 50];
  const hmPrix = [0.85, 0.925, 1.0, 1.075, 1.15].map(f => Math.round(basePrix * f));
  const hmMatrix = hmPrix.map(px => hmApport.map(a => computeFiscal(bien, g, b, Object.assign({}, opts, { apportPct: a, prix: px })).cashAvg));

  const cashMoyen = F.cashAvg / 12;
  const triOk = F.tri != null && F.tri * 100 > 5;
  const vanOk = F.van >= 0;
  const gainOk = F.gainNet >= 0;

  c.innerHTML = `
  <div class="sim-page">
    <p class="sim-intro">Modèle simplifié — pas un conseil fiscal. Cliquer sur un bien ou un régime pour recalculer instantanément.</p>

    <!-- ① Sélecteur de bien -->
    <div class="sim-block">
      <div class="sim-block-title">Bien analysé</div>
      <div class="prop-chips">${chipsHtml}</div>
    </div>

    <!-- ② Paramètres (collapsible) -->
    <details class="sim-params-panel" open>
      <summary class="sim-params-summary">⚙️ Paramètres <span class="sim-params-hint">apport · durée · fiscalité · hypothèses</span></summary>
      <div class="sim-params-body">
        <div class="spa-row">
          <div class="spa-field"><label>Régime fiscal</label><select onchange="setSimf('regime', this.value)">${regOpts}</select></div>
          <div class="spa-field"><label>TMI</label><select onchange="setSimf('tmi', this.value)">${tmiOpts}</select></div>
          <div class="spa-field"><label>Année de revente</label><input type="number" min="1" max="40" value="${reventeAnnee}" oninput="setSimf('reventeAnnee', this.value)"></div>
          <div class="spa-field"><label>Indexation loyer (%/an)</label><input type="number" step="0.1" value="${simf.loyerIndexPct}" oninput="setSimf('loyerIndexPct', this.value)"></div>
          <div class="spa-field"><label>Revalo. prix (%/an)</label><input type="number" step="0.1" value="${simf.revaloPrixPct}" oninput="setSimf('revaloPrixPct', this.value)"></div>
          <div class="spa-field"><label>Frais de vente (%)</label><input type="number" step="0.5" value="${simf.fraisVentePct}" oninput="setSimf('fraisVentePct', this.value)"></div>
        </div>
        <div class="spa-sliders">
          <div class="spa-slider-wrap">
            <label>Apport — <strong>${Math.round(curApport)}%</strong> <span class="spa-sl-val">(${_eur(F.apport)})</span></label>
            <input type="range" min="0" max="50" step="1" value="${curApport}" oninput="setSimf('apportPct', this.value)">
          </div>
          <div class="spa-slider-wrap">
            <label>Prix d'achat — <strong>${_eur(curPrix)}</strong> ${decoteAchat != null ? `<span class="spa-sl-val">${decoteAchat <= 0 ? '↓ ' + (-decoteAchat) + '% sous marché' : '↑ +' + decoteAchat + '% sur marché'}</span>` : ''}</label>
            <input type="range" min="${Math.round(basePrix * 0.7)}" max="${Math.round(basePrix * 1.2)}" step="1000" value="${curPrix}" oninput="setSimf('prix', this.value)">
          </div>
        </div>
        ${simf.regime === 'sci_is' ? `<label class="spa-check"><input type="checkbox" ${simf.sciSortieCash ? 'checked' : ''} onchange="setSimf('sciSortieCash', this.checked)"> Sortir le cash en perso à la revente (flat tax 30%)</label>` : ''}
        <div class="spa-actions"><button class="btn-ghost" onclick="resetSimf()">↺ Réinitialiser apport / prix</button></div>
      </div>
    </details>

    <!-- ③ KPI cards -->
    <div class="sim-block">
      <div class="sim-block-title">Décision — ${REGIMES.find(x=>x.id===simf.regime)?.label || simf.regime}</div>
      <div class="dk-grid">
        <div class="dk ${cashMoyen >= 0 ? 'dk--good' : cashMoyen >= -300 ? 'dk--mid' : 'dk--bad'}">
          <div class="dk-label">Cashflow / mois</div>
          <div class="dk-value">${cashMoyen >= 0 ? '+' : ''}${Math.round(cashMoyen)} €</div>
          <div class="dk-sub">${cashMoyen >= 0 ? 'autofinancé ✅' : 'effort ' + _eur(-cashMoyen) + '/mois'}</div>
        </div>
        <div class="dk ${triOk ? 'dk--good' : 'dk--mid'}">
          <div class="dk-label">TRI annualisé</div>
          <div class="dk-value">${F.tri != null ? (F.tri * 100).toFixed(1) + '%' : '—'}</div>
          <div class="dk-sub">revente an ${F.saleYear} incluse</div>
        </div>
        <div class="dk ${vanOk ? 'dk--good' : 'dk--bad'}">
          <div class="dk-label">VAN vs ${rendAlt}%</div>
          <div class="dk-value">${F.van >= 0 ? '+' : ''}${_eur(F.van)}</div>
          <div class="dk-sub">${vanOk ? 'bat le placement 👍' : 'sous le placement'}</div>
        </div>
        <div class="dk ${gainOk ? 'dk--good' : 'dk--bad'}">
          <div class="dk-label">Gain net total</div>
          <div class="dk-value">${F.gainNet >= 0 ? '+' : ''}${_eur(F.gainNet)}</div>
          <div class="dk-sub">× ${F.multiple ? F.multiple.toFixed(2) : '—'} l'apport</div>
        </div>
      </div>
    </div>

    <!-- ④ Comparaison tous régimes -->
    <div class="sim-block">
      <div class="sim-block-title">Comparaison fiscale — cliquer une ligne pour sélectionner le régime</div>
      <div class="rg-wrap">
        <table class="rg-table">
          <thead><tr><th>Régime</th><th>Cashflow /an</th><th>TRI</th><th>VAN</th><th>Gain net</th><th>Multiple</th></tr></thead>
          <tbody>${regTableRows}</tbody>
        </table>
        <p class="hint" style="margin-top:6px">Vert = meilleur régime pour ce critère. Ligne surlignée = régime actif.</p>
      </div>
    </div>

    <!-- ⑤ Bilan revente -->
    <div class="sim-block">
      <div class="sim-block-title">Bilan à la revente — année ${F.saleYear}</div>
      <div class="res-grid">
        <div class="res"><div class="res-lbl">Fair value estimée</div><div class="res-val">${fairBase ? _eur(fairBase) : 'N/A'}</div><div class="res-sub">${fvSub}</div></div>
        <div class="res"><div class="res-lbl">Prix d'achat</div><div class="res-val">${_eur(curPrix)}</div><div class="res-sub">${decoteAchat != null ? (decoteAchat <= 0 ? `${-decoteAchat}% sous marché 👍` : `+${decoteAchat}% sur marché`) : ''}</div></div>
        <div class="res"><div class="res-lbl">Prix de revente</div><div class="res-val">${_eur(F.revente.prixVente)}</div><div class="res-sub">+${simf.revaloPrixPct}%/an</div></div>
        <div class="res"><div class="res-lbl">Capital restant dû</div><div class="res-val">${_eur(F.revente.crd)}</div><div class="res-sub">remboursé à la vente</div></div>
        <div class="res"><div class="res-lbl">Impôt plus-value</div><div class="res-val">${_eur(F.revente.impotPV)}</div><div class="res-sub">${F.revente.modeIS ? 'IS + sortie perso' : 'IR 19% + PS 17,2%'}</div></div>
        <div class="res"><div class="res-lbl">Net vendeur</div><div class="res-val">${_eur(F.revente.netVendeur)}</div><div class="res-sub">après crédit &amp; impôt</div></div>
        <div class="res"><div class="res-lbl">Bilan total</div><div class="res-val ${F.bilan >= 0 ? 'pos' : 'neg'}">${F.bilan >= 0 ? '+' : ''}${_eur(F.bilan)}</div><div class="res-sub">cashflows + revente</div></div>
        <div class="res"><div class="res-lbl">Apport / emprunt</div><div class="res-val">${_eur(F.apport)}</div><div class="res-sub">${Math.round(F.apportPct)}% · ${_eur(F.emprunt)} emprunt</div></div>
      </div>
    </div>

    <!-- ⑥ Graphiques -->
    <div class="sim-block">
      <div class="sim-block-title">Cashflow net par année</div>
      <p class="hint">Barres = cashflow net annuel (capital inclus). Loyer indexé ${simf.loyerIndexPct}%/an.</p>
      ${chartYears(F.rowsY)}
    </div>
    <div class="sim-cols">
      <div class="sim-block">
        <div class="sim-block-title">Cashflow selon l'apport</div>
        <p class="hint">Repère = apport actuel.</p>
        ${chartLine(apportPts, { markerX: curApport, xfmt: x => x + '%', color: '#2b453e' })}
      </div>
      <div class="sim-block">
        <div class="sim-block-title">Cashflow selon le prix</div>
        <p class="hint">Repère = prix actuel.</p>
        ${chartLine(prixPts, { markerX: curPrix, xfmt: x => Math.round(x / 1000) + 'k', color: '#93aaa8' })}
      </div>
    </div>

    <!-- ⑦ Accordéons -->
    <details class="sim-details">
      <summary>🔍 Optimiseur de rendement</summary>
      <div>
        <p class="hint">Teste toutes les combinaisons régime × apport × prix × horizon pour maximiser l'objectif, coût d'opportunité inclus.</p>
        <div class="sim-fields">
          <div><label>Objectif</label><select onchange="setSolver('objective', this.value)">${objOpts}</select></div>
          <div><label>Apport max (%)</label><input type="number" min="0" max="100" value="${sv.apportMaxPct}" oninput="setSolver('apportMaxPct', this.value)"></div>
          <div><label>Prix min (€)</label><input type="number" step="1000" value="${solverPrixMin}" oninput="setSolver('prixMin', this.value)"></div>
          <div><label>Horizon max (ans)</label><input type="number" min="1" max="40" value="${sv.horizonMax}" oninput="setSolver('horizonMax', this.value)"></div>
          <div><label>Rendement alternatif (%/an)</label><input type="number" step="0.5" value="${sv.rendAltPct}" oninput="setSolver('rendAltPct', this.value)"></div>
          <div><label>Fair value (€)</label><input type="number" step="1000" value="${simf.fairValueOverride != null ? simf.fairValueOverride : (fairVal ? Math.round(fairVal) : '')}" placeholder="auto (régression)" oninput="setSimf('fairValueOverride', this.value)"></div>
          <div><label>Régimes testés</label><select onchange="setSolver('testAllRegimes', this.value)"><option value="true" ${sv.testAllRegimes ? 'selected' : ''}>Tous les régimes</option><option value="false" ${!sv.testAllRegimes ? 'selected' : ''}>Régime actuel</option></select></div>
        </div>
        <div style="margin-top:12px"><button class="btn-primary" onclick="runSolver()">🔍 Optimiser</button></div>
        <div id="solver-result" style="margin-top:14px"></div>
      </div>
    </details>

    <details class="sim-details">
      <summary>🗺️ Carte de chaleur apport × prix</summary>
      <div>
        <p class="hint">Cashflow net moyen/an (k€). Vert = positif.</p>
        <div class="cmp-wrap">${chartHeatmap(hmApport, hmPrix, hmMatrix, { xfmt: a => a + '%', yfmt: p => _eur(p), xtitle: "Apport →   (lignes = prix d'achat)" })}</div>
      </div>
    </details>

    <details class="sim-details">
      <summary>📅 Compte de résultat année par année (${F.years} ans)</summary>
      <div class="cmp-wrap"><table class="ins-table">
        <thead><tr><th>Année</th><th>Loyer net</th><th>Charges</th><th>Intérêts</th><th>Amort.</th><th>Résultat fiscal</th><th>Impôt</th><th>Cashflow</th><th>Cumulé</th></tr></thead>
        <tbody>${trs}</tbody>
      </table></div>
    </details>
  </div>`;
}

function setSimf(key, val) {
  const s = getSimf();
  if (key === 'bienId' || key === 'regime') { s[key] = val; if (key === 'bienId') { s.apportPct = null; s.prix = null; s.fairValueOverride = null; } }
  else if (key === 'tmi') s.tmi = parseFloat(val) || 0;
  else if (key === 'reventeAnnee') s.reventeAnnee = parseFloat(val) || 1;
  else if (key === 'sciSortieCash') s.sciSortieCash = (val === true || val === 'true');
  else if (key === 'fairValueOverride') s.fairValueOverride = (val === '' || val == null) ? null : (parseFloat(val) || null);
  else s[key] = parseFloat(val);
  saveSimf(s);
  clearTimeout(window._simfT); window._simfT = setTimeout(buildSimulationFiscale, 200);
}
function resetSimf() { const s = getSimf(); s.apportPct = null; s.prix = null; saveSimf(s); buildSimulationFiscale(); }

// ── Optimiseur (recherche exhaustive régime × apport × prix × horizon) ──
function getSolver() {
  return Object.assign({ objective: 'tri', apportMaxPct: 40, prixMin: null, horizonMax: 25, rendAltPct: 5, testAllRegimes: true },
    JSON.parse(localStorage.getItem('simSolver') || '{}'));
}
function saveSolver(s) { localStorage.setItem('simSolver', JSON.stringify(s)); }
function setSolver(key, val) {
  const s = getSolver();
  if (key === 'objective') s.objective = val;
  else if (key === 'testAllRegimes') s.testAllRegimes = (val === 'true' || val === true);
  else s[key] = parseFloat(val);
  saveSolver(s);
  if (key === 'rendAltPct') { clearTimeout(window._simfT); window._simfT = setTimeout(buildSimulationFiscale, 300); }
}
function runSolver() {
  const el = document.getElementById('solver-result');
  if (el) el.innerHTML = '<div class="hint">⏳ Optimisation en cours…</div>';
  setTimeout(() => {
    const g = getSimGlobal(), simf = getSimf(), sv = getSolver();
    const candidates = rows.filter(r => !isStructured(r) && !isExcludedLocG(getDisplayVal(r, 'location')) && r.surface && r.price);
    const bien = candidates.find(r => r.id === simf.bienId) || candidates[0];
    if (!bien) { if (el) el.innerHTML = 'Aucun bien.'; return; }
    const b = getSimBien(bien);
    const basePrix = +b.prix || 0;
    const fvm = fairValueModel(getDisplayVal(bien, 'location'));
    const fvBase = (simf.fairValueOverride != null && simf.fairValueOverride > 0) ? simf.fairValueOverride : (fvm ? fvm.predict(bien.surface) : null);
    const prixMin = sv.prixMin || Math.round(basePrix * 0.85);
    const regimes = sv.testAllRegimes ? REGIMES.map(x => x.id) : [simf.regime];
    const baseOpts = { tmi: simf.tmi, loyerIndexPct: simf.loyerIndexPct, revaloPrixPct: simf.revaloPrixPct, fraisVentePct: simf.fraisVentePct, sciSortieCash: simf.sciSortieCash, rendAltPct: sv.rendAltPct, fairValueBase: fvBase };
    const apMax = Math.max(0, sv.apportMaxPct), apStep = Math.max(1, Math.round(apMax / 12));
    const apportGrid = []; for (let a = 0; a <= apMax; a += apStep) apportGrid.push(a);
    const nP = 8, prixGrid = []; for (let i = 0; i <= nP; i++) prixGrid.push(Math.round(prixMin + (basePrix - prixMin) * i / nP));
    const hMax = Math.max(1, Math.min(sv.horizonMax, 40));
    let best = null, evals = 0;
    for (const reg of regimes) for (const ap of apportGrid) for (const px of prixGrid) for (let h = 1; h <= hMax; h++) {
      evals++;
      const F = computeFiscal(bien, g, b, Object.assign({}, baseOpts, { regime: reg, apportPct: ap, prix: px, reventeAnnee: h }));
      const val = sv.objective === 'tri' ? F.tri : sv.objective === 'van' ? F.van : F.gainNet;
      if (val != null && isFinite(val) && (best === null || val > best.val)) best = { val, reg, ap, px, h, F };
    }
    window._solverBest = best;
    if (!best || !el) { if (el) el.innerHTML = 'Aucune solution trouvée.'; return; }
    const regLabel = (REGIMES.find(x => x.id === best.reg) || {}).label || best.reg;
    el.innerHTML = `
      <div class="res-grid">
        <div class="res"><div class="res-lbl">Régime optimal</div><div class="res-val" style="font-size:.95rem">${regLabel}</div></div>
        <div class="res"><div class="res-lbl">Apport</div><div class="res-val">${best.ap}%</div><div class="res-sub">${_eur(best.F.apport)}</div></div>
        <div class="res"><div class="res-lbl">Prix d'achat</div><div class="res-val">${_eur(best.px)}</div></div>
        <div class="res"><div class="res-lbl">Horizon revente</div><div class="res-val">${best.h} ans</div></div>
        <div class="res"><div class="res-lbl">TRI</div><div class="res-val ${best.F.tri >= 0 ? 'pos' : 'neg'}">${best.F.tri != null ? (best.F.tri * 100).toFixed(1) + '%' : 'N/A'}</div></div>
        <div class="res"><div class="res-lbl">VAN @ ${sv.rendAltPct}%</div><div class="res-val ${best.F.van >= 0 ? 'pos' : 'neg'}">${best.F.van >= 0 ? '+' : ''}${_eur(best.F.van)}</div></div>
        <div class="res"><div class="res-lbl">Gain net</div><div class="res-val ${best.F.gainNet >= 0 ? 'pos' : 'neg'}">${best.F.gainNet >= 0 ? '+' : ''}${_eur(best.F.gainNet)}</div></div>
        <div class="res"><div class="res-lbl">Cashflow moyen</div><div class="res-val ${best.F.cashAvg >= 0 ? 'pos' : 'neg'}">${best.F.cashAvg >= 0 ? '+' : ''}${_eur(best.F.cashAvg)}/an</div></div>
      </div>
      <div style="margin-top:12px"><button class="btn-primary" onclick="applyOptimum()">✅ Appliquer ces paramètres</button> <span class="hint">${evals.toLocaleString('fr-FR')} combinaisons testées</span></div>`;
  }, 30);
}
function applyOptimum() {
  const best = window._solverBest; if (!best) return;
  const s = getSimf();
  s.regime = best.reg; s.apportPct = best.ap; s.prix = best.px; s.reventeAnnee = best.h;
  saveSimf(s);
  buildSimulationFiscale();
}

// ═══════════════════════════════════════════════════════════════════════
//  AJOUT MANUEL D'UN BIEN — persistant (localStorage), scoré comme les autres
// ═══════════════════════════════════════════════════════════════════════
function injectManualStyles() {
  if (document.getElementById('manual-styles')) return;
  const css = `
  .add-bien-btn { background: #10b981; color: #fff; border: none; padding: 9px 16px; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 0.88rem; margin-bottom: 16px; }
  .add-bien-btn:hover { background: #059669; }
  .modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.45); display: flex; align-items: flex-start; justify-content: center; padding-top: 6vh; z-index: 1000; }
  .modal { background: #fff; border-radius: 14px; padding: 24px 26px; width: min(560px, 92vw); box-shadow: 0 20px 60px rgba(0,0,0,.3); max-height: 86vh; overflow-y: auto; }
  .modal h2 { margin: 0 0 4px; font-size: 1.15rem; }
  .modal .sub { color: var(--muted); font-size: 0.85rem; margin-bottom: 18px; }
  .modal-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
  .modal-grid .full { grid-column: 1 / -1; }
  .modal label { display: block; font-size: 0.74rem; text-transform: uppercase; letter-spacing: .03em; color: var(--muted); margin-bottom: 4px; }
  .modal input, .modal select { width: 100%; box-sizing: border-box; padding: 8px 10px; border: 1px solid #d1d5db; border-radius: 7px; font-size: 0.92rem; }
  .modal-actions { display: flex; justify-content: flex-end; gap: 10px; margin-top: 20px; }
  .modal-err { color: #dc2626; font-size: 0.84rem; margin-top: 10px; min-height: 1em; }
  .btn-primary { background: #1f2937; color: #fff; border: 1px solid #1f2937; padding: 9px 18px; border-radius: 8px; cursor: pointer; font-weight: 600; font-size: 0.9rem; }
  .btn-ghost { background: #fff; border: 1px solid #d1d5db; padding: 9px 18px; border-radius: 8px; cursor: pointer; font-size: 0.9rem; }
  `;
  const s = document.createElement('style');
  s.id = 'manual-styles'; s.textContent = css;
  document.head.appendChild(s);
}

function injectManualUI() {
  injectManualStyles();
  const host = document.getElementById('view-listings');
  if (host && !document.getElementById('add-bien-btn')) {
    const btn = document.createElement('button');
    btn.id = 'add-bien-btn'; btn.className = 'add-bien-btn';
    btn.textContent = '➕ Ajouter un bien';
    btn.onclick = openAddModal;
    host.insertBefore(btn, host.firstChild);
  }
  if (!document.getElementById('add-modal')) {
    const locOpts = ALL_LOCATIONS.map(l => `<option value="${l}">${l}</option>`).join('');
    const dpeOpts = ['', 'A', 'B', 'C', 'D', 'E', 'F', 'G'].map(d => `<option value="${d}">${d || '—'}</option>`).join('');
    const ov = document.createElement('div');
    ov.id = 'add-modal'; ov.className = 'modal-overlay'; ov.style.display = 'none';
    ov.innerHTML = `
      <div class="modal">
        <h2>➕ Ajouter un bien</h2>
        <div class="sub">Saisi à la main — sauvegardé dans ton navigateur et scoré comme les annonces du bot.</div>
        <div class="modal-grid">
          <div class="full"><label>Commune *</label><select id="m-loc">${locOpts}</select></div>
          <div><label>Prix (€) *</label><input id="m-prix" type="number" step="1000" placeholder="ex: 150000"></div>
          <div><label>Surface (m²) *</label><input id="m-surf" type="number" step="0.5" placeholder="ex: 45"></div>
          <div><label>Pièces</label><input id="m-rooms" type="number" step="1" placeholder="ex: 2"></div>
          <div><label>Loyer (€/mois)</label><input id="m-loyer" type="number" step="10" placeholder="auto si vide"></div>
          <div><label>DPE</label><select id="m-dpe">${dpeOpts}</select></div>
          <div><label>Type</label><select id="m-furnished"><option value="meuble" selected>Meublé</option><option value="nu">Nu (loué vide)</option></select></div>
          <div class="full"><label>Lien de l'annonce</label><input id="m-url" type="url" placeholder="https://..."></div>
          <div class="full"><label>Note</label><input id="m-note" type="text" placeholder="optionnel"></div>
        </div>
        <div class="modal-err" id="m-err"></div>
        <div class="modal-actions">
          <button class="btn-ghost" onclick="closeAddModal()">Annuler</button>
          <button class="btn-primary" onclick="submitManualListing()">Ajouter le bien</button>
        </div>
      </div>`;
    ov.addEventListener('click', e => { if (e.target === ov) closeAddModal(); });
    document.body.appendChild(ov);
  }
}

function openAddModal() {
  injectManualUI();
  ['m-prix', 'm-surf', 'm-rooms', 'm-loyer', 'm-url', 'm-note'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  document.getElementById('m-err').textContent = '';
  document.getElementById('add-modal').style.display = 'flex';
}
function closeAddModal() {
  const m = document.getElementById('add-modal'); if (m) m.style.display = 'none';
}

function loadManualListings() {
  const arr = JSON.parse(localStorage.getItem('manualListings') || '[]');
  for (const m of arr) {
    if (rows.some(r => r.id === m.id)) continue;
    m.manual = true;
    const sc = computeScore(m, m.location);
    m.score = sc.score; m.reasons = sc.reasons; m.yield = sc.gross_yield; m.vs_market = sc.vs_market;
    rows.push(m);
  }
}

function submitManualListing() {
  const v = id => (document.getElementById(id).value || '').trim();
  const err = document.getElementById('m-err');
  const loc = v('m-loc');
  const prix = parseFloat(v('m-prix'));
  const surf = parseFloat(v('m-surf'));
  const rooms = parseInt(v('m-rooms')) || null;
  const loyer = parseFloat(v('m-loyer')) || null;
  const dpe = v('m-dpe');
  const furnished = v('m-furnished') !== 'nu';
  const url = v('m-url');
  const note = v('m-note');
  if (!loc) { err.textContent = 'Choisis une commune.'; return; }
  if (!prix || prix <= 0) { err.textContent = 'Prix invalide.'; return; }
  if (!surf || surf <= 0) { err.textContent = 'Surface invalide.'; return; }

  const id = 'manual-' + Date.now().toString(36);
  const row = {
    id, url: url || '#', urls: url ? [url] : [], title: 'Bien saisi à la main',
    price: prix, surface: surf, rooms, location: loc, charges: null, dpe, ges: '',
    furnished, enriched: 0, manual: true, manual_loyer: loyer, first_seen: new Date().toISOString()
  };
  const sc = computeScore(row, loc);
  row.score = sc.score; row.reasons = sc.reasons; row.yield = sc.gross_yield; row.vs_market = sc.vs_market;

  const arr = JSON.parse(localStorage.getItem('manualListings') || '[]');
  arr.push(row); localStorage.setItem('manualListings', JSON.stringify(arr));
  if (note) {
    const ovr = JSON.parse(localStorage.getItem('listingOverrides') || '{}');
    ovr[id] = Object.assign(ovr[id] || {}, { note });
    localStorage.setItem('listingOverrides', JSON.stringify(ovr));
  }
  rows.push(row);
  closeAddModal();
  sort('score'); render();
}

function deleteManualListing(id) {
  if (!confirm('Supprimer définitivement ce bien saisi à la main ?')) return;
  let arr = JSON.parse(localStorage.getItem('manualListings') || '[]');
  arr = arr.filter(m => m.id !== id);
  localStorage.setItem('manualListings', JSON.stringify(arr));
  const i = rows.findIndex(r => r.id === id);
  if (i >= 0) rows.splice(i, 1);
  ['listingStates', 'listingOverrides', 'simBiens'].forEach(k => {
    const o = JSON.parse(localStorage.getItem(k) || '{}');
    if (o[id]) { delete o[id]; localStorage.setItem(k, JSON.stringify(o)); }
  });
  saveSimSelected(getSimSelected().filter(x => x !== id));
  render();
}

function buildSummaryBar() {
  const sb = document.getElementById('summary-bar');
  if (!sb) return;
  const valid = rows.filter(r => !isStructured(r) && r.price);
  const nb = rows.length;
  const nbHigh = valid.filter(r => getDisplayVal(r,'score') >= 80).length;
  const yields = valid.filter(r => r.yield != null).map(r => r.yield);
  const avgY = yields.length ? (yields.reduce((a,b)=>a+b,0)/yields.length).toFixed(1) : null;
  const vss = valid.filter(r => r.vs_market != null).map(r => r.vs_market);
  const bestVs = vss.length ? Math.min(...vss) : null;
  const minPrice = valid.length ? Math.min(...valid.map(r=>r.price)) : null;
  sb.innerHTML =
    `<div class="stat-chip"><strong>${nb}</strong> annonces</div>` +
    `<div class="stat-chip">Score ≥80 : <strong>${nbHigh}</strong></div>` +
    (avgY ? `<div class="stat-chip">Rdt moyen <strong>${avgY}%</strong></div>` : '') +
    (bestVs != null ? `<div class="stat-chip">Meilleure décote <strong>${Math.round(bestVs)}%</strong></div>` : '') +
    (minPrice ? `<div class="stat-chip">À partir de <strong>${minPrice.toLocaleString('fr-FR')} €</strong></div>` : '');
}

// Init au chargement : injecte l'UI, charge les biens saisis, re-render
injectManualUI();
loadManualListings();
sort('score');
render();
buildSummaryBar();
</script>
"""
    html_content = html_content.replace("</body>", insights_block + "</body>")
    path.write_text(html_content, encoding="utf-8")
    logger.info(f"Dashboard généré: {path}")


# ── Main ────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--db", default="appart_alerts.sqlite")
    parser.add_argument("--report-only", action="store_true")
    parser.add_argument("--eml-dir", default=None)
    parser.add_argument("--enrich", action="store_true", help="Fetch one-shot des fiches candidates (score > 50)")
    parser.add_argument("--history-file", default=None,
                        help="Chemin fichier historique des prix (défaut: listing_history.json dans le dossier du bot)")
    parser.add_argument("--json-output", default=None,
                        help="Chemin data.json à écrire (défaut: ../appart-alert-dashboard-v2/public/data.json si présent)")
    args = parser.parse_args()

    base = Path(__file__).resolve().parent
    cfg_path = base / args.config
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    logger.info(f"Config: {cfg_path} | Stratégie: {cfg.get('strategy', 'balanced')}")

    load_env(base / args.env)
    conn = init_db(base / args.db)

    # ── Historique persistant des prix ───────────────────────────────
    history_path = Path(args.history_file) if args.history_file else base / HISTORY_FILE
    history = load_history(history_path)
    logger.info(f"Historique chargé : {len(history['listings'])} entrées ({history_path.name})")

    # Optim : annonces déjà traitées lors d'un run précédent.
    # On garde leur commune déjà vérifiée pour pouvoir bypasser le fetch réseau (lent)
    # sans rien manquer ni perdre en justesse (on continue à re-scorer avec la config actuelle).
    verified_locations = {}
    for _id, _loc, _enr in conn.execute("SELECT id, location, enriched FROM listings"):
        if _enr:
            verified_locations[_id] = _loc
    logger.info(f"{len(verified_locations)} annonce(s) déjà vérifiée(s) en base (fetch réseau bypassé)")

    # Exclusions étendues
    excluded_subjects = [s.lower() for s in cfg["criteria"].get("excluded_email_subject_keywords", [])]
    excluded_subjects.append("nouvelle recherche sauvegardee")

    if not args.report_only:
        messages = []
        if args.eml_dir:
            d = base / args.eml_dir
            messages = [email.message_from_binary_file(f.open("rb"), policy=policy.default) for f in d.glob("*.eml")]
            logger.info(f"{len(messages)} fichiers .eml")
        else:
            messages = list(fetch_messages(cfg))

        for msg in messages:
            subject = msg.get("Subject", "")
            from_header = msg.get("From", "").lower()
            # CORRECTION v5 : normaliser le sujet (strip accents) avant comparaison
            subject_normalized = _strip_accents(subject).lower()

            # Exclusion par sujet
            if any(excl in subject_normalized for excl in excluded_subjects):
                logger.info(f"Email exclu par sujet: {subject[:60]}")
                continue

            text = _extract_text(msg)
            all_urls = extract_urls(text)

            # CORRECTION v6 : résoudre les liens de tracking AVANT filtrage
            candidate_urls = []
            seen = set()
            for url in all_urls:
                # Nettoyer et résoudre les tracking links
                clean = clean_url(url)
                
                # Vérifier si c'est une URL d'annonce valide
                if not is_listing_url(clean, cfg):
                    logger.info(f"URL rejetée (pas une annonce): {clean[:80]}")
                    continue
                
                # Éviter les doublons (même ID = même annonce)
                item_id = listing_id(clean)
                if item_id in seen:
                    continue
                seen.add(item_id)
                candidate_urls.append(clean)

            logger.info(f"Email: {subject[:50]}... | {len(all_urls)} URLs trouvées, {len(candidate_urls)} candidates")

            # ── Rescue SeLoger digest ("résultats instantanés") ──────────────────────
            # Ces emails ont des liens view.by.seloger.com/ (vue navigateur de l'email) mais pas
            # de liens click.by.seloger.com/ directs. On fetche la page view pour extraire les vrais liens.
            if not candidate_urls:
                view_urls = [u for u in all_urls
                             if "view.by.seloger.com" in u.lower() and len(u) > 35
                             and not u.rstrip("/").endswith("seloger.com")]
                if view_urls:
                    logger.info(f"  → Rescue SeLoger digest : fetch {view_urls[0][:70]}...")
                    digest_html = fetch_page_text(view_urls[0])
                    if digest_html:
                        digest_raw_urls = extract_urls(digest_html)
                        rescued = []
                        rescued_seen = set(seen)
                        for du in digest_raw_urls:
                            dc = clean_url(du)
                            if is_listing_url(dc, cfg):
                                did = listing_id(dc)
                                if did not in rescued_seen:
                                    rescued_seen.add(did)
                                    rescued.append(dc)
                                    if len(rescued) >= 3:
                                        break
                        if rescued:
                            logger.info(f"  → {len(rescued)} listing(s) rescapé(s) du digest SeLoger")
                            candidate_urls = rescued
                            seen.update(rescued_seen)
                        else:
                            logger.info("  → Fetch digest réussi mais aucun listing extrait")
                    else:
                        logger.info("  → Fetch digest échoué (page inaccessible)")

            # Max 3 URLs candidates par email
            if len(candidate_urls) > 3:
                candidate_urls = candidate_urls[:3]

            for url in candidate_urls:
                # CORRECTION v5 : parsing LOCAL autour de l'URL
                context = get_context_around_url(text, url, window=1200)

                # Exclusion par mot-clé dans le texte de l'annonce
                excluded_kw = [_searchable(k) for k in cfg["criteria"].get("excluded_keywords", [])]
                if any(kw in _searchable(context + text) for kw in excluded_kw):
                    matched = next(kw for kw in excluded_kw if kw in _searchable(context + text))
                    logger.info(f"REJET mot-clé exclu '{matched}' pour {url[:60]}...")
                    continue

                price = parse_price(context)
                surface = parse_surface(context)
                rooms = parse_rooms(context)

                # Priorité 1 (la plus fiable) : commune encodée dans le chemin de l'URL
                # Évite les erreurs dues aux titres marketing ("Chamonix / Les Houches")
                # où l'agent cite une commune premium pour attirer mais le bien est ailleurs.
                location = location_from_url(url, cfg["criteria"]["location_aliases"])
                if location:
                    logger.debug(f"  → Commune depuis URL : {location}")
                else:
                    # Priorité 2 : analyse du texte de l'email (phrases locatives + heuristique)
                    location = find_location(context + "\n" + text, cfg["criteria"]["location_aliases"], cfg["criteria"]["location_potential_score"])

                # Fallback 1 : email entier si le contexte local est trop pauvre
                if not price:
                    price = parse_price(text)
                if not surface:
                    surface = parse_surface(text)
                if not rooms:
                    rooms = parse_rooms(text)

                # Fallback 2 : sujet de l'email (souvent "T2 75m² Chamonix 195 000€")
                if subject and (not price or not surface or not rooms):
                    if not price:
                        price = parse_price(subject)
                    if not surface:
                        surface = parse_surface(subject)
                    if not rooms:
                        rooms = parse_rooms(subject)
                    if price or surface or rooms:
                        logger.debug(f"Données extraites du sujet email : prix={price} surface={surface} rooms={rooms}")

                # Guardrails prix
                if not price or not (PRICE_MIN <= price <= PRICE_MAX):
                    logger.info(f"REJET prix={price} pour {url[:60]}...")
                    continue
                # Surface : conserver si None (SeLoger bloque les fetches)
                if surface is not None and not (SURFACE_MIN <= surface <= SURFACE_MAX):
                    logger.info(f"REJET surface aberrante={surface} pour {url[:60]}...")
                    surface = None  # Annonce conservée sans surface plutôt que rejetée
                if surface is None:
                    logger.warning(f"Surface non trouvée pour {url[:60]}… annonce conservée sans surface")
                if rooms is not None and (rooms < 1 or rooms > 15):
                    logger.info(f"Rooms aberrant={rooms} pour {url[:60]}, ignoré")
                    rooms = None

                # CORRECTION v5 : ID stable basé uniquement sur URL
                item_id = listing_id(url)

                item = {
                    "id": item_id,
                    "url": url,
                    "title": subject or "Sans titre",
                    "price": price,
                    "surface": surface,
                    "rooms": rooms,
                    "location": location,
                    "charges": parse_charges(context) or parse_charges(text),
                    "dpe": parse_dpe(context) or parse_dpe(text),
                    "ges": parse_ges(context) or parse_ges(text),
                    "text": context + "\n\n" + text,  # contexte prioritaire + email entier pour scoring
                    "first_seen": datetime.now(timezone.utc).isoformat()
                }

                # vs market
                ref = cfg["criteria"]["market_price_per_m2"].get(location)
                if ref and surface:
                    item["vs_market"] = round(((price / surface) - ref) / ref * 100, 1)
                else:
                    item["vs_market"] = None

                # Score email-only
                email_score, email_reasons, breakdown = compute_score(item, cfg)
                item["score"] = email_score
                item["reasons"] = email_reasons
                item["_score_cashflow"] = breakdown["_score_cashflow"]
                item["_score_structured"] = breakdown["_score_structured"]

                # ── Bypass : annonce déjà vérifiée lors d'un run précédent ──
                # On réutilise la commune vérifiée stockée et on re-score (config actuelle),
                # mais on SAUTE le fetch réseau (gain de temps), sans rien manquer.
                already_verified = item_id in verified_locations
                if already_verified:
                    prev_loc = verified_locations[item_id]
                    if prev_loc and prev_loc != location:
                        location = prev_loc
                        item["location"] = prev_loc
                        ref = cfg["criteria"]["market_price_per_m2"].get(prev_loc)
                        item["vs_market"] = round(((price / surface) - ref) / ref * 100, 1) if ref and surface else None
                        email_score, email_reasons, breakdown = compute_score(item, cfg)
                        item["score"] = email_score
                        item["reasons"] = email_reasons
                        item["_score_cashflow"] = breakdown["_score_cashflow"]
                        item["_score_structured"] = breakdown["_score_structured"]

                # Fetch systématique pour les communes nécessitant vérification (ex: Passy → exclure Plateau d'Assy)
                # Déclenché si : localisation détectée OU si le contexte mentionne la commune (même si mal détectée)
                verify_locations = cfg["criteria"].get("verify_exclusions_locations", [])
                needs_verify = (
                    location in verify_locations or
                    any(_searchable(loc) in _searchable(context + "\n" + text) for loc in verify_locations)
                )
                # --enrich reste respecté ; la vérif auto est bypassée si déjà vérifiée.
                should_enrich = (args.enrich and email_score > 50) or (needs_verify and not already_verified)

                if should_enrich:
                    logger.info(f"Fetch {'vérif exclusions' if needs_verify else 'enrichissement'} {email_score}/100 : {url[:60]}...")
                    page_html = fetch_page_text(url)
                    if page_html:
                        page_text = html_to_text(page_html)
                        full_text = item["text"] + "\n\n" + page_text
                        # Re-vérifier les mots-clés d'exclusion sur le texte complet de la page
                        excluded_kw = [_searchable(k) for k in cfg["criteria"].get("excluded_keywords", [])]
                        if any(kw in _searchable(full_text) for kw in excluded_kw):
                            matched = next(kw for kw in excluded_kw if kw in _searchable(full_text))
                            logger.info(f"REJET (page) mot-clé exclu '{matched}' pour {url[:60]}...")
                            continue
                        # Reclassification de localisation (ex: Saint-Gervais → Le Fayet)
                        # Tester toutes les règles, pas seulement celles de la localisation détectée
                        reclassify = cfg["criteria"].get("reclassify_location_keywords", {})
                        reclassified = False
                        for _src_loc, kw_map in reclassify.items():
                            if reclassified:
                                break
                            for kw, new_loc in kw_map.items():
                                if _searchable(kw) in _searchable(full_text):
                                    logger.info(f"Reclassification {location} → {new_loc} ('{kw}' trouvé dans la page)")
                                    location = new_loc
                                    item["location"] = new_loc
                                    ref = cfg["criteria"]["market_price_per_m2"].get(new_loc)
                                    item["vs_market"] = round(((price / surface) - ref) / ref * 100, 1) if ref and surface else None
                                    reclassified = True
                                    break
                        item["text"] = full_text
                        item["enriched"] = 1
                        if args.enrich and email_score > 50:
                            enriched_score, enriched_reasons, _ = compute_score(item, cfg)
                            item["score"] = enriched_score
                            item["reasons"] = enriched_reasons
                            logger.info(f"  → Enrichi : {email_score} → {enriched_score}")
                    else:
                        logger.warning(f"Fetch échoué (page inaccessible) pour vérif : {url[:80]}")
                        item["enriched"] = 0
                else:
                    # Conserve le statut "vérifié" si le bien l'était déjà (bypass)
                    item["enriched"] = 1 if already_verified else 0

                save_listing(conn, item)
                logger.info(f"Score {item['score']} - {item['title'][:50]}...")

            # ── Fallback : email d'agence décrivant un bien SANS URL d'annonce reconnue ──
            # (ex: BARNES, Douglas Elliman qui ne lient que leur site agence). On évite de
            # perdre ces biens réels. Si la surface manque, le bien est créé en mode
            # "à compléter" (score partiel + raison explicite) plutôt que d'être ignoré.
            if not candidate_urls:
                fb_price = parse_price(text)
                fb_surface = parse_surface(text)
                fb_rooms = parse_rooms(text)
                fb_location = find_location(
                    text, cfg["criteria"]["location_aliases"], cfg["criteria"]["location_potential_score"]
                )
                ref_m = REFERENCE_RE.search(_strip_accents(text))
                excluded_kw = [_searchable(k) for k in cfg["criteria"].get("excluded_keywords", [])]
                kw_hit = any(kw in _searchable(text) for kw in excluded_kw)
                target_locs = set(cfg["criteria"].get("target_locations", [])) | set(cfg["criteria"].get("location_aliases", {}).keys())

                if fb_surface is not None and not (5 <= fb_surface <= 500):
                    fb_surface = None
                if fb_rooms is not None and not (1 <= fb_rooms <= 15):
                    fb_rooms = None
                valid_price = bool(fb_price) and 10000 <= fb_price <= 2_000_000

                if valid_price and fb_location in target_locs and (ref_m or fb_surface) and not kw_hit:
                    # Préférer les URLs significatives (pas les images/ressources statiques)
                    _bad = (".jpg", ".png", ".gif", ".jpeg", ".webp", ".svg", ".woff", "cache/",
                            "static/", "/img/", "transparent.png", "logo-", "favicon")
                    _good_urls = [u for u in all_urls
                                  if u.lower().startswith("http")
                                  and not any(b in u.lower() for b in _bad)]
                    link = next((clean_url(u) for u in _good_urls), "")
                    ref_token = ref_m.group("ref").strip() if ref_m else ""
                    seed = f"{from_header}|{ref_token}|{fb_price}|{fb_location}|{fb_surface}"
                    item_id = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
                    item = {
                        "id": item_id, "url": link or "#",
                        "title": subject or "Bien (email agence, sans lien)",
                        "price": fb_price, "surface": fb_surface, "rooms": fb_rooms,
                        "location": fb_location, "charges": parse_charges(text),
                        "dpe": parse_dpe(text), "ges": parse_ges(text), "text": text,
                        "first_seen": datetime.now(timezone.utc).isoformat(),
                    }
                    ref_mk = cfg["criteria"]["market_price_per_m2"].get(fb_location)
                    item["vs_market"] = (
                        round(((fb_price / fb_surface) - ref_mk) / ref_mk * 100, 1)
                        if (ref_mk and fb_surface) else None
                    )
                    score, reasons, breakdown = compute_score(item, cfg)
                    if not fb_surface:
                        reasons = ["⚠️ surface inconnue (à compléter)"] + reasons
                    item["score"] = score
                    item["reasons"] = reasons
                    item["_score_cashflow"] = breakdown["_score_cashflow"]
                    item["_score_structured"] = breakdown["_score_structured"]
                    item["enriched"] = 0
                    save_listing(conn, item)
                    logger.info(f"Bien capturé sans URL (fallback agence) score={score} : {subject[:50]}")
                else:
                    logger.info(f"Email sans annonce exploitable (aucune URL d'annonce): {subject[:50]}")

    # Génération rapport
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM listings ORDER BY score DESC").fetchall()
    listings = [dict(r) for r in rows]
    for r in listings:
        r["reasons"] = json.loads(r["reasons"] or "[]")

    # Déduplication : regrouper par (prix, surface, localisation), fusionner les URLs
    def dedup_listings(lst):
        groups = {}
        for r in lst:
            key = (r.get("price"), round(r.get("surface") or 0, 1))
            if key not in groups:
                r["urls"] = [r["url"]]
                groups[key] = r
            else:
                existing = groups[key]
                if r["url"] not in existing["urls"]:
                    existing["urls"].append(r["url"])
                if r["score"] > existing["score"]:
                    r["urls"] = existing["urls"]
                    groups[key] = r

        def best_url_per_domain(urls):
            """Ne garde que la meilleure URL par domaine."""
            by_domain = {}
            for u in urls:
                parsed = urlparse(u)
                domain = parsed.netloc.lower().replace("www.", "")
                score = 0
                path = parsed.path.lower()
                # Plus le path est spécifique, plus le score est haut
                if "/annonce/" in path:      score += 100
                elif "/annonces/" in path:   score += 80
                elif "/ad/" in path:         score += 70
                elif "/achat/" in path or "/location/" in path: score += 60
                elif "/p/" in path:          score += 50
                elif "/detail-" in path:    score += 50
                elif path.endswith((".htm", ".html")): score += 40
                elif len(path) > 1:          score += 20
                if parsed.query:             score -= 10
                if domain not in by_domain or score > by_domain[domain][0]:
                    by_domain[domain] = (score, u)
            return [u for _, u in sorted(by_domain.values(), key=lambda x: x[0], reverse=True)]

        result = list(groups.values())
        for r in result:
            r["urls"] = best_url_per_domain(r["urls"])
            r["url"] = r["urls"][0] if r["urls"] else ""

            # ── Correction de commune depuis les URLs fusionnées ──────────────
            # Après fusion, on dispose de toutes les URLs (SeLoger, Logic-Immo…).
            # Si l'une d'elles contient la commune dans son chemin (ex: /les-houches-74/),
            # on l'utilise comme source de vérité — plus fiable que le texte de l'email
            # qui peut citer Chamonix pour un bien situé aux Houches (titre marketing).
            url_locs = []
            for u in r["urls"]:
                ul = location_from_url(u, cfg["criteria"]["location_aliases"])
                if ul:
                    url_locs.append(ul)
            if url_locs:
                # Commune la plus fréquente parmi les URLs (consensus)
                from collections import Counter
                best_url_loc = Counter(url_locs).most_common(1)[0][0]
                if best_url_loc != r.get("location"):
                    logger.info(
                        f"Correction commune (URLs): {r.get('location')!r} → {best_url_loc!r} "
                        f"| {r.get('price')}€ {r.get('surface')}m² "
                        f"| {[u[:45] for u in r['urls']]}"
                    )
                    r["_location_original"] = r["location"]  # pour info dans le dashboard
                    r["location"] = best_url_loc
                    r["_loc_corrected"] = True  # signal JS pour recalculer le score

        result.sort(key=lambda x: x["score"], reverse=True)
        return result

    listings = dedup_listings(listings)

    # ── Mise à jour historique + enrichissement ──────────────────────
    today_iso = datetime.now(timezone.utc).isoformat()
    current_ids: set = set()

    for listing in listings:
        lid   = listing["id"]
        price = listing.get("price")
        current_ids.add(lid)
        update_history(history, lid, price, today_iso)

    # Marquer absents (non vus ce run)
    mark_absent_listings(history, current_ids, today_iso)

    # Enrichir chaque listing avec données historiques
    for listing in listings:
        enrich_from_history(listing, history, today_iso)

    # Sauvegarder l'historique mis à jour
    save_history(history_path, history)
    logger.info(f"Historique sauvegardé : {history_path}")

    # ── DVF stats ─────────────────────────────────────────────────────
    dvf_stats = load_dvf_stats(base)
    if dvf_stats:
        enhance_config_with_dvf(cfg, dvf_stats)

    # ── Export data.json pour dashboard React ────────────────────────
    # Chercher le chemin de sortie automatiquement si non spécifié
    if args.json_output:
        json_out = Path(args.json_output)
    else:
        # Chercher ../appart-alert-dashboard-v2/public/
        candidate = base.parent / "appart-alert-dashboard-v2" / "public" / "data.json"
        json_out = candidate if candidate.parent.exists() else base / "data.json"

    generate_json(listings, cfg, json_out, dvf_stats=dvf_stats)

    generate_html(listings, cfg, base / "dashboard.html")
    logger.info(f"Terminé. {len(listings)} annonces dans dashboard.html")


if __name__ == "__main__":
    main()