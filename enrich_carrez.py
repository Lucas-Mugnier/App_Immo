"""
enrich_carrez.py
================
Visite les pages détail SeLoger pour les appartements > SURFACE_THRESHOLD m²
sans override Carrez connu, extrait la surface Loi Carrez depuis la page,
et met à jour _surface_carrez_overrides.json.

Usage :
    python enrich_carrez.py [--threshold 80] [--dry-run]

Ne modifie rien en --dry-run. Relancer _export_react_data.py après.
"""
import sys, argparse, json, asyncio, random, time
import sqlite3
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE      = Path(__file__).parent
DB        = BASE / "dvf" / "listings_market.db"
OVERRIDES = BASE / "_surface_carrez_overrides.json"

parser = argparse.ArgumentParser()
parser.add_argument("--threshold", type=float, default=80.0,
                    help="Surface min pour enrichissement (défaut 80m²)")
parser.add_argument("--dry-run", action="store_true")
args = parser.parse_args()

# ── Charger overrides existants ───────────────────────────────────────────────
existing: dict[str, float] = {}
if OVERRIDES.exists():
    existing = {k: float(v) for k, v in json.loads(OVERRIDES.read_text(encoding="utf-8")).items()}
print(f"Overrides Carrez existants : {len(existing)}")

# ── Trouver les appartements > threshold sans override ────────────────────────
con = sqlite3.connect(DB)
con.row_factory = sqlite3.Row
candidates = [
    {"id": r["id"], "url": r["url"], "surface": r["surface"], "titre": r["titre"]}
    for r in con.execute(
        "SELECT id, url, surface, titre FROM listings "
        "WHERE type_bien='appartement' AND active=1 AND surface > ? AND url IS NOT NULL",
        (args.threshold,)
    ).fetchall()
    if r["id"] not in existing
]
con.close()

print(f"Candidats à enrichir (>{args.threshold:.0f}m², sans override) : {len(candidates)}")
for c in candidates:
    print(f"  {c['id'][:12]}  {c['surface']:.0f}m²  {(c['titre'] or '')[:40]}")

if not candidates:
    print("\nRien à faire.")
    sys.exit(0)

if args.dry_run:
    print("\n[DRY RUN] — aucune visite ni écriture.")
    sys.exit(0)

# ── Scraping via nodriver ─────────────────────────────────────────────────────
try:
    import nodriver as uc
except ImportError:
    print("\nERREUR : nodriver non installé (pip install nodriver)")
    sys.exit(1)

from bot_overnight import _SL_DETAIL_JS   # JS partagé avec le bot

async def enrich():
    new_overrides: dict[str, float] = {}

    browser = await uc.start(
        headless=False,
        browser_args=["--window-size=1366,768", "--lang=fr-FR", "--no-sandbox"],
    )
    try:
        # Warmup anti-bot
        print("\nWarmup seloger.com...")
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
            print(f"→ {c['id'][:12]}  {c['surface']:.0f}m²  {c['url'][-55:]}")
            await tab.get(c["url"])

            # Attendre rendu React
            for _ in range(15):
                await asyncio.sleep(1)
                body_len = await tab.evaluate("document.body.innerText.length")
                if body_len > 300:
                    break

            # Scroll lazy-load
            for y in [600, 1400]:
                await tab.evaluate(f"window.scrollTo(0, {y})")
                await asyncio.sleep(0.5)
            await asyncio.sleep(random.uniform(0.5, 1.0))

            raw = await tab.evaluate(f"({_SL_DETAIL_JS})()")
            d = json.loads(raw)
            carrez = d.get("carrez", 0)
            desc   = d.get("desc", "")

            if carrez and 10 < carrez <= c["surface"] * 1.05:
                diff = c["surface"] - carrez
                print(f"  ✓ Carrez trouvé : {carrez}m²  (total {c['surface']:.0f}m², écart {diff:.1f}m²)")
                if diff > 2:   # écart significatif — override utile
                    new_overrides[c["id"]] = carrez
                else:
                    print(f"    → écart < 2m², pas d'override nécessaire")
            else:
                # Tentative depuis la description parsée
                import re
                CARREZ_RE = re.compile(
                    r'(\d+[,.]\d+|\d+)\s*m[²2]\s*(?:loi\s+)?carrez|(?:loi\s+)?carrez\s*[:\s]+(\d+[,.]\d+|\d+)\s*m[²2]',
                    re.IGNORECASE
                )
                m = CARREZ_RE.search(desc)
                if m:
                    val_str = (m.group(1) or m.group(2) or '').replace(',', '.')
                    try:
                        carrez_desc = float(val_str)
                        if 10 < carrez_desc <= c["surface"] * 1.05:
                            diff = c["surface"] - carrez_desc
                            print(f"  ✓ Carrez (desc) : {carrez_desc}m²  (écart {diff:.1f}m²)")
                            if diff > 2:
                                new_overrides[c["id"]] = carrez_desc
                            continue
                    except ValueError:
                        pass
                print(f"  ✗ Carrez non trouvé  (carrez={carrez}, desc={len(desc)} chars)")

            await asyncio.sleep(random.uniform(2.0, 3.5))

    finally:
        browser.stop()

    # ── Écrire overrides ──────────────────────────────────────────────────────
    if new_overrides:
        merged = {**existing, **new_overrides}
        OVERRIDES.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2),
            encoding="utf-8"
        )
        print(f"\n✓ {len(new_overrides)} nouveaux overrides ajoutés → {OVERRIDES.name}")
        for lid, carrez in new_overrides.items():
            print(f"  {lid[:12]} → {carrez}m²")
        print("\nRelancer : python _export_react_data.py")
    else:
        print("\nAucun override nouveau.")

asyncio.run(enrich())
