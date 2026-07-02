"""
_export_comps.py
================
Exporte les transactions DVF récentes (2022+) appartements
vers dashboard-react/src/data/comps.json

Format minifié pour limiter la taille :
  { d, c, s, a, v, sf, pm2, lat, lon }
  d   = date (YYYY-MM-DD)
  c   = commune uppercase
  s   = section cadastrale
  a   = adresse (ex. "29 Pas du Temple")
  v   = valeur €
  sf  = surface m²
  pm2 = prix/m² arrondi
  lat, lon = coordonnées
"""
import sys, json
import pandas as pd
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

BASE     = Path(__file__).parent
DVF_DIR  = BASE / "dvf"
OUT      = BASE / "dashboard-react" / "src" / "data" / "comps.json"

df = pd.read_csv(DVF_DIR / "dvf_clean.csv")

apt = df[
    (df["type_local"] == "appart") &
    (df["annee"] >= 2022) &
    df["prix_m2"].between(3_500, 30_000) &
    (df["surface"] >= 14) &
    (df["surf_terrain"].fillna(0) == 0)
].copy()

print(f"Transactions apparts 2022+ : {len(apt)}")

def fmt_address(row) -> str:
    no  = str(int(row["no_voie"])) if pd.notna(row["no_voie"]) else ""
    typ = str(row["type_voie"]).strip() if pd.notna(row["type_voie"]) else ""
    rue = str(row["voie"]).strip().title() if pd.notna(row["voie"]) else ""
    parts = [p for p in [no, typ, rue] if p]
    return " ".join(parts) if parts else ""

def fmt_date(d: str) -> str:
    # Input: "13/01/2023" → "2023-01-13"
    try:
        parts = str(d).split("/")
        if len(parts) == 3:
            return f"{parts[2]}-{parts[1]}-{parts[0]}"
    except Exception:
        pass
    return str(d)

records = []
for _, row in apt.iterrows():
    addr = fmt_address(row)
    if not addr:
        addr = str(row.get("voie", "")).strip().title()

    rec = {
        "d":   fmt_date(row["date"]),
        "c":   str(row["commune"]).upper().strip(),
        "s":   str(row["section"]).upper().strip() if pd.notna(row["section"]) else "G",
        "a":   addr,
        "v":   int(row["valeur"]),
        "sf":  round(float(row["surface"]), 1),
        "pm2": int(round(row["prix_m2"])),
    }
    if pd.notna(row.get("lat")):
        rec["lat"] = round(float(row["lat"]), 5)
        rec["lon"] = round(float(row["lon"]), 5)
    records.append(rec)

# Tri par commune puis date desc
records.sort(key=lambda r: (r["c"], r["d"]), reverse=False)

OUT.write_text(json.dumps(records, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
size_kb = OUT.stat().st_size / 1024
print(f"✓ comps.json — {len(records)} transactions — {size_kb:.0f} KB")
print(f"  → {OUT}")
