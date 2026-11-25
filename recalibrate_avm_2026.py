"""
recalibrate_avm_2026.py
=======================
Utilise les annonces actives SeLoger pour corriger l'index de marché 2026
du modèle AVM appartements.

Logique :
  Pour chaque commune, on calcule :
    pm2_observé   = médiane(prix / surface) des annonces actuelles × (1 - négo)
    pm2_modèle    = médiane(avm_pred / surface) des mêmes annonces
    correction[c] = pm2_observé / pm2_modèle

  On applique correction[c] × avm_pred dans la DB, puis on recalcule
  avm_ratio et avm_score.

  Seules les annonces "raisonnables" (ratio 0.70-1.50, non structurées)
  entrent dans le calcul — ça exclut les outliers qui biaisent la médiane.

Usage :
    python recalibrate_avm_2026.py [--dry-run]

    --dry-run  : affiche les corrections sans toucher à la DB
"""
import sys, argparse, json, sqlite3
import numpy as np
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE     = Path(__file__).parent
DB       = BASE / "dvf" / "listings_market.db"
DASH_DIR = BASE / "dashboard-react" / "private-data"
AUDIT    = BASE / "_avm_market_correction.json"

NEGO_DISCOUNT   = 0.04   # décote négociation implicite
RATIO_MIN       = 0.70   # exclure les trop bonnes affaires aberrantes
RATIO_MAX       = 1.50   # exclure les surcotes extrêmes
MIN_LISTINGS    = 3      # minimum d'annonces pour corriger une commune
CORRECTION_CAP  = (0.80, 1.35)   # borne de sécurité sur la correction

parser = argparse.ArgumentParser()
parser.add_argument("--dry-run", action="store_true", help="Simulation sans écriture DB")
args = parser.parse_args()

# ─────────────────────────────────────────────────────────────────────────────
print("=== 1. Chargement listings.json ===")
listings_raw = json.loads((DASH_DIR / "listings.json").read_text(encoding="utf-8"))
listings = [
    l for l in listings_raw
    if not l.get("is_structured", False)
    and l.get("avm_pred") is not None
    and l.get("price", 0) > 0
    and l.get("surface", 0) > 10
]
print(f"Annonces avec avm_pred : {len(listings)}")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 2. Calcul des corrections par commune ===\n")

from collections import defaultdict
by_commune = defaultdict(list)
for l in listings:
    ratio = l.get("avm_ratio")
    if ratio is None:
        continue
    if not (RATIO_MIN <= ratio <= RATIO_MAX):
        continue
    by_commune[l["_location_original"]].append({
        "id":       l["id"],
        "price":    l["price"],
        "surface":  l["surface"],
        "avm_pred": l["avm_pred"],
        "ratio":    ratio,
    })

corrections = {}  # commune_db → float

print(f"{'Commune':<28}  {'n':>4}  {'pm2 obs':>9}  {'pm2 mdl':>9}  {'correction':>11}  {'action':>10}")
print("─" * 80)

for commune, items in sorted(by_commune.items()):
    n = len(items)
    pm2_obs = np.median([i["price"] / i["surface"] for i in items]) * (1 - NEGO_DISCOUNT)
    pm2_mdl = np.median([i["avm_pred"] / i["surface"] for i in items])
    raw_corr = pm2_obs / pm2_mdl if pm2_mdl > 0 else 1.0

    if n < MIN_LISTINGS:
        action = f"SKIP (n<{MIN_LISTINGS})"
        corr = 1.0
    else:
        corr = float(np.clip(raw_corr, CORRECTION_CAP[0], CORRECTION_CAP[1]))
        if corr == raw_corr:
            action = "OK"
        else:
            action = f"CAPÉ ({raw_corr:.3f})"

    corrections[commune] = corr
    flag = "→" if abs(corr - 1.0) > 0.02 else " "
    print(f"  {flag} {commune:<26}  {n:>4}  {pm2_obs:>8.0f}€  {pm2_mdl:>8.0f}€"
          f"  ×{corr:>8.4f}  {action:>10}")

# Correction globale (fallback communes sans assez d'annonces)
all_items = [i for items in by_commune.values() for i in items]
# Fallback = pas de correction pour les communes sans assez de données
# (chaque marché a sa propre dynamique, le global Chamonix-dominé ne s'applique pas)
global_corr = 1.0
print(f"\n  Global (fallback)  : ×{global_corr:.4f}  [pas de correction par défaut]")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 3. Mise à jour de la DB ===")

def avm_ratio_to_score(ratio):
    if ratio is None: return None
    if ratio <= 0.75: return 95
    if ratio <= 0.85: return 80
    if ratio <= 0.95: return 65
    if ratio <= 1.05: return 50
    if ratio <= 1.20: return 30
    if ratio <= 1.40: return 15
    return 5

if args.dry_run:
    print("  [DRY RUN] — aucune écriture en base")
else:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    updated = 0
    score_changed = 0

    for row in con.execute(
        "SELECT id, commune, prix, avm_pred, avm_ratio, avm_score FROM listings "
        "WHERE type_bien='appartement' AND active=1 AND avm_pred IS NOT NULL"
    ).fetchall():
        commune_db = (row["commune"] or "").upper().strip()
        corr = corrections.get(commune_db, global_corr)

        if abs(corr - 1.0) < 0.001:
            continue

        old_pred  = row["avm_pred"]
        new_pred  = round(old_pred * corr)
        prix      = row["prix"] or 0
        new_ratio = round(prix / new_pred, 3) if new_pred else None
        new_score = avm_ratio_to_score(new_ratio)
        old_score = row["avm_score"]

        con.execute(
            "UPDATE listings SET avm_pred=?, avm_ratio=?, avm_score=? WHERE id=?",
            (new_pred, new_ratio, new_score, row["id"])
        )
        updated += 1
        if new_score != old_score:
            score_changed += 1

    con.commit()
    con.close()
    print(f"  {updated} annonces mises à jour ({score_changed} scores modifiés)")

# ─────────────────────────────────────────────────────────────────────────────
print("\n=== 4. Sauvegarde audit ===")

audit = {
    "date": __import__("datetime").date.today().isoformat(),
    "nego_discount": NEGO_DISCOUNT,
    "ratio_filter": [RATIO_MIN, RATIO_MAX],
    "correction_cap": list(CORRECTION_CAP),
    "global_correction": global_corr,
    "by_commune": corrections,
    "dry_run": args.dry_run,
}
AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"  Écrit : {AUDIT.name}")

# ─────────────────────────────────────────────────────────────────────────────
if not args.dry_run:
    print("\n=== 5. Re-export ===")
    import subprocess
    result = subprocess.run(
        [sys.executable, str(BASE / "_export_react_data.py")],
        capture_output=True, text=True, encoding="utf-8", cwd=str(BASE)
    )
    print(result.stdout.strip())
    if result.returncode != 0:
        print("ERREUR export:", result.stderr[:300])
    else:
        print("\nOK — relancer `npm run dev` pour voir les nouveaux scores.")
else:
    print("\n[DRY RUN] Fin. Relancer sans --dry-run pour appliquer.")
