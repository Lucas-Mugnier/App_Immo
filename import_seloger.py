# -*- coding: utf-8 -*-
"""
import_seloger.py — Import manuel listings SeLoger
====================================================
USAGE :
    1. Sur SeLoger, fais Ctrl+A puis Ctrl+C sur la page de résultats
    2. Colle dans le fichier  seloger_paste.txt  (même dossier)
    3. Lance : python import_seloger.py

    Ou passe directement le fichier :
        python import_seloger.py mon_fichier.txt

A chaque import :
    - Nouveaux listings ajoutés
    - Merge par surface EXACTE + commune → détecte baisses de prix
    - Rapport affiché dans le terminal

DB : dvf/seloger_manual.db  (séparée du bot, pas de conflit)
"""
import sys; sys.stdout.reconfigure(encoding="utf-8")
import re, sqlite3, json, argparse
from pathlib import Path
from datetime import date, datetime

BASE    = Path(__file__).parent
DVF_DIR = BASE / "dvf"
DB_PATH = DVF_DIR / "seloger_manual.db"
DVF_DIR.mkdir(exist_ok=True)

# ── DB ────────────────────────────────────────────────────────────────────────
def get_db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript("""
        CREATE TABLE IF NOT EXISTS listings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            merge_key   TEXT NOT NULL,          -- surface|commune|type
            source      TEXT DEFAULT 'seloger',
            commune     TEXT,
            type_bien   TEXT,
            surface     REAL,
            pieces      INTEGER,
            prix        INTEGER,
            url         TEXT,
            titre       TEXT,
            first_seen  TEXT,
            last_seen   TEXT,
            prix_initial INTEGER,
            nb_baisses  INTEGER DEFAULT 0,
            historique  TEXT DEFAULT '[]'       -- JSON [{date, prix}]
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_merge ON listings(merge_key);
    """)
    con.commit()
    return con

