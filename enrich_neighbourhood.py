"""
enrich_neighbourhood.py
=======================
Visite les pages détail SeLoger pour les appartements actifs sans slug de
quartier dans leur URL (= adresse générique "Chamonix-Mont-Blanc").

Pour chaque annonce :
  1. Extrait la description depuis la page (via _SL_DETAIL_JS)
  2. Sauve la description en DB (colonne `description`)
  3. Détecte le quartier depuis le texte de la description + titre
  4. Si un quartier spécifique est trouvé, l'ajoute dans _neighbourhood_overrides.json

Usage :
    python enrich_neighbourhood.py [--dry-run]

Relancer _export_react_data.py ensuite pour reconstruire le JSON.
"""
import sys, argparse, json, asyncio, random, re, sqlite3, unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE      = Path(__file__).parent
DB        = BASE / "dvf" / "listings_market.db"
OVERRIDES = BASE / "_neighbourhood_overrides.json"

parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true", help="Aucune écriture")
args = parser.parse_args()

# ── Charger les overrides existants ──────────────────────────────────────────
existing_overrides: dict[str, str] = {}
if OVERRIDES.exists():
    existing_overrides = json.loads(OVERRIDES.read_text(encoding="utf-8"))
print(f"Overrides quartier existants : {len(existing_overrides)}")

# ── Identifier les candidats (sans slug quartier, sans description) ──────────
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
all_apts = con.execute(
    "SELECT id, titre, adresse_raw, url, description FROM listings "
    "WHERE type_bien='appartement' AND active=1 AND url IS NOT NULL"
).fetchall()
con.close()

candidates = []
for r in all_apts:
    url = r["url"] or ""
    already_overridden = r["id"] in existing_overrides
    already_has_desc   = bool((r["description"] or "").strip())

    # Visit all apartments without a description — whether they have a slug or not.
    # A slug can be stale/wrong (SeLoger reassigns zones); the description is always accurate.
    # Listings with a manual override already are skipped.
    if not already_overridden and not already_has_desc:
        candidates.append({
            "id":    r["id"],
            "url":   url,
            "titre": r["titre"] or "",
        })

print(f"Candidats à enrichir (sans description, sans override) : {len(candidates)}")
for c in candidates:
    print(f"  {c['id'][:12]}  {c['url'][-50:]}")

if not candidates:
    print("\nRien à faire.")
    sys.exit(0)

if args.dry_run:
    print("\n[DRY RUN] — aucune visite ni écriture.")
    sys.exit(0)

# ── Détection quartier (miroir de _export_react_data.py) ─────────────────────
_DESC_NEIGHBOURHOOD = [
    (["montroc"],                                         "Montroc"),
    (["domaine de balme", "le tour"],                    "Le Tour"),
    (["lavancher"],                                      "Le Lavancher"),
    (["argentiere", "grands montets", "grand-montets"],  "Argentière"),
    (["tines"],                                          "Les Tines"),
    (["flegere", "golf de chamonix"],                    "Les Praz"),
    (["gaillands", "bois du bouchet"],                   "Les Gaillands"),
    (["pelerins", "le betty"],                           "Les Pélerins"),
    (["bossons", "moussoux", "chemin napoleon"],         "Les Bossons"),
    (["chavants", "les houches", "houches"],             "Les Houches"),
]


def _norm(s: str) -> str:
    s = re.sub(r"(?<=[a-zA-Z])\?(?=[a-zA-Z])", "e", s)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if unicodedata.category(c) != "Mn")
    return s.lower()


def detect_from_text(text: str) -> str | None:
    t = _norm(text)
    for kws, name in _DESC_NEIGHBOURHOOD:
        if any(k in t for k in kws):
            return name
    return None


# ── Scraping via nodriver ─────────────────────────────────────────────────────
try:
    import nodriver as uc
except ImportError:
    print("\nERREUR : nodriver non installé (pip install nodriver)")
    sys.exit(1)

from bot_overnight import _SL_DETAIL_JS


async def enrich() -> None:
    new_overrides: dict[str, str] = {}
    new_descriptions: dict[str, str] = {}

    browser = await uc.start(
        headless=False,
        browser_args=["--window-size=1366,768", "--lang=fr-FR", "--no-sandbox"],
    )
    try:
        # Warmup anti-bot
        print("\nWarmup seloger.com…")
        tab = await browser.get("https://www.seloger.com/")
        await asyncio.sleep(6)
        await tab.evaluate("""
            for (const b of document.querySelectorAll('button,a')) {
                if (b.innerText && b.innerText.includes('Continuer sans')) { b.click(); break; }
            }
        """)
        await asyncio.sleep(2)
        print("Warmup OK\n")

        for c in candidates:
            print(f"→ {c['id'][:12]}  {c['url'][-55:]}")
            await tab.get(c["url"])

            # Attendre rendu React
            for _ in range(20):
                await asyncio.sleep(1)
                body_len = await tab.evaluate("document.body.innerText.length")
                if body_len and body_len > 500:
                    break

            # Scroll pour déclencher le lazy-load
            for y in [600, 1400, 800]:
                await tab.evaluate(f"window.scrollTo(0, {y})")
                await asyncio.sleep(0.4)
            await asyncio.sleep(random.uniform(0.5, 1.0))

            try:
                raw = await tab.evaluate(f"({_SL_DETAIL_JS})()")
                d   = json.loads(raw)
            except Exception as e:
                print(f"  ✗ JS error: {e}")
                await asyncio.sleep(2)
                continue

            desc  = (d.get("desc") or "").strip()
            titre = (d.get("titre") or c["titre"] or "").strip()
            text  = f"{desc} {titre}"

            quartier = detect_from_text(text)

            if desc:
                new_descriptions[c["id"]] = desc[:400]
                print(f"  desc: {desc[:80]}…")
            else:
                print(f"  ✗ description vide")

            if quartier:
                print(f"  ✓ Quartier détecté : {quartier}")
                new_overrides[c["id"]] = quartier
            else:
                print(f"  — quartier non détecté")

            await asyncio.sleep(random.uniform(2.5, 4.0))

    finally:
        browser.stop()

    # ── Écrire en DB ─────────────────────────────────────────────────────────
    if new_descriptions:
        con2 = sqlite3.connect(DB)
        for lid, desc in new_descriptions.items():
            con2.execute(
                "UPDATE listings SET description=? WHERE id=?",
                (desc, lid)
            )
        con2.commit()
        con2.close()
        print(f"\n✓ {len(new_descriptions)} descriptions sauvées en DB")

    # ── Écrire les overrides ──────────────────────────────────────────────────
    if new_overrides:
        merged = {**existing_overrides, **new_overrides}
        OVERRIDES.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"✓ {len(new_overrides)} overrides de quartier ajoutés")
        for lid, q in new_overrides.items():
            print(f"  {lid[:12]} → {q}")

    if new_descriptions or new_overrides:
        print("\nRelancer : python _export_react_data.py")
    else:
        print("\nAucune donnée nouvelle.")


asyncio.run(enrich())