# ── Normalisation ─────────────────────────────────────────────────────────────
def norm_commune(s: str) -> str:
    s = re.sub(r"\(\d{5}\)", "", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s.upper().strip()

def parse_price(s: str) -> int | None:
    s = re.sub(r"\s", "", s)
    m = re.search(r"(\d[\d\s]*)\s*[€Ee]", s.replace(" ","").replace("\xa0",""))
    if not m: return None
    try: return int(re.sub(r"\D","", m.group(1)))
    except: return None

def parse_surface(s: str) -> float | None:
    m = re.search(r"(\d+[\.,]?\d*)\s*m[²2]", s, re.I)
    if not m: return None
    try: return float(m.group(1).replace(",","."))
    except: return None

def parse_pieces(s: str) -> int:
    m = re.search(r"(\d+)\s*pi[eè]ce", s, re.I)
    if m: return int(m.group(1))
    m = re.search(r"(\d+)\s*P\b", s)
    if m: return int(m.group(1))
    return 0

# ── Parser texte copié-collé SeLoger ─────────────────────────────────────────
def parse_seloger_paste(text: str) -> list[dict]:
    """
    Parse le texte brut copié depuis une page de résultats SeLoger.
    Stratégie : repère chaque bloc "Maison/Appartement ... m² ... € ..."
    et extrait les infos disponibles.
    """
    listings = []

    # Sépare en blocs par les marqueurs de type de bien
    # SeLoger affiche typiquement : "Maison 5 pièces 120 m²" ou "Appartement 3 pièces 67 m²"
    TYPE_RE = re.compile(
        r"(Maison|Appartement|Villa|Chalet|Mas|Propriété|Ferme|Terrain|Loft|Studio)"
        r"[^\n]*?(\d+)\s*pi[eè]ces?[^\n]*?(\d+[\.,]?\d*)\s*m[²2]",
        re.I | re.DOTALL
    )

    # Alternative : blocs séparés par des prix (€)
    PRICE_RE  = re.compile(r"(\d[\d\s \xa0]{2,9})\s*€", re.I)
    CITY_RE   = re.compile(
        r"(Chamonix|Argentière|Les Houches|Saint[- ]Gervais|Sallanches|Servoz|Passy|Megève|Combloux|Les Contamines)"
        r"(?:[^\n]*?\((\d{5})\))?",
        re.I
    )

    # Nettoyer le texte
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Supprimer les lignes de nav inutiles
    skip = re.compile(
        r"(Accueil|Connexion|Mon compte|Mes alertes|Carte|Trier|Filtrer"
        r"|SeLoger|Nous contacter|CGU|Mentions légales|Cookie|©|\d+ annonces?)",
        re.I
    )

    lines = [l.strip() for l in text.split("\n") if l.strip() and not skip.search(l)]
    clean_text = "\n".join(lines)

    # ── Méthode 1 : blocs structurés (Maison X pièces Y m²) ──────────────────
    pos = 0
    for m in TYPE_RE.finditer(clean_text):
        type_bien = m.group(1).lower()
        pieces    = int(m.group(2))
        surface   = float(m.group(3).replace(",","."))

        # Cherche prix dans les 400 chars suivants
        after = clean_text[m.start():m.start()+500]
        prix_m = PRICE_RE.search(after)
        prix   = None
        if prix_m:
            raw_p = re.sub(r"[\s \xa0]","", prix_m.group(1))
            try: prix = int(raw_p)
            except: pass

        # Cherche commune
        commune = "CHAMONIX MONT BLANC"
        city_m  = CITY_RE.search(after)
        if city_m:
            commune = norm_commune(city_m.group(1) + (" " + city_m.group(2) if city_m.group(2) else ""))

        # Cherche URL (pattern seloger.com/annonces/...)
        url_m = re.search(r"https?://www\.seloger\.com/\S+", after)
        url   = url_m.group(0).rstrip(".,)") if url_m else ""

        if prix and prix > 50000 and surface and surface > 10:
            listings.append({
                "type_bien": type_bien,
                "surface":   surface,
                "pieces":    pieces,
                "prix":      prix,
                "commune":   commune,
                "url":       url,
                "titre":     m.group(0)[:80].strip(),
            })
        pos = m.end()

    # ── Méthode 2 : fallback ligne par ligne si méthode 1 trop pauvre ────────
    if len(listings) < 3:
        listings = []
        current: dict = {}
        for line in lines:
            # Nouvelle annonce si on voit "Maison" ou "Appartement"
            type_m = re.match(
                r"^(Maison|Appartement|Villa|Chalet|Studio|Loft|Propriété)\b", line, re.I
            )
            if type_m:
                if current.get("prix") and current.get("surface"):
                    listings.append(current)
                current = {"type_bien": type_m.group(1).lower(), "commune": "CHAMONIX MONT BLANC",
                           "url": "", "titre": line[:80]}

            if not current:
                continue

            # Surface
            if not current.get("surface"):
                s = parse_surface(line)
                if s and s > 10: current["surface"] = s

            # Pièces
            if not current.get("pieces"):
                p = parse_pieces(line)
                if p: current["pieces"] = p

            # Prix
            if not current.get("prix"):
                pr = parse_price(line)
                if pr and pr > 50000: current["prix"] = pr

            # Commune vallée
            city_m = CITY_RE.search(line)
            if city_m:
                current["commune"] = norm_commune(city_m.group(1))

            # URL
            if not current.get("url") and "seloger.com" in line:
                url_m = re.search(r"https?://\S+seloger\S+", line)
                if url_m: current["url"] = url_m.group(0).rstrip(".,)")

        if current.get("prix") and current.get("surface"):
            listings.append(current)

    return listings

# ── Merge / store ─────────────────────────────────────────────────────────────
def upsert(con, lst: dict, today: str) -> dict:
    """
    Upsert listing dans DB.
    merge_key = surface|commune|type_bien
    Retourne dict avec action ('new' / 'baisse' / 'stable' / 'hausse')
    """
    surf_k = int(lst["surface"])          # surface exacte comme clé
    key    = f"{surf_k}|{lst['commune']}|{lst['type_bien']}"

    existing = con.execute(
        "SELECT * FROM listings WHERE merge_key=?", (key,)
    ).fetchone()

    if not existing:
        hist = json.dumps([{"date": today, "prix": lst["prix"]}])
        con.execute("""
            INSERT INTO listings
            (merge_key, source, commune, type_bien, surface, pieces,
             prix, url, titre, first_seen, last_seen, prix_initial, nb_baisses, historique)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?)
        """, (key, "seloger", lst["commune"], lst["type_bien"],
              lst["surface"], lst.get("pieces",0), lst["prix"],
              lst.get("url",""), lst.get("titre",""),
              today, today, lst["prix"], hist))
        return {"action": "new", "listing": lst}

    # Listing existant → compare prix
    old_prix = existing["prix"]
    new_prix  = lst["prix"]
    hist = json.loads(existing["historique"] or "[]")

    if new_prix != old_prix:
        hist.append({"date": today, "prix": new_prix})
        nb_b = existing["nb_baisses"] + (1 if new_prix < old_prix else 0)
        con.execute("""
            UPDATE listings SET prix=?, last_seen=?, nb_baisses=?, historique=?,
                                url=COALESCE(NULLIF(?,''), url)
            WHERE merge_key=?
        """, (new_prix, today, nb_b, json.dumps(hist), lst.get("url",""), key))
        action = "baisse" if new_prix < old_prix else "hausse"
        return {"action": action, "old_prix": old_prix, "new_prix": new_prix,
                "delta": new_prix - old_prix, "listing": lst}

    # Prix inchangé : update last_seen
    con.execute("UPDATE listings SET last_seen=? WHERE merge_key=?", (today, key))
    return {"action": "stable", "listing": lst}

# ── Affichage ─────────────────────────────────────────────────────────────────
def fmt_prix(p): return f"{p/1e6:.3f} M€" if p >= 500_000 else f"{p:,} €".replace(",", " ")

def print_report(results: list, today: str):
    new_l    = [r for r in results if r["action"] == "new"]
    baisses  = [r for r in results if r["action"] == "baisse"]
    hausses  = [r for r in results if r["action"] == "hausse"]
    stables  = [r for r in results if r["action"] == "stable"]

    print(f"\n{'═'*62}")
    print(f"  IMPORT SELOGER — {today} — {len(results)} listings traités")
    print(f"{'═'*62}")
    print(f"  🆕 Nouveaux          : {len(new_l)}")
    print(f"  📉 Baisses de prix   : {len(baisses)}")
    print(f"  📈 Hausses de prix   : {len(hausses)}")
    print(f"  ➡  Inchangés         : {len(stables)}")

    if baisses:
        print(f"\n{'─'*62}")
        print(f"  BAISSES DE PRIX :")
        for r in sorted(baisses, key=lambda x: x["delta"]):
            l   = r["listing"]
            pct = r["delta"] / r["old_prix"] * 100
            print(f"  📉 {l['type_bien']:<12} {l['surface']:.0f}m²  {l['commune']}")
            print(f"     {fmt_prix(r['old_prix'])} → {fmt_prix(r['new_prix'])}  "
                  f"({pct:+.1f}%  {r['delta']/1000:+.0f}k€)")
            if l.get("url"): print(f"     {l['url']}")

    if new_l:
        print(f"\n{'─'*62}")
        print(f"  NOUVEAUX LISTINGS :")
        for r in new_l[:20]:
            l = r["listing"]
            print(f"  🆕 {l['type_bien']:<12} {l['surface']:.0f}m²  {l.get('pieces',0)}P  "
                  f"{fmt_prix(l['prix'])}  —  {l['commune']}")

    print(f"\n{'═'*62}")

# ── Stats DB ──────────────────────────────────────────────────────────────────
def print_stats():
    con = get_db()
    rows = con.execute("""
        SELECT commune, type_bien, COUNT(*) n,
               ROUND(AVG(prix)) avg_p,
               SUM(nb_baisses) baisses
        FROM listings GROUP BY commune, type_bien ORDER BY commune, n DESC
    """).fetchall()
    total = con.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
    baisses_total = con.execute("SELECT COUNT(*) FROM listings WHERE nb_baisses>0").fetchone()[0]

    print(f"\n{'═'*62}")
    print(f"  BASE SELOGER MANUELLE — {total} listings  ({baisses_total} avec baisse)")
    print(f"{'═'*62}")
    print(f"  {'Commune':<28} {'Type':<14} {'N':>4}  {'Prix moy':>12}  {'Baisses':>8}")
    print(f"  {'─'*60}")
    for r in rows:
        print(f"  {r['commune']:<28} {r['type_bien']:<14} {r['n']:>4}  "
              f"{fmt_prix(int(r['avg_p'])):>12}  {int(r['baisses'] or 0):>8}")
    con.close()

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Import manuel SeLoger → DB")
    parser.add_argument("fichier", nargs="?",
                        default=str(BASE / "seloger_paste.txt"),
                        help="Fichier texte collé depuis SeLoger (défaut: seloger_paste.txt)")
    parser.add_argument("--stats", action="store_true",
                        help="Affiche stats de la DB sans importer")
    args = parser.parse_args()

    if args.stats:
        print_stats()
        return

    paste_file = Path(args.fichier)
    if not paste_file.exists():
        print(f"Fichier introuvable : {paste_file}")
        print(f"  → Colle le texte SeLoger dans : {BASE / 'seloger_paste.txt'}")
        return

    text = paste_file.read_text(encoding="utf-8", errors="ignore")
    print(f"Lecture : {paste_file.name}  ({len(text):,} caractères)")

    listings = parse_seloger_paste(text)
    print(f"Listings détectés dans le texte : {len(listings)}")

    if not listings:
        print("\nAucun listing parsé. Vérifie le format du fichier.")
        print("Le parseur cherche des blocs : 'Maison X pièces Y m² ... Z €'")
        return

    today = date.today().isoformat()
    con   = get_db()
    results = []
    for l in listings:
        try:
            r = upsert(con, l, today)
            results.append(r)
        except Exception as e:
            print(f"  Erreur listing {l}: {e}")
    con.commit()
    con.close()

    print_report(results, today)
    print_stats()

if __name__ == "__main__":
    main()
